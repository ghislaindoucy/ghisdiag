"""
Ghisdiag - Historique des diagnostics : comparaison de deux rapports JSON

Confronte deux diagnostics complets de la MÊME machine à deux dates
différentes — la machine s'améliore ou se dégrade ?

  - garde-fou identité : même machine obligatoire (n° de série BIOS prioritaire,
    hostname en repli) — comparer deux PC différents n'a aucun sens ;
  - rôles avant/après assignés chronologiquement (meta.collected_at) ;
  - freins de performance : diff des findings du résumé exécutif
    (executive_summary du JSON, recalculés via report.exec_summary pour les
    rapports antérieurs à la v1.8.0 → l'historique marche sur d'anciens JSON) ;
  - chiffres clés durables : boot, plantages, erreurs, espace disque, usure
    SMART (disques appariés par n° de série), démarrage, pilotes ;
  - verdict pondéré HONNÊTE : seuls les freins et les métriques durables
    comptent — les mesures instantanées (CPU/RAM à l'instant T) sont montrées
    mais n'influencent jamais le verdict ;
  - rapport HTML autonome (CSS en ligne), hors-ligne et imprimable.
"""

import html
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from report.exec_summary import compute_findings

logger = logging.getLogger(__name__)

# Palette Catppuccin Mocha (alignée sur thermal_compare.py / assets/report.css)
_BG = "#1e1e2e"; _SURFACE = "#313244"; _SURFACE2 = "#45475a"
_FG = "#cdd6f4"; _FG_DIM = "#9399b2"; _FG_MUTED = "#6c7086"
_ACCENT = "#89b4fa"; _GREEN = "#a6e3a1"; _YELLOW = "#f9e2af"
_RED = "#f38ba8"; _ORANGE = "#fab387"

# Seuil de signification du verdict (points pondérés par les scores des freins)
_VERDICT_MARGIN = 30


# --- Aides ------------------------------------------------------------------

def _v(data, *keys, default=None):
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k, default)
        if data is default:
            return default
    return data if data is not None else default


def _dicts(val):
    if isinstance(val, list):
        return [x for x in val if isinstance(x, dict)]
    if isinstance(val, dict) and val:
        return [val]
    return []


def _num(val):
    return val if isinstance(val, (int, float)) and not isinstance(val, bool) else None


def load_report(path) -> Optional[dict]:
    """Charge un rapport JSON Ghisdiag. None si illisible ou pas un rapport."""
    try:
        with open(path, encoding="utf-8") as f:
            rep = json.load(f)
        if not isinstance(rep, dict) or "meta" not in rep or "data" not in rep:
            return None
        return rep
    except Exception:
        logger.exception("Chargement rapport %s", path)
        return None


def _meta(rep: dict) -> dict:
    return rep.get("meta") or {}


def _serial(rep: dict):
    s = _v(rep.get("data"), "system_info", "bios", "serial_number")
    s = str(s).strip() if s else ""
    # Les BIOS OEM sans numéro renvoient des placeholders — pas une identité.
    if s.lower() in ("", "n/a", "none", "default string", "to be filled by o.e.m.",
                     "system serial number", "0"):
        return None
    return s


def _findings(rep: dict) -> list:
    """Findings du résumé exécutif : ceux du JSON (>= v1.8.0), sinon recalculés
    depuis les données — l'historique fonctionne aussi sur d'anciens rapports."""
    stored = rep.get("executive_summary")
    if isinstance(stored, list) and all(isinstance(f, dict) and f.get("key") for f in stored):
        return stored
    return compute_findings(rep.get("data") or {})


def _latest_boot_ms(rep: dict):
    boots = [e for e in _dicts(_v(rep.get("data"), "events", "diag_perf"))
             if e.get("category") == "boot" and _num(e.get("duration_ms")) is not None]
    if not boots:
        return None
    return max(boots, key=lambda e: str(e.get("time_created") or ""))["duration_ms"]


def _crash_count(rep: dict, kind=None):
    ev = _dicts(_v(rep.get("data"), "events", "crash_events"))
    if kind:
        ev = [e for e in ev if e.get("kind") == kind]
    return len(ev)


