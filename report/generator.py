"""
PlanetDiag - Générateur de rapport HTML et JSON
"""

import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

VERSION = "1.0.2"
AUTHORS = "Ghislain DOUCY & Claude Code"
DEFAULT_REPORTS_DIR = Path(os.path.expanduser("~")) / "Documents" / "PlanetDiag_Reports"


def get_css() -> str:
    """Charge le CSS (embarqué dans l'exe via PyInstaller, sinon fichier local)."""
    if getattr(sys, "frozen", False):
        css_path = Path(sys._MEIPASS) / "assets" / "report.css"
    else:
        css_path = Path(__file__).parent.parent / "assets" / "report.css"

    if css_path.exists():
        return css_path.read_text(encoding="utf-8")
    return ""


def _ensure_list(val) -> list:
    """Normalise une valeur en liste (gère les dicts PS1 à 1 élément sérialisé en objet)."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    if isinstance(val, dict):
        # PowerShell sérialise parfois un tableau à 1 objet sans les crochets
        return [val]
    return []


def _ensure_dicts(val) -> list:
    """Comme _ensure_list mais filtre les éléments non-dict.
    Protège contre les sérialisations PS5.1 dégénérées (DateTime → string, etc.)."""
    return [item for item in _ensure_list(val) if isinstance(item, dict)]


def _v(data: dict, *keys, default="N/A"):
    """Accès sécurisé à un chemin de clés imbriquées."""
    for k in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(k, default)
        if data is default:
            return default
    return data if data is not None else default


def _badge(value, ok_label="OK", warn_label="Attention", crit_label="Critique",
           ok_cond=True, warn_cond=False, crit_cond=False) -> str:
    if crit_cond:
        return f'<span class="badge badge-crit">{crit_label}</span>'
    if warn_cond:
        return f'<span class="badge badge-warn">{warn_label}</span>'
    return f'<span class="badge badge-ok">{ok_label}</span>'


def _pct_bar(pct: float, warn=70, crit=90) -> str:
    cls = "pbar-crit" if pct >= crit else ("pbar-warn" if pct >= warn else "pbar-ok")
    return (f'<div class="pbar-wrap"><div class="pbar {cls}" '
            f'style="width:{min(pct, 100):.0f}%"></div></div>')


def _esc(s: Any) -> str:
    """Échappement HTML complet (incluant guillemets) — protège contre XSS même en attributs."""
    if s is None:
        return ""
    return html.escape(str(s), quote=True)


# Règles d'alerte scalaires : (extracteur, condition, level, title, description)
# Pour ajouter une alerte en v1.2+ : ajouter un tuple ici, sans toucher à _analyse().
_ALERT_RULES = [
    (
        lambda d: _v(d, "performance", "ram", "usage_percent"),
        lambda v: isinstance(v, (int, float)) and v >= 90,
        "crit", "RAM critique",
        lambda v: f"Utilisation RAM à {v}%",
    ),
    (
        lambda d: _v(d, "performance", "ram", "usage_percent"),
        lambda v: isinstance(v, (int, float)) and 75 <= v < 90,
        "warn", "RAM élevée",
        lambda v: f"Utilisation RAM à {v}%",
    ),
    (
        lambda d: _v(d, "performance", "cpu", "load_percent"),
        lambda v: isinstance(v, (int, float)) and v >= 80,
        "warn", "CPU élevé",
        lambda v: f"Charge CPU à {v}%",
    ),
    (
        lambda d: _v(d, "events", "total_errors", default=0),
        lambda v: isinstance(v, int) and v >= 50,
        "crit", "Nombreuses erreurs système",
        lambda v: f"{v} erreurs/critiques en 72h",
    ),
    (
        lambda d: _v(d, "events", "total_errors", default=0),
        lambda v: isinstance(v, int) and 20 <= v < 50,
        "warn", "Erreurs système",
        lambda v: f"{v} erreurs en 72h",
    ),
    (
        lambda d: _v(d, "security", "windows_update", "pending_count", default=-1),
        lambda v: isinstance(v, int) and v > 5,
        "warn", "Mises à jour en attente",
        lambda v: f"{v} mises à jour Windows disponibles",
    ),
    (
        lambda d: _v(d, "network", "internet_ok", default=None),
        lambda v: v is False,
        "crit", "Pas de connexion Internet",
        lambda v: "Impossible de joindre 8.8.8.8",
    ),
    (
        lambda d: _v(d, "software", "drivers", "errors_count", default=0),
        lambda v: isinstance(v, int) and v > 0,
        "warn", "Drivers en erreur",
        lambda v: f"{v} driver(s) en erreur détectés",
    ),
    (
        lambda d: _v(d, "security", "logon_failures", default=0),
        lambda v: isinstance(v, int) and v >= 5,
        "warn", "Échecs d'authentification",
        lambda v: f"{v} échecs de connexion en 7 jours",
    ),
    (
        lambda d: _v(d, "security", "uac", "enabled", default=None),
        lambda v: v is False,
        "crit", "UAC désactivé",
        lambda v: "Le Contrôle de Compte Utilisateur est désactivé",
    ),
]


class ReportGenerator:
    def __init__(self, report_data: dict, output_dir: Path | None = None):
        self.report     = report_data
        self.meta       = report_data.get("meta", {})
        self.data       = report_data.get("data", {})
        self.alerts     = []  # liste (level, title, desc)
        self.output_dir = output_dir or DEFAULT_REPORTS_DIR

    def save(self) -> tuple[Path, Path]:
        """Génère et sauvegarde le rapport HTML + JSON. Retourne (html_path, json_path)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        machine  = self.meta.get("machine", "UNKNOWN")
        basename = f"PlanetDiag_{machine}_{ts}"

        html_path = self.output_dir / f"{basename}.html"
        json_path = self.output_dir / f"{basename}.json"

        html_path.write_text(self._build_html(), encoding="utf-8")
        json_path.write_text(
            json.dumps(self.report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )
        return html_path, json_path

    # ── Analyse & alertes ─────────────────────────────────────────────────────
    def _analyse(self):
        """Détecte les anomalies et peuple self.alerts."""
        d = self.data

        for extract, condition, level, title, desc in _ALERT_RULES:
            val = extract(d)
            if condition(val):
                self.alerts.append((level, title, desc(val)))

        self._analyse_disks(d)
        self._analyse_antivirus(d)
        self._analyse_firewall(d)
        self._analyse_events(d)

    def _analyse_disks(self, d: dict):
        vols = _ensure_dicts(_v(d, "system_info", "disks", "volumes", default=[]))
        for vol in vols:
            if vol.get("low_space"):
                self.alerts.append((
                    "warn",
                    f"Espace disque faible ({vol.get('drive_letter')})",
                    f"Seulement {vol.get('free_gb')} GB libres ({vol.get('used_percent')}% utilisé)",
                ))

    def _analyse_antivirus(self, d: dict):
        # Aucun AV détecté → warn
        # Aucun AV actif (tous désactivés) → crit
        # Defender désactivé + 1 tiers actif → OK (tiers gère la protection)
        # Plusieurs AV actifs simultanément → warn (conflits/perf)
        avs = _ensure_dicts(_v(d, "security", "antivirus", default=[]))
        if not avs:
            self.alerts.append(("warn", "Antivirus", "Aucun antivirus détecté via Windows Security Center"))
            return
        active_avs = [av for av in avs if av.get("realtime_enabled")]
        if not active_avs:
            names = ", ".join(av.get("name", "?") for av in avs)
            self.alerts.append(("crit", "Aucun antivirus actif",
                                 f"Aucune protection temps réel active — produits détectés : {names}"))
        elif len(active_avs) > 1:
            names = ", ".join(av.get("name", "?") for av in active_avs)
            self.alerts.append(("warn", "Plusieurs antivirus actifs simultanément",
                                 f"Conflits possibles et impact sur les performances : {names}"))

    def _analyse_firewall(self, d: dict):
        fw = _ensure_dicts(_v(d, "security", "firewall", default=[]))
        for profile in fw:
            if not profile.get("enabled"):
                self.alerts.append(("crit",
                                     f"Pare-feu désactivé ({profile.get('profile')})",
                                     "Le profil pare-feu Windows est désactivé"))

    def _analyse_events(self, d: dict):
        diag_perf = _ensure_dicts(_v(d, "events", "diag_perf", default=[]))
        boot_slow = [e for e in diag_perf if e.get("category") == "boot"]
        if boot_slow:
            self.alerts.append(("warn", "Démarrage Windows lent détecté",
                                 f"{len(boot_slow)} événement(s) de ralentissement au démarrage sur 30 jours"))

        gpo_events = _ensure_dicts(_v(d, "events", "gpo_events", default=[]))
        gpo_errors = [e for e in gpo_events if e.get("level") == "Error"]
        if gpo_errors:
            self.alerts.append(("warn", "Erreurs Stratégie de groupe (GPO)",
                                 f"{len(gpo_errors)} erreur(s) GPO détectée(s) — cause fréquente de session lente"))

        profile_events = _ensure_dicts(_v(d, "events", "profile_events", default=[]))
        profile_errors = [e for e in profile_events if e.get("level") == "Error"]
        if profile_errors:
            self.alerts.append(("warn", "Erreurs de chargement de profil utilisateur",
                                 f"{len(profile_errors)} erreur(s) de profil détectée(s)"))

    # ── HTML ──────────────────────────────────────────────────────────────────
    def _build_html(self) -> str:
        self._analyse()
        css  = get_css()
        body = "\n".join([
            self._section_alerts(),
            self._section_system(),
            self._section_performance(),
            self._section_startup(),
            self._section_events(),
            self._section_network(),
            self._section_security(),
            self._section_software(),
        ])

        machine   = _esc(self.meta.get("machine", "N/A"))
        collected = _esc(self.meta.get("collected_at", "N/A"))
        ok_count  = self.meta.get("collectors_ok", 0)
        total_col = ok_count + len(self.meta.get("collectors_fail", []))
        crit_count = sum(1 for a in self.alerts if a[0] == "crit")
        warn_count = sum(1 for a in self.alerts if a[0] == "warn")

        alert_badge = ""
        if crit_count:
            alert_badge = f' &nbsp; <span class="badge badge-crit">⚠ {crit_count} critique(s)</span>'
        if warn_count:
            alert_badge += f' &nbsp; <span class="badge badge-warn">⚡ {warn_count} avertissement(s)</span>'

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PlanetDiag – {machine} – {collected}</title>
<style>{css}</style>
</head>
<body>

<div class="header">
  <h1>🔍 PlanetDiag <span style="font-size:14px;color:var(--fg-muted);font-weight:400">v{VERSION}</span></h1>
  <div class="header-meta">
    <span>💻 <strong>{machine}</strong></span>
    <span>🕐 {collected}</span>
    <span>📦 {ok_count}/{total_col} modules{alert_badge}</span>
  </div>
</div>

<nav class="nav">
  <a href="#alerts">⚠ Points d'attention</a>
  <a href="#system">🖥 Système</a>
  <a href="#performance">📊 Performance</a>
  <a href="#startup">🚀 Démarrage</a>
  <a href="#events">📋 Événements</a>
  <a href="#network">🌐 Réseau</a>
  <a href="#security">🔒 Sécurité</a>
  <a href="#software">📦 Logiciels</a>
</nav>

{body}

<footer>
  Généré par <strong>PlanetDiag v{VERSION}</strong> le {collected} — Machine : {machine}<br>
  <span style="color:var(--fg-muted);font-size:11px">Développé par {_esc(AUTHORS)}</span>
</footer>
<a class="back-top" href="#" title="Haut de page">↑</a>

</body></html>"""

    # ── Sections ─────────────────────────────────────────────────────────────
    def _section_alerts(self) -> str:
        if not self.alerts:
            content = '<div class="alert-box alert-info"><span class="label">✅ Aucune anomalie détectée</span><p>Tous les indicateurs analysés semblent dans les normes.</p></div>'
        else:
            rows = []
            for level, title, desc in self.alerts:
                cls = {"crit": "alert-crit", "warn": "alert-warn"}.get(level, "alert-info")
                icon = {"crit": "🔴", "warn": "🟠"}.get(level, "🔵")
                rows.append(f'<div class="alert-box {cls}"><span class="label">{icon} {_esc(title)}</span><p>{_esc(desc)}</p></div>')
            content = "\n".join(rows)

        return f'<div id="alerts" class="alerts"><h2 class="section-title">⚠ Points d\'attention</h2>{content}</div>'

    def _section_system(self) -> str:
        d   = self.data.get("system_info", {})
        err = d.get("_status") != "ok"

        if err:
            return self._err_section("system", "🖥 Système & Matériel", d)

        os_d  = d.get("os", {})
        comp  = d.get("computer", {})
        bios  = d.get("bios", {})
        cpus  = d.get("cpu", []) or []
        ram   = d.get("ram", {})
        gpus  = d.get("gpu", []) or []
        vols  = (d.get("disks") or {}).get("volumes", []) or []
        disks = (d.get("disks") or {}).get("physical", []) or []

        ram_pct = ram.get("usage_percent", 0) or 0
        ram_bar = _pct_bar(ram_pct)

        summary = (f"Machine : <strong>{_esc(comp.get('manufacturer',''))} {_esc(comp.get('model',''))}</strong> "
                   f"— OS : <strong>{_esc(os_d.get('caption',''))}</strong> build {_esc(os_d.get('build_number',''))} "
                   f"— Uptime : <strong>{_esc(os_d.get('uptime','N/A'))}</strong> "
                   f"— RAM utilisée : <strong>{ram_pct}%</strong>.")

        # Cards OS
        cards = f"""
<div class="cards">
  <div class="card"><div class="card-title">Système d'exploitation</div>
    <div class="card-value" style="font-size:14px">{_esc(os_d.get("caption","N/A"))}</div>
    <div class="card-sub">Build {_esc(os_d.get("build_number",""))} · {_esc(os_d.get("architecture",""))}</div></div>
  <div class="card"><div class="card-title">Dernier redémarrage</div>
    <div class="card-value" style="font-size:14px">{_esc(os_d.get("last_boot","N/A"))}</div>
    <div class="card-sub">Uptime : {_esc(os_d.get("uptime","N/A"))}</div></div>
  <div class="card"><div class="card-title">Modèle machine</div>
    <div class="card-value" style="font-size:13px">{_esc(comp.get("manufacturer",""))} {_esc(comp.get("model",""))}</div>
    <div class="card-sub">S/N BIOS : {_esc(bios.get("serial_number","N/A"))}</div></div>
  <div class="card"><div class="card-title">BIOS / Firmware</div>
    <div class="card-value" style="font-size:13px">{_esc(bios.get("firmware_type","N/A"))}</div>
    <div class="card-sub">{_esc(bios.get("version",""))} · {_esc(bios.get("release_date",""))}</div></div>
</div>"""

        # CPU table
        cpu_rows = "".join(
            f"<tr><td>{_esc(c.get('name',''))}</td><td>{_esc(c.get('cores',''))}</td>"
            f"<td>{_esc(c.get('logical_processors',''))}</td>"
            f"<td>{_esc(c.get('max_clock_speed',''))} MHz</td>"
            f"<td class='{'crit' if (c.get('load_percentage') or 0) >= 80 else 'ok'}'>"
            f"{_esc(c.get('load_percentage','N/A'))}%</td></tr>"
            for c in cpus
        )

        # RAM
        modules_rows = "".join(
            f"<tr><td>{_esc(m.get('slot',''))}</td><td>{_esc(m.get('capacity_gb',''))} GB</td>"
            f"<td>{_esc(m.get('memory_type',''))}</td><td>{_esc(m.get('speed_mhz',''))} MHz</td>"
            f"<td>{_esc(m.get('manufacturer',''))}</td></tr>"
            for m in (ram.get("modules") or [])
        )
        ram_cls = "crit" if ram_pct >= 90 else ("warn" if ram_pct >= 75 else "ok")

        # Volumes
        vol_rows = "".join(
            f"<tr><td>{_esc(v.get('drive_letter',''))}</td><td>{_esc(v.get('label',''))}</td>"
            f"<td>{_esc(v.get('filesystem',''))}</td><td>{_esc(v.get('size_gb',''))} GB</td>"
            f"<td>{_esc(v.get('used_gb',''))} GB</td><td>{_esc(v.get('free_gb',''))} GB</td>"
            f"<td class='{'crit' if v.get('low_space') else ''}'>"
            f"{_pct_bar(v.get('used_percent',0))} {v.get('used_percent',0)}%</td></tr>"
            for v in vols
        )

        gpu_cards = "".join(
            f'<div class="card"><div class="card-title">GPU</div>'
            f'<div class="card-value" style="font-size:12px">{_esc(g.get("name",""))}</div>'
            f'<div class="card-sub">{_esc(g.get("adapter_ram_gb",""))} GB VRAM · Driver {_esc(g.get("driver_version",""))}</div></div>'
            for g in gpus
        )

        return f"""<section id="system" class="section">
<h2 class="section-title">🖥 Système & Matériel</h2>
<div class="section-summary">{summary}</div>
{cards}
{gpu_cards and f'<div class="cards">{gpu_cards}</div>' or ''}
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase;letter-spacing:.08em">Processeur(s)</h3>
<div class="table-wrap"><table>
<tr><th>Modèle</th><th>Cœurs</th><th>Threads</th><th>Fréquence max</th><th>Charge</th></tr>
{cpu_rows or '<tr><td colspan="5" class="dim">Données indisponibles</td></tr>'}
</table></div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase;letter-spacing:.08em">
  Mémoire RAM — <span class="{ram_cls}">{ram.get("used_gb","?")} GB / {ram.get("total_gb","?")} GB ({ram_pct}%)</span>
</h3>
{ram_bar}
<div class="table-wrap" style="margin-top:8px"><table>
<tr><th>Slot</th><th>Capacité</th><th>Type</th><th>Fréquence</th><th>Fabricant</th></tr>
{modules_rows or '<tr><td colspan="5" class="dim">Données indisponibles</td></tr>'}
</table></div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase;letter-spacing:.08em">Volumes logiques</h3>
<div class="table-wrap"><table>
<tr><th>Lecteur</th><th>Nom</th><th>FS</th><th>Taille</th><th>Utilisé</th><th>Libre</th><th>Usage</th></tr>
{vol_rows or '<tr><td colspan="7" class="dim">Données indisponibles</td></tr>'}
</table></div>
</section>"""

    def _section_performance(self) -> str:
        d   = self.data.get("performance", {})
        if d.get("_status") != "ok":
            return self._err_section("performance", "📊 Performance", d)

        cpu = d.get("cpu", {}) or {}
        ram = d.get("ram", {}) or {}

        cpu_pct = cpu.get("load_percent", 0) or 0
        ram_pct = ram.get("usage_percent", 0) or 0
        cpu_cls = "crit" if cpu_pct >= 80 else ("warn" if cpu_pct >= 60 else "ok")
        ram_cls = "crit" if ram_pct >= 90 else ("warn" if ram_pct >= 75 else "ok")

        summary = (f"Au moment du diagnostic : CPU à <strong class='{cpu_cls}'>{cpu_pct}%</strong>, "
                   f"RAM à <strong class='{ram_cls}'>{ram_pct}%</strong> "
                   f"({ram.get('used_mb',0)} MB / {ram.get('total_mb',0)} MB).")

        top_cpu_rows = "".join(
            f"<tr><td class='mono'>{_esc(p.get('name',''))}</td><td>{_esc(p.get('pid',''))}</td>"
            f"<td>{_esc(p.get('cpu_sec',''))}s</td><td>{_esc(p.get('memory_mb',''))} MB</td>"
            f"<td>{_esc(p.get('threads',''))}</td></tr>"
            for p in _ensure_list(cpu.get("top_processes"))
        )
        top_ram_rows = "".join(
            f"<tr><td class='mono'>{_esc(p.get('name',''))}</td><td>{_esc(p.get('pid',''))}</td>"
            f"<td>{_esc(p.get('ram_mb',''))} MB</td><td>{_esc(p.get('cpu_sec',''))}s</td></tr>"
            for p in _ensure_list(ram.get("top_processes"))
        )
        return f"""<section id="performance" class="section">
<h2 class="section-title">📊 Performance</h2>
<div class="section-summary">{summary}</div>
<div class="cards">
  <div class="card card-{cpu_cls}"><div class="card-title">Charge CPU</div>
    <div class="card-value {cpu_cls}">{cpu_pct}%</div>{_pct_bar(cpu_pct,60,80)}</div>
  <div class="card card-{ram_cls}"><div class="card-title">Utilisation RAM</div>
    <div class="card-value {ram_cls}">{ram_pct}%</div>{_pct_bar(ram_pct)}
    <div class="card-sub">{ram.get('used_mb',0)} / {ram.get('total_mb',0)} MB</div></div>
</div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Top 10 processus CPU</h3>
<div class="table-wrap"><table>
<tr><th>Processus</th><th>PID</th><th>CPU cumulé</th><th>RAM</th><th>Threads</th></tr>
{top_cpu_rows or '<tr><td colspan="5" class="dim">Données indisponibles</td></tr>'}
</table></div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Top 10 processus RAM</h3>
<div class="table-wrap"><table>
<tr><th>Processus</th><th>PID</th><th>RAM utilisée</th><th>CPU cumulé</th></tr>
{top_ram_rows or '<tr><td colspan="4" class="dim">Données indisponibles</td></tr>'}
</table></div>
</section>"""

    def _section_startup(self) -> str:
        d = self.data.get("startup", {})
        if d.get("_status") != "ok":
            return self._err_section("startup", "🚀 Démarrage Windows", d)

        progs    = _ensure_list(d.get("startup_programs"))
        svcs     = d.get("services", {}) or {}
        tasks    = d.get("scheduled_tasks", {}) or {}
        boot     = d.get("boot_info", {}) or {}
        svc_list = _ensure_list(svcs.get("items"))

        summary = (f"{len(progs)} programme(s) au démarrage — "
                   f"{svcs.get('running',0)} services auto démarrés / {svcs.get('auto_start_total',0)} configurés — "
                   f"{tasks.get('non_microsoft_count',0)} tâche(s) planifiée(s) non-Microsoft.")

        prog_rows = "".join(
            f"<tr><td>{_esc(p.get('name',''))}</td><td>{_esc(p.get('hive',''))}</td>"
            f"<td class='mono' style='font-size:11px'>{_esc((p.get('command') or '')[:80])}</td></tr>"
            for p in progs
        )

        stopped_svcs = [s for s in svc_list if s.get("state") != "Running"]
        stopped_rows = "".join(
            f"<tr><td>{_esc(s.get('display_name',''))}</td><td>{_esc(s.get('name',''))}</td>"
            f"<td class='warn'>{_esc(s.get('state',''))}</td></tr>"
            for s in stopped_svcs[:20]
        )

        return f"""<section id="startup" class="section">
<h2 class="section-title">🚀 Démarrage Windows</h2>
<div class="section-summary">{summary}</div>
<div class="cards">
  <div class="card"><div class="card-title">Programmes démarrage</div>
    <div class="card-value">{len(progs)}</div></div>
  <div class="card"><div class="card-title">Services auto (actifs)</div>
    <div class="card-value">{svcs.get('running',0)} / {svcs.get('auto_start_total',0)}</div></div>
  <div class="card"><div class="card-title">Tâches planifiées</div>
    <div class="card-value">{tasks.get('non_microsoft_count',0)}</div>
    <div class="card-sub">hors Microsoft</div></div>
  <div class="card"><div class="card-title">Dernier démarrage OS</div>
    <div class="card-value" style="font-size:12px">{_esc(boot.get('last_boot_start','N/A'))}</div></div>
</div>
<details><summary>Programmes au démarrage ({len(progs)})</summary>
<div class="table-wrap"><table>
<tr><th>Nom</th><th>Source</th><th>Commande</th></tr>
{prog_rows or '<tr><td colspan="3" class="dim">Aucun</td></tr>'}
</table></div></details>
<details><summary>Services auto-start arrêtés ({len(stopped_svcs)})</summary>
<div class="table-wrap"><table>
<tr><th>Nom affiché</th><th>Nom service</th><th>État</th></tr>
{stopped_rows or '<tr><td colspan="3" class="ok">Tous les services démarrent correctement</td></tr>'}
</table></div></details>
</section>"""

    def _section_events(self) -> str:
        d = self.data.get("events", {})
        if d.get("_status") != "ok":
            return self._err_section("events", "📋 Événements Windows", d)

        sys_ev       = d.get("system", {}) or {}
        app_ev       = d.get("application", {}) or {}
        sec_ev       = d.get("security", {}) or {}
        sources      = _ensure_list(d.get("top_error_sources"))
        total        = d.get("total_errors", 0)
        diag_perf    = _ensure_dicts(d.get("diag_perf") or [])
        gpo_events   = _ensure_dicts(d.get("gpo_events") or [])
        prof_events  = _ensure_dicts(d.get("profile_events") or [])
        net_prof     = _ensure_dicts(d.get("net_profile") or [])
        wlan_events  = _ensure_dicts(d.get("wlan_events") or [])
        setup_events = _ensure_dicts(d.get("setup_events") or [])

        boot_slow = [e for e in diag_perf if e.get("category") in ("boot", "boot-app")]

        summary = (f"{total} erreur(s)/critique(s) en 72h — "
                   f"{sys_ev.get('count',0)} système, {app_ev.get('count',0)} application — "
                   f"{sec_ev.get('auth_failures_count',0)} échec(s) d'authentification"
                   + (f" — ⚠ {len(boot_slow)} event(s) de démarrage lent" if boot_slow else "") + ".")

        def ev_rows(events, max_msg=120):
            return "".join(
                f"<tr><td class='mono'>{_esc(e.get('time_created',''))}</td>"
                f"<td class='crit'>{_esc(e.get('level',''))}</td>"
                f"<td>{_esc(e.get('source',''))}</td>"
                f"<td>{_esc(e.get('event_id',''))}</td>"
                f"<td style='font-size:11px'>{_esc((e.get('message') or '')[:max_msg])}</td></tr>"
                for e in _ensure_list(events)[:30]
            )

        def diag_rows(events):
            rows = []
            for e in events:
                desc     = e.get("description") or ""
                app      = e.get("app_name")
                dur_ms   = e.get("duration_ms")
                cat      = e.get("category", "")
                is_slow  = cat in ("boot", "shutdown", "resume")
                is_culprit = cat in ("boot-app", "shutdown-app", "resume-app")
                row_cls  = "warn" if is_slow else ("crit" if is_culprit else "dim")

                dur_html = ""
                if dur_ms:
                    dur_s = round(dur_ms / 1000, 1) if dur_ms > 1000 else dur_ms
                    unit  = "s" if dur_ms > 1000 else "ms"
                    dur_html = f" <span class='badge badge-warn'>{dur_s}{unit}</span>"

                app_html = ""
                if app:
                    app_html = f" <span class='badge badge-crit'>⚠ {_esc(app)}</span>"

                rows.append(
                    f"<tr>"
                    f"<td class='mono'>{_esc(e.get('time_created',''))}</td>"
                    f"<td class='{row_cls}'>{_esc(desc)}{dur_html}</td>"
                    f"<td>{_esc(e.get('event_id',''))}</td>"
                    f"<td style='font-size:11px'>{_esc((e.get('message') or '')[:200])}{app_html}</td>"
                    f"</tr>"
                )
            return "".join(rows)

        def simple_rows(events, label_key="level"):
            return "".join(
                f"<tr><td class='mono'>{_esc(e.get('time_created',''))}</td>"
                f"<td class='{'crit' if e.get(label_key)=='Error' else 'warn' if e.get(label_key)=='Warning' else 'dim'}'>"
                f"{_esc(e.get(label_key,''))}</td>"
                f"<td>{_esc(e.get('event_id',''))}</td>"
                f"<td style='font-size:11px'>{_esc((e.get('message') or '')[:160])}</td></tr>"
                for e in events
            )

        source_rows = "".join(
            f"<tr><td>{_esc(s.get('source',''))}</td><td>{_esc(s.get('count',''))}</td></tr>"
            for s in sources
        )

        # Bannière alerte démarrage lent
        boot_banner = ""
        if boot_slow:
            boot_banner = (f'<div class="alert-box alert-warn"><span class="label">⚠ Démarrage Windows lent détecté</span>'
                           f'<p>{len(boot_slow)} événement(s) enregistré(s) sur 30 jours — voir journal Diagnostics-Performance ci-dessous.</p></div>')

        gpo_banner = ""
        gpo_errors = [e for e in gpo_events if e.get("level") == "Error"]
        if gpo_errors:
            gpo_banner = (f'<div class="alert-box alert-warn"><span class="label">⚠ Erreurs Stratégie de groupe (GPO)</span>'
                          f'<p>{len(gpo_errors)} erreur(s) GPO — cause fréquente de lenteur d\'ouverture de session sur réseau d\'entreprise.</p></div>')

        return f"""<section id="events" class="section">
<h2 class="section-title">📋 Événements Windows</h2>
<div class="section-summary">{summary}</div>
{boot_banner}
{gpo_banner}
<div class="cards">
  <div class="card card-{'crit' if total>=50 else 'warn' if total>=20 else 'ok'}">
    <div class="card-title">Erreurs système 72h</div>
    <div class="card-value {'crit' if total>=50 else 'warn' if total>=20 else 'ok'}">{total}</div></div>
  <div class="card"><div class="card-title">Journal Système</div>
    <div class="card-value">{sys_ev.get('count',0)}</div></div>
  <div class="card"><div class="card-title">Journal Application</div>
    <div class="card-value">{app_ev.get('count',0)}</div></div>
  <div class="card card-{'crit' if (sec_ev.get('auth_failures_count',0) or 0)>=5 else 'ok'}">
    <div class="card-title">Échecs d'auth</div>
    <div class="card-value">{sec_ev.get('auth_failures_count',0)}</div></div>
  <div class="card card-{'warn' if boot_slow else 'ok'}">
    <div class="card-title">Démarrages lents (30j)</div>
    <div class="card-value {'warn' if boot_slow else 'ok'}">{len(boot_slow)}</div></div>
  <div class="card card-{'warn' if gpo_errors else 'ok'}">
    <div class="card-title">Erreurs GPO (7j)</div>
    <div class="card-value {'warn' if gpo_errors else 'ok'}">{len(gpo_errors)}</div></div>
</div>

<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Top sources d'erreurs (72h)</h3>
<div class="table-wrap"><table>
<tr><th>Source</th><th>Occurrences</th></tr>
{source_rows or '<tr><td colspan="2" class="dim">Aucune erreur — système propre ✅</td></tr>'}
</table></div>

{self._diag_culprit_summary(diag_perf)}
<details><summary>📊 Diagnostics-Performance — Démarrages/arrêts lents ({len(diag_perf)} événement(s) sur 30j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Microsoft-Windows-Diagnostics-Performance/Operational</code> — IDs 100/101 (boot), 200/201 (arrêt), 300/301 (veille)</p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Description</th><th>ID</th><th>Détail / Application responsable</th></tr>
{diag_rows(diag_perf) or '<tr><td colspan="4" class="ok">Aucun ralentissement détecté ✅</td></tr>'}
</table></div></details>

<details><summary>🏢 Stratégie de groupe GPO ({len(gpo_events)} événement(s), {len(gpo_errors)} erreur(s) sur 7j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Microsoft-Windows-GroupPolicy/Operational</code></p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>ID</th><th>Message</th></tr>
{simple_rows(gpo_events) or '<tr><td colspan="4" class="ok">Aucune erreur GPO ✅</td></tr>'}
</table></div></details>

<details><summary>👤 Profil utilisateur ({len(prof_events)} événement(s) sur 7j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Microsoft-Windows-User Profile Service/Operational</code></p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>ID</th><th>Message</th></tr>
{simple_rows(prof_events) or '<tr><td colspan="4" class="ok">Aucune erreur de profil ✅</td></tr>'}
</table></div></details>

<details><summary>🌐 Profil réseau ({len(net_prof)} événement(s) sur 3j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Microsoft-Windows-NetworkProfile/Operational</code> — connexions/déconnexions réseau</p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>ID</th><th>Message</th></tr>
{simple_rows(net_prof) or '<tr><td colspan="4" class="dim">Aucun événement réseau</td></tr>'}
</table></div></details>

<details><summary>📶 Wi-Fi / WLAN ({len(wlan_events)} erreur(s)/avertissement(s) sur 3j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Microsoft-Windows-WLAN-AutoConfig/Operational</code></p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>ID</th><th>Message</th></tr>
{simple_rows(wlan_events) or '<tr><td colspan="4" class="dim">Aucune erreur Wi-Fi (ou adaptateur filaire)</td></tr>'}
</table></div></details>

<details><summary>🔧 Journal Installation / Setup ({len(setup_events)} événement(s) sur 30j)</summary>
<p style="padding:4px 0 8px;color:var(--fg-muted);font-size:12px">Source : <code>Setup</code> — installations Windows Update, mises à jour de composants</p>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>ID</th><th>Message</th></tr>
{simple_rows(setup_events) or '<tr><td colspan="4" class="dim">Aucune installation récente</td></tr>'}
</table></div></details>

<details><summary>Événements Système ({sys_ev.get('count',0)} erreurs/critiques sur 72h)</summary>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>Source</th><th>ID</th><th>Message</th></tr>
{ev_rows(sys_ev.get('events',[]))}
</table></div></details>
<details><summary>Événements Application ({app_ev.get('count',0)} erreurs/critiques sur 72h)</summary>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Niveau</th><th>Source</th><th>ID</th><th>Message</th></tr>
{ev_rows(app_ev.get('events',[]))}
</table></div></details>
</section>"""

    def _section_network(self) -> str:
        d = self.data.get("network", {})
        if d.get("_status") != "ok":
            return self._err_section("network", "🌐 Réseau", d)

        adapters  = _ensure_list(d.get("adapters"))
        conn      = _ensure_list(d.get("connectivity"))
        shares    = _ensure_list(d.get("shares"))
        tcp       = _ensure_list(d.get("tcp_connections"))
        internet  = d.get("internet_ok", None)
        dns_ok    = d.get("dns_ok", None)

        int_cls = "ok" if internet else "crit"
        dns_cls = "ok" if dns_ok   else "warn"

        summary = (f"Internet : <span class='{int_cls}'>{'✅ OK' if internet else '❌ Hors ligne'}</span> — "
                   f"DNS : <span class='{dns_cls}'>{'✅ OK' if dns_ok else '❌ Échec'}</span> — "
                   f"{len([a for a in adapters if a.get('status')=='Up'])} adaptateur(s) actif(s).")

        adapter_rows = "".join(
            f"<tr><td>{_esc(a.get('name',''))}</td><td>{_esc(a.get('description',''))}</td>"
            f"<td class='{'ok' if a.get('status')=='Up' else 'dim'}'>{_esc(a.get('status',''))}</td>"
            f"<td class='mono'>{_esc(a.get('ipv4_address',''))}</td>"
            f"<td class='mono'>{_esc(a.get('gateway',''))}</td>"
            f"<td>{_esc(', '.join(a.get('dns_servers') or []))}</td>"
            f"<td>{_esc(a.get('link_speed_mbps',''))} Mb/s</td></tr>"
            for a in adapters
        )
        ping_rows = "".join(
            f"<tr><td>{_esc(c.get('label',''))}</td><td>{_esc(c.get('target',''))}</td>"
            f"<td class='{'ok' if c.get('reachable') else 'crit'}'>"
            f"{'✅' if c.get('reachable') else '❌'}</td>"
            f"<td>{_esc(c.get('avg_rtt_ms','N/A'))} ms</td></tr>"
            for c in conn
        )
        tcp_rows = "".join(
            f"<tr><td class='mono'>{_esc(t.get('remote_address',''))}:{_esc(t.get('remote_port',''))}</td>"
            f"<td>{_esc(t.get('process_name',''))}</td><td>{_esc(t.get('pid',''))}</td></tr>"
            for t in tcp[:20]
        )

        return f"""<section id="network" class="section">
<h2 class="section-title">🌐 Réseau</h2>
<div class="section-summary">{summary}</div>
<h3 style="margin:0 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Tests de connectivité</h3>
<div class="table-wrap"><table>
<tr><th>Cible</th><th>Adresse</th><th>Joignable</th><th>RTT moyen</th></tr>
{ping_rows or '<tr><td colspan="4" class="dim">Tests non effectués</td></tr>'}
</table></div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Adaptateurs réseau</h3>
<div class="table-wrap"><table>
<tr><th>Nom</th><th>Description</th><th>État</th><th>IP</th><th>Passerelle</th><th>DNS</th><th>Vitesse</th></tr>
{adapter_rows or '<tr><td colspan="7" class="dim">Données indisponibles</td></tr>'}
</table></div>
<details><summary>Connexions TCP actives ({len(tcp)})</summary>
<div class="table-wrap"><table>
<tr><th>Destination</th><th>Processus</th><th>PID</th></tr>
{tcp_rows or '<tr><td colspan="3" class="dim">Aucune connexion</td></tr>'}
</table></div></details>
</section>"""

    def _section_security(self) -> str:
        d = self.data.get("security", {})
        if d.get("_status") != "ok":
            return self._err_section("security", "🔒 Sécurité", d)

        avs     = _ensure_list(d.get("antivirus"))
        fw      = _ensure_list(d.get("firewall"))
        wu      = d.get("windows_update", {}) or {}
        uac     = d.get("uac", {}) or {}
        logons  = _ensure_list(d.get("last_logons"))
        fail_ct = d.get("logon_failures", 0)

        active_avs = [a for a in avs if a.get("realtime_enabled")]
        fw_ok  = all(p.get("enabled") for p in fw)
        uac_ok = uac.get("enabled", False)

        # Statut AV : OK si exactement 1 actif (Defender désactivé par tiers = normal)
        if not avs:
            av_status_cls, av_status_lbl = "warn", "⚠ Non détecté"
        elif not active_avs:
            av_status_cls, av_status_lbl = "crit", "❌ Aucun actif"
        elif len(active_avs) > 1:
            av_status_cls, av_status_lbl = "warn", f"⚠ {len(active_avs)} actifs"
        else:
            av_status_cls, av_status_lbl = "ok", "✅ OK"

        summary = (f"Antivirus : <span class='{av_status_cls}'>{av_status_lbl}</span> — "
                   f"Pare-feu : <span class='{'ok' if fw_ok else 'crit'}'>{'✅' if fw_ok else '❌'}</span> — "
                   f"UAC : <span class='{'ok' if uac_ok else 'crit'}'>{'✅' if uac_ok else '❌'}</span> — "
                   f"{wu.get('pending_count','?')} MAJ en attente — {fail_ct} échec(s) auth (7j).")

        # Libellé contextuel : si au moins un autre AV est actif, désactivé = normal ;
        # sinon c'est un vrai problème (aucune protection temps réel).
        has_other_active = len(active_avs) >= 1
        def _av_state_cell(a):
            if a.get("realtime_enabled"):
                return "<td class='ok'>✅ Actif</td>"
            label = "— Désactivé (normal, un autre AV protège)" if has_other_active else "❌ Désactivé (aucune protection)"
            cls   = "dim" if has_other_active else "crit"
            return f"<td class='{cls}'>{label}</td>"

        av_rows = "".join(
            f"<tr><td>{_esc(a.get('name',''))}</td>"
            f"{_av_state_cell(a)}"
            f"<td class='{'ok' if a.get('definitions_ok') else 'warn'}'>"
            f"{'✅ À jour' if a.get('definitions_ok') else '⚠ Vérifier'}</td></tr>"
            for a in avs
        )
        fw_rows = "".join(
            f"<tr><td>{_esc(p.get('profile',''))}</td>"
            f"<td class='{'ok' if p.get('enabled') else 'crit'}'>"
            f"{'✅ Activé' if p.get('enabled') else '❌ Désactivé'}</td>"
            f"<td>{_esc(p.get('default_inbound',''))}</td><td>{_esc(p.get('default_outbound',''))}</td></tr>"
            for p in fw
        )
        logon_rows = "".join(
            f"<tr><td class='mono'>{_esc(l.get('time',''))}</td>"
            f"<td class='{'ok' if l.get('event')=='Succès' else 'crit'}'>{_esc(l.get('event',''))}</td>"
            f"<td>{_esc(l.get('user',''))}</td></tr>"
            for l in logons[:20]
        )

        return f"""<section id="security" class="section">
<h2 class="section-title">🔒 Sécurité</h2>
<div class="section-summary">{summary}</div>
<div class="cards">
  <div class="card card-{av_status_cls}"><div class="card-title">Antivirus</div>
    <div class="card-value {av_status_cls}" style="font-size:18px">{av_status_lbl}</div>
    <div class="card-sub">{', '.join(a.get('name','?') for a in avs) or 'Non détecté'}</div></div>
  <div class="card card-{'ok' if fw_ok else 'crit'}"><div class="card-title">Pare-feu</div>
    <div class="card-value {'ok' if fw_ok else 'crit'}" style="font-size:18px">{'✅ OK' if fw_ok else '❌ KO'}</div></div>
  <div class="card card-{'ok' if uac_ok else 'crit'}"><div class="card-title">UAC</div>
    <div class="card-value {'ok' if uac_ok else 'crit'}" style="font-size:18px">{'✅ Actif' if uac_ok else '❌ Désactivé'}</div></div>
  <div class="card card-{'warn' if (wu.get('pending_count') or 0)>5 else 'ok'}">
    <div class="card-title">MAJ en attente</div>
    <div class="card-value">{wu.get('pending_count','?')}</div></div>
</div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Antivirus</h3>
<div class="table-wrap"><table>
<tr><th>Produit</th><th>Protection temps réel</th><th>Définitions</th></tr>
{av_rows or '<tr><td colspan="3" class="warn">Aucun antivirus détecté</td></tr>'}
</table></div>
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Pare-feu Windows</h3>
<div class="table-wrap"><table>
<tr><th>Profil</th><th>État</th><th>Entrant par défaut</th><th>Sortant par défaut</th></tr>
{fw_rows or '<tr><td colspan="4" class="dim">Données indisponibles</td></tr>'}
</table></div>
<details><summary>Dernières connexions utilisateur ({len(logons)})</summary>
<div class="table-wrap"><table>
<tr><th>Date/heure</th><th>Résultat</th><th>Utilisateur</th></tr>
{logon_rows or '<tr><td colspan="3" class="dim">Aucune donnée</td></tr>'}
</table></div></details>
</section>"""

    def _section_software(self) -> str:
        d = self.data.get("software", {})
        if d.get("_status") != "ok":
            return self._err_section("software", "📦 Logiciels & Drivers", d)

        sw      = d.get("software", {}) or {}
        wu      = d.get("windows_updates", {}) or {}
        drivers = d.get("drivers", {}) or {}
        items   = _ensure_list(sw.get("items"))
        drv_err = _ensure_list(drivers.get("error_drivers"))
        recent  = _ensure_list(drivers.get("recent_drivers"))

        summary = (f"{sw.get('count',0)} logiciel(s) installé(s) — "
                   f"{drivers.get('errors_count',0)} driver(s) en erreur — "
                   f"{drivers.get('recent_count',0)} driver(s) modifié(s) récemment.")

        sw_rows = "".join(
            f"<tr><td>{_esc(s.get('name',''))}</td><td>{_esc(s.get('version',''))}</td>"
            f"<td>{_esc(s.get('publisher',''))}</td><td>{_esc(s.get('install_date',''))}</td></tr>"
            for s in items[:100]
        )
        wu_rows = "".join(
            f"<tr><td class='mono'>{_esc(u.get('hotfix_id',''))}</td><td>{_esc(u.get('description',''))}</td>"
            f"<td>{_esc(u.get('installed_on',''))}</td></tr>"
            for u in _ensure_list(wu.get("items"))
        )
        drv_err_rows = "".join(
            f"<tr><td>{_esc(dr.get('device_name',''))}</td><td>{_esc(dr.get('manufacturer',''))}</td>"
            f"<td class='crit'>{_esc(dr.get('status',''))}</td>"
            f"<td>{_esc(dr.get('driver_version',''))}</td></tr>"
            for dr in drv_err
        )
        recent_rows = "".join(
            f"<tr><td>{_esc(dr.get('device_name',''))}</td><td>{_esc(dr.get('manufacturer',''))}</td>"
            f"<td>{_esc(dr.get('driver_date',''))}</td><td>{_esc(dr.get('driver_version',''))}</td></tr>"
            for dr in recent[:20]
        )

        return f"""<section id="software" class="section">
<h2 class="section-title">📦 Logiciels & Drivers</h2>
<div class="section-summary">{summary}</div>
<div class="cards">
  <div class="card"><div class="card-title">Logiciels installés</div>
    <div class="card-value">{sw.get('count',0)}</div></div>
  <div class="card card-{'crit' if drivers.get('errors_count',0) else 'ok'}">
    <div class="card-title">Drivers en erreur</div>
    <div class="card-value {'crit' if drivers.get('errors_count',0) else 'ok'}">{drivers.get('errors_count',0)}</div></div>
  <div class="card"><div class="card-title">Drivers récents (30j)</div>
    <div class="card-value">{drivers.get('recent_count',0)}</div></div>
</div>
{'<div class="alert-box alert-crit"><span class="label">🔴 Drivers en erreur</span><p>Des pilotes présentent des erreurs et peuvent causer des instabilités.</p></div>' if drv_err else ''}
{f'<div class="table-wrap"><table><tr><th>Périphérique</th><th>Fabricant</th><th>Erreur</th><th>Version</th></tr>{drv_err_rows}</table></div>' if drv_err else ''}
<h3 style="margin:16px 0 8px;color:var(--fg-dim);font-size:13px;text-transform:uppercase">Mises à jour Windows (10 dernières)</h3>
<div class="table-wrap"><table>
<tr><th>KB</th><th>Description</th><th>Date</th></tr>
{wu_rows or '<tr><td colspan="3" class="dim">Données indisponibles</td></tr>'}
</table></div>
<details><summary>Drivers récemment modifiés ({len(recent)})</summary>
<div class="table-wrap"><table>
<tr><th>Périphérique</th><th>Fabricant</th><th>Date driver</th><th>Version</th></tr>
{recent_rows or '<tr><td colspan="4" class="dim">Aucun driver récent</td></tr>'}
</table></div></details>
<details><summary>Logiciels installés ({sw.get('count',0)})</summary>
<div class="table-wrap"><table>
<tr><th>Nom</th><th>Version</th><th>Éditeur</th><th>Installation</th></tr>
{sw_rows or '<tr><td colspan="4" class="dim">Données indisponibles</td></tr>'}
</table></div></details>
</section>"""

    def _diag_culprit_summary(self, diag_perf: list) -> str:
        """Encadré de synthèse des applications/processus responsables de ralentissements."""
        culprits = [e for e in diag_perf if e.get("app_name")]
        if not culprits:
            return ""

        # Déduplique et compte les occurrences par app
        from collections import Counter
        counts = Counter(e["app_name"] for e in culprits)
        items  = "".join(
            f"<li><strong>{_esc(app)}</strong> — {count} fois</li>"
            for app, count in counts.most_common()
        )
        return (
            f'<div class="alert-box alert-warn">'
            f'<span class="label">🔍 Processus responsables de ralentissements identifiés</span>'
            f'<ul style="margin:6px 0 0 16px;padding:0">{items}</ul>'
            f'</div>'
        )

    def _err_section(self, anchor: str, title: str, d: dict) -> str:
        err = _esc(d.get("error", "Erreur inconnue"))
        return f"""<section id="{anchor}" class="section">
<h2 class="section-title">{title}</h2>
<div class="alert-box alert-crit">
  <span class="label">❌ Collecte échouée</span>
  <p>Ce module n'a pas pu être collecté : {err}</p>
</div></section>"""
