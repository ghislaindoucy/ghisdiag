r"""
GhisdiagDisk - rapport client HTML (phase 2, specification du 08/09/2026).

Ce que ce module fait, et ce qu'il refuse de faire, est fixe dans ROADMAP.md
(section << Phase 2 - le rapport client >>). En resume :

  - le rapport est produit A PART du balayage : il relit une session JSON et
    ecrit un HTML a cote, sans ouvrir de disque. Le nom du client ne vit que
    dans le HTML (jamais dans le nom de fichier) ;
  - la synthese et le verdict sont RECALCULES avec les regles courantes de
    `scan`, sans reecrire le JSON. Motif : la session du 08/09 porte encore un
    verdict << surface complete >> ecrit par un exe qui ne savait pas qu'une
    zone coupee par un Ctrl+C laisse un trou de 157 Mio. Un rapport remis a un
    client doit dire ce que l'outil sait AUJOURD'HUI de cette mesure ;
  - le mot du verdict et sa phrase de portee sont indissociables : << sain >>
    en mode express, c'est sain sur ~0,3 % de la surface, et c'est ecrit ;
  - HTML autonome (aucune ressource externe, aucun JavaScript : le PE n'a pas
    de reseau), courbe et histogramme en SVG en ligne, CSS clair pense pour le
    papier (assets/disk_report.css, embarque via le .spec).

Limite connue de l'histogramme des latences (choix A du 08/09) : la session ne
conserve pas le temps de chaque bloc, seulement les blocs lents (au plus 50
retenus et 20 isoles par zone) et les statistiques de zone. Les bornes 5 et
10 ms de l'outil commercial ne sont donc pas remplies ; les bornes 25 / 50 /
150 / 500 ms le sont sur les blocs lents conserves, et l'excedent tronque est
compte a part. Le rapport le dit en clair plutot que d'inventer des chiffres.

Le code source est en ASCII strict (convention du paquet) : les accents du
HTML sont ecrits en sequences \u00XX.
"""

import html
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import __version__, OUTIL
from . import inventory, scan

# Bornes de l'histogramme, en ms. Ce sont celles de l'outil commercial de
# l'atelier ramenees au Mio (ROADMAP, confrontation du 08/09) : un rapport
# comparable case a case avec le leur est un argument commercial. Les deux
# premieres (5 et 10) ne sont pas calculables depuis une session de schema 2.
BORNES_HISTOGRAMME_MS = (5, 10, 25, 50, 150, 500)
BORNES_CALCULABLES_MS = (25, 50, 150, 500)

# Nombre de lignes au-dela duquel une table de zones est abregee : un rapport
# papier n'a pas a lister 434 blocs lents un par un, la position des premiers
# et le total suffisent au technicien.
MAX_LIGNES_ZONES = 12

# Titres client et phrases de portee OBLIGATOIRES (spec, section 4). Ne pas
# reformuler : ces mots ont ete arretes avec l'atelier. La phrase du << sain >>
# est construite avec la couverture reelle, celle du << non concluant >> avec
# la raison exacte de la session.
VERDICTS = {
    "sain": {
        "titre":  "Aucun d\u00e9faut d\u00e9tect\u00e9",
        "classe": "ok",
    },
    "a_surveiller": {
        "titre":  "Signes de faiblesse",
        "classe": "warn",
        "portee": "le disque fonctionne mais pr\u00e9sente des signaux \u00e0 surveiller "
                  "\u2014 voir le d\u00e9tail ci-dessous",
    },
    "a_remplacer": {
        "titre":  "Disque d\u00e9faillant",
        "classe": "crit",
        "portee": "remplacement n\u00e9cessaire \u2014 <strong>ne pas continuer \u00e0 "
                  "l\u2019utiliser</strong>",
    },
    "non_concluant": {
        "titre":  "Diagnostic non concluant",
        "classe": "info",
    },
}

CONSIGNES = {
    "sain": "Aucune action n\u2019est requise : le disque peut \u00eatre remis en service. "
            "Une sauvegarde r\u00e9guli\u00e8re reste la seule protection contre une panne "
            "subite, qu\u2019aucun test ne peut pr\u00e9dire.",
    "a_surveiller": "Sauvegarder les donn\u00e9es sans attendre, puis replanifier un "
                    "contr\u00f4le (balayage complet en WinPE). Remplacer le disque au "
                    "premier signe suppl\u00e9mentaire.",
    "a_remplacer": "<strong>Imager d\u2019abord, tester ensuite</strong> : copier les "
                   "donn\u00e9es vers un autre support avant toute autre manipulation. "
                   "Ne pas remettre ce disque en service.",
}

LIBELLES_MODE = {
    "express":  "express",
    "standard": "standard",
    "complet":  "complet",
}

# Compteurs SMART bruts affiches, dans l'ordre : ce sont ceux que le verdict
# lit (scan._smart_prealable) et ceux que le rapport concurrent ignore
# (34 secteurs realloues rendus << BON >>). Le drapeau PASSED n'est qu'une
# ligne d'etat, jamais la conclusion.
ATTRIBUTS_SMART = (
    (5,   "secteurs_realloues",                   "Secteurs r\u00e9allou\u00e9s",                 "crit"),
    (187, "erreurs_non_corrigeables_rapportees",  "Erreurs non corrigeables rapport\u00e9es",     "crit"),
    (196, "evenements_reallocation",              "\u00c9v\u00e9nements de r\u00e9allocation",     "warn"),
    (197, "secteurs_en_attente",                  "Secteurs en attente de r\u00e9allocation",     "crit"),
    (198, "secteurs_non_corrigeables_hors_ligne", "Secteurs non corrigeables (hors ligne)",       "crit"),
    (199, "erreurs_crc_udma",                     "Erreurs CRC (c\u00e2ble / interface)",         "warn"),
)