# --- Métriques comparées ----------------------------------------------------
# (key, label, extracteur, unité, sens, durable)
#   sens : "lower" = plus bas c'est mieux ; "higher" = l'inverse
#   durable : True = compte dans le verdict ; False = instantané (indicatif)
_METRICS = (
    ("boot_ms", "Démarrage Windows (dernier mesuré)",
     _latest_boot_ms, "s", "lower", True),
    ("bsod", "Écrans bleus (14 j)",
     lambda r: _crash_count(r, "bugcheck-bsod"), "", "lower", True),
    ("crashes", "Plantages / arrêts inattendus (14 j)",
     lambda r: _crash_count(r), "", "lower", True),
    ("whea", "Erreurs matérielles WHEA (30 j)",
     lambda r: len(_dicts(_v(r.get("data"), "events", "whea_events"))), "", "lower", True),
    ("disk_errors", "Erreurs disque + NTFS (14 j)",
     lambda r: (len(_dicts(_v(r.get("data"), "events", "disk_events")))
                + len(_dicts(_v(r.get("data"), "events", "ntfs_events")))), "", "lower", True),
    ("total_errors", "Erreurs journaux (72 h)",
     lambda r: _num(_v(r.get("data"), "events", "total_errors")), "", "lower", True),
    ("c_free_gb", "Espace libre sur C:",
     lambda r: next((_num(v.get("free_gb"))
                     for v in _dicts(_v(r.get("data"), "system_info", "disks", "volumes"))
                     if str(v.get("drive_letter") or "").upper().startswith("C")), None),
     "Go", "higher", True),
    ("startup", "Programmes au démarrage",
     lambda r: (len(_v(r.get("data"), "startup", "startup_programs") or [])
                if isinstance(_v(r.get("data"), "startup", "startup_programs"), list) else None),
     "", "lower", True),
    ("drv_errors", "Pilotes en erreur",
     lambda r: _num(_v(r.get("data"), "software", "drivers", "errors_count")), "", "lower", True),
    ("drv_outdated", "Pilotes anciens (>5 ans)",
     lambda r: _num(_v(r.get("data"), "software", "drivers", "outdated_count")), "", "lower", True),
    ("ram_pct", "RAM utilisée (à l'instant du diagnostic)",
     lambda r: _num(_v(r.get("data"), "performance", "ram", "usage_percent")), "%", "lower", False),
    ("cpu_pct", "Charge CPU (à l'instant du diagnostic)",
     lambda r: _num(_v(r.get("data"), "performance", "cpu", "load_percent")), "%", "lower", False),
)

# Poids verdict des métriques durables : (seuil de changement significatif, points)
_METRIC_WEIGHTS = {
    "boot_ms":      (15_000, 40),   # ±15 s de boot
    "bsod":         (1, 80),
    "crashes":      (2, 40),
    "whea":         (1, 60),
    "disk_errors":  (1, 70),
    "total_errors": (20, 20),
    "c_free_gb":    (10, 30),       # ±10 Go
    "startup":      (5, 15),
    "drv_errors":   (1, 20),
    "drv_outdated": (2, 10),
}


def _compare_metrics(before: dict, after: dict) -> list:
    out = []
    for key, label, extract, unit, sense, durable in _METRICS:
        try:
            b, a = extract(before), extract(after)
        except Exception:
            b = a = None
        if b is None and a is None:
            continue
        trend = "same"
        if b is not None and a is not None and a != b:
            better = (a < b) if sense == "lower" else (a > b)
            trend = "improved" if better else "worsened"
        out.append({"key": key, "label": label, "before": b, "after": a,
                    "unit": unit, "sense": sense, "durable": durable,
                    "trend": trend})
    return out


def _compare_smart(before: dict, after: dict) -> list:
    """Disques appariés par n° de série : usure, réalloués, en attente.
    Un disque présent d'un seul côté est ignoré (remplacé/ajouté ≠ dégradé)."""
    def by_serial(rep):
        disks = {}
        sm = _v(rep.get("data"), "smart", default={})
        if not isinstance(sm, dict) or not sm.get("available"):
            return disks
        for d in _dicts(sm.get("disks")):
            ser = str(d.get("serial") or "").strip()
            if ser:
                disks[ser] = d
        return disks

    db, da = by_serial(before), by_serial(after)
    out = []
    for ser in sorted(set(db) & set(da)):
        b, a = db[ser], da[ser]
        entry = {"serial": ser, "model": a.get("model") or b.get("model") or "disque",
                 "fields": [], "worsened": False}
        for fkey, flabel, sense in (
                ("wear_percent", "Usure", "lower"),
                ("reallocated_sectors", "Secteurs réalloués", "lower"),
                ("pending_sectors", "Secteurs en attente", "lower"),
                ("smart_passed", "SMART", None)):
            vb, va = b.get(fkey), a.get(fkey)
            if fkey == "smart_passed":
                if vb is True and va is False:
                    entry["fields"].append({"label": flabel, "before": "OK",
                                            "after": "ÉCHEC", "trend": "worsened"})
                    entry["worsened"] = True
                continue
            vb, va = _num(vb), _num(va)
            if vb is None and va is None:
                continue
            trend = "same"
            if vb is not None and va is not None and va != vb:
                trend = "improved" if va < vb else "worsened"
                if trend == "worsened" and fkey in ("reallocated_sectors",
                                                    "pending_sectors"):
                    entry["worsened"] = True
                # +1-2 % d'usure entre deux visites = vie normale d'un SSD ;
                # seuil de 5 points avant de compter une dégradation.
                if trend == "worsened" and fkey == "wear_percent" and va - vb >= 5:
                    entry["worsened"] = True
            entry["fields"].append({"label": flabel, "before": vb, "after": va,
                                    "trend": trend})
        if entry["fields"]:
            out.append(entry)
    return out


