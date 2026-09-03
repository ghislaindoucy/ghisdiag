r"""
GhisdiagDisk - moteur de balayage T1 (lecture seule).

Ce que mesure un balayage, et pourquoi (ROADMAP, campagnes du 02 et 03/09) :

  - le TEMPS PAR BLOC, et surtout son maximum par zone : un bloc qui met
    800 ms a sortir est un secteur en train de mourir que SMART ne compte pas
    encore. Seuil calibre en WinPE : un bloc au-dela de 3x la mediane de sa
    zone est une anomalie reelle (le pire observe sur des disques sains en PE
    est 1,7x ; sous Windows il monte a 4,4x a cause de l'I/O de fond de l'OS).
    Sous Windows le moteur mesure quand meme, mais REFUSE DE CONCLURE sur les
    latences - les medianes, elles, sont identiques dans les deux
    environnements, donc le debit reste exploitable ;
  - les SECTEURS ILLISIBLES (ReadFile en echec : CRC, erreur E/S), localises
    par bissection jusqu'au secteur physique, et concluants dans TOUS les
    environnements ;
  - le DEBIT par zone, dont la forme (profil ZBR) identifie un disque
    mecanique, et dont la mediane se compare a la classe du support ;
  - un profil de LECTURE ALEATOIRE (p50/p99) : controleur SSD degrade, SMR
    qui rame, NAND fatiguee.

Deux pieges que seuls les disques mecaniques revelent, traites ici :
  - le reveil des plateaux (313 ms sur le premier bloc d'un disque en veille)
    est indistinguable d'un secteur mourant -> lecture d'ECHAUFFEMENT non
    mesuree avant chaque zone, faite AU-DELA de la fenetre mesuree pour que
    la lecture anticipee du disque ne pre-charge pas la zone dans son cache ;
  - 16 Mio tiennent dans le cache d'un disque (64-256 Mo) -> les zones font
    256 Mio (express) ou 1 Gio (standard/complet), et les lectures aleatoires
    tombent a des offsets non previsibles.

Le moteur est PUR : il recoit un lecteur (`lire(offset, taille) -> octets`,
OSError sur secteur illisible) et une horloge. Les tests le font tourner sur
un faux disque, sans materiel. La session est ecrite AU FIL DE L'EAU
(checkpoint apres chaque zone) et REPRENABLE : un balayage de 9 h interrompu
laisse un rapport partiel exploitable.

Avertissement metier, porte par le verdict : balayer integralement un disque
mourant peut l'achever. Le moteur s'arrete de lui-meme au-dela d'un nombre de
blocs illisibles - imager d'abord, tester ensuite.
"""

import json
import random
import statistics
import threading
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from . import __version__, OUTIL
from . import inventory, niveaux

SCHEMA_VERSION = 1

MODES = ("express", "standard", "complet")

MIB = 1024 * 1024
GIB = 1024 * MIB

BLOC_OCTETS = 1 * MIB            # granularite de la latence : un secteur mourant
                                 # doit ressortir, pas se diluer dans 64 Mio
SOUS_BLOC_MIN = 4096             # bissection des blocs illisibles : jusqu'au
                                 # secteur physique, jamais moins que 4 Kio
ECART_ECHAUFFEMENT = 64 * MIB    # quand la zone touche la fin du disque

# Parametres par mode - calibres pour ~2 min / ~15 min sur un disque mecanique
# a ~100 Mo/s ; le mode complet lit tout (une nuit sur 4 To).
PARAMS_MODE = {
    "express":  {"nb_segments": 12,   "segment_octets": 256 * MIB},
    "standard": {"nb_segments": 48,   "segment_octets": 1 * GIB},
    "complet":  {"nb_segments": None, "segment_octets": 1 * GIB},
}

FACTEUR_ANOMALIE       = 3.0     # x mediane de la zone (WinPE, calibre 03/09)
PLANCHER_ANOMALIE_MS   = 25.0    # sur SSD la mediane est < 1 ms : 3x mediane
                                 # serait du bruit d'ordonnanceur. A VALIDER.
SEUIL_BLOC_MOURANT_MS  = 500.0   # bloc en re-essais internes du disque
MAX_BLOCS_ILLISIBLES   = 64      # au-dela on arrete : preserver les donnees
MAX_SOUS_LECTURES_BLOC = 64      # echecs de bissection par bloc avant de
                                 # declarer le reste presume illisible