class RapportRefuse(Exception):
    """La session ne peut pas donner lieu a un rapport (rien de mesure, ou ce
    n'est pas une session GhisdiagDisk). Code de sortie 2 dans la console."""


# --- Utilitaires -------------------------------------------------------------

def get_css() -> str:
    """Charge le CSS du rapport client : embarque dans l'exe (datas du .spec),
    sinon le fichier du depot. Vide si absent : le HTML reste lisible."""
    if getattr(sys, "frozen", False):
        chemin = Path(sys._MEIPASS) / "assets" / "disk_report.css"
    else:
        chemin = Path(__file__).parent.parent / "assets" / "disk_report.css"
    try:
        return chemin.read_text(encoding="utf-8")
    except OSError:
        return ""


def _esc(s) -> str:
    """Echappement HTML complet : un client nomme << <b>Dupont >> ne casse pas
    la page, et rien de ce qui vient d'une session n'est interprete."""
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


def _fmt_date(iso) -> str:
    try:
        d = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return _esc(iso) or "\u2014"
    return d.strftime("%d/%m/%Y \u00e0 %H:%M")


def _fmt_duree(secondes) -> str:
    try:
        s = int(round(float(secondes)))
    except (TypeError, ValueError):
        return "\u2014"
    h, reste = divmod(s, 3600)
    m, sec = divmod(reste, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {sec:02d} s"
    return f"{sec} s"


def _fmt_nombre(x, decimales: int = 0, unite: str = "") -> str:
    """1234.5 -> << 1 234,5 >> : ecriture francaise, espace insecable."""
    if x is None:
        return "\u2014"
    try:
        v = float(x)
    except (TypeError, ValueError):
        return _esc(x)
    txt = f"{v:,.{decimales}f}".replace(",", "\u00a0").replace(".", ",")
    return txt + (f"\u00a0{unite}" if unite else "")


def _ou_tiret(x) -> str:
    return _esc(x) if x not in (None, "") else "\u2014"


def _mib_lisible(octets) -> str:
    try:
        o = int(octets)
    except (TypeError, ValueError):
        return "\u2014"
    if o >= scan.GIB and o % scan.GIB == 0:
        return f"{o // scan.GIB} Gio"
    return f"{o // scan.MIB} Mio"


# --- Preparation de la session ----------------------------------------------

def bloc_dossier(client=None, technicien=None, reference=None) -> Optional[dict]:
    """Bloc `dossier` d'une session, tel que la spec le fixe : un seul endroit,
    explicite, horodate. Rendu None si rien n'est saisi (le JSON reste alors
    exempt de donnees personnelles)."""
    if not any((client, technicien, reference)):
        return None
    return {"client": client or None, "technicien": technicien or None,
            "reference": reference or None,
            "saisi_a": datetime.now().isoformat(timespec="seconds")}


def preparer(session: dict) -> dict:
    """Copie de la session prete a etre rendue : schema migre, synthese et
    verdict recalcules avec les regles courantes. Ne modifie pas l'original.
    Leve RapportRefuse si rien ne peut etre dit."""
    import json
    if not isinstance(session, dict) or session.get("outil") != OUTIL:
        raise RapportRefuse("ce fichier n'est pas une session GhisdiagDisk")
    s = scan.migrer_session(json.loads(json.dumps(session)))
    if not s.get("segments"):
        raise RapportRefuse("aucune zone mesuree dans cette session : rien a rapporter")
    if not s.get("disque"):
        raise RapportRefuse("session sans fiche de disque")
    s["synthese"] = scan.synthese(s)
    s["verdict"] = scan.calculer_verdict(s)
    return s


def histogramme_latences(session: dict) -> dict:
    """Repartition des blocs lus par latence, avec ce que la session conserve.

    Rend {"total", "illisibles", "sous_seuil", "bornes": [(label, n), ...],
          "non_conserves", "isoles"}.
    `sous_seuil` = blocs sous le seuil d'anomalie de LEUR zone (3x la mediane
    de zone, plancher 25 ms) : leur temps individuel n'est pas dans la session.
    Les blocs lents conserves sont ventiles aux bornes 25/50/150/500 ms ; ceux
    dont la liste a ete tronquee (> 50 retenus ou > 20 isoles par zone) sont
    comptes dans `non_conserves`. Aucune borne n'est inventee.
    """
    bornes = BORNES_CALCULABLES_MS
    compte = [0] * len(bornes)          # [25-50), [50-150), [150-500), [500+
    total = sous_seuil = non_conserves = isoles = illisibles = 0
    # Le compteur de blocs mourants de chaque zone est exact meme quand la
    # liste des anomalies est tronquee (les 50 conservees sont les premieres
    # par position, pas les pires) : il alimente la derniere borne quand le
    # seuil << mourant >> de la session est cette borne (500 ms).
    seuil_mourant = (session.get("config") or {}).get("seuil_mourant_ms")
    mourants_fiables = (seuil_mourant == bornes[-1])
    for z in session.get("segments") or []:
        nb = int(z.get("nb_blocs") or 0)
        n_anor = int(z.get("nb_blocs_anormaux") or 0)
        n_isol = int(z.get("nb_blocs_isoles") or 0)
        total += nb
        isoles += n_isol
        illisibles += int(z.get("nb_blocs_illisibles") or 0)
        sous_seuil += max(0, nb - n_anor - n_isol)
        connus = list(z.get("anomalies") or []) + list(z.get("anomalies_isolees") or [])
        inconnus = max(0, n_anor - len(z.get("anomalies") or [])) \
            + max(0, n_isol - len(z.get("anomalies_isolees") or []))
        connus_500 = 0
        for a in connus:
            try:
                ms = float(a.get("ms"))
            except (TypeError, ValueError):
                inconnus += 1
                continue
            idx = -1
            for i, b in enumerate(bornes):
                if ms >= b:
                    idx = i
            if idx < 0:
                # Impossible en theorie (seuil >= 25 ms) : on ne l'invente pas
                # ailleurs, il reste sous le seuil.
                sous_seuil += 1
            else:
                compte[idx] += 1
                if idx == len(bornes) - 1:
                    connus_500 += 1
        if mourants_fiables:
            manquants = min(inconnus, max(0, int(z.get("nb_blocs_mourants") or 0) - connus_500))
            compte[-1] += manquants
            inconnus -= manquants
        non_conserves += inconnus
    libelles = []
    for i, b in enumerate(bornes):
        if i + 1 < len(bornes):
            libelles.append(f"{b} \u00e0 {bornes[i + 1]} ms")
        else:
            libelles.append(f"plus de {b} ms")
    return {"total": total, "illisibles": illisibles, "sous_seuil": sous_seuil,
            "bornes": list(zip(libelles, compte)), "non_conserves": non_conserves,
            "isoles": isoles}


# --- Blocs de la page --------------------------------------------------------

def _bloc_entete(s: dict, identite: dict) -> str:
    d = s.get("disque") or {}
    return f"""
<header class="entete">
  <div class="entete-titre">
    <h1>Rapport de sant\u00e9 disque</h1>
    <div class="entete-sous">{_esc(OUTIL)} \u00b7 test de surface en lecture seule, niveau {_esc(s.get('niveau'))}</div>
    <div class="entete-disque">{_esc(d.get('modele') or 'disque')} \u00b7 {_fmt_nombre(d.get('taille_go'), 1, 'Go')}</div>
  </div>
  <table class="identite">
    <tr><th>Atelier</th><td class="a-remplir">{_ou_tiret(identite.get('atelier'))}</td></tr>
    <tr><th>Date du diagnostic</th><td>{_fmt_date(s.get('demarre_a'))}</td></tr>
    <tr><th>Technicien</th><td class="a-remplir">{_ou_tiret(identite.get('technicien'))}</td></tr>
    <tr><th>Client</th><td class="a-remplir">{_ou_tiret(identite.get('client'))}</td></tr>
    <tr><th>R\u00e9f\u00e9rence dossier</th><td class="a-remplir">{_ou_tiret(identite.get('reference'))}</td></tr>
  </table>
</header>"""


def _bloc_disque(s: dict) -> str:
    d = s.get("disque") or {}
    idt = d.get("identite") or {}
    sm = d.get("smart") or {}
    serie = sm.get("numero_serie") or idt.get("numero_serie") or d.get("cle_identite")
    # Une serie en zeros ou trop courte n'est pas un numero de serie : c'est
    # ce que rend un pont USB (atelier du 09/09, deux disques en dock). On
    # le dit plutot que d'imprimer vingt zeros sur un rapport client.
    ok_serie, pourquoi = inventory.serie_solide(serie)
    if ok_serie:
        serie_html = f"<span class=\"mono\">{_esc(serie)}</span>"
    else:
        via = " par le pont USB" if d.get("bus") == "USB" else ""
        serie_html = (f"non expos\u00e9e{via} <span class=\"dim\">({_esc(pourquoi)})</span>")
    # Le type est fixe a l'inventaire, sans mesure ; le profil de debit
    # mesure ensuite peut le completer (signature mecanique calibree sur
    # 12 disques), jamais le contredire.
    type_sup = _esc(d.get("type_support")) or "\u2014"
    profil = ((s.get("synthese") or {}).get("profil_zbr") or {})
    if "indetermine" in str(d.get("type_support") or "") and profil.get("signature_mecanique"):
        type_sup += (" \u2014 profil de d\u00e9bit d\u2019un disque m\u00e9canique "
                     f"(ratio fin/d\u00e9but {_esc(profil.get('ratio_fin_debut'))})")
    lignes = [
        ("Mod\u00e8le", _ou_tiret(d.get("modele"))),
        ("Num\u00e9ro de s\u00e9rie", serie_html),
        ("Capacit\u00e9", _fmt_nombre(d.get("taille_go"), 1, "Go")),
        ("Type de support", type_sup),
        ("Bus", _ou_tiret(d.get("bus"))),
        ("Heures de fonctionnement", _fmt_nombre(sm.get("heures"), 0, "h") if sm else "non disponible (SMART absent)"),
        ("Allumages", _fmt_nombre(sm.get("cycles_demarrage")) if sm else "non disponible (SMART absent)"),
        ("Temp\u00e9rature", _fmt_nombre(sm.get("temperature"), 0, "\u00b0C") if sm else "non disponible (SMART absent)"),
    ]
    # La source de la cle n'est dite que quand elle n'est pas la meilleure :
    # un NVMe identifie par son EUI-64 IOCTL (serie smartctl absente) ou un
    # repli modele+taille doivent etre visibles sur le papier.
    if d.get("source_cle") != "smartctl" or d.get("confiance_cle") != "forte":
        lignes.append(("Identifiant retenu",
                       f"<span class=\"mono\">{_esc(d.get('cle_identite'))}</span> "
                       f"(source : {_esc(d.get('source_cle'))}, confiance {_esc(d.get('confiance_cle'))})"))
    for a in d.get("avertissements") or []:
        lignes.append(("Avertissement", _esc(a)))
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in lignes)
    return f"""
<section class="card">
  <h2>Le disque</h2>
  <table class="fiche">{rows}</table>
</section>"""