# --- Comparaison ------------------------------------------------------------

def compare_reports(r1: dict, r2: dict) -> dict:
    """Compare deux rapports JSON Ghisdiag. Retourne compatibilité, diff des
    freins, métriques, SMART, verdict."""
    # Rôles chronologiques (collected_at = "YYYY-MM-DD HH:MM:SS", tri lexical OK)
    t1 = str(_meta(r1).get("collected_at") or "")
    t2 = str(_meta(r2).get("collected_at") or "")
    before, after = (r1, r2) if t1 <= t2 else (r2, r1)

    # Garde-fou identité : série BIOS prioritaire (le hostname se renomme),
    # hostname en repli quand une des séries manque.
    sb, sa = _serial(before), _serial(after)
    hb = str(_meta(before).get("machine") or "").strip().upper()
    ha = str(_meta(after).get("machine") or "").strip().upper()
    if sb and sa:
        same_machine = (sb == sa)
    else:
        same_machine = bool(hb and ha and hb == ha)

    fb = {f["key"]: f for f in _findings(before)}
    fa = {f["key"]: f for f in _findings(after)}
    resolved   = [fb[k] for k in fb if k not in fa]
    appeared   = [fa[k] for k in fa if k not in fb]
    persistent = [fa[k] for k in fa if k in fb]

    metrics = _compare_metrics(before, after)
    smart   = _compare_smart(before, after)

    verdict_text, verdict_level = _verdict(resolved, appeared, metrics, smart)

    return {
        "compatible": same_machine,
        "machine": _meta(after).get("machine") or _meta(before).get("machine") or "?",
        "machine_before": _meta(before).get("machine"),
        "machine_after": _meta(after).get("machine"),
        "date_before": _meta(before).get("collected_at"),
        "date_after": _meta(after).get("collected_at"),
        "before": before,
        "after": after,
        "resolved": resolved,
        "appeared": appeared,
        "persistent": persistent,
        "metrics": metrics,
        "smart": smart,
        "verdict": verdict_text,
        "verdict_level": verdict_level,
    }


def _verdict(resolved, appeared, metrics, smart) -> tuple:
    """Verdict pondéré. Seuls comptent les freins (scores du résumé exécutif)
    et les métriques DURABLES au-delà de leur seuil de signification — jamais
    les mesures instantanées."""
    imp = sum(int(f.get("score") or 0) for f in resolved)
    deg = sum(int(f.get("score") or 0) for f in appeared)

    for m in metrics:
        if not m["durable"] or m["trend"] == "same":
            continue
        thr, pts = _METRIC_WEIGHTS.get(m["key"], (1, 10))
        b, a = m["before"], m["after"]
        if b is None or a is None or abs(a - b) < thr:
            continue
        if m["trend"] == "improved":
            imp += pts
        else:
            deg += pts

    for d in smart:
        if d["worsened"]:
            deg += 80

    if deg - imp >= _VERDICT_MARGIN:
        lead = appeared[0]["title"] if appeared else None
        detail = f" — nouveau frein : {lead}" if lead else ""
        if any(d["worsened"] for d in smart):
            detail = " — un disque se dégrade (SMART), sauvegarde recommandée"
        return (f"Dégradation depuis le dernier diagnostic{detail}", "crit")
    if imp - deg >= _VERDICT_MARGIN:
        n = len(resolved)
        detail = ""
        if n:
            names = ", ".join(f.get("title", "?") for f in resolved[:2])
            detail = f" — {n} frein(s) résolu(s) ({names})"
        return (f"Amélioration nette{detail}", "ok")
    return ("Machine stable — pas de changement notable entre les deux diagnostics",
            "stable")


# --- Rapport HTML -----------------------------------------------------------

def _fmt(v, unit):
    if v is None:
        return "—"
    if unit == "s":  # valeurs stockées en ms
        return f"{v / 1000:.0f} s"
    if isinstance(v, float):
        v = round(v, 1)
    return f"{v} {unit}".strip()


