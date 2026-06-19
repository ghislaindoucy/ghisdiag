"""
Ghisdiag - Comparaison de deux sessions de bench thermique (Phase 3)

Confronte une session « avant » et une session « après » intervention
(nettoyage, changement de pâte thermique) :

  - controle que les deux suivent le MEME protocole (sinon comparaison invalide) ;
  - calcule la carte des gains (ΔT repos / max / plateau, Δ retour au calme,
    throttling eliminé) ;
  - rend un verdict clair pour le client ;
  - genere un rapport HTML autonome (CSS + courbes SVG superposees en ligne),
    hors-ligne et imprimable.

Garde-fou honnêteté : la température ambiante n'est pas contrôlée. La mesure la
plus fiable est le **ΔT** (écart à la température de repos), insensible à la
température de la pièce, contrairement aux températures absolues.
"""

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Palette Catppuccin Mocha (alignée sur assets/report.css et main.py)
_BG = "#1e1e2e"; _SURFACE = "#313244"; _SURFACE2 = "#45475a"
_FG = "#cdd6f4"; _FG_DIM = "#9399b2"; _FG_MUTED = "#6c7086"
_ACCENT = "#89b4fa"; _GREEN = "#a6e3a1"; _YELLOW = "#f9e2af"
_RED = "#f38ba8"; _ORANGE = "#fab387"
_ZONE_IDLE = "#2a2b3c"; _ZONE_LOAD = "#3a2a30"; _ZONE_COOL = "#27314a"

_LABELS_FR = {"avant": "Avant", "apres": "Après", "libre": "Libre"}


# --- Aides ------------------------------------------------------------------

def _cfg(session: dict) -> dict:
    return session.get("config", {}) or {}


def _metric(session: dict, key: str):
    return (session.get("metrics") or {}).get(key)


def _protocol(session: dict) -> tuple:
    c = _cfg(session)
    return (int(c.get("idle_sec", 0)), int(c.get("load_sec", 0)),
            int(c.get("cooldown_sec", 0)), int(c.get("intensity", 0)))


def _session_total(session: dict) -> int:
    c = _cfg(session)
    return int(c.get("idle_sec", 0)) + int(c.get("load_sec", 0)) + int(c.get("cooldown_sec", 0))


def _assign_roles(s1: dict, s2: dict) -> tuple:
    """Détermine (avant, après) à partir des étiquettes, sinon chronologiquement."""
    l1, l2 = s1.get("label"), s2.get("label")
    if l1 == "avant" and l2 == "apres":
        return s1, s2
    if l1 == "apres" and l2 == "avant":
        return s2, s1
    t1, t2 = s1.get("started_at", ""), s2.get("started_at", "")
    return (s1, s2) if t1 <= t2 else (s2, s1)


def _gain(before, after):
    """Gain = avant - après (positif = amélioration : plus froid / plus rapide)."""
    if before is None or after is None:
        return None
    return round(before - after, 1)


# --- Comparaison ------------------------------------------------------------

def compare_sessions(s1: dict, s2: dict) -> dict:
    """Compare deux sessions. Retourne un dict avec compatibilité, gains, verdict."""
    before, after = _assign_roles(s1, s2)
    compatible = _protocol(before) == _protocol(after)

    keys = ("idle_c", "load_max_c", "load_plateau_c", "delta_c", "cooldown_sec")
    gains = {}
    for k in keys:
        b, a = _metric(before, k), _metric(after, k)
        gains[k] = {"before": b, "after": a, "gain": _gain(b, a)}

    thr_b = bool(_metric(before, "throttling"))
    thr_a = bool(_metric(after, "throttling"))
    throttling = {"before": thr_b, "after": thr_a,
                  "eliminated": thr_b and not thr_a,
                  "appeared": (not thr_b) and thr_a}

    verdict_text, verdict_level = _verdict(gains, throttling)

    return {
        "compatible": compatible,
        "protocol_before": _protocol(before),
        "protocol_after": _protocol(after),
        "before": before,
        "after": after,
        "gains": gains,
        "throttling": throttling,
        "verdict": verdict_text,
        "verdict_level": verdict_level,
    }


