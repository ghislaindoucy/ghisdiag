"""
Ghisdiag - Pieces jointes au diagnostic IA (v2.2.0).

Mecanisme GENERIQUE : une piece jointe est un digest compact d'une mesure faite
sur le poste, rendue dans un bloc SEPARE du prompt, place AVANT le dump JSON du
diagnostic et dote de son PROPRE budget. Le prompt est plafonne a 120 000
caracteres et le JSON compact du diagnostic en frole deja 109 000 sur une
machine chargee ; la troncature coupe la FIN. Une piece jointe glissee dans
`data` serait donc la premiere sacrifiee, en silence. Ici seul le diagnostic se
tronque, jamais la piece jointe.

Premier client : le bench thermique (thermal_bench). Regles tranchees le
07/08/2026 (ROADMAP, v2.2.0) :

  - FENETRE DE FRAICHEUR : la session DU JOUR, et rien d'autre. On benche et on
    diagnostique dans la meme passe ; une fenetre plus large finirait par
    joindre un bench d'avant intervention et faire conclure l'IA sur un etat
    perime. Aucun bench du jour -> aucune piece jointe, prompt strictement
    inchange (zero regression).
  - UNE SESSION PAR CIBLE : le bench CPU ET le bench GPU sont joints quand les
    deux existent. Deux mesures independantes, et leur ecart est un signal.
  - DIGEST, jamais la session brute : metriques + verdict + une courbe
    re-echantillonnee (~20 points). Les series d'echantillons restent hors prompt.
  - LE TRI-ETAT SURVIT AU TRANSFERT : « non mesure » (charge ecourtee, test
    avorte, arret d'urgence, frequence illisible) n'est NI « oui » NI « non ».
    Aplatir ca en booleen ferait conclure « refroidissement sain » a partir d'un
    test qui n'a jamais atteint le regime etabli — le faux negatif que la
    v2.0.3 a elimine. Le digest le porte en clair et le prompt interdit d'en
    tirer un verdict.
  - AVANT/APRES : si le jour compte une session « avant » et une « apres » pour
    la meme cible, c'est le DELTA (thermal_compare) qu'on joint, pas les deux.

Le module disque (GhisdiagDisk, phase 3) se branchera sur le meme rendu :
`render_attachments` accepte n'importe quelle liste de digests.
"""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from thermal_bench import (LOAD_COMPLETE_FRACTION, idle_load_pct, idle_polluted,
                           list_sessions, load_session, phase_duration,
                           throttling_state)

logger = logging.getLogger(__name__)

# Budget PROPRE du bloc pieces jointes (caracteres). Independant des 120 000
# du prompt : on ne prend jamais sur le diagnostic, et le diagnostic ne prend
# jamais sur nous. Un digest complet avec courbe pese ~2 000 caracteres.
MAX_ATTACHMENTS_LEN = 12000
CURVE_POINTS = 20

TYPE_BENCH = "bench_thermique"
TYPE_COMPARAISON = "bench_thermique_comparaison"

_PHASE_CODE = {"idle": "R", "load": "C", "cooldown": "F"}

_ETAT_LIBELLE = {
    "complet": "test mene a son terme",
    "ecourte": "charge ecourtee avant le regime etabli",
    "avorte":  "test interrompu avant la fin",
    "urgence": "arret d'urgence : seuil de securite atteint",
}


# --- Selection des sessions du jour -----------------------------------------

def bench_dir(output_dir) -> Path:
    """Dossier des sessions de bench : <dossier de sortie>\\thermal (main.py)."""
    return Path(output_dir) / "thermal"


def _session_day(session: dict) -> Optional[date]:
    try:
        return datetime.fromisoformat(session.get("started_at")).date()
    except (TypeError, ValueError):
        return None


def sessions_du_jour(output_dir, today: Optional[date] = None) -> list[dict]:
    """Toutes les sessions demarrees AUJOURD'HUI, chargees, plus recentes en tete."""
    today = today or date.today()
    out = []
    try:
        entries = list_sessions(str(bench_dir(output_dir)))
    except Exception as exc:
        logger.debug("ai_attachments : liste des sessions impossible (%s)", exc)
        return out
    for e in entries:
        try:
            day = datetime.fromisoformat(e.get("started_at") or "").date()
        except (TypeError, ValueError):
            continue
        if day != today:
            continue
        s = load_session(e["file"])
        if s:
            s["_file"] = e["file"]
            out.append(s)
    out.sort(key=lambda s: s.get("started_at") or "", reverse=True)
    return out


def _target(session: dict) -> str:
    return (session.get("config") or {}).get("target", "cpu") or "cpu"