LECTURES_ALEATOIRES    = 200

# Debit median sequentiel en dessous duquel un disque de la classe est
# anormal (planchers volontairement bas : un disque lent n'est pas un disque
# malade, on ne crie pas au loup). Un SATA SSD a 40 Mo/s est mourant ou sur un
# lien degrade.
DEBIT_MIN_CLASSE_MO_S = {"nvme": 300.0, "ssd": 100.0, "hdd": 25.0}

ETATS = ("sain", "a_surveiller", "a_remplacer", "non_concluant")
_RANG = {"sain": 0, "non_concluant": 1, "a_surveiller": 2, "a_remplacer": 3}


# --- Configuration -----------------------------------------------------------

@dataclass
class ScanConfig:
    mode: str = "express"
    niveau: str = niveaux.NIVEAU_DEFAUT
    bloc_octets: int = BLOC_OCTETS
    nb_segments: Optional[int] = None         # None = defaut du mode
    segment_octets: Optional[int] = None      # None = defaut du mode
    facteur_anomalie: float = FACTEUR_ANOMALIE
    plancher_anomalie_ms: float = PLANCHER_ANOMALIE_MS
    seuil_mourant_ms: float = SEUIL_BLOC_MOURANT_MS
    max_blocs_illisibles: int = MAX_BLOCS_ILLISIBLES
    lectures_aleatoires: int = LECTURES_ALEATOIRES
    graine_aleatoire: Optional[int] = None

    def normalized(self) -> "ScanConfig":
        mode = self.mode if self.mode in MODES else "express"
        p = PARAMS_MODE[mode]
        return ScanConfig(
            mode=mode,
            niveau=self.niveau if self.niveau in niveaux.NIVEAUX else niveaux.NIVEAU_DEFAUT,
            bloc_octets=max(SOUS_BLOC_MIN, int(self.bloc_octets)),
            nb_segments=(max(2, int(self.nb_segments)) if self.nb_segments
                         else p["nb_segments"]),
            segment_octets=(max(SOUS_BLOC_MIN, int(self.segment_octets))
                            if self.segment_octets else p["segment_octets"]),
            facteur_anomalie=max(1.0, float(self.facteur_anomalie)),
            plancher_anomalie_ms=max(0.0, float(self.plancher_anomalie_ms)),
            seuil_mourant_ms=max(0.0, float(self.seuil_mourant_ms)),
            max_blocs_illisibles=max(1, int(self.max_blocs_illisibles)),
            lectures_aleatoires=max(0, int(self.lectures_aleatoires)),
            graine_aleatoire=self.graine_aleatoire,
        )


# --- Plan de balayage --------------------------------------------------------

@dataclass
class Segment:
    index: int
    offset: int
    longueur: int


def _aligner(x: int, a: int) -> int:
    return x - (x % a) if a else x


def planifier(taille: int, secteur: int, cfg: ScanConfig) -> list:
    """Decoupe le disque en zones a mesurer.

    complet          : zones contigues de `segment_octets`, tout le disque.
    express/standard : `nb_segments` zones reparties uniformement, la premiere
                       a l'offset 0 et la derniere finissant EXACTEMENT a la
                       fin du disque (les pistes interieures sont les plus
                       lentes et les plus parlantes). Un disque trop petit pour
                       ce plan est balaye en entier.
    Offsets et longueurs sont multiples du secteur (exige par NO_BUFFERING).
    """
    cfg = cfg.normalized()
    secteur = max(512, int(secteur))
    bloc = _aligner(cfg.bloc_octets, secteur) or secteur
    seg = _aligner(cfg.segment_octets, secteur) or secteur
    taille = _aligner(int(taille), secteur)
    if taille <= 0:
        return []

    def _contigu() -> list:
        out, off, i = [], 0, 0
        while off < taille:
            out.append(Segment(i, off, min(seg, taille - off)))
            off += seg
            i += 1
        return out

    if cfg.mode == "complet" or cfg.nb_segments is None:
        return _contigu()
    n = cfg.nb_segments
    if taille <= n * seg:
        return _contigu()
    out = []
    for i in range(n):
        if i == n - 1:
            off = _aligner(taille - seg, secteur)
        else:
            off = _aligner(round(i * (taille - seg) / (n - 1)), bloc)
        out.append(Segment(i, off, min(seg, taille - off)))
    return out