def _verdict(gains: dict, throttling: dict) -> tuple:
    """Verdict client + niveau (ok | warn | crit). Basé sur le plateau en charge."""
    key = gains["load_plateau_c"]["gain"]
    if key is None:
        key = gains["load_max_c"]["gain"]
    elim = throttling["eliminated"]
    appeared = throttling["appeared"]

    if key is None:
        return ("Comparaison incomplète — données de charge manquantes", "warn")

    if appeared:
        return (f"Throttling apparu après intervention — à surveiller", "crit")
    if key >= 5:
        msg = f"−{key:.0f} °C en charge — intervention efficace"
        if elim:
            msg += " (throttling éliminé)"
        return (msg, "ok")
    if key >= 2:
        msg = f"−{key:.0f} °C en charge — gain modéré"
        if elim:
            msg = f"Throttling éliminé, −{key:.0f} °C en charge — intervention utile"
            return (msg, "ok")
        return (msg, "ok")
    if key > -2:
        if elim:
            return ("Throttling éliminé (températures stables) — intervention utile", "ok")
        return ("Pas de gain thermique notable — dans la marge de mesure", "warn")
    return (f"+{-key:.0f} °C en charge — dégradation", "crit")


# --- Courbes SVG ------------------------------------------------------------

def _cpu_series(session: dict) -> list:
    return [(s.get("t", 0), s.get("cpu")) for s in (session.get("samples") or [])
            if s.get("cpu") is not None]


def _svg_compare(before: dict, after: dict) -> str:
    W, H = 920, 380
    ml, mr, mt, mb = 48, 16, 26, 30
    x0, y0, x1, y1 = ml, mt, W - mr, H - mb
    pw, ph = x1 - x0, y1 - y0
    tmax = 100.0
    total = max(1, _session_total(after), _session_total(before))

    def X(t):
        return round(x0 + (max(0.0, min(t, total)) / total) * pw, 1)

    def Y(v):
        return round(y1 - (max(0.0, min(v, tmax)) / tmax) * ph, 1)

    p = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" '
         f'style="width:100%;height:auto;font-family:Segoe UI,sans-serif">']

    # Zones de phase (protocole de l'« après », identique à l'« avant »)
    c = _cfg(after)
    b1 = int(c.get("idle_sec", 0))
    b2 = b1 + int(c.get("load_sec", 0))
    for a, b, col in ((0, b1, _ZONE_IDLE), (b1, b2, _ZONE_LOAD), (b2, total, _ZONE_COOL)):
        p.append(f'<rect x="{X(a)}" y="{y0}" width="{X(b) - X(a)}" '
                 f'height="{ph}" fill="{col}"/>')

    # Grille température
    for temp in (0, 25, 50, 75, 100):
        yy = Y(temp)
        p.append(f'<line x1="{x0}" y1="{yy}" x2="{x1}" y2="{yy}" '
                 f'stroke="{_SURFACE2}" stroke-width="1"/>')
        p.append(f'<text x="{x0 - 6}" y="{yy + 4}" fill="{_FG_MUTED}" '
                 f'font-size="11" text-anchor="end">{temp}</text>')

    # Ligne d'arrêt d'urgence
    ye = Y(95)
    p.append(f'<line x1="{x0}" y1="{ye}" x2="{x1}" y2="{ye}" stroke="{_RED}" '
             f'stroke-width="1" stroke-dasharray="5,3"/>')
    p.append(f'<text x="{x1 - 2}" y="{ye - 5}" fill="{_RED}" font-size="11" '
             f'text-anchor="end">95 °C</text>')

    # Repères de temps
    for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
        t = total * frac
        mm = int(t) // 60
        ss = int(t) % 60
        p.append(f'<text x="{X(t)}" y="{y1 + 16}" fill="{_FG_MUTED}" font-size="11" '
                 f'text-anchor="middle">{mm}:{ss:02d}</text>')

    # Cadre
    p.append(f'<rect x="{x0}" y="{y0}" width="{pw}" height="{ph}" fill="none" '
             f'stroke="{_SURFACE2}" stroke-width="1"/>')

    # Courbes CPU superposées
    def polyline(series, color, dash=""):
        if len(series) < 2:
            return
        pts = " ".join(f"{X(t)},{Y(v)}" for t, v in series)
        d = f' stroke-dasharray="{dash}"' if dash else ""
        p.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                 f'stroke-width="2"{d}/>')

    polyline(_cpu_series(before), _ORANGE, dash="6,3")
    polyline(_cpu_series(after), _GREEN)

    # Légende
    lx, ly = x0 + 10, y0 + 14
    p.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 22}" y2="{ly}" stroke="{_ORANGE}" '
             f'stroke-width="2" stroke-dasharray="6,3"/>')
    p.append(f'<text x="{lx + 28}" y="{ly + 4}" fill="{_FG_DIM}" font-size="12">Avant (CPU)</text>')
    p.append(f'<line x1="{lx + 120}" y1="{ly}" x2="{lx + 142}" y2="{ly}" stroke="{_GREEN}" '
             f'stroke-width="2"/>')
    p.append(f'<text x="{lx + 148}" y="{ly + 4}" fill="{_FG_DIM}" font-size="12">Après (CPU)</text>')

    p.append("</svg>")
    return "".join(p)