def selectionner(sessions: list[dict]) -> list[dict]:
    """Applique les regles : une entree par cible ; delta si avant+apres.

    Rend une liste de pieces jointes (digests) prete pour le rendu.
    """
    par_cible: dict[str, list[dict]] = {}
    for s in sessions:
        par_cible.setdefault(_target(s), []).append(s)
    out = []
    for cible in sorted(par_cible):
        lot = sorted(par_cible[cible], key=lambda s: s.get("started_at") or "", reverse=True)
        avant = next((s for s in lot if s.get("label") == "avant"), None)
        apres = next((s for s in lot if s.get("label") == "apres"), None)
        if avant is not None and apres is not None and (avant.get("started_at") or "") < (apres.get("started_at") or ""):
            out.append(digest_comparaison(avant, apres))
        else:
            out.append(digest_bench(lot[0]))
    return out


def build_attachments(output_dir, today: Optional[date] = None) -> list[dict]:
    """Point d'entree : les pieces jointes du jour pour ce dossier de sortie."""
    try:
        return selectionner(sessions_du_jour(output_dir, today))
    except Exception:
        logger.exception("ai_attachments : construction des pieces jointes")
        return []


# --- Digest d'une session ---------------------------------------------------

def _deroulement(session: dict) -> dict:
    """Etat de deroulement : ce qui rend les metriques exploitables ou non.

    Meme lecture que thermal_compare._conditions, reecrite ici pour ne pas
    dependre d'une fonction privee du module de rapport.
    """
    cfg = session.get("config") or {}
    samples = session.get("samples") or []
    metrics = session.get("metrics") or {}
    load_cfg = int(cfg.get("load_sec", 0) or 0)
    load_real = phase_duration(samples, "load")
    load_trunc = bool(metrics.get("load_truncated")) or bool(
        load_real is not None and load_cfg > 0
        and load_real < load_cfg * LOAD_COMPLETE_FRACTION)
    idle_load = metrics.get("idle_load_pct")
    if idle_load is None:
        idle_load = idle_load_pct(samples)
    if session.get("emergency"):
        etat = "urgence"
    elif session.get("aborted"):
        etat = "avorte"
    elif load_trunc:
        etat = "ecourte"
    else:
        etat = "complet"
    detail = _ETAT_LIBELLE[etat]
    if etat != "complet" and load_real is not None and load_cfg:
        detail += f" (charge {load_real:.0f} s sur {load_cfg} s prevues)"
    if session.get("abort_reason"):
        detail += f" — {session['abort_reason']}"
    return {
        "etat":                    etat,
        "detail":                  detail,
        "charge_reelle_s":         load_real,
        "charge_prevue_s":         load_cfg or None,
        "plateau_et_deltaT_valides": etat == "complet",
        "repos_pollue":            bool(idle_polluted(idle_load)),
        "charge_cpu_au_repos_pct": (round(idle_load, 1) if isinstance(idle_load, (int, float)) else None),
        "refroidissement_ecourte": bool(session.get("cooldown_truncated")),
        "trou_capteurs_max_s":     session.get("sensor_max_gap_sec"),
    }


def _tri_etat(session: dict, cible: str, cle: str) -> tuple[str, Optional[str]]:
    """('oui' | 'non' | 'non mesure', raison) pour throttling ou limite de puissance."""
    metrics = session.get("metrics") or {}
    if cle == "throttling":
        val = throttling_state(metrics, cible)
        brut = metrics.get("gpu_throttling" if cible == "gpu" else "throttling")
    else:
        brut = metrics.get("gpu_power_limited" if cible == "gpu" else "power_limited")
        val = brut
        # Meme requalification que throttling_state : un False sur une charge
        # ecourtee n'a pas ete observe assez longtemps pour valoir comme absence.
        if val is False and metrics.get("load_truncated"):
            val = None
    if val is True:
        return "oui", None
    if val is False:
        return "non", None
    trunc = _deroulement(session)["etat"] != "complet"
    if brut is not None and trunc:
        return "non mesure", "charge ecourtee avant le regime etabli"
    if trunc:
        return "non mesure", "test incomplet"
    return "non mesure", ("aucune frequence GPU exploitable" if cible == "gpu"
                          else "aucune frequence CPU exploitable")


_CLES_CPU = ("idle_c", "load_max_c", "load_plateau_c", "delta_c", "cooldown_sec",
             "fan_idle_rpm", "fan_load_rpm", "clock_max_mhz", "clock_drop_pct",
             "clock_burst_drop_pct", "cpu_load_avg", "load_ramp_sec")