# --- Statistiques ------------------------------------------------------------

def _percentile(valeurs: list, p: float) -> Optional[float]:
    if not valeurs:
        return None
    v = sorted(valeurs)
    k = min(len(v) - 1, max(0, int(round(p * (len(v) - 1)))))
    return v[k]


def _stats_temps(temps: list) -> dict:
    if not temps:
        return {"bloc_median_ms": None, "bloc_p99_ms": None,
                "bloc_max_ms": None, "bloc_moyen_ms": None}
    return {"bloc_median_ms": round(statistics.median(temps), 3),
            "bloc_p99_ms":    round(_percentile(temps, 0.99), 3),
            "bloc_max_ms":    round(max(temps), 3),
            "bloc_moyen_ms":  round(sum(temps) / len(temps), 3)}


def _debit(octets: int, duree_ms: float) -> Optional[float]:
    return round(octets / 1e6 / (duree_ms / 1000.0), 1) if duree_ms > 0 else None


# --- Session -----------------------------------------------------------------

def nouvelle_session(fiche: dict, cfg: ScanConfig, environnement: dict) -> dict:
    cfg = cfg.normalized()
    geo = fiche.get("geometrie") or {}
    plan = planifier(geo.get("taille_octets") or 0, geo.get("secteur_logique") or 512, cfg)
    env = dict(environnement or {})
    # C'est ICI que se decide le droit de conclure sur les latences.
    env["conclusion_latence_autorisee"] = bool(env.get("winpe"))
    return {
        "outil":          OUTIL,
        "version":        __version__,
        "schema":         SCHEMA_VERSION,
        "niveau":         cfg.niveau,
        "mention_niveau": niveaux.MENTION_RAPPORT.get(cfg.niveau),
        "mode":           cfg.mode,
        "config":         asdict(cfg),
        "environnement":  env,
        "disque":         fiche,
        "demarre_a":      datetime.now().isoformat(timespec="seconds"),
        "termine_a":      None,
        "duree_s":        None,
        "reprises":       [],
        "statut":         "en_cours",
        "arret":          None,
        "plan": {
            "nb_segments":    len(plan),
            "segment_octets": cfg.segment_octets,
            "bloc_octets":    cfg.bloc_octets,
            "octets_prevus":  sum(s.longueur for s in plan),
            "segments":       [asdict(s) for s in plan],
        },
        "segments":         [],
        "lecture_aleatoire": None,
        "synthese":         None,
        "verdict":          None,
    }


def reprendre_session(session: dict, fiche: dict) -> dict:
    """Prepare une session existante a etre reprise sur LE MEME disque.

    On compare la cle d'identite ET la taille : PhysicalDrive0 et
    PhysicalDrive1 se confondent en une seconde en PE sans lettres de lecteur.
    """
    disque = session.get("disque") or {}
    geo_s = (disque.get("geometrie") or {}).get("taille_octets")
    geo_f = (fiche.get("geometrie") or {}).get("taille_octets")
    if disque.get("cle_identite") != fiche.get("cle_identite") or geo_s != geo_f:
        raise ValueError(
            f"la session decrit le disque {disque.get('cle_identite')!r} "
            f"({geo_s} octets), pas {fiche.get('cle_identite')!r} ({geo_f} octets)")
    if session.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"schema de session {session.get('schema')} inconnu")
    session = json.loads(json.dumps(session))          # copie profonde
    session.setdefault("reprises", []).append(datetime.now().isoformat(timespec="seconds"))
    session["statut"] = "en_cours"
    session["arret"] = None
    session["termine_a"] = None
    session["verdict"] = None
    return session


def dossier_sessions(prefere: Optional[Path] = None) -> Path:
    """A cote de l'exe (= la cle USB, l'archive) ; repli Documents sous
    Windows normal si ce dossier n'est pas inscriptible."""
    from . import rawdisk
    candidats = [Path(prefere)] if prefere else []
    candidats += [rawdisk.dossier_exe() / "rapports_disque",
                  Path.home() / "Documents" / "Ghisdiag" / "disque"]
    for c in candidats:
        try:
            c.mkdir(parents=True, exist_ok=True)
            temoin = c / ".ghisdiagdisk_write_test"
            temoin.write_text("ok", encoding="utf-8")
            temoin.unlink()
            return c
        except OSError:
            continue
    return candidats[-1]