def _libelle_mode(s: dict) -> str:
    plan = s.get("plan") or {}
    mode = s.get("mode")
    n = plan.get("nb_segments")
    taille = _mib_lisible(plan.get("segment_octets"))
    if mode == "complet":
        return f"complet \u2014 toute la surface, zones contigu\u00ebs de {taille}"
    return f"{LIBELLES_MODE.get(mode, _esc(mode))} \u2014 {n} zones de {taille} r\u00e9parties sur le disque"


def _libelle_env(s: dict) -> str:
    env = s.get("environnement") or {}
    hote = env.get("hostname")
    if env.get("winpe"):
        txt = "WinPE (hors syst\u00e8me d\u2019exploitation)"
    else:
        txt = f"Windows ({_esc(env.get('windows') or '?')}) \u2014 hors WinPE"
    if hote and not env.get("hostname_inutile"):
        txt += f", h\u00f4te {_esc(hote)}"
    return txt


def _bloc_test(s: dict) -> str:
    syn = s.get("synthese") or {}
    d = s.get("disque") or {}
    statut = s.get("statut")
    couverture = (f"{_fmt_nombre(syn.get('go_lus'), 2, 'Go')} lus sur "
                  f"{_fmt_nombre(d.get('taille_go'), 1, 'Go')}, soit "
                  f"<strong>{_fmt_nombre(syn.get('couverture_disque_pct'), 2, '%')} de la surface</strong> "
                  f"({syn.get('nb_segments_mesures')} zone(s) sur {syn.get('nb_segments_prevus')})")
    if syn.get("nb_zones_incompletes"):
        couverture += (f" \u2014 dont {syn['nb_zones_incompletes']} zone(s) incompl\u00e8te(s), "
                       "lue(s) en partie seulement")
    if statut == "termine":
        etat = "termin\u00e9"
    elif statut == "arrete_securite":
        etat = f"<span class=\"crit\">arr\u00eat de s\u00e9curit\u00e9</span> \u2014 {_esc(s.get('arret'))}"
    elif statut == "interrompu":
        etat = f"<span class=\"warn\">interrompu</span> \u2014 {_esc(s.get('arret'))}"
    else:
        etat = _esc(statut)
    lignes = [
        ("Niveau", f"{_esc(s.get('niveau'))} \u2014 {_esc(s.get('mention_niveau'))}"),
        ("Mode", _libelle_mode(s)),
        ("Surface r\u00e9ellement lue", couverture),
        ("Dur\u00e9e", _fmt_duree(s.get("duree_s"))),
        ("Environnement", _libelle_env(s)),
        ("D\u00e9roulement", etat),
    ]
    reprises = s.get("reprises") or []
    if reprises:
        lignes.append(("Reprises", f"{len(reprises)} reprise(s) apr\u00e8s interruption, "
                                   f"derni\u00e8re le {_fmt_date(reprises[-1])}"))
    rows = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in lignes)
    return f"""
<section class="card">
  <h2>Le test</h2>
  <table class="fiche">{rows}</table>
</section>"""