# --- Rapport HTML -----------------------------------------------------------

def _deg(x) -> str:
    return f"{x:.0f} °C" if x is not None else "—"


def _gain_html(g: dict, unit="°C", lower_is_better=True) -> str:
    """Rend la valeur 'après' + le gain coloré. lower_is_better : T et temps."""
    after = g["after"]; gain = g["gain"]
    if after is None:
        main = "—"
    elif unit == "s":
        main = f"{after:.0f} s"
    else:
        main = f"{after:.0f} {unit}"
    if gain is None:
        sub = "avant —"
    else:
        before = g["before"]
        bstr = f"{before:.0f} {unit}" if unit != "s" else f"{before:.0f} s"
        improved = gain > 0  # gain = avant - après ; positif = baisse = mieux
        cls = "ok" if improved else ("crit" if gain < 0 else "dim")
        sign = "−" if gain > 0 else ("+" if gain < 0 else "")
        gstr = f"{sign}{abs(gain):.0f} {unit}" if unit != "s" else f"{sign}{abs(gain):.0f} s"
        sub = f'avant {bstr} · <span class="{cls}">{gstr}</span>'
    return f'<div class="card-value">{main}</div><div class="card-sub">{sub}</div>'


def generate_comparison_report(s1: dict, s2: dict, output_dir,
                               comparison: Optional[dict] = None) -> Path:
    """Génère le rapport HTML de comparaison. Retourne le chemin du fichier."""
    cmp = comparison or compare_sessions(s1, s2)
    before, after = cmp["before"], cmp["after"]
    g = cmp["gains"]
    thr = cmp["throttling"]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out / f"Ghisdiag_bench_comparaison_{ts}.html"

    def when(s):
        try:
            return datetime.fromisoformat(s["started_at"]).strftime("%d/%m/%Y %H:%M")
        except Exception:
            return "?"

    machine = html.escape(str((after.get("machine") or {}).get("hostname", "?")))
    cpu_name = html.escape(str((after.get("machine") or {}).get("cpu", "?")))
    pidle, pload, pcool, pintens = cmp["protocol_after"]

    lvl = cmp["verdict_level"]
    verdict = cmp["verdict"]

    # Cartes de gains
    cards = [
        ("ΔT en charge (clé)", _gain_html(g["delta_c"]),
         "Écart à la température de repos — insensible à la température ambiante."),
        ("T plateau (charge)", _gain_html(g["load_plateau_c"]), "Régime établi sous charge."),
        ("T max (charge)", _gain_html(g["load_max_c"]), "Pic atteint pendant la charge."),
        ("T repos", _gain_html(g["idle_c"]), "Au repos (dépend de l'ambiant)."),
        ("Retour au calme", _gain_html(g["cooldown_sec"], unit="s"),
         "Temps pour redescendre au repos après la charge."),
    ]
    cards_html = "\n".join(
        f'<div class="card"><div class="card-title">{html.escape(t)}</div>'
        f'{v}<div class="card-note">{html.escape(note)}</div></div>'
        for t, v, note in cards
    )

    # Throttling
    if thr["eliminated"]:
        thr_html = '<span class="badge badge-ok">Éliminé</span> (présent avant, absent après)'
    elif thr["appeared"]:
        thr_html = '<span class="badge badge-crit">Apparu</span> (absent avant, présent après)'
    elif thr["before"] and thr["after"]:
        thr_html = '<span class="badge badge-warn">Toujours présent</span>'
    else:
        thr_html = '<span class="badge badge-ok">Absent dans les deux cas</span>'

    incompat_html = ""
    if not cmp["compatible"]:
        incompat_html = (
            '<div class="alert alert-crit"><b>Protocoles différents.</b> '
            'Les deux sessions n\'utilisent pas la même durée ou intensité de charge : '
            'la comparaison n\'est pas fiable.</div>')

    svg = _svg_compare(before, after)

    html_doc = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ghisdiag — Comparaison bench thermique</title>