def chemin_session(dossier: Path, session: dict) -> Path:
    cle = (session.get("disque") or {}).get("cle_identite") or "DISQUE"
    cle = inventory.nettoyer_serie(cle)[0] or "DISQUE"
    ts = datetime.fromisoformat(session["demarre_a"]).strftime("%Y%m%d_%H%M%S")
    return Path(dossier) / f"ghisdiagdisk_{cle}_{session.get('niveau', 'T1')}_{ts}.json"


def sauver_session(session: dict, chemin: Path) -> Path:
    """Ecriture atomique (tmp + replace) : un plantage pendant l'ecriture ne
    laisse jamais un JSON tronque a la place du precedent."""
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    tmp.replace(chemin)
    return chemin


def charger_session(chemin) -> Optional[dict]:
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- Moteur ------------------------------------------------------------------

class ScanEngine:
    """Execute le plan sur un lecteur, zone par zone, avec checkpoint.

    lecteur        : objet avec `lire(offset, taille) -> int` (octets lus),
                     OSError sur bloc illisible. Reel : rawdisk.LecteurDisque.
    fiche          : inventory.construire_fiche(...)
    session        : None (nouvelle) ou une session a reprendre (deja passee
                     par reprendre_session)
    clock          : horloge monotone en secondes (injectable pour les tests)
    on_segment     : callable(session, resultat_segment)
    on_progression : callable(fraction 0..1, texte)
    checkpoint     : callable(session) - appele apres chaque zone
    annulation     : threading.Event - arret demande par l'utilisateur
    """

    def __init__(self, lecteur, fiche: dict, config: ScanConfig,
                 environnement: dict, session: Optional[dict] = None,
                 clock: Callable[[], float] = time.perf_counter,
                 on_segment: Optional[Callable] = None,
                 on_progression: Optional[Callable] = None,
                 checkpoint: Optional[Callable] = None,
                 annulation: Optional[threading.Event] = None):
        self.cfg = config.normalized()
        self.lecteur = lecteur
        self.fiche = fiche
        self.clock = clock
        self._on_segment = on_segment
        self._on_progression = on_progression
        self._checkpoint = checkpoint
        self._annulation = annulation or threading.Event()
        self.session = session or nouvelle_session(fiche, self.cfg, environnement)
        geo = fiche.get("geometrie") or {}
        self.taille = int(geo.get("taille_octets") or 0)
        self.secteur = max(512, int(geo.get("secteur_logique") or 512))
        self.secteur_physique = max(self.secteur, int(geo.get("secteur_physique") or self.secteur))
        self._octets_lus = sum(s.get("octets_lus", 0) for s in self.session["segments"])
        self._t_debut = None

    # -- API -----------------------------------------------------------------

    def run(self) -> dict:
        s = self.session
        plan = [Segment(**d) for d in s["plan"]["segments"]]
        faits = {seg["index"] for seg in s["segments"]}
        restants = [seg for seg in plan if seg.index not in faits]
        self._t_debut = self.clock()
        nb_illisibles = sum(seg.get("nb_blocs_illisibles", 0) for seg in s["segments"])
        premier = True
        for seg in restants:
            if self._annulation.is_set():
                s["statut"] = "interrompu"
                break
            # Echauffement : a chaque zone en mode echantillonne (on arrive de
            # loin), seulement a la premiere en mode complet (tetes deja la).
            echauffer = premier or self.cfg.mode != "complet"
            res = self._mesurer_segment(seg, echauffer)
            premier = False
            s["segments"].append(res)
            self._octets_lus += res["octets_lus"]
            nb_illisibles += res["nb_blocs_illisibles"]
            if self._on_segment:
                self._on_segment(s, res)
            if nb_illisibles >= self.cfg.max_blocs_illisibles:
                s["statut"] = "arrete_securite"
                s["arret"] = (f"{nb_illisibles} bloc(s) illisible(s) : arret volontaire "
                              "pour ne pas achever un disque en defaillance. "
                              "Imager d'abord, tester ensuite.")
            elif res.get("interrompu"):
                s["statut"] = "interrompu"
            self._progression(f"zone {seg.index + 1}/{len(plan)}")
            if self._checkpoint:
                self._checkpoint(s)
            if s["statut"] != "en_cours":
                break
        else:
            s["statut"] = "termine"

        if s["statut"] == "termine" and self.cfg.lectures_aleatoires and s.get("lecture_aleatoire") is None:
            s["lecture_aleatoire"] = self._lecture_aleatoire()
            if self._annulation.is_set():
                s["statut"] = "interrompu"

        s["termine_a"] = datetime.now().isoformat(timespec="seconds")
        duree_precedente = s.get("duree_s") or 0.0
        s["duree_s"] = round(duree_precedente + (self.clock() - self._t_debut), 1)
        s["synthese"] = synthese(s)
        s["verdict"] = calculer_verdict(s)
        if self._checkpoint:
            self._checkpoint(s)
        return s

    # -- Zones ---------------------------------------------------------------

    def _progression(self, texte: str):
        if self._on_progression:
            prevu = self.session["plan"]["octets_prevus"] or 1
            self._on_progression(min(1.0, self._octets_lus / prevu), texte)

    def _offset_echauffement(self, seg: Segment) -> int:
        bloc = self.cfg.bloc_octets
        apres = seg.offset + seg.longueur
        if apres + bloc <= self.taille:
            return apres
        avant = seg.offset - ECART_ECHAUFFEMENT
        if avant >= 0:
            return _aligner(avant, self.secteur)
        return seg.offset

    def _echauffer(self, seg: Segment):
        """Lecture NON MESUREE : absorbe le reveil des plateaux et le premier
        positionnement. Faite hors de la fenetre pour ne pas la pre-charger."""
        off = self._offset_echauffement(seg)
        n = min(self.cfg.bloc_octets, self.taille - off)
        n = _aligner(n, self.secteur)
        if n <= 0:
            return
        try:
            self.lecteur.lire(off, n)
        except OSError:
            pass

    def _mesurer_segment(self, seg: Segment, echauffer: bool) -> dict:
        cfg = self.cfg
        if echauffer:
            self._echauffer(seg)
        blocs = []            # (offset, ms) des blocs lus sans erreur
        plages = []           # plages illisibles localisees
        octets = 0
        octets_blocs = 0      # octets des blocs lus sans erreur (pour le debit)
        nb_illisibles = 0
        duree_erreurs_ms = 0.0
        interrompu = False
        pos, fin = seg.offset, seg.offset + seg.longueur
        compteur = 0
        while pos < fin:
            if self._annulation.is_set():
                interrompu = True
                break
            n = min(cfg.bloc_octets, fin - pos)
            t0 = self.clock()
            try:
                lus = self.lecteur.lire(pos, n)
            except OSError as exc:
                nb_illisibles += 1
                sous, ok = self._localiser_illisibles(pos, n, str(exc))
                plages.extend(sous)
                octets += ok
                duree_erreurs_ms += (self.clock() - t0) * 1000.0
                if nb_illisibles + self._illisibles_precedents() >= cfg.max_blocs_illisibles:
                    pos += n
                    break
                pos += n
                continue
            dt = (self.clock() - t0) * 1000.0
            blocs.append((pos, dt))
            octets += lus
            octets_blocs += lus
            if lus < n:              # fin de peripherique inattendue
                break
            pos += n
            compteur += 1
            if compteur % 32 == 0:
                self._progression(f"zone {seg.index + 1} : {round((pos - seg.offset) / seg.longueur * 100)} %")

        temps = [ms for _, ms in blocs]
        st = _stats_temps(temps)
        seuil = None
        anomalies, mourants = [], 0
        if st["bloc_median_ms"] is not None:
            seuil = max(cfg.facteur_anomalie * st["bloc_median_ms"], cfg.plancher_anomalie_ms)
            for off, ms in blocs:
                if ms > seuil:
                    anomalies.append({"offset": off, "ms": round(ms, 2)})
                if ms > cfg.seuil_mourant_ms:
                    mourants += 1
        duree = sum(temps)
        plages = _fusionner_plages(plages, self.secteur)
        return {
            "index":                seg.index,
            "offset":               seg.offset,
            "longueur":             seg.longueur,
            "offset_go":            round(seg.offset / 1e9, 2),
            "octets_lus":           octets,
            "nb_blocs":             len(blocs),
            "duree_ms":             round(duree, 1),
            "duree_erreurs_ms":     round(duree_erreurs_ms, 1),
            "debit_mo_s":           _debit(octets_blocs, duree) if blocs else None,
            **st,
            "seuil_anomalie_ms":    round(seuil, 2) if seuil is not None else None,
            "nb_blocs_anormaux":    len(anomalies),
            "nb_blocs_mourants":    mourants,
            "anomalies":            anomalies[:50],
            "nb_blocs_illisibles":  nb_illisibles,
            "nb_secteurs_illisibles": sum(p["secteurs"] for p in plages),
            "plages_illisibles":    plages[:100],
            "nb_plages_illisibles": len(plages),
            "complet":              (pos >= fin) and not interrompu,
            "interrompu":           interrompu,
        }

    def _illisibles_precedents(self) -> int:
        return sum(s.get("nb_blocs_illisibles", 0) for s in self.session["segments"])

    def _localiser_illisibles(self, debut: int, longueur: int, erreur: str) -> tuple:
        """Bissection d'un bloc en echec jusqu'au secteur physique.

        Rend (plages, octets_lus_ok). Chaque essai sur un secteur mort peut
        couter plusieurs secondes de re-essais internes du disque : on plafonne
        le nombre d'echecs par bloc, le reste est declare << presume illisible
        (non localise) >> plutot que de marteler le disque.
        """
        pas = max(SOUS_BLOC_MIN, self.secteur_physique)
        pas = _aligner(pas, self.secteur) or self.secteur
        plages, ok = [], 0
        echecs = 0
        pile = [(debut, longueur)]
        while pile:
            off, n = pile.pop()
            if echecs >= MAX_SOUS_LECTURES_BLOC:
                plages.append({"offset": off, "octets": n, "localise": False,
                               "erreur": erreur})
                continue
            try:
                ok += self.lecteur.lire(off, n)
                continue
            except OSError as exc:
                echecs += 1
                erreur = str(exc)
            if n <= pas:
                plages.append({"offset": off, "octets": n, "localise": True,
                               "erreur": erreur})
                continue
            moitie = _aligner(n // 2, pas) or pas
            # Empiler la seconde moitie d'abord : on depile la premiere.
            pile.append((off + moitie, n - moitie))
            pile.append((off, moitie))
        return plages, ok

    # -- Lecture aleatoire ---------------------------------------------------

    def _lecture_aleatoire(self) -> dict:
        cfg = self.cfg
        taille_lecture = max(SOUS_BLOC_MIN, self.secteur_physique)
        graine = cfg.graine_aleatoire if cfg.graine_aleatoire is not None \
            else int(time.time()) & 0xFFFFFFFF
        rng = random.Random(graine)
        nb_pos = max(1, self.taille // taille_lecture)
        temps, erreurs = [], 0
        # Echauffement non mesure (meme raison que pour les zones).
        try:
            self.lecteur.lire(rng.randrange(nb_pos) * taille_lecture, taille_lecture)
        except OSError:
            pass
        for _ in range(cfg.lectures_aleatoires):
            if self._annulation.is_set():
                break
            off = rng.randrange(nb_pos) * taille_lecture
            t0 = self.clock()
            try:
                self.lecteur.lire(off, taille_lecture)
            except OSError:
                erreurs += 1
                continue
            temps.append((self.clock() - t0) * 1000.0)
        return {"nb_lectures": len(temps) + erreurs,
                "taille_lecture": taille_lecture,
                "graine": graine,
                "p50_ms": round(_percentile(temps, 0.50), 3) if temps else None,
                "p99_ms": round(_percentile(temps, 0.99), 3) if temps else None,
                "max_ms": round(max(temps), 3) if temps else None,
                "erreurs": erreurs}


def _fusionner_plages(plages: list, secteur: int) -> list:
    """Plages contigues -> une seule, exprimee aussi en LBA (secteur logique)."""
    out = []
    for p in sorted(plages, key=lambda x: x["offset"]):
        if out and out[-1]["localise"] == p["localise"] \
                and out[-1]["offset"] + out[-1]["octets"] == p["offset"]:
            out[-1]["octets"] += p["octets"]
        else:
            out.append(dict(p))
    for p in out:
        p["lba"] = p["offset"] // secteur
        p["secteurs"] = -(-p["octets"] // secteur)
    return out


# --- Synthese et verdict -----------------------------------------------------

def synthese(session: dict) -> dict:
    segs = sorted(session.get("segments") or [], key=lambda s: s["index"])
    taille = ((session.get("disque") or {}).get("geometrie") or {}).get("taille_octets") or 0
    prevu = (session.get("plan") or {}).get("octets_prevus") or 0
    octets = sum(s.get("octets_lus", 0) for s in segs)
    debits = [s["debit_mo_s"] for s in segs if s.get("debit_mo_s")]
    maxs = [s["bloc_max_ms"] for s in segs if s.get("bloc_max_ms") is not None]
    profil = {"ratio_fin_debut": None, "monotone_decroissant": None,
              "signature_mecanique": None}
    if len(debits) >= 3:
        # Meme regle que la calibration (3 zones : debut / milieu / fin).
        profil = inventory.profil_zbr([debits[0], debits[len(debits) // 2], debits[-1]])
    return {
        "nb_segments_mesures":    len(segs),
        "nb_segments_prevus":     (session.get("plan") or {}).get("nb_segments"),
        "octets_lus":             octets,
        "go_lus":                 round(octets / 1e9, 2),
        "couverture_disque_pct":  round(octets / taille * 100, 2) if taille else None,
        "avancement_plan_pct":    round(octets / prevu * 100, 1) if prevu else None,
        "debit_median_mo_s":      round(statistics.median(debits), 1) if debits else None,
        "debit_min_mo_s":         min(debits) if debits else None,
        "debit_max_mo_s":         max(debits) if debits else None,
        "courbe_debit":           [(s["offset_go"], s.get("debit_mo_s")) for s in segs],
        "profil_zbr":             profil,
        "bloc_max_ms":            max(maxs) if maxs else None,
        "nb_blocs_anormaux":      sum(s.get("nb_blocs_anormaux", 0) for s in segs),
        "nb_blocs_mourants":      sum(s.get("nb_blocs_mourants", 0) for s in segs),
        "nb_blocs_illisibles":    sum(s.get("nb_blocs_illisibles", 0) for s in segs),
        "nb_secteurs_illisibles": sum(s.get("nb_secteurs_illisibles", 0) for s in segs),
        "nb_plages_illisibles":   sum(s.get("nb_plages_illisibles", 0) for s in segs),
        "zones_avec_anomalies":   [s["index"] for s in segs
                                   if s.get("nb_blocs_anormaux") or s.get("nb_blocs_illisibles")],
    }


def _smart_prealable(disque: dict) -> list:
    """Ce que SMART disait deja AVANT le balayage - pese dans le verdict."""
    raisons = []
    smart = (disque or {}).get("smart") or {}
    if not smart:
        return raisons
    if smart.get("smart_actif") is False:
        raisons.append(("a_remplacer", "SMART : etat de sante declare en echec par le disque"))
    attrs = smart.get("attributs_ata") or {}
    for cle, libelle in (("secteurs_en_attente", "secteur(s) en attente de reallocation"),
                         ("secteurs_realloues", "secteur(s) realloue(s)"),
                         ("secteurs_non_corrigeables_hors_ligne", "secteur(s) non corrigeable(s)")):
        v = attrs.get(cle)
        if isinstance(v, (int, float)) and v > 0:
            raisons.append(("a_surveiller", f"SMART : {int(v)} {libelle}"))
    nvme = smart.get("nvme") or {}
    if isinstance(nvme.get("erreurs_media"), (int, float)) and nvme["erreurs_media"] > 0:
        raisons.append(("a_surveiller", f"SMART NVMe : {int(nvme['erreurs_media'])} erreur(s) media"))
    if isinstance(nvme.get("avertissement_critique"), int) and nvme["avertissement_critique"]:
        raisons.append(("a_surveiller", f"SMART NVMe : avertissement critique 0x{nvme['avertissement_critique']:02X}"))
    return raisons


def calculer_verdict(session: dict) -> dict:
    """Verdict tri-etat + non concluant, avec ses raisons - jamais << sain >>
    pour ce qui n'a pas ete mesure."""
    synth = session.get("synthese") or synthese(session)
    env = session.get("environnement") or {}
    disque = session.get("disque") or {}
    concl_latence = bool(env.get("conclusion_latence_autorisee"))
    statut = session.get("statut")
    mode = session.get("mode")
    avis = []          # (etat, raison)
    notes = []

    n_ill = synth.get("nb_secteurs_illisibles") or 0
    if n_ill:
        avis.append(("a_remplacer",
                     f"{n_ill} secteur(s) illisible(s) sur {synth.get('nb_plages_illisibles')} "
                     "plage(s) - concluant quel que soit l'environnement"))
    if statut == "arrete_securite":
        avis.append(("a_remplacer", session.get("arret") or "arret de securite"))

    n_mour = synth.get("nb_blocs_mourants") or 0
    n_anor = synth.get("nb_blocs_anormaux") or 0
    seuil = session.get("config", {}).get("seuil_mourant_ms")
    if concl_latence:
        if n_mour:
            avis.append(("a_remplacer", f"{n_mour} bloc(s) au-dela de {seuil:.0f} ms : "
                                        "secteur(s) en re-essais internes, en train de mourir"))
        elif n_anor:
            avis.append(("a_surveiller", f"{n_anor} bloc(s) anormalement lent(s) "
                                         f"(> {session['config']['facteur_anomalie']:.0f}x la "
                                         "mediane de leur zone), max "
                                         f"{synth.get('bloc_max_ms')} ms"))
    elif n_mour or n_anor:
        avis.append(("non_concluant",
                     f"{n_anor} bloc(s) lent(s) observe(s) (max {synth.get('bloc_max_ms')} ms) "
                     "mais mesure hors WinPE : l'I/O de fond de l'OS pollue les maximums, "
                     "aucune conclusion sur les latences. Rejouer le balayage en WinPE."))

    classe = disque.get("classe")
    usb = any("USB" in a for a in (disque.get("avertissements") or []))
    debit = synth.get("debit_median_mo_s")
    plancher = DEBIT_MIN_CLASSE_MO_S.get(classe)
    if plancher and debit is not None and not usb:
        if debit < plancher:
            avis.append(("a_surveiller", f"debit median {debit} Mo/s sous le plancher de la "
                                         f"classe {classe} ({plancher:.0f} Mo/s) : disque "
                                         "mourant ou lien degrade"))
    elif usb and debit is not None:
        notes.append("debit non compare a la classe (pont USB)")

    avis.extend(_smart_prealable(disque))

    profil = synth.get("profil_zbr") or {}
    if profil.get("signature_mecanique"):
        notes.append(f"profil de debit d'un disque mecanique (ratio fin/debut "
                     f"{profil.get('ratio_fin_debut')})")

    if statut == "interrompu":
        avis.append(("non_concluant", f"balayage interrompu a {synth.get('avancement_plan_pct')} % "
                                      "du plan : verdict partiel"))
    elif statut == "en_cours":
        avis.append(("non_concluant", "balayage en cours"))

    etats = [e for e, _ in avis]
    if not etats:
        if not concl_latence:
            etat = "non_concluant"
            avis.append(("non_concluant", "aucun secteur illisible ni debit anormal, mais la "
                                          "conclusion sur les latences exige WinPE"))
        else:
            etat = "sain"
    else:
        etat = max(etats, key=lambda e: _RANG[e])
        # Un << non concluant >> ne masque pas un defaut avere, et un defaut
        # avere ne rend pas le reste concluant : on garde les deux raisons.
    portee = "surface complete" if mode == "complet" and statut == "termine" else "echantillon"
    couverture = synth.get("couverture_disque_pct")
    if etat == "sain" and portee == "echantillon":
        notes.append(f"sain sur l'echantillon lu ({couverture} % de la surface, mode {mode})")
    return {
        "etat":       etat,
        "concluant":  etat != "non_concluant",
        "raisons":    [r for _, r in avis],
        "notes":      notes,
        "portee":     portee,
        "couverture_disque_pct": couverture,
        "niveau":     session.get("niveau"),
        "environnement": env.get("environnement"),
    }


LIBELLES_ETAT = {
    "sain":          "SAIN",
    "a_surveiller":  "A SURVEILLER",
    "a_remplacer":   "A REMPLACER",
    "non_concluant": "NON CONCLUANT",
}