def phrase_portee(s: dict) -> str:
    """La phrase qui suit OBLIGATOIREMENT le mot du verdict (spec, section 4).
    Rendue en HTML deja echappe."""
    v = s.get("verdict") or {}
    etat = v.get("etat")
    if etat == "sain":
        complete = (" \u2014 surface compl\u00e8te, toutes les zones lues en entier"
                    if v.get("portee") == "surface complete" else "")
        return (f"sur la surface effectivement lue : "
                f"<strong>{_fmt_nombre(v.get('couverture_disque_pct'), 2, '%')} du disque, "
                f"mode {_esc(s.get('mode'))}</strong>{complete}")
    if etat == "non_concluant":
        raisons = [r for r in (v.get("raisons") or [])] or ["raison absente de la session"]
        return " ; ".join(_esc(r) for r in raisons)
    return VERDICTS.get(etat, {}).get("portee", "")


def _bloc_verdict(s: dict) -> str:
    v = s.get("verdict") or {}
    env = s.get("environnement") or {}
    etat = v.get("etat")
    info = VERDICTS.get(etat) or {"titre": _esc(etat), "classe": "info"}
    portee = phrase_portee(s)
    raisons = ""
    if v.get("raisons") and etat != "non_concluant":
        raisons = "<ul class=\"raisons\">" + "".join(
            f"<li>{_esc(r)}</li>" for r in v["raisons"]) + "</ul>"
    notes = ""
    # La note << sain sur l'echantillon lu >> de la session redit la phrase
    # de portee obligatoire juste au-dessus : on ne l'imprime pas deux fois.
    utiles = [n for n in (v.get("notes") or []) if not str(n).startswith("sain sur l'echantillon")]
    if utiles:
        notes = "<ul class=\"notes\">" + "".join(
            f"<li>{_esc(n)}</li>" for n in utiles) + "</ul>"
    if v.get("portee") == "surface complete":
        etendue = "surface compl\u00e8te : toutes les zones du disque ont \u00e9t\u00e9 lues en entier"
    else:
        etendue = (f"\u00e9chantillon : {_fmt_nombre(v.get('couverture_disque_pct'), 2, '%')} "
                   f"de la surface, mode {_esc(s.get('mode'))}")
    etendue = (f"<p class=\"verdict-etendue\">Port\u00e9e du test \u2014 {etendue}</p>"
               if etat != "sain" else "")
    hors_pe = ""
    if not env.get("conclusion_latence_autorisee"):
        hors_pe = ("<p class=\"alert-box alert-warn\"><span class=\"label\">Mesure hors WinPE :</span> "
                   "les latences ont \u00e9t\u00e9 mesur\u00e9es mais ne concluent pas (l\u2019activit\u00e9 "
                   "de fond du syst\u00e8me pollue les maximums). Seuls les secteurs illisibles et le "
                   "d\u00e9bit sont concluants.</p>")
    return f"""
<section class="verdict verdict-{info['classe']}">
  <div class="verdict-mot"><span class="badge badge-{info['classe']}">Verdict</span> {info['titre']}</div>
  <p class="verdict-portee">{portee}</p>
  {etendue}{raisons}{notes}{hors_pe}
</section>"""