def _metric_card(m: dict) -> str:
    cls = {"improved": "ok", "worsened": "crit", "same": "dim"}[m["trend"]]
    arrow = {"improved": "↘", "worsened": "↗", "same": "→"}[m["trend"]]
    if m["sense"] == "higher":  # ex. espace libre : la hausse est une amélioration
        arrow = {"improved": "↗", "worsened": "↘", "same": "→"}[m["trend"]]
    note = "" if m["durable"] else \
        '<div class="card-note">Mesure instantanée — hors verdict.</div>'
    return (f'<div class="card"><div class="card-title">{html.escape(m["label"])}</div>'
            f'<div class="card-value">{_fmt(m["after"], m["unit"])} '
            f'<span class="{cls}" style="font-size:15px">{arrow}</span></div>'
            f'<div class="card-sub">avant : {_fmt(m["before"], m["unit"])}</div>{note}</div>')


def _findings_list(items, cls, empty) -> str:
    if not items:
        return f'<p class="dim">{empty}</p>'
    lis = "".join(
        f'<li><b>{html.escape(str(f.get("title", "?")))}</b>'
        f'<br><span class="dim">{html.escape(str(f.get("constat", "")))}</span></li>'
        for f in items)
    return f'<ul class="flist {cls}">{lis}</ul>'


def generate_history_report(cmp: dict, output_dir) -> Path:
    """Génère le rapport HTML d'historique. Retourne le chemin du fichier."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    machine = str(cmp.get("machine") or "PC")
    path = out / f"Ghisdiag_historique_{machine}_{ts}.html"

    lvl = cmp["verdict_level"]
    incompat_html = ""
    if not cmp["compatible"]:
        mb = html.escape(str(cmp.get("machine_before") or "?"))
        ma = html.escape(str(cmp.get("machine_after") or "?"))
        incompat_html = (
            f'<div class="alert alert-crit"><b>Machines différentes.</b> '
            f'Le premier rapport porte sur « {mb} », le second sur « {ma} » : '
            f'l\'historique n\'a de sens que sur la même machine.</div>')

    metrics_html = "\n".join(_metric_card(m) for m in cmp["metrics"])

    smart_html = ""
    if cmp["smart"]:
        blocks = []
        for d in cmp["smart"]:
            rows = "".join(
                f"<tr><td>{html.escape(str(f['label']))}</td>"
                f"<td>{html.escape(str(f['before'] if f['before'] is not None else '—'))}</td>"
                f"<td class='{ {'improved': 'ok', 'worsened': 'crit', 'same': 'dim'}[f['trend']] }'>"
                f"{html.escape(str(f['after'] if f['after'] is not None else '—'))}</td></tr>"
                for f in d["fields"])
            badge = ('<span class="badge badge-crit">se dégrade</span>' if d["worsened"]
                     else '<span class="badge badge-ok">stable</span>')
            blocks.append(
                f'<h3 class="sub">{html.escape(str(d["model"]))} {badge}</h3>'
                f'<table class="tbl"><tr><th>Indicateur</th><th>Avant</th><th>Après</th></tr>'
                f'{rows}</table>')
        smart_html = (f'<section class="section">'
                      f'<h2 class="section-title">Santé des disques (SMART, appariés par n° de série)</h2>'
                      f'{"".join(blocks)}</section>')

    html_doc = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ghisdiag — Historique {html.escape(machine)}</title>
<style>{_CSS}</style></head>
<body>
<header class="header">
  <h1>📈 Historique des diagnostics — {html.escape(machine)}</h1>
  <div class="header-meta">
    <span><b>Avant&nbsp;:</b> {html.escape(str(cmp.get("date_before") or "?"))}</span>
    <span><b>Après&nbsp;:</b> {html.escape(str(cmp.get("date_after") or "?"))}</span>
  </div>
</header>

<main>
  <div class="verdict verdict-{lvl}">{html.escape(cmp["verdict"])}</div>
  {incompat_html}

  <section class="section">
    <h2 class="section-title">Freins de performance</h2>
    <div class="cols">
      <div><h3 class="sub ok">✅ Résolus ({len(cmp["resolved"])})</h3>
        {_findings_list(cmp["resolved"], "ok", "Aucun frein résolu.")}</div>
      <div><h3 class="sub crit">🆕 Apparus ({len(cmp["appeared"])})</h3>
        {_findings_list(cmp["appeared"], "crit", "Aucun nouveau frein — bon signe.")}</div>
      <div><h3 class="sub warn">⏳ Persistants ({len(cmp["persistent"])})</h3>
        {_findings_list(cmp["persistent"], "warn", "Aucun frein persistant.")}</div>
    </div>
  </section>

  <section class="section">
    <h2 class="section-title">Chiffres clés</h2>
    <div class="cards">{metrics_html}</div>
  </section>

  {smart_html}

  <section class="section">
    <h2 class="section-title">Honnêteté de la mesure</h2>
    <div class="alert alert-info">
      Les journaux Windows couvrent des fenêtres glissantes (72&nbsp;h à 30&nbsp;j
      avant chaque diagnostic)&nbsp;: les compteurs d'erreurs décrivent la période
      précédant chaque rapport, pas l'intervalle entre les deux. Les mesures
      instantanées (CPU/RAM au moment du diagnostic) sont affichées à titre
      indicatif et <b>n'influencent pas le verdict</b>.
    </div>
  </section>
</main>

<footer>Rapport généré par <b>Ghisdiag</b> — historique des diagnostics</footer>
</body></html>"""

    path.write_text(html_doc, encoding="utf-8")
    logger.info("Rapport d'historique généré : %s", path)
    return path