_CLES_GPU = ("gpu_idle_c", "gpu_max_c", "gpu_plateau_c", "gpu_delta_c",
             "gpu_hotspot_max_c", "gpu_power_max_w", "gpu_clock_max_mhz",
             "gpu_clock_drop_pct", "gpu_cooldown_sec", "gpu_load_avg",
             "gpu_slowdown_c", "fan_idle_rpm", "fan_load_rpm")


def _courbe(session: dict, cible: str, n: int = CURVE_POINTS) -> dict:
    """~n points [t_s, phase, temp, charge %, clock MHz] sur toute la session."""
    samples = session.get("samples") or []
    if not samples:
        return {"legende": "aucun echantillon", "points": []}
    if cible == "gpu":
        k_t, k_l, k_c = "gpu", "gpu_load", "gpu_clock"
    else:
        k_t, k_l, k_c = "cpu", "cpu_load", "clock"
    n = max(2, min(n, len(samples)))
    idx = sorted({round(i * (len(samples) - 1) / (n - 1)) for i in range(n)})
    pts = []
    for i in idx:
        s = samples[i]
        def _r(v, nd=0):
            return round(v, nd) if isinstance(v, (int, float)) else None
        pts.append([_r(s.get("t")), _PHASE_CODE.get(s.get("phase"), "?"),
                    _r(s.get(k_t), 1), _r(s.get(k_l)), _r(s.get(k_c))])
    return {"legende": "[t_s, phase R=repos C=charge F=refroidissement, "
                       f"temperature_{'GPU' if cible == 'gpu' else 'CPU'}_C, charge_%, "
                       "frequence_MHz] — null = non releve",
            "points": pts}


def _heure(session: dict) -> Optional[str]:
    try:
        return datetime.fromisoformat(session["started_at"]).strftime("%H:%M")
    except (KeyError, TypeError, ValueError):
        return None


def digest_bench(session: dict) -> dict:
    """Digest compact d'une session de bench thermique (CPU ou GPU)."""
    cible = _target(session)
    cfg = session.get("config") or {}
    metrics = session.get("metrics") or {}
    thr, thr_raison = _tri_etat(session, cible, "throttling")
    pl, pl_raison = _tri_etat(session, cible, "power_limited")
    cles = _CLES_GPU if cible == "gpu" else _CLES_CPU
    mesures = {k: metrics.get(k) for k in cles if k in metrics}
    d = {
        "type":        TYPE_BENCH,
        "cible":       cible,
        "libelle":     session.get("label"),
        "date":        (_session_day(session) or "").isoformat() if _session_day(session) else None,
        "heure":       _heure(session),
        "fichier":     os.path.basename(session.get("_file") or "") or None,
        "duree_s":     session.get("duration_sec"),
        "adaptateur_gpu": (session.get("gpu_adapter") or {}).get("name"),
        "protocole": {
            "repos_s":           cfg.get("idle_sec"),
            "charge_s":          cfg.get("load_sec"),
            "refroidissement_s": cfg.get("cooldown_sec"),
            "noyau":             cfg.get("kernel"),
            "intensite_pct":     cfg.get("intensity"),
            "seuil_urgence_c":   cfg.get("gpu_emergency_temp_c" if cible == "gpu"
                                         else "emergency_temp_c"),
        },
        "deroulement": _deroulement(session),
        "mesures":     mesures,
        "throttling_thermique": thr,
        "throttling_raison":    thr_raison,
        "limite_puissance":     pl,
        "limite_puissance_raison": pl_raison,
        "courbe":      _courbe(session, cible),
    }
    return d


def digest_comparaison(avant: dict, apres: dict) -> dict:
    """Delta avant/apres via thermal_compare : gains, reserves, verdict."""
    from thermal_compare import compare_sessions
    cmp_ = compare_sessions(avant, apres)
    cible = _target(avant)

    def _tri(v):
        return "oui" if v is True else "non" if v is False else "non mesure"

    thr = cmp_.get("throttling") or {}
    return {
        "type":    TYPE_COMPARAISON,
        "cible":   cible,
        "date":    (_session_day(apres) or date.today()).isoformat(),
        "avant":   {"heure": _heure(avant), "fichier": os.path.basename(avant.get("_file") or "") or None,
                    "deroulement": _deroulement(avant)},
        "apres":   {"heure": _heure(apres), "fichier": os.path.basename(apres.get("_file") or "") or None,
                    "deroulement": _deroulement(apres)},
        "adaptateur_gpu": (apres.get("gpu_adapter") or {}).get("name"),
        "protocoles_compatibles": bool(cmp_.get("compatible")),
        "gains":   {k: {"avant": v.get("before"), "apres": v.get("after"), "gain": v.get("gain")}
                    for k, v in (cmp_.get("gains") or {}).items()},
        "gpu":     cmp_.get("gpu_extras"),
        "throttling_thermique": {"avant": _tri(thr.get("before")), "apres": _tri(thr.get("after")),
                                 "elimine": bool(thr.get("eliminated")),
                                 "apparu": bool(thr.get("appeared"))},
        "reserves": [i.get("text") for i in (cmp_.get("issues") or [])],
        "comparaison_bloquante": bool(cmp_.get("blocking")),
        "verdict": cmp_.get("verdict"),
        "niveau":  cmp_.get("verdict_level"),
    }