def _svg_courbe(s: dict) -> str:
    """Courbe du debit par zone, en SVG en ligne. Les zones degradees et sous
    le plancher sont pointees ; le plancher de la classe est trace quand la
    comparaison a un sens (pas derriere un pont USB)."""
    syn = s.get("synthese") or {}
    d = s.get("disque") or {}
    courbe = [(x, y) for x, y in (syn.get("courbe_debit") or []) if y]
    if not courbe:
        return "<p class=\"dim\">Aucune zone lue sans erreur : pas de courbe de d\u00e9bit.</p>"
    W, H, ML, MR, MT, MB = 720, 135, 70, 12, 8, 24
    taille = float(d.get("taille_go") or max(x for x, _ in courbe) or 1.0)
    plancher = scan.DEBIT_MIN_CLASSE_MO_S.get(d.get("classe"))
    usb = any("USB" in a for a in (d.get("avertissements") or []))
    ymax = max(y for _, y in courbe)
    if plancher and not usb:
        ymax = max(ymax, plancher)
    ymax = ymax * 1.1 or 1.0

    def X(go):
        return ML + (float(go) / taille) * (W - ML - MR)

    def Y(v):
        return MT + (1.0 - float(v) / ymax) * (H - MT - MB)

    pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in courbe)
    out = [f"<svg class=\"courbe\" viewBox=\"0 0 {W} {H}\" role=\"img\" "
           "aria-label=\"D\u00e9bit de lecture par zone\">"]
    # Grille et axes
    for frac in (0.0, 0.5, 1.0):
        yv = ymax * frac
        out.append(f"<line class=\"grille\" x1=\"{ML}\" y1=\"{Y(yv):.1f}\" x2=\"{W - MR}\" y2=\"{Y(yv):.1f}\"/>")
        unite = " Mo/s" if frac == 1.0 else ""
        out.append(f"<text class=\"axe\" x=\"{ML - 4}\" y=\"{Y(yv) + 4:.1f}\" text-anchor=\"end\">"
                   f"{_fmt_nombre(yv, 0)}{unite}</text>")
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        xv = taille * frac
        out.append(f"<text class=\"axe\" x=\"{X(xv):.1f}\" y=\"{H - 8}\" text-anchor=\"middle\">"
                   f"{_fmt_nombre(xv, 0)} Go</text>")
    if plancher and not usb:
        out.append(f"<line class=\"plancher\" x1=\"{ML}\" y1=\"{Y(plancher):.1f}\" "
                   f"x2=\"{W - MR}\" y2=\"{Y(plancher):.1f}\"/>")
        out.append(f"<text class=\"axe plancher-txt\" x=\"{W - MR}\" y=\"{Y(plancher) - 3:.1f}\" "
                   f"text-anchor=\"end\">plancher {_esc(d.get('classe'))} {_fmt_nombre(plancher, 0)} Mo/s</text>")
    if len(courbe) == 1:
        x, y = courbe[0]
        out.append(f"<circle class=\"point\" cx=\"{X(x):.1f}\" cy=\"{Y(y):.1f}\" r=\"3\"/>")
    else:
        out.append(f"<polyline class=\"trace\" points=\"{pts}\"/>")
    for z in syn.get("zones_degradees") or []:
        y = next((v for x, v in courbe if x == z.get("offset_go")), None)
        if y:
            out.append(f"<circle class=\"zone-degradee\" cx=\"{X(z['offset_go']):.1f}\" cy=\"{Y(y):.1f}\" r=\"4\"/>")
    for z in syn.get("zones_sous_plancher") or []:
        if z.get("debit_mo_s"):
            out.append(f"<circle class=\"zone-plancher\" cx=\"{X(z['offset_go']):.1f}\" "
                       f"cy=\"{Y(z['debit_mo_s']):.1f}\" r=\"4\"/>")
    out.append("</svg>")
    return "".join(out)


def _svg_histogramme(h: dict) -> str:
    """Barres horizontales : une par borne calculable, plus la part sous le
    seuil de zone et, s'il y en a, les blocs lents dont le temps n'est pas
    dans la session. L'echelle est en part du total, avec un minimum visible
    pour qu'un seul bloc a 500 ms ne disparaisse pas."""
    total = max(1, int(h.get("total") or 0))
    lignes = [("sous le seuil d\u2019anomalie de leur zone", h.get("sous_seuil") or 0, "ok")]
    classes = ("warn", "warn", "crit", "crit")
    for (lib, n), cl in zip(h.get("bornes") or [], classes):
        lignes.append((lib, n, cl))
    if h.get("non_conserves"):
        lignes.append(("blocs lents dont le temps n\u2019a pas \u00e9t\u00e9 conserv\u00e9", h["non_conserves"], "warn"))
    if h.get("illisibles"):
        lignes.append(("blocs illisibles", h["illisibles"], "crit"))
    W, LH, ML, MR = 720, 13, 250, 90
    H = LH * len(lignes) + 6
    out = [f"<svg class=\"histo\" viewBox=\"0 0 {W} {H}\" role=\"img\" "
           "aria-label=\"R\u00e9partition des blocs par latence\">"]
    for i, (lib, n, cl) in enumerate(lignes):
        y = 3 + i * LH
        part = float(n) / total
        largeur = (W - ML - MR) * part
        if n and largeur < 3:
            largeur = 3
        out.append(f"<text class=\"axe\" x=\"{ML - 6}\" y=\"{y + 12}\" text-anchor=\"end\">{_esc(lib)}</text>")
        out.append(f"<rect class=\"barre barre-{cl}\" x=\"{ML}\" y=\"{y + 2}\" width=\"{largeur:.1f}\" height=\"{LH - 6}\"/>")
        pct = f"{part * 100:.2f}".replace(".", ",")
        out.append(f"<text class=\"axe\" x=\"{ML + largeur + 6:.1f}\" y=\"{y + 12}\">"
                   f"{_fmt_nombre(n)} ({pct} %)</text>")
    out.append("</svg>")
    return "".join(out)