_CSS = f"""
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: {_BG}; color: {_FG}; font-family: "Segoe UI", system-ui, sans-serif;
       font-size: 14px; line-height: 1.6; padding-bottom: 32px; }}
.header {{ background: linear-gradient(135deg, #181825, {_BG}); border-bottom: 2px solid {_SURFACE};
          padding: 28px 40px; }}
.header h1 {{ font-size: 26px; color: {_ACCENT}; }}
.header-meta {{ margin-top: 8px; color: {_FG_DIM}; font-size: 13px; }}
.header-meta span {{ margin-right: 22px; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 0 24px; }}
.verdict {{ margin: 24px 0 8px; padding: 18px 22px; border-radius: 8px; font-size: 20px;
           font-weight: 700; border-left: 5px solid; }}
.verdict-ok {{ background: #1e3a2e; color: {_GREEN}; border-color: {_GREEN}; }}
.verdict-stable {{ background: #1a2233; color: {_ACCENT}; border-color: {_ACCENT}; }}
.verdict-crit {{ background: #3a1e1e; color: {_RED}; border-color: {_RED}; }}
.section {{ margin: 28px 0; }}
.section-title {{ font-size: 17px; font-weight: 700; color: {_ACCENT};
                 padding-bottom: 8px; border-bottom: 1px solid {_SURFACE}; margin-bottom: 16px; }}
.sub {{ font-size: 14px; margin: 12px 0 6px; }}
.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }}
.flist {{ list-style: none; }}
.flist li {{ background: {_SURFACE}; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
            border-left: 3px solid {_SURFACE2}; font-size: 13px; }}
.flist.ok li {{ border-left-color: {_GREEN}; }}
.flist.crit li {{ border-left-color: {_RED}; }}
.flist.warn li {{ border-left-color: {_YELLOW}; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 12px; }}
.card {{ background: {_SURFACE}; border-radius: 8px; padding: 14px 16px; }}
.card-title {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
              color: {_FG_MUTED}; margin-bottom: 6px; }}
.card-value {{ font-size: 22px; font-weight: 700; color: {_FG}; }}
.card-sub {{ font-size: 12px; color: {_FG_DIM}; margin-top: 2px; }}
.card-note {{ font-size: 11px; color: {_FG_MUTED}; margin-top: 8px; }}
.tbl {{ border-collapse: collapse; width: 100%; margin: 6px 0 14px; }}
.tbl th {{ background: {_SURFACE}; color: {_FG_DIM}; text-align: left; padding: 7px 12px; font-size: 12px; }}
.tbl td {{ padding: 7px 12px; border-bottom: 1px solid {_SURFACE}; font-size: 13px; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
.badge-ok {{ background: #1e3a2e; color: {_GREEN}; }}
.badge-crit {{ background: #3a1e1e; color: {_RED}; }}
.alert {{ border-radius: 8px; padding: 14px 18px; margin: 12px 0; border-left: 4px solid; font-size: 13px; }}
.alert-info {{ background: #1a2233; border-color: {_ACCENT}; color: {_FG_DIM}; }}
.alert-crit {{ background: #2a1521; border-color: {_RED}; color: {_FG}; }}
.ok {{ color: {_GREEN}; }} .warn {{ color: {_YELLOW}; }} .crit {{ color: {_RED}; }} .dim {{ color: {_FG_MUTED}; }}
footer {{ text-align: center; padding: 28px; color: {_FG_MUTED}; font-size: 12px;
         border-top: 1px solid {_SURFACE}; margin-top: 24px; }}
@media print {{ body {{ background: white; color: black; }} }}
"""