# --- Rendu dans le prompt ---------------------------------------------------

_ENTETE = """PIÈCES JOINTES — MESURES DU JOUR (bench thermique Ghisdiag, {date})
Ces mesures ont été faites AUJOURD'HUI sur ce poste, sous charge synthétique contrôlée (phases repos → charge → refroidissement). Elles complètent l'instantané du diagnostic : croise-les avec lui (températures, ventilateurs, âge de la machine, événements). Règles de lecture, non négociables :
- `throttling_thermique` et `limite_puissance` sont en TRI-ÉTAT : « oui », « non » ou « non mesure ». « non mesure » (charge écourtée, test avorté, arrêt d'urgence, fréquence illisible) n'est NI un oui NI un non : n'en tire AUCUN verdict, ni positif ni négatif, et dis explicitement que le point n'est pas tranché. Seul un « non » sur un test « complet » autorise « refroidissement sain ».
- `deroulement.etat` différent de « complet » ⇒ le plateau et le ΔT ne décrivent pas un régime établi (ils sont null) ; seul le maximum atteint reste une donnée. Un arrêt d'urgence est en soi un fait : le seuil de sécurité a été atteint.
- « limite_puissance : oui » est un comportement NORMAL (PL1/TDP, power cap constructeur) : ce n'est PAS un défaut de refroidissement, ne le présente jamais comme tel.
- Une comparaison avant/après « comparaison_bloquante : true » ne chiffre pas de gain : ne le fais pas à sa place, cite les réserves.
- `courbe.points` : liste de points {legende} ré-échantillonnée (~{n} points) pour donner la forme de la rampe et du plateau.

```json
{json}
```

---

"""


def render_attachments(attachments: list[dict], max_len: int = MAX_ATTACHMENTS_LEN) -> str:
    """Bloc texte pret a etre insere dans le prompt ; chaine vide si rien.

    Budget propre : au-dela de `max_len`, on retire d'abord les courbes (la
    forme est un bonus, les metriques sont l'essentiel), puis les pieces les
    moins recentes, jamais le diagnostic.
    """
    if not attachments:
        return ""
    pieces = [json.loads(json.dumps(a, default=str)) for a in attachments]
    dates = [p.get("date") for p in pieces if p.get("date")]
    legende = next((p["courbe"]["legende"] for p in pieces if p.get("courbe")), "")

    def _render(lot: list[dict]) -> str:
        return _ENTETE.format(
            date=max(dates) if dates else date.today().isoformat(),
            legende=legende or "[t_s, phase, température, charge, fréquence]",
            n=CURVE_POINTS,
            json=json.dumps(lot, separators=(",", ":"), ensure_ascii=False, default=str))

    txt = _render(pieces)
    if len(txt) <= max_len:
        return txt
    for p in pieces:
        p.pop("courbe", None)
    txt = _render(pieces)
    while len(txt) > max_len and len(pieces) > 1:
        pieces.pop()
        txt = _render(pieces)
    if len(txt) > max_len:
        logger.warning("ai_attachments : bloc tronque (%d > %d)", len(txt), max_len)
        txt = txt[:max_len] + "\n[… pièce jointe tronquée …]\n\n---\n\n"
    return txt


def resume_attachments(attachments: list[dict]) -> str:
    """Libelle court pour l'UI et le journal : « CPU 14:32 (avant/après), GPU 15:10 »."""
    if not attachments:
        return ""
    parts = []
    for a in attachments:
        cible = (a.get("cible") or "?").upper()
        if a.get("type") == TYPE_COMPARAISON:
            parts.append(f"{cible} {a['avant'].get('heure')}→{a['apres'].get('heure')} (avant/après)")
        else:
            etat = (a.get("deroulement") or {}).get("etat")
            suffixe = "" if etat == "complet" else f", {etat}"
            parts.append(f"{cible} {a.get('heure')} ({a.get('libelle')}{suffixe})")
    return ", ".join(parts)