def _bloc_mesure(s: dict) -> str:
    syn = s.get("synthese") or {}
    d = s.get("disque") or {}
    la = s.get("lecture_aleatoire") or {}
    h = histogramme_latences(s)
    usb = any("USB" in a for a in (d.get("avertissements") or []))
    plancher = scan.DEBIT_MIN_CLASSE_MO_S.get(d.get("classe"))
    chiffres = (f"D\u00e9bit s\u00e9quentiel m\u00e9dian <strong>{_fmt_nombre(syn.get('debit_median_mo_s'), 1, 'Mo/s')}</strong> "
                f"(min {_fmt_nombre(syn.get('debit_min_mo_s'), 1)}, max {_fmt_nombre(syn.get('debit_max_mo_s'), 1)}) "
                f"\u00b7 bloc le plus lent {_fmt_nombre(syn.get('bloc_max_ms'), 1, 'ms')}")
    if la:
        chiffres += (f" \u00b7 lecture al\u00e9atoire {_esc(la.get('taille_lecture'))} o : "
                     f"p50 {_fmt_nombre(la.get('p50_ms'), 2, 'ms')}, p99 {_fmt_nombre(la.get('p99_ms'), 2, 'ms')}, "
                     f"max {_fmt_nombre(la.get('max_ms'), 2, 'ms')}")
    if usb:
        classe = d.get("classe")
        a_quoi = ("\u00e0 une classe de support" if classe in (None, "", "inconnue")
                  else f"\u00e0 la classe {_esc(classe)}")
        comparaison = ("<p class=\"alert-box alert-info\"><span class=\"label\">D\u00e9bit non compar\u00e9 "
                       f"{a_quoi} :</span> le disque est derri\u00e8re un pont USB, "
                       "le lien plafonne le d\u00e9bit ind\u00e9pendamment de l\u2019\u00e9tat du disque. "
                       "Aucun plancher de classe n\u2019est appliqu\u00e9.</p>")
    elif plancher:
        comparaison = (f"<p class=\"dim\">Plancher de la classe {_esc(d.get('classe'))} : "
                       f"{_fmt_nombre(plancher, 0, 'Mo/s')} (ligne pointill\u00e9e), volontairement bas : "
                       "un disque lent n\u2019est pas un disque malade.</p>")
    else:
        comparaison = "<p class=\"dim\">Classe de support ind\u00e9termin\u00e9e : aucun plancher de d\u00e9bit appliqu\u00e9.</p>"
    limite = ("<p class=\"dim\">Bornes 5 / 10 / 25 / 50 / 150 / 500 ms par Mio (celles de l\u2019outil de "
              "comparaison). Le temps de chaque bloc n\u2019est pas conserv\u00e9 : les bornes 5 et 10 ms ne sont "
              "pas calculables, ces blocs sont compt\u00e9s sous le seuil d\u2019anomalie de leur zone "
              f"(3\u00d7 sa m\u00e9diane, au moins {_fmt_nombre(scan.PLANCHER_ANOMALIE_MS, 0)} ms).</p>")
    return f"""
<section class="card">
  <h2>La mesure</h2>
  <p>{chiffres}</p>
  <h3>D\u00e9bit de lecture par zone</h3>
  {_svg_courbe(s)}
  {comparaison}
  <h3>R\u00e9partition des {_fmt_nombre(h['total'])} blocs de {_mib_lisible((s.get('plan') or {}).get('bloc_octets'))} par latence</h3>
  {_svg_histogramme(h)}
  {limite}
</section>"""