<style>{_CSS}</style></head>
<body>
<header class="header">
  <h1>🌡️ Bench thermique — Avant / Après</h1>
  <div class="header-meta">
    <span><b>Machine&nbsp;:</b> {machine}</span>
    <span><b>CPU&nbsp;:</b> {cpu_name}</span>
    <span><b>Avant&nbsp;:</b> {when(before)}</span>
    <span><b>Après&nbsp;:</b> {when(after)}</span>
  </div>
</header>

<main>
  <div class="verdict verdict-{lvl}">{html.escape(verdict)}</div>
  {incompat_html}

  <section class="section">
    <h2 class="section-title">Carte des gains</h2>
    <div class="cards">{cards_html}</div>
    <p class="line"><b>Throttling thermique&nbsp;:</b> {thr_html}</p>
  </section>

  <section class="section">
    <h2 class="section-title">Courbes superposées (température CPU)</h2>
    <div class="chart">{svg}</div>
  </section>

  <section class="section">
    <h2 class="section-title">Protocole &amp; honnêteté</h2>
    <p class="line">Protocole identique pour les deux sessions&nbsp;:
      repos {pidle}&nbsp;s → charge {pload}&nbsp;s à {pintens}&nbsp;% → refroidissement {pcool}&nbsp;s.</p>
    <div class="alert alert-info">
      La <b>température ambiante n'est pas contrôlée</b>. La mesure la plus fiable est le
      <b>ΔT</b> (écart à la température de repos)&nbsp;: il reflète l'efficacité du
      refroidissement indépendamment de la température de la pièce. Les températures
      absolues peuvent varier d'un jour à l'autre selon l'ambiant.
    </div>
  </section>
</main>

<footer>Rapport généré par <b>Ghisdiag</b> — bench thermique</footer>
</body></html>"""

    path.write_text(html_doc, encoding="utf-8")
    logger.info("Rapport de comparaison généré : %s", path)
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
.verdict-warn {{ background: #3a2e1e; color: {_YELLOW}; border-color: {_YELLOW}; }}
.verdict-crit {{ background: #3a1e1e; color: {_RED}; border-color: {_RED}; }}
.section {{ margin: 28px 0; }}
.section-title {{ font-size: 17px; font-weight: 700; color: {_ACCENT};
                 padding-bottom: 8px; border-bottom: 1px solid {_SURFACE}; margin-bottom: 16px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }}
.card {{ background: {_SURFACE}; border-radius: 8px; padding: 14px 16px; }}
.card-title {{ font-size: 11px; text-transform: uppercase; letter-spacing: .06em;
              color: {_FG_MUTED}; margin-bottom: 6px; }}
.card-value {{ font-size: 24px; font-weight: 700; color: {_FG}; }}
.card-sub {{ font-size: 12px; color: {_FG_DIM}; margin-top: 2px; }}
.card-note {{ font-size: 11px; color: {_FG_MUTED}; margin-top: 8px; }}
.line {{ margin: 10px 0; color: {_FG_DIM}; }}
.chart {{ background: {_BG}; border: 1px solid {_SURFACE2}; border-radius: 8px; padding: 12px; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }}
.badge-ok {{ background: #1e3a2e; color: {_GREEN}; }}
.badge-warn {{ background: #3a2e1e; color: {_YELLOW}; }}
.badge-crit {{ background: #3a1e1e; color: {_RED}; }}
.alert {{ border-radius: 8px; padding: 14px 18px; margin: 12px 0; border-left: 4px solid; font-size: 13px; }}
.alert-info {{ background: #1a2233; border-color: {_ACCENT}; color: {_FG_DIM}; }}
.alert-crit {{ background: #2a1521; border-color: {_RED}; color: {_FG}; }}
.ok {{ color: {_GREEN}; }} .crit {{ color: {_RED}; }} .dim {{ color: {_FG_MUTED}; }}
footer {{ text-align: center; padding: 28px; color: {_FG_MUTED}; font-size: 12px;
         border-top: 1px solid {_SURFACE}; margin-top: 24px; }}
@media print {{ body {{ background: white; color: black; }} }}
"""