def _bloc_smart(s: dict) -> str:
    d = s.get("disque") or {}
    sm = d.get("smart") or {}
    if not sm:
        raison = (d.get("smart_absence")
                  or "raison non enregistr\u00e9e par la version de l\u2019outil qui a mesur\u00e9")
        return f"""
<section class="card">
  <h2>SMART</h2>
  <p class="alert-box alert-warn"><span class="label">SMART indisponible pour ce disque.</span>
  {_esc(raison)}</p>
  <p class="dim">Le test de surface ci-dessus est alors la seule source : aucun compteur d\u2019usure ou
  de secteurs r\u00e9allou\u00e9s n\u2019a pu \u00eatre lu.</p>
</section>"""
    attrs = sm.get("attributs_ata") or {}
    if sm.get("smart_actif") is True:
        etat = "<span class=\"ok\">auto-\u00e9valuation du disque : PASSED</span> \u2014 ce drapeau ne suffit pas, les compteurs bruts font foi"
    elif sm.get("smart_actif") is False:
        etat = "<span class=\"crit\">auto-\u00e9valuation du disque : FAILED</span>"
    else:
        etat = "auto-\u00e9valuation non lue"
    # Une cellule par compteur, en grille : la table a trois colonnes
    # coutait 120 px et faisait deborder un disque sain sur une 2e page.
    cellules = []
    for num, cle, lib, gravite in ATTRIBUTS_SMART:
        v = attrs.get(cle)
        if v is None:
            if not attrs and sm.get("nvme"):
                continue
            cellules.append(f"<div class=\"smart-cell\"><span class=\"smart-id\">{num}</span>{lib}"
                            f"<span class=\"smart-val dim\">non expos\u00e9</span></div>")
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            n = None
        if n is not None and n > 0:
            cellules.append(f"<div class=\"smart-cell smart-{gravite}\"><span class=\"smart-id\">{num}</span>{lib}"
                            f"<span class=\"smart-val {gravite}\">{_fmt_nombre(n)}</span></div>")
        else:
            cellules.append(f"<div class=\"smart-cell\"><span class=\"smart-id\">{num}</span>{lib}"
                            f"<span class=\"smart-val\">{_esc(v)}</span></div>")
    nvme = sm.get("nvme") or {}
    if nvme:
        for lib, cle, gravite in (("Erreurs m\u00e9dia", "erreurs_media", "crit"),
                                  ("Avertissement critique", "avertissement_critique", "crit"),
                                  ("R\u00e9serve disponible (%)", "reserve_disponible_pct", "ok")):
            v = nvme.get(cle)
            cl = gravite if (isinstance(v, (int, float)) and v and gravite != "ok") else ""
            cellules.append(f"<div class=\"smart-cell{' smart-' + cl if cl else ''}\"><span class=\"smart-id\">NVMe</span>{lib}"
                            f"<span class=\"smart-val {cl}\">{_ou_tiret(v)}</span></div>")
    usure = ""
    if sm.get("usure_nvme_pct") is not None:
        usure = f"<p>Usure d\u00e9clar\u00e9e par le SSD : <strong>{_fmt_nombre(sm['usure_nvme_pct'], 0, '%')}</strong>"
        if d.get("usure"):
            usure += (f" \u2014 projection : environ {_fmt_nombre(d['usure'].get('annees_restantes_estimees'), 1)} an(s) "
                      "restant(s) <em>(projection lin\u00e9aire, usage constant : ce n\u2019est pas une garantie)</em>")
        usure += ".</p>"
    raid = ""
    if sm.get("muet_controleur_raid"):
        raid = ("<p class=\"alert-box alert-info\"><span class=\"label\">Contr\u00f4leur RAID/RST :</span> "
                "SMART partiellement muet, le test de surface est la source principale.</p>")
    table = f"<div class=\"smart-grille\">{''.join(cellules)}</div>" if cellules else ""
    return f"""
<section class="card">
  <h2>SMART \u2014 compteurs bruts</h2>
  <p>{etat}</p>
  {table}{usure}{raid}
</section>"""


def _zones_grappes(s: dict) -> list:
    """Zones avec des blocs lents retenus (grappes) ou des secteurs illisibles,
    avec la position des premiers blocs."""
    out = []
    for z in s.get("segments") or []:
        if not (z.get("nb_blocs_anormaux") or z.get("nb_blocs_illisibles")):
            continue
        positions = [f"{a['offset'] / 1e9:.2f}" for a in (z.get("anomalies") or [])[:4]]
        out.append({"index": z.get("index"), "offset_go": z.get("offset_go"),
                    "nb": z.get("nb_blocs_anormaux") or 0,
                    "max_ms": z.get("bloc_max_ms"), "mourants": z.get("nb_blocs_mourants") or 0,
                    "illisibles": z.get("nb_secteurs_illisibles") or 0,
                    "plages": z.get("plages_illisibles") or [],
                    "positions": positions})
    return out


def _bloc_zones(s: dict) -> str:
    """Bloc affiche SEULEMENT s'il y a quelque chose a detailler."""
    syn = s.get("synthese") or {}
    degr = syn.get("zones_degradees") or []
    sous = syn.get("zones_sous_plancher") or []
    grappes = _zones_grappes(s)
    if not (degr or sous or grappes):
        return ""
    parts = []

    def _abrege(lignes, n):
        reste = n - len(lignes)
        return (f"<tr><td colspan=\"4\" class=\"dim\">\u2026 et {reste} autre(s) zone(s)</td></tr>"
                if reste > 0 else "")

    if degr:
        rows = "".join(
            f"<tr><td>{z['index'] + 1}</td><td>{_fmt_nombre(z['offset_go'], 1, 'Go')}</td>"
            f"<td>{_fmt_nombre(z['bloc_median_ms'], 1, 'ms')} par bloc</td><td>{_esc(z['ratio'])}\u00d7 la r\u00e9f\u00e9rence</td></tr>"
            for z in degr[:MAX_LIGNES_ZONES])
        parts.append(f"<h3>Zones uniform\u00e9ment lentes ({len(degr)})</h3>"
                     "<p class=\"dim\">M\u00e9diane de la zone \u00e0 plus de 4\u00d7 celle du quart le plus rapide du disque "
                     f"({_fmt_nombre(syn.get('reference_zones_ms'), 2, 'ms')} par bloc).</p>"
                     f"<table class=\"zones\"><tr><th>Zone</th><th>Position</th><th>M\u00e9diane</th><th>Ratio</th></tr>{rows}{_abrege(degr[:MAX_LIGNES_ZONES], len(degr))}</table>")
    if sous:
        rows = "".join(
            f"<tr><td>{z['index'] + 1}</td><td>{_fmt_nombre(z['offset_go'], 1, 'Go')}</td>"
            f"<td>{_fmt_nombre(z['debit_mo_s'], 1, 'Mo/s')}</td><td></td></tr>"
            for z in sous[:MAX_LIGNES_ZONES])
        parts.append(f"<h3>Zones sous le plancher de la classe ({len(sous)})</h3>"
                     f"<table class=\"zones\"><tr><th>Zone</th><th>Position</th><th>D\u00e9bit</th><th></th></tr>{rows}{_abrege(sous[:MAX_LIGNES_ZONES], len(sous))}</table>")
    if grappes:
        rows = []
        for z in grappes[:MAX_LIGNES_ZONES]:
            detail = []
            if z["nb"]:
                detail.append(f"{z['nb']} bloc(s) lent(s) en grappe, max {_fmt_nombre(z['max_ms'], 0, 'ms')}"
                              + (f" \u00e0 {', '.join(z['positions'])} Go" if z["positions"] else ""))
            if z["mourants"]:
                detail.append(f"<span class=\"crit\">{z['mourants']} bloc(s) au-del\u00e0 de 500 ms</span>")
            if z["illisibles"]:
                lbas = ", ".join(f"LBA {p.get('lba')} ({p.get('secteurs')} sect.)" for p in z["plages"][:3])
                detail.append(f"<span class=\"crit\">{z['illisibles']} secteur(s) illisible(s)</span>"
                              + (f" : {lbas}" if lbas else ""))
            rows.append(f"<tr><td>{z['index'] + 1}</td><td>{_fmt_nombre(z['offset_go'], 1, 'Go')}</td>"
                        f"<td colspan=\"2\">{' \u00b7 '.join(detail)}</td></tr>")
        parts.append(f"<h3>Grappes de blocs lents et secteurs illisibles ({len(grappes)} zone(s))</h3>"
                     f"<table class=\"zones\"><tr><th>Zone</th><th>Position</th><th colspan=\"2\">D\u00e9tail</th></tr>{''.join(rows)}{_abrege(grappes[:MAX_LIGNES_ZONES], len(grappes))}</table>")
    return f"""
<section class="card page-suivante">
  <h2>Les zones \u00e0 probl\u00e8me</h2>
  {''.join(parts)}
</section>"""


def _consigne(s: dict) -> str:
    v = s.get("verdict") or {}
    etat = v.get("etat")
    if etat in CONSIGNES:
        return CONSIGNES[etat]
    # Non concluant : dire ce qu'il faut REFAIRE, pas seulement que ca n'a pas conclu.
    env = s.get("environnement") or {}
    actions = []
    if not env.get("conclusion_latence_autorisee"):
        actions.append("rejouer le balayage depuis la cl\u00e9 WinPE, hors syst\u00e8me d\u2019exploitation")
    if s.get("statut") in ("interrompu", "en_cours"):
        actions.append("terminer le balayage (reprise de la session interrompue)")
    if not actions:
        actions.append("refaire le test dans les conditions requises")
    return "Diagnostic \u00e0 compl\u00e9ter : " + " ; ".join(actions) + "."


def _bloc_pied(s: dict, identite: dict, nom_session: str) -> str:
    v = s.get("verdict") or {}
    info = VERDICTS.get(v.get("etat")) or {"classe": "info"}
    return f"""
<section class="pied">
  <div class="consigne consigne-{info['classe']}"><span class="label">Consigne :</span> {_consigne(s)}</div>
  <div class="signatures">
    <div class="case"><div class="case-titre">Technicien \u2014 signature</div><div class="case-nom">{_ou_tiret(identite.get('technicien'))}</div></div>
    <div class="case"><div class="case-titre">Tampon de l\u2019atelier</div></div>
    <div class="case"><div class="case-titre">Prix</div><div class="case-nom">\u2026\u2026\u2026\u2026\u2026\u2026 \u20ac</div></div>
  </div>
  <footer>
    Mesure r\u00e9alis\u00e9e avec {_esc(s.get('outil'))} {_esc(s.get('version'))} \u00b7 verdict \u00e9tabli avec les r\u00e8gles de
    {_esc(OUTIL)} {_esc(__version__)} \u00b7 rapport g\u00e9n\u00e9r\u00e9 le {_fmt_date(datetime.now().isoformat(timespec='seconds'))}
    \u00b7 session <span class="mono">{_esc(nom_session)}</span>
  </footer>
</section>"""


# --- Assemblage --------------------------------------------------------------

def generer_html(session: dict, identite: Optional[dict] = None,
                 nom_session: str = "") -> str:
    """Rend le HTML complet d'une session. `identite` = {client, technicien,
    reference[, atelier]} pour le rapport seulement ; a defaut, le bloc
    `dossier` de la session s'il existe. Leve RapportRefuse."""
    s = preparer(session)
    ident = dict(s.get("dossier") or {})
    for k, val in (identite or {}).items():
        if val:
            ident[k] = val
    d = s.get("disque") or {}
    titre = f"Rapport disque \u2014 {d.get('modele') or 'disque'} \u2014 {_fmt_date(s.get('demarre_a'))}"
    corps = "".join([
        _bloc_entete(s, ident),
        "<div class=\"colonnes\">", _bloc_disque(s), _bloc_test(s), "</div>",
        _bloc_verdict(s),
        _bloc_mesure(s),
        _bloc_smart(s),
        _bloc_zones(s),
        _bloc_pied(s, ident, nom_session),
    ])
    return (f"<!DOCTYPE html>\n<html lang=\"fr\">\n<head>\n<meta charset=\"utf-8\">\n"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{_esc(titre)}</title>\n<style>\n{get_css()}\n</style>\n</head>\n"
            f"<body>\n<div class=\"page\">{corps}\n</div>\n</body>\n</html>\n")


def chemin_rapport(chemin_json) -> Path:
    """Meme nom de base que la session, extension .html : le nom classe par
    disque et ne contient jamais le nom du client."""
    return Path(chemin_json).with_suffix(".html")


def ecrire_rapport(session: dict, chemin_json, identite: Optional[dict] = None) -> Path:
    """Ecrit le HTML a cote du JSON (ecriture atomique, comme la session).
    Ne touche pas au JSON."""
    cible = chemin_rapport(chemin_json)
    contenu = generer_html(session, identite, nom_session=Path(chemin_json).name)
    tmp = cible.with_suffix(".html.tmp")
    tmp.write_text(contenu, encoding="utf-8")
    tmp.replace(cible)
    return cible
