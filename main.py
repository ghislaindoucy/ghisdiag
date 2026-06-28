"""
Ghisdiag - Interface graphique principale
"""

import os
import subprocess
import sys
import gc
import threading
import webbrowser
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

try:
    from collectors.realtime_monitor import (
        get_cpu_percent, get_ram_percent, get_disk_io_percent, get_temperatures,
        get_gpu_disk_temps, get_cpu_temp_acpi,
    )
    _HAS_MONITOR = True
except Exception:
    _HAS_MONITOR = False

# Flux capteurs persistant (LibreHardwareMonitor ouvert une seule fois) pour le
# moniteur temps reel : evite le cout d'un read_once a chaque tick et rafraichit
# la temperature CPU en continu, au lieu d'un process relance toutes les 10 s.
try:
    from collectors.sensors import SensorStream as _SensorStream, lhm_available as _lhm_available
    _HAS_STREAM = True
except Exception:
    _SensorStream = None
    _lhm_available = None
    _HAS_STREAM = False

# Verdict << pourquoi la temperature CPU est absente >> (PawnIO / elevation /
# backend). Sert a afficher une raison a cote d'un CPU : N/A muet.
try:
    from collectors import sensors_health as _sensors_health
    _HAS_SENSOR_HEALTH = True
except Exception:
    _sensors_health = None
    _HAS_SENSOR_HEALTH = False

try:
    from thermal_bench import (
        ThermalBench, BenchConfig, BenchPhase,
        list_sessions as bench_list_sessions,
        load_session as bench_load_session,
        THROTTLE_CLOCK_DROP, THROTTLE_TEMP_FLOOR_C,
    )
    from thermal_compare import compare_sessions, generate_comparison_report
    _HAS_BENCH = True
except Exception:
    _HAS_BENCH = False

from prefs    import LOG_DIR, load_prefs, save_prefs
from security import is_admin, request_elevation, is_safe_output_dir

# ── Logging (avec rotation pour éviter la croissance illimitée) ──────────────
_log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "ghisdiag.log",
    maxBytes=2 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[_log_handler],
)
logger = logging.getLogger(__name__)

from orchestrator import DiagnosticOrchestrator, VERSION, AUTHORS, COLLECTORS, run_ps_action, run_ps_stream
from report.generator import ReportGenerator, DEFAULT_REPORTS_DIR

try:
    import ai_analyzer
    from ai_analyzer import analyze_diagnostic, test_api_key
    from ai_report import generate_ai_report
    _HAS_AI = True
except ImportError:
    _HAS_AI = False
    logger.warning("Modules d'analyse IA non disponibles (requests/cryptography manquants)")

# ── Palette Catppuccin Mocha — alignée sur le rapport HTML (assets/report.css)
BG        = "#1e1e2e"   # base   — fond principal
SURFACE   = "#313244"   # surface0 — panneaux, champs
SURFACE2  = "#45475a"   # surface1 — éléments interactifs / hover
BORDER    = "#45475a"   # bordures discrètes des panneaux
FG        = "#cdd6f4"   # text     — texte principal
FG_DIM    = "#a6adc8"   # subtext0 — texte secondaire
FG_MUTED  = "#7f849c"   # overlay1 — texte tertiaire
ACCENT    = "#89b4fa"   # blue
PURPLE    = "#cba6f7"   # mauve
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"
ORANGE    = "#fab387"   # peach — courbe « avant » du comparatif thermique

# Variantes pressées des boutons colorés (≈ −15 % de luminosité)
ACCENT_HOVER = "#7499d4"
RED_HOVER    = "#cf768f"
YELLOW_HOVER = "#d3c094"
GREEN_HOVER  = "#8dc189"
YELLOW_BG    = "#3a2e1e"   # fond des encarts d'avertissement

# Teintes de fond des zones de phase du graphe de bench thermique
ZONE_IDLE = "#2a2b3c"   # repos
ZONE_LOAD = "#3a2a30"   # charge (teinte chaude)
ZONE_COOL = "#27314a"   # refroidissement (teinte froide)

TOTAL_MODULES  = len(COLLECTORS)
_LOG_MAX_LINES = 500

# Lien de soutien — pour ceux qui veulent récompenser le travail (« offrir un café »)
PAYPAL_URL = "https://www.paypal.com/paypalme/spiriteom"
# Dépôt du projet (code source, releases, signalement de bugs)
GITHUB_URL = "https://github.com/ghislaindoucy/ghisdiag"
# Mentions légales des composants tiers (version en ligne, repli si fichier absent)
LICENSES_URL = "https://github.com/ghislaindoucy/ghisdiag/blob/main/THIRD-PARTY-NOTICES.md"


class GhisdiagApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ghisdiag")
        self.resizable(True, True)
        self.minsize(700, 580)
        self.configure(bg=BG)

        # Taille de restauration (utilisée quand l'utilisateur rétrécit depuis le mode maximisé)
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h   = min(1280, int(sw * 0.85)), min(900, int(sh * 0.85))
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
        # Démarre maximisé : tout le contenu visible dès l'ouverture
        self.state("zoomed")

        self._running    = False
        self._tick_id    = None
        self.report_path = None
        self.json_path   = None
        self.ai_report_path = None

        # Moniteur temps réel
        self._monitor_paused  = False
        self._monitor_tick_id = None
        self._temp_cache      = {"cpu": None, "gpu": None, "disks": []}
        self._temp_loading    = False
        self._temp_tick       = 0
        self._sensor_reason   = None   # raison d'un CPU temp N/A (PawnIO/admin…)
        self._temp_stream     = None   # SensorStream persistant (temp CPU continue)

        # Bench thermique
        self._bench           = None       # instance ThermalBench en cours
        self._bench_samples   = []         # échantillons de la session courante
        self._bench_total_sec = 1          # durée totale (échelle X du graphe)
        self._bench_running   = False

        # Setup/MAJ state
        self._setup_busy      = False
        self._winget_needs_update = False

        prefs     = load_prefs()
        saved_dir = prefs.get("output_dir", "")
        self.out_dir_var = tk.StringVar(
            value=saved_dir if saved_dir and Path(saved_dir).exists()
                  else str(DEFAULT_REPORTS_DIR)
        )
        self.auto_open_var = tk.BooleanVar(
            value=prefs.get("auto_open_browser", True)
        )
        self.auto_open_var.trace_add("write", self._on_auto_open_changed)

        # ── Analyse IA multi-fournisseurs ──────────────────────────────────
        # Une clé API par fournisseur (StringVar), + le fournisseur actif.
        if _HAS_AI:
            self.ai_key_vars = {
                pid: tk.StringVar(value=prefs.get(ai_analyzer.PROVIDERS[pid]["key_pref"], ""))
                for pid in ai_analyzer.UI_PROVIDERS
            }
            # Fournisseur actif : préférence enregistrée, sinon migration depuis
            # une ancienne clé Mistral, sinon le défaut.
            saved_provider = prefs.get("ai_provider", "")
            if saved_provider in ai_analyzer.UI_PROVIDERS:
                active = saved_provider
            elif prefs.get("mistral_api_key"):
                active = "mistral"
            else:
                active = ai_analyzer.DEFAULT_PROVIDER
            self.ai_provider_var = tk.StringVar(value=active)
            # Persistance + rafraîchissement du résumé à chaque modification.
            self.ai_provider_var.trace_add("write", self._on_ai_provider_changed)
            for var in self.ai_key_vars.values():
                var.trace_add("write", self._on_ai_key_changed)
        else:
            self.ai_key_vars = {}
            self.ai_provider_var = tk.StringVar(value="")

        # Spooler state
        self._spooler_busy     = False
        self._spooler_printers = []   # [{"name":…, "jobs":[…], …}]
        self._spooler_jobs     = []   # jobs de l'imprimante sélectionnée

        # Network state
        self._network_busy     = False
        self._network_adapters = []  # [{"name":…, "status":…, …}]

        # Repair state
        self._repair_busy = False

        # WiFi state
        self._wifi_busy     = False
        self._wifi_profiles = []  # [{"name":…}]
        self._wifi_networks = []  # [{"ssid":…, "signal":…, …}]

        # Supprime l'anneau de focus clair (couleur système) des widgets tk
        self.option_add("*Listbox.highlightThickness", 0)
        self.option_add("*Text.highlightThickness", 0)
        self.option_add("*Entry.highlightThickness", 0)
        # Liste déroulante des Combobox aux couleurs du thème
        self.option_add("*TCombobox*Listbox.background", SURFACE)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", BG)

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self._set_icon()
        self._enable_dark_titlebar()
        self.update_idletasks()
        self.geometry("740x640")
        x = (self.winfo_screenwidth()  - 740) // 2
        y = (self.winfo_screenheight() - 640) // 2
        self.geometry(f"740x640+{x}+{y}")

    def _set_icon(self):
        # En mode exe gelé (PyInstaller), les assets sont extraits dans _MEIPASS.
        assets = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
        # Barre de titre : .ico (frames multi-tailles nettes).
        try:
            ico = assets / "icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass
        # Barre des tâches : iconbitmap seul ne suffit pas sous Windows — il faut
        # un iconphoto. La référence est conservée pour éviter le ramasse-miettes.
        try:
            png = assets / "icon.png"
            if png.exists():
                self._icon_img = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _enable_dark_titlebar(self):
        """Barre de titre sombre (Windows 10 20H1+) — sans effet ailleurs."""
        try:
            import ctypes
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (19 sur les builds antérieures)
            for attr in (20, 19):
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                    break
        except Exception:
            pass

    # ── UI principale ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # En-tête Ghost Protocol
        hdr = tk.Frame(self, bg=BG, pady=10)
        hdr.pack(fill="x")

        hdr_inner = tk.Frame(hdr, bg=BG)
        hdr_inner.pack()

        # Logo chat (assets/icon.png, 256×256 → réduit en facteur entier).
        # PhotoImage natif Tk 8.6 : pas de dépendance PIL, alpha PNG conservé.
        logo_done = False
        try:
            assets = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"
            png = assets / "icon.png"
            if png.exists():
                img = tk.PhotoImage(file=str(png))
                factor = max(1, min(img.width(), img.height()) // 60)  # 256 → /4 ≈ 64px
                self._header_logo = img.subsample(factor, factor)
                tk.Label(hdr_inner, image=self._header_logo, bg=BG).pack(
                    side="left", padx=(0, 18))
                logo_done = True
        except Exception:
            logo_done = False

        # Repli : planète stylisée si le logo n'a pas pu être chargé.
        if not logo_done:
            planet_c = tk.Canvas(hdr_inner, width=60, height=60, bg=BG, highlightthickness=0)
            planet_c.pack(side="left", padx=(0, 18))
            planet_c.create_arc(1, 22, 59, 38, start=0, extent=180,
                                style="arc", outline=ACCENT, width=1)
            planet_c.create_oval(11, 8, 49, 52, outline=ACCENT, width=2, fill=SURFACE)
            planet_c.create_oval(16, 13, 44, 47, outline=PURPLE, width=1)
            planet_c.create_oval(18, 13, 27, 22, fill=ACCENT, outline="")
            planet_c.create_arc(1, 22, 59, 38, start=180, extent=180,
                                style="arc", outline=ACCENT, width=1)
            planet_c.create_oval(53, 26, 59, 32, fill=PURPLE, outline=ACCENT, width=1)

        # Zone titre
        title_zone = tk.Frame(hdr_inner, bg=BG)
        title_zone.pack(side="left", anchor="center")
        tk.Label(title_zone, text="Ghisdiag",
                 font=("Segoe UI Semibold", 22), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(title_zone, text="Diagnostic & maintenance Windows",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(anchor="w")
        tk.Label(title_zone, text=f"v{VERSION}  ·  {AUTHORS}",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 0))

        # Lien de soutien — « offrez-moi un café » (PayPal)
        coffee = tk.Label(
            title_zone,
            text="☕  Ghisdiag vous est utile ? Offrez-moi un café",
            font=("Segoe UI", 9, "underline"),
            bg=BG, fg=ACCENT, cursor="hand2")
        coffee.pack(anchor="w", pady=(4, 0))
        coffee.bind("<Button-1>", lambda e: webbrowser.open(PAYPAL_URL))
        coffee.bind("<Enter>", lambda e: coffee.config(fg=PURPLE))
        coffee.bind("<Leave>", lambda e: coffee.config(fg=ACCENT))

        # Lien vers le dépôt GitHub (code source, releases, bugs)
        github = tk.Label(
            title_zone,
            text="⌨  Code source & releases sur GitHub",
            font=("Segoe UI", 9, "underline"),
            bg=BG, fg=ACCENT, cursor="hand2")
        github.pack(anchor="w", pady=(2, 0))
        github.bind("<Button-1>", lambda e: webbrowser.open(GITHUB_URL))
        github.bind("<Enter>", lambda e: github.config(fg=PURPLE))
        github.bind("<Leave>", lambda e: github.config(fg=ACCENT))

        # Lien vers les licences & mentions légales des composants tiers
        licences = tk.Label(
            title_zone,
            text="⚖  Licences & mentions légales",
            font=("Segoe UI", 9, "underline"),
            bg=BG, fg=ACCENT, cursor="hand2")
        licences.pack(anchor="w", pady=(2, 0))
        licences.bind("<Button-1>", lambda e: self._show_licenses())
        licences.bind("<Enter>", lambda e: licences.config(fg=PURPLE))
        licences.bind("<Leave>", lambda e: licences.config(fg=ACCENT))

        # Ligne décorative bicolore (remplace ttk.Separator)
        sep_c = tk.Canvas(self, height=3, bg=BG, highlightthickness=0)
        sep_c.pack(fill="x", pady=(6, 0))

        def _refresh_sep(e=None, c=sep_c):
            w = c.winfo_width()
            if w < 10:
                return
            c.delete("all")
            c.create_line(20, 1, w // 2 - 10, 1, fill=ACCENT, width=2)
            c.create_line(w // 2 + 10, 1, w - 20, 1, fill=PURPLE, width=1)

        sep_c.bind("<Configure>", _refresh_sep)
        self.after(80, _refresh_sep)

        # Style des onglets
        style = ttk.Style()
        style.theme_use("default")
        style.configure("PD.TNotebook",
                        background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("PD.TNotebook.Tab",
                        background=BG, foreground=FG_MUTED,
                        font=("Segoe UI", 10, "bold"),
                        padding=[20, 10])
        style.map("PD.TNotebook.Tab",
                  background=[("selected", SURFACE2), ("active", SURFACE)],
                  foreground=[("selected", ACCENT), ("active", FG_DIM)])
        style.configure("PD.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=SURFACE,
                        bordercolor=BG, borderwidth=0,
                        lightcolor=ACCENT, darkcolor=ACCENT)
        style.configure("PD.Vertical.TScrollbar",
                        background=SURFACE2, troughcolor=BG,
                        bordercolor=BG, arrowcolor=FG_MUTED, relief="flat")
        style.map("PD.Vertical.TScrollbar",
                  background=[("active", FG_MUTED), ("pressed", FG_MUTED)])
        style.configure("PD.TCombobox",
                        fieldbackground=SURFACE2, background=SURFACE2,
                        foreground=FG, arrowcolor=FG_DIM,
                        bordercolor=BORDER, lightcolor=SURFACE2, darkcolor=SURFACE2,
                        selectbackground=SURFACE2, selectforeground=FG)
        style.map("PD.TCombobox",
                  fieldbackground=[("readonly", SURFACE2)],
                  foreground=[("readonly", FG)])

        # Notebook
        nb = ttk.Notebook(self, style="PD.TNotebook")
        nb.pack(fill="both", expand=True)
        self._nb = nb

        analyse_frame = tk.Frame(nb, bg=BG)
        nb.add(analyse_frame, text="  Analyse  ")

        if _HAS_BENCH:
            bench_frame = tk.Frame(nb, bg=BG)
            nb.add(bench_frame, text="  Bench thermique  ")

        troubleshoot_frame = tk.Frame(nb, bg=BG)
        nb.add(troubleshoot_frame, text="  Dépannage  ")

        wifi_frame = tk.Frame(nb, bg=BG)
        nb.add(wifi_frame, text="  WiFi  ")

        setup_frame = tk.Frame(nb, bg=BG)
        nb.add(setup_frame, text="  Setup / MAJ  ")

        self._build_analyse_tab(analyse_frame)
        if _HAS_BENCH:
            self._build_bench_tab(bench_frame)
        self._build_troubleshoot_tab(troubleshoot_frame)
        self._build_wifi_tab(wifi_frame)
        self._build_setup_tab(setup_frame)

        # Installation du driver PawnIO (temp/freq CPU) au plus tot, en tache de
        # fond : il sera pret avant le 1er relevé de températures (~10 s).
        self.after(300, lambda: threading.Thread(
            target=self._ensure_pawnio_startup, daemon=True).start())

        # Démarrage du moniteur et vérification SMART au lancement
        self.after(800, self._monitor_start)
        self.after(1200, lambda: threading.Thread(
            target=self._smart_startup_check, daemon=True).start())

    # ── Licences & mentions légales ───────────────────────────────────────────
    def _show_licenses(self):
        """Affiche les mentions légales des composants tiers (fichier embarqué)."""
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
        notices = base / "THIRD-PARTY-NOTICES.md"
        try:
            text = notices.read_text(encoding="utf-8")
        except Exception:
            # Repli : pas de fichier embarqué (ex. dev sans build) → version en ligne
            webbrowser.open(LICENSES_URL)
            return

        win = tk.Toplevel(self)
        win.title("Ghisdiag — Licences & mentions légales")
        win.configure(bg=BG)
        win.geometry("760x620")
        win.minsize(560, 420)
        win.transient(self)

        tk.Label(win, text="Licences & mentions légales",
                 font=("Segoe UI Semibold", 15), bg=BG, fg=FG).pack(
                     anchor="w", padx=16, pady=(14, 2))
        tk.Label(win,
                 text="Composants tiers redistribués par Ghisdiag et leurs licences respectives.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(anchor="w", padx=16)

        body = tk.Frame(win, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        sb = ttk.Scrollbar(body, orient="vertical", style="PD.Vertical.TScrollbar")
        sb.pack(side="right", fill="y")
        txt = tk.Text(body, wrap="word", bg=SURFACE, fg=FG,
                      font=("Consolas", 9), relief="flat", padx=12, pady=10,
                      yscrollcommand=sb.set, insertbackground=FG)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        txt.insert("1.0", text)
        txt.config(state="disabled")

        bar = tk.Frame(win, bg=BG)
        bar.pack(fill="x", padx=16, pady=(0, 14))
        tk.Button(bar, text="Voir sur GitHub", font=("Segoe UI", 9),
                  bg=SURFACE2, fg=FG, relief="flat", cursor="hand2",
                  activebackground=SURFACE, activeforeground=ACCENT,
                  command=lambda: webbrowser.open(LICENSES_URL)).pack(side="left")
        tk.Button(bar, text="Fermer", font=("Segoe UI", 9),
                  bg=SURFACE2, fg=FG, relief="flat", cursor="hand2",
                  activebackground=SURFACE, activeforeground=ACCENT,
                  command=win.destroy).pack(side="right")

    # ── Onglet Analyse ────────────────────────────────────────────────────────
    def _build_analyse_tab(self, parent: tk.Frame):
        # Dossier de destination
        dest = tk.Frame(parent, bg=BG, pady=12)
        dest.pack(fill="x", padx=28)

        tk.Label(dest, text="Enregistrer le rapport dans :",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(anchor="w")

        row = tk.Frame(dest, bg=BG)
        row.pack(fill="x", pady=(4, 0))

        tk.Entry(
            row, textvariable=self.out_dir_var,
            font=("Consolas", 10), bg=SURFACE, fg=FG,
            insertbackground=FG, relief="flat", bd=0,
            readonlybackground=SURFACE, state="readonly",
        ).pack(side="left", fill="x", expand=True, ipady=7, ipadx=8)

        tk.Button(
            row, text="  Parcourir…  ",
            font=("Segoe UI", 10), bg=SURFACE2, fg=FG,
            activebackground=SURFACE, activeforeground=FG,
            relief="flat", cursor="hand2", pady=7,
            command=self._browse,
        ).pack(side="left", padx=(8, 0))

        tk.Frame(parent, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(4, 0))

        # Bouton principal
        btn_zone = tk.Frame(parent, bg=BG, pady=14)
        btn_zone.pack(fill="x", padx=28)

        self.btn_start = tk.Button(
            btn_zone,
            text="▶   Lancer le diagnostic",
            font=("Segoe UI", 14, "bold"),
            bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2",
            padx=32, pady=14,
            command=self._start,
        )
        self.btn_start.pack(fill="x")

        # Zone de progression
        prog_zone = tk.Frame(parent, bg=BG)
        prog_zone.pack(fill="x", padx=28)

        self.step_var = tk.StringVar(value="En attente…")
        self.step_lbl = tk.Label(
            prog_zone, textvariable=self.step_var,
            font=("Segoe UI", 11), bg=BG, fg=FG, anchor="w",
        )
        self.step_lbl.pack(fill="x", pady=(0, 6))

        self.pbar = ttk.Progressbar(
            prog_zone, style="PD.Horizontal.TProgressbar",
            mode="determinate", maximum=TOTAL_MODULES,
        )
        self.pbar.pack(fill="x", ipady=4, pady=(0, 4))

        counter_row = tk.Frame(prog_zone, bg=BG)
        counter_row.pack(fill="x")
        self.counter_var = tk.StringVar(value="")
        tk.Label(counter_row, textvariable=self.counter_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, anchor="w").pack(side="left")
        self.elapsed_var = tk.StringVar(value="")
        tk.Label(counter_row, textvariable=self.elapsed_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, anchor="e").pack(side="right")

        tk.Frame(parent, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(10, 0))

        # ── Moniteur Temps Réel ───────────────────────────────────────────────
        mon_outer = tk.Frame(parent, bg=BG)
        mon_outer.pack(fill="x", padx=28, pady=(8, 0))

        mon_hdr_row = tk.Frame(mon_outer, bg=BG)
        mon_hdr_row.pack(fill="x")
        tk.Label(mon_hdr_row, text="Moniteur Temps Réel",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack(side="left")
        self._mon_status_var = tk.StringVar(value="")
        tk.Label(mon_hdr_row, textvariable=self._mon_status_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(side="right")

        mon_box = tk.Frame(mon_outer, bg=SURFACE, pady=8, padx=4,
                           highlightbackground=BORDER, highlightthickness=1, bd=0)
        mon_box.pack(fill="x", pady=(4, 6))

        # 4 colonnes : CPU, RAM, Disque I/O, Températures
        self._mon_bars = {}
        self._mon_vals = {}

        col_defs = [
            ("cpu",  "Processeur"),
            ("ram",  "Mémoire"),
            ("disk", "Disque I/O"),
        ]
        for key, label in col_defs:
            col = tk.Frame(mon_box, bg=SURFACE)
            col.pack(side="left", fill="x", expand=True, padx=8)

            top = tk.Frame(col, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=label,
                     font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG_DIM).pack(side="left")
            val_var = tk.StringVar(value="—")
            self._mon_vals[key] = val_var
            tk.Label(top, textvariable=val_var,
                     font=("Consolas", 9, "bold"), bg=SURFACE, fg=FG).pack(side="right")

            pb = ttk.Progressbar(col, style="PD.Horizontal.TProgressbar",
                                  mode="determinate", maximum=100)
            pb.pack(fill="x", ipady=3, pady=(2, 0))
            self._mon_bars[key] = pb

        # Colonne températures
        temp_col = tk.Frame(mon_box, bg=SURFACE)
        temp_col.pack(side="left", padx=(12, 8), anchor="n")
        tk.Label(temp_col, text="Températures",
                 font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG_DIM).pack(anchor="w")
        self._mon_temp_cpu_var  = tk.StringVar(value="CPU : —")
        self._mon_temp_gpu_var  = tk.StringVar(value="GPU : —")
        self._mon_temp_disk_var = tk.StringVar(value="SSD/HDD : —")
        for var in (self._mon_temp_cpu_var, self._mon_temp_gpu_var, self._mon_temp_disk_var):
            tk.Label(temp_col, textvariable=var,
                     font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED).pack(anchor="w")

        tk.Frame(parent, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(0, 0))

        # ── Boutons bas + panneau IA (packés AVANT le log pour rester visibles) ───
        foot = tk.Frame(parent, bg=BG, pady=10)
        foot.pack(fill="x", padx=28)

        self.btn_open = tk.Button(
            foot, text="Ouvrir le rapport HTML",
            font=("Segoe UI", 11), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, activeforeground=FG,
            relief="flat", cursor="hand2", padx=20, pady=10,
            state="disabled", command=self._open_html,
        )
        self.btn_open.pack(side="left")

        self.btn_folder = tk.Button(
            foot, text="Ouvrir le dossier",
            font=("Segoe UI", 11), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, activeforeground=FG,
            relief="flat", cursor="hand2", padx=20, pady=10,
            state="disabled", command=self._open_folder,
        )
        self.btn_folder.pack(side="left", padx=(8, 0))

        tk.Checkbutton(
            foot, text="Ouvrir auto.",
            variable=self.auto_open_var,
            font=("Segoe UI", 9), bg=BG, fg=FG_MUTED,
            activebackground=BG, activeforeground=FG,
            selectcolor=SURFACE, relief="flat", cursor="hand2",
        ).pack(side="left", padx=(16, 0))

        self.result_lbl = tk.Label(
            foot, text="",
            font=("Segoe UI", 10), bg=BG, fg=GREEN, anchor="e",
        )
        self.result_lbl.pack(side="right")

        # ── Analyse IA (résumé + bouton de configuration) ───────────────────────
        ai_panel = tk.Frame(parent, bg=SURFACE, pady=8)
        ai_panel.pack(fill="x", padx=28, pady=(0, 6))

        tk.Label(
            ai_panel, text="🤖  Analyse IA (optionnel)",
            font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=ACCENT,
        ).pack(side="left", padx=(8, 12))

        # Libellé d'état (fournisseur actif + clé renseignée ou non), tenu à jour.
        self.ai_status_lbl = tk.Label(
            ai_panel, text="",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED,
        )
        self.ai_status_lbl.pack(side="left")

        tk.Button(
            ai_panel, text="Configurer l'IA…",
            font=("Segoe UI", 9), bg=ACCENT, fg=BG,
            activebackground=PURPLE, relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=self._open_ai_config,
        ).pack(side="right", padx=(8, 8))

        self._refresh_ai_status()

        # Journal d'activité (expand=True → prend tout l'espace restant, DOIT être en dernier)
        log_hdr = tk.Frame(parent, bg=BG)
        log_hdr.pack(fill="x", padx=28, pady=(4, 4))
        tk.Label(log_hdr, text="Journal d'activité",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=FG_DIM).pack(side="left")
        tk.Button(
            log_hdr, text="Effacer",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=8, pady=2, command=self._clear_log,
        ).pack(side="right")
        tk.Button(
            log_hdr, text="Voir le fichier log",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=8, pady=2, command=self._open_log_file,
        ).pack(side="right", padx=(0, 6))

        log_wrap = tk.Frame(parent, bg=SURFACE, bd=0,
                            highlightbackground=BORDER, highlightthickness=1)
        log_wrap.pack(fill="both", expand=True, padx=28, pady=(0, 6))

        self.log = tk.Text(
            log_wrap,
            bg=SURFACE, fg=FG_DIM,
            font=("Consolas", 10),
            bd=0, padx=10, pady=10,
            state="disabled", wrap="word",
            selectbackground=SURFACE2,
        )
        sb = ttk.Scrollbar(log_wrap, command=self.log.yview, style="PD.Vertical.TScrollbar")
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        self.log.tag_config("ok",   foreground=GREEN)
        self.log.tag_config("warn", foreground=YELLOW)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("info", foreground=ACCENT)
        self.log.tag_config("dim",  foreground=FG_MUTED)
        self.log.tag_config("time", foreground=PURPLE)

    # ── Onglet Dépannage ──────────────────────────────────────────────────────
    def _build_troubleshoot_tab(self, parent: tk.Frame):
        style = ttk.Style()
        style.configure("Dep.TNotebook",
                        background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("Dep.TNotebook.Tab",
                        background=BG, foreground=FG_MUTED,
                        font=("Segoe UI", 10), padding=[16, 8])
        style.map("Dep.TNotebook.Tab",
                  background=[("selected", SURFACE2), ("active", SURFACE)],
                  foreground=[("selected", ACCENT), ("active", FG_DIM)])

        sub_nb = ttk.Notebook(parent, style="Dep.TNotebook")
        sub_nb.pack(fill="both", expand=True)

        impression_frame  = tk.Frame(sub_nb, bg=BG)
        reseau_frame      = tk.Frame(sub_nb, bg=BG)
        reparation_frame  = tk.Frame(sub_nb, bg=BG)

        sub_nb.add(impression_frame, text="  Impression  ")
        sub_nb.add(reseau_frame,     text="  Réseau  ")
        sub_nb.add(reparation_frame, text="  Réparation système  ")

        self._build_impression_panel(impression_frame)
        self._build_reseau_panel(reseau_frame)
        self._build_reparation_panel(reparation_frame)

    def _build_impression_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._build_spooler_section(inner)

    def _build_reseau_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))
        self._build_network_section(inner)

    # ── Section Spooler ───────────────────────────────────────────────────────
    def _build_spooler_section(self, parent: tk.Frame):
        section = tk.Frame(parent, bg=BG, pady=16)
        section.pack(fill="x", padx=28)

        tk.Label(section, text="🖨  Spooler d'impression",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(section,
                 text="Gérez les imprimantes installées et leurs files d'attente.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 10))

        # ── Barre statut + boutons globaux ────────────────────────────────────
        top_row = tk.Frame(section, bg=BG)
        top_row.pack(fill="x", pady=(0, 10))

        status_frame = tk.Frame(top_row, bg=SURFACE, padx=14, pady=8)
        status_frame.pack(side="left")

        tk.Label(status_frame, text="Service Spooler",
                 font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM).grid(row=0, column=0, sticky="w")
        self.spooler_status_var = tk.StringVar(value="—")
        tk.Label(status_frame, textvariable=self.spooler_status_var,
                 font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG).grid(row=1, column=0, sticky="w")

        btns_global = tk.Frame(top_row, bg=BG)
        btns_global.pack(side="right")

        self.btn_spooler_refresh = tk.Button(
            btns_global, text="↻  Actualiser",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=12, pady=7, command=self._spooler_refresh,
        )
        self.btn_spooler_refresh.pack(side="left", padx=(0, 6))

        self.btn_spooler_fix = tk.Button(
            btns_global, text="🗑  Vider tout",
            font=("Segoe UI", 10), bg=RED, fg=BG,
            activebackground=RED_HOVER, relief="flat", cursor="hand2",
            padx=12, pady=7, command=self._spooler_fix,
        )
        self.btn_spooler_fix.pack(side="left")

        # ── Imprimantes + Travaux ─────────────────────────────────────────────
        lists_row = tk.Frame(section, bg=BG)
        lists_row.pack(fill="x")

        # Colonne imprimantes
        left_col = tk.Frame(lists_row, bg=BG)
        left_col.pack(side="left", fill="both", expand=True)

        tk.Label(left_col, text="Imprimantes installées",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack(anchor="w", pady=(0, 4))

        printer_wrap = tk.Frame(left_col, bg=SURFACE)
        printer_wrap.pack(fill="both", expand=True)

        self.printer_listbox = tk.Listbox(
            printer_wrap,
            bg=SURFACE, fg=FG, font=("Segoe UI", 10),
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0, activestyle="none", height=5,
        )
        pr_sb = ttk.Scrollbar(printer_wrap, command=self.printer_listbox.yview, style="PD.Vertical.TScrollbar")
        self.printer_listbox.configure(yscrollcommand=pr_sb.set)
        pr_sb.pack(side="right", fill="y")
        self.printer_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.printer_listbox.bind("<<ListboxSelect>>", self._spooler_on_printer_select)

        # Colonne travaux
        right_col = tk.Frame(lists_row, bg=BG)
        right_col.pack(side="left", fill="both", expand=True, padx=(10, 0))

        self._spooler_jobs_title = tk.StringVar(value="Travaux d'impression")
        tk.Label(right_col, textvariable=self._spooler_jobs_title,
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack(anchor="w", pady=(0, 4))

        job_wrap = tk.Frame(right_col, bg=SURFACE)
        job_wrap.pack(fill="both", expand=True)

        self.job_listbox = tk.Listbox(
            job_wrap,
            bg=SURFACE, fg=FG, font=("Consolas", 9),
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0, activestyle="none", height=5,
        )
        job_sb = ttk.Scrollbar(job_wrap, command=self.job_listbox.yview, style="PD.Vertical.TScrollbar")
        self.job_listbox.configure(yscrollcommand=job_sb.set)
        job_sb.pack(side="right", fill="y")
        self.job_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.job_listbox.bind("<<ListboxSelect>>", self._spooler_on_job_select)

        # ── Boutons d'action sur les travaux ──────────────────────────────────
        job_btns = tk.Frame(section, bg=BG)
        job_btns.pack(fill="x", pady=(8, 0))

        self.btn_cancel_job = tk.Button(
            job_btns, text="✗  Annuler ce travail",
            font=("Segoe UI", 10), bg=YELLOW, fg=BG,
            activebackground=YELLOW_HOVER, relief="flat", cursor="hand2",
            padx=12, pady=6, state="disabled", command=self._spooler_cancel_job,
        )
        self.btn_cancel_job.pack(side="left", padx=(0, 6))

        self.btn_cancel_all = tk.Button(
            job_btns, text="✗  Annuler tous les travaux",
            font=("Segoe UI", 10), bg=YELLOW, fg=BG,
            activebackground=YELLOW_HOVER, relief="flat", cursor="hand2",
            padx=12, pady=6, state="disabled", command=self._spooler_cancel_all,
        )
        self.btn_cancel_all.pack(side="left")

        # Bouton page de test
        test_row = tk.Frame(section, bg=BG)
        test_row.pack(fill="x", pady=(8, 0))
        self.btn_print_test = tk.Button(
            test_row, text="🖨  Imprimer une page de test",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=12, pady=7, state="disabled",
            command=self._spooler_print_test,
        )
        self.btn_print_test.pack(side="left")

        # Log
        self.spooler_log_var = tk.StringVar(value="")
        log_frame = tk.Frame(section, bg=SURFACE, pady=6, padx=10)
        log_frame.pack(fill="x", pady=(10, 0))
        tk.Label(log_frame, textvariable=self.spooler_log_var,
                 font=("Consolas", 9), bg=SURFACE, fg=FG_DIM,
                 justify="left", anchor="w", wraplength=620).pack(fill="x")

        self.after(200, self._spooler_refresh)

    def _spooler_refresh(self):
        if self._spooler_busy:
            return
        self._spooler_busy = True
        self.btn_spooler_refresh.configure(state="disabled")
        self.btn_spooler_fix.configure(state="disabled")
        self.btn_cancel_job.configure(state="disabled")
        self.btn_cancel_all.configure(state="disabled")
        self.btn_print_test.configure(state="disabled")
        self.spooler_status_var.set("Chargement…")
        self.printer_listbox.delete(0, "end")
        self.printer_listbox.insert("end", "  Chargement…")
        self.job_listbox.delete(0, "end")

        def _worker():
            try:
                data     = run_ps_action("collectors/spooler_fix.ps1", ["-Action", "printers"])
                printers = data.get("printers", [])
                svc      = data.get("service", {})

                def _update():
                    self._spooler_printers = printers
                    self._spooler_jobs     = []
                    self.spooler_status_var.set(svc.get("status", "?"))
                    self.printer_listbox.delete(0, "end")
                    for p in printers:
                        icon   = "●" if p.get("status") == "Normal" else "○"
                        jobs_n = p.get("job_count", 0)
                        suffix = f"  ({jobs_n} travail{'x' if jobs_n > 1 else ''})" if jobs_n else ""
                        dflt   = "  ★" if p.get("is_default") else ""
                        self.printer_listbox.insert("end", f"  {icon}  {p.get('name', '?')}{dflt}{suffix}")
                    if not printers:
                        self.printer_listbox.insert("end", "  Aucune imprimante trouvée")
                    self.job_listbox.delete(0, "end")
                    self._spooler_jobs_title.set("Travaux d'impression")
                    self.spooler_log_var.set("")
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_spooler_fix.configure(state="normal")
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.spooler_status_var.set("Erreur")
                    self.printer_listbox.delete(0, "end")
                    self.printer_listbox.insert("end", "  Erreur de chargement")
                    self.spooler_log_var.set(f"Erreur : {e}")
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_spooler_fix.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _spooler_on_printer_select(self, event=None):
        sel = self.printer_listbox.curselection()
        if not sel or not self._spooler_printers:
            self.job_listbox.delete(0, "end")
            self.btn_cancel_job.configure(state="disabled")
            self.btn_cancel_all.configure(state="disabled")
            self.btn_print_test.configure(state="disabled")
            return
        idx = sel[0]
        if idx >= len(self._spooler_printers):
            return
        p = self._spooler_printers[idx]
        self._spooler_jobs = p.get("jobs", [])
        self._spooler_jobs_title.set(f"Travaux — {p.get('name', '?')}")
        self.job_listbox.delete(0, "end")
        if self._spooler_jobs:
            # En-tête colonnes
            self.job_listbox.insert("end", f"  {'ID':<5} {'Document':<28} {'Utilisateur':<14} {'Statut':<12} {'Pages'}")
            self.job_listbox.insert("end", "  " + "─" * 72)
            for j in self._spooler_jobs:
                doc  = (j.get("document", "") or "")[:27]
                user = (j.get("user", "") or "")[:13]
                stat = (j.get("status", "") or "")[:11]
                jid  = j.get("id", "?")
                pages = j.get("pages", 0)
                self.job_listbox.insert("end", f"  {str(jid):<5} {doc:<28} {user:<14} {stat:<12} {pages}")
            self.btn_cancel_all.configure(state="normal")
        else:
            self.job_listbox.insert("end", "  (file vide)")
            self.btn_cancel_all.configure(state="disabled")
        self.btn_cancel_job.configure(state="disabled")
        self.btn_print_test.configure(state="normal")

    def _spooler_on_job_select(self, event=None):
        sel = self.job_listbox.curselection()
        if not sel:
            self.btn_cancel_job.configure(state="disabled")
            return
        # Les 2 premières lignes sont l'en-tête — pas cliquables
        job_data_idx = sel[0] - 2
        if job_data_idx >= 0 and job_data_idx < len(self._spooler_jobs):
            self.btn_cancel_job.configure(state="normal")
        else:
            self.btn_cancel_job.configure(state="disabled")

    def _spooler_cancel_job(self):
        if self._spooler_busy:
            return
        sel_printer = self.printer_listbox.curselection()
        sel_job     = self.job_listbox.curselection()
        if not sel_printer or not sel_job:
            return
        idx_p = sel_printer[0]
        idx_j = sel_job[0]
        if idx_p >= len(self._spooler_printers):
            return
        printer = self._spooler_printers[idx_p]
        # Les 2 premières lignes sont l'en-tête — offset de 2
        job_data_idx = idx_j - 2
        if job_data_idx < 0 or job_data_idx >= len(self._spooler_jobs):
            return
        job      = self._spooler_jobs[job_data_idx]
        job_id   = job.get("id", -1)
        doc_name = job.get("document", "?")
        p_name   = printer.get("name", "")

        if not messagebox.askyesno(
            "Confirmer annulation",
            f"Annuler le travail ?\n\n  {doc_name}\n  (ID {job_id} — {p_name})",
            icon="warning",
        ):
            return

        self._spooler_busy = True
        self.btn_spooler_refresh.configure(state="disabled")
        self.btn_cancel_job.configure(state="disabled")
        self.btn_cancel_all.configure(state="disabled")
        self.spooler_log_var.set("Annulation en cours…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/spooler_fix.ps1",
                    ["-Action", "cancel-job", "-PrinterName", p_name, "-JobId", str(job_id)],
                )
                success = data.get("success", False)
                def _update():
                    self._spooler_busy = False
                    if success:
                        self.spooler_log_var.set(f"Travail {job_id} annulé.")
                    else:
                        self.spooler_log_var.set(f"Erreur : {data.get('error', '?')}")
                    self.after(300, self._spooler_refresh)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.spooler_log_var.set(f"Erreur : {e}")
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_cancel_job.configure(state="normal")
                    self.btn_cancel_all.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _spooler_cancel_all(self):
        if self._spooler_busy:
            return
        sel = self.printer_listbox.curselection()
        if not sel or not self._spooler_printers:
            return
        idx = sel[0]
        if idx >= len(self._spooler_printers):
            return
        printer = self._spooler_printers[idx]
        p_name  = printer.get("name", "")
        n_jobs  = printer.get("job_count", 0)

        if not messagebox.askyesno(
            "Confirmer annulation",
            f"Annuler tous les travaux de :\n\n  {p_name}\n\n"
            f"  {n_jobs} travail(s) sera(ont) annulé(s).",
            icon="warning",
        ):
            return

        self._spooler_busy = True
        self.btn_spooler_refresh.configure(state="disabled")
        self.btn_cancel_job.configure(state="disabled")
        self.btn_cancel_all.configure(state="disabled")
        self.btn_spooler_fix.configure(state="disabled")
        self.spooler_log_var.set("Annulation en cours…")

        def _worker():
            try:
                data    = run_ps_action(
                    "collectors/spooler_fix.ps1",
                    ["-Action", "cancel-all", "-PrinterName", p_name],
                )
                success  = data.get("success", False)
                cancelled = data.get("cancelled", 0)
                def _update():
                    self._spooler_busy = False
                    if success:
                        self.spooler_log_var.set(f"{cancelled} travail(s) annulé(s) sur {p_name}.")
                    else:
                        self.spooler_log_var.set(f"Erreur : {data.get('error', '?')}")
                    self.after(300, self._spooler_refresh)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.spooler_log_var.set(f"Erreur : {e}")
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_cancel_job.configure(state="normal")
                    self.btn_cancel_all.configure(state="normal")
                    self.btn_spooler_fix.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _spooler_fix(self):
        if self._spooler_busy:
            return
        if not messagebox.askyesno(
            "Vider tout le spooler",
            "Vider TOUTE la file d'impression ?\n\n"
            "Tous les travaux de toutes les imprimantes seront supprimés\n"
            "et le service Spooler sera redémarré.",
            icon="warning",
        ):
            return

        self._spooler_busy = True
        self.btn_spooler_refresh.configure(state="disabled")
        self.btn_spooler_fix.configure(state="disabled", text="⏳  En cours…")
        self.btn_cancel_job.configure(state="disabled")
        self.btn_cancel_all.configure(state="disabled")
        self.spooler_log_var.set("Opération en cours…")

        def _worker():
            try:
                data    = run_ps_action("collectors/spooler_fix.ps1", ["-Action", "fix"], timeout=90)
                success = data.get("success", False)
                steps   = data.get("steps", [])
                svc     = data.get("service", {})
                log_txt = "\n".join(steps)

                def _update():
                    self.spooler_status_var.set(svc.get("status", "?"))
                    self.spooler_log_var.set(log_txt)
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_spooler_fix.configure(state="normal", text="🗑  Vider tout")
                    if success:
                        messagebox.showinfo("Spooler", "Spooler vidé et redémarré avec succès.")
                    else:
                        messagebox.showerror("Erreur spooler", data.get("error", "Erreur inconnue"))
                    self.after(300, self._spooler_refresh)
                self.after(0, _update)
            except Exception as exc:
                logger.exception("Erreur spooler fix")
                _exc = exc
                def _err(e=_exc):
                    self.spooler_log_var.set(f"Erreur : {e}")
                    self._spooler_busy = False
                    self.btn_spooler_refresh.configure(state="normal")
                    self.btn_spooler_fix.configure(state="normal", text="🗑  Vider tout")
                    messagebox.showerror("Erreur", str(e))
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _spooler_print_test(self):
        sel = self.printer_listbox.curselection()
        if not sel or not self._spooler_printers:
            return
        idx = sel[0]
        if idx >= len(self._spooler_printers):
            return
        printer_name = self._spooler_printers[idx].get("name", "")
        if not printer_name:
            return

        self.btn_print_test.configure(state="disabled")
        self.spooler_log_var.set(f"Envoi de la page de test à {printer_name}…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/spooler_fix.ps1",
                    ["-Action", "print-test", "-PrinterName", printer_name],
                )
                def _result():
                    if data.get("success"):
                        self.spooler_log_var.set(f"✓ Page de test envoyée à {printer_name}")
                    else:
                        err = data.get("error", "Erreur inconnue")
                        self.spooler_log_var.set(f"✗ Erreur : {err}")
                    self.btn_print_test.configure(state="normal")
                self.after(0, _result)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.spooler_log_var.set(f"✗ Erreur : {e}")
                    self.btn_print_test.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Section Réseau ────────────────────────────────────────────────────────
    def _build_network_section(self, parent: tk.Frame):
        section = tk.Frame(parent, bg=BG, pady=16)
        section.pack(fill="x", padx=28)

        tk.Label(section, text="🌐  Cartes réseau",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(section, text="Liste et réinitialise les adaptateurs réseau (Ethernet, Wi-Fi, VPN).",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 10))

        content = tk.Frame(section, bg=BG)
        content.pack(fill="x")

        # Liste des adaptateurs
        list_frame = tk.Frame(content, bg=SURFACE)
        list_frame.pack(side="left", fill="both", expand=True)

        self.network_listbox = tk.Listbox(
            list_frame,
            bg=SURFACE, fg=FG,
            font=("Consolas", 10),
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0,
            activestyle="none",
            height=7,
        )
        lb_scroll = ttk.Scrollbar(list_frame, command=self.network_listbox.yview, style="PD.Vertical.TScrollbar")
        self.network_listbox.configure(yscrollcommand=lb_scroll.set)
        lb_scroll.pack(side="right", fill="y")
        self.network_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.network_listbox.bind("<<ListboxSelect>>", self._network_on_select)

        # Panneau détail
        detail_frame = tk.Frame(content, bg=SURFACE2, padx=12, pady=10, width=220)
        detail_frame.pack(side="left", anchor="n", padx=(8, 0))

        self.net_detail_vars = {}
        fields = [
            ("Statut",    "status"),
            ("Type",      "media_type"),
            ("Vitesse",   "link_speed"),
            ("IPv4",      "ipv4"),
            ("MAC",       "mac"),
        ]
        for label, key in fields:
            tk.Label(detail_frame, text=label,
                     font=("Segoe UI", 9), bg=SURFACE2, fg=FG_DIM,
                     anchor="w").pack(fill="x")
            var = tk.StringVar(value="—")
            self.net_detail_vars[key] = var
            tk.Label(detail_frame, textvariable=var,
                     font=("Segoe UI", 9, "bold"), bg=SURFACE2, fg=FG,
                     anchor="w").pack(fill="x", pady=(0, 6))

        # Boutons
        btns = tk.Frame(content, bg=BG)
        btns.pack(side="left", padx=(10, 0), anchor="n")

        self.btn_net_refresh = tk.Button(
            btns, text="↻  Actualiser",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=8, command=self._network_refresh,
        )
        self.btn_net_refresh.pack(fill="x", pady=(0, 6))

        self.btn_net_reset = tk.Button(
            btns, text="⟳  Réinitialiser",
            font=("Segoe UI", 10), bg=YELLOW, fg=BG,
            activebackground=YELLOW_HOVER, relief="flat", cursor="hand2",
            padx=14, pady=8, state="disabled", command=self._network_reset,
        )
        self.btn_net_reset.pack(fill="x")

        # Log réseau
        self.network_log_var = tk.StringVar(value="")
        net_log_frame = tk.Frame(section, bg=SURFACE, pady=6, padx=10)
        net_log_frame.pack(fill="x", pady=(10, 0))
        tk.Label(net_log_frame, textvariable=self.network_log_var,
                 font=("Consolas", 9), bg=SURFACE, fg=FG_DIM,
                 justify="left", anchor="w", wraplength=620).pack(fill="x")

        self.after(300, self._network_refresh)

    def _network_refresh(self):
        if self._network_busy:
            return
        self._network_busy = True
        self.btn_net_refresh.configure(state="disabled")
        self.btn_net_reset.configure(state="disabled")
        self.network_listbox.delete(0, "end")
        self.network_listbox.insert("end", "  Chargement…")
        self.network_log_var.set("")

        def _worker():
            try:
                data     = run_ps_action("collectors/network_cards.ps1", ["-Action", "list"])
                adapters = data.get("adapters", [])

                def _update():
                    self._network_adapters = adapters
                    self.network_listbox.delete(0, "end")
                    for a in adapters:
                        icon  = "●" if a.get("status") == "Up" else "○"
                        label = f"  {icon}  {a.get('name', '?')}  —  {a.get('status', '?')}"
                        self.network_listbox.insert("end", label)
                    if not adapters:
                        self.network_listbox.insert("end", "  Aucun adaptateur trouvé")
                    self._clear_net_detail()
                    self._network_busy = False
                    self.btn_net_refresh.configure(state="normal")
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.network_listbox.delete(0, "end")
                    self.network_listbox.insert("end", "  Erreur de chargement")
                    self.network_log_var.set(f"Erreur : {e}")
                    self._network_busy = False
                    self.btn_net_refresh.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _network_on_select(self, event=None):
        sel = self.network_listbox.curselection()
        if not sel or not self._network_adapters:
            self._clear_net_detail()
            self.btn_net_reset.configure(state="disabled")
            return
        idx = sel[0]
        if idx >= len(self._network_adapters):
            return
        a = self._network_adapters[idx]
        for key, var in self.net_detail_vars.items():
            val = a.get(key, "")
            var.set(str(val) if val else "—")
        self.btn_net_reset.configure(state="normal")

    def _clear_net_detail(self):
        for var in self.net_detail_vars.values():
            var.set("—")

    def _network_reset(self):
        if self._network_busy:
            return
        sel = self.network_listbox.curselection()
        if not sel or not self._network_adapters:
            return
        idx     = sel[0]
        adapter = self._network_adapters[idx]
        name    = adapter.get("name", "")
        if not name:
            return

        if not messagebox.askyesno(
            "Confirmer réinitialisation",
            f"Réinitialiser l'adaptateur réseau ?\n\n"
            f"  {name}\n\n"
            "L'adaptateur sera désactivé puis réactivé.\n"
            "La connexion sera coupée brièvement.",
            icon="warning",
        ):
            return

        self._network_busy = True
        self.btn_net_refresh.configure(state="disabled")
        self.btn_net_reset.configure(state="disabled", text="⏳  En cours…")
        self.network_log_var.set("Réinitialisation en cours…")

        def _worker():
            try:
                data    = run_ps_action(
                    "collectors/network_cards.ps1",
                    ["-Action", "reset", "-AdapterName", name],
                    timeout=60,
                )
                success = data.get("success", False)
                steps   = data.get("steps", [])
                log_txt = "\n".join(steps)

                def _update():
                    self.network_log_var.set(log_txt)
                    self._network_busy = False
                    self.btn_net_refresh.configure(state="normal")
                    self.btn_net_reset.configure(state="normal", text="⟳  Réinitialiser")
                    if success:
                        messagebox.showinfo("Réseau", f"Adaptateur '{name}' réinitialisé avec succès.")
                    else:
                        messagebox.showerror("Erreur réseau", data.get("error", "Erreur inconnue"))
                    self.after(500, self._network_refresh)
                self.after(0, _update)
            except Exception as exc:
                logger.exception("Erreur network reset")
                _exc = exc
                def _err(e=_exc):
                    self.network_log_var.set(f"Erreur : {e}")
                    self._network_busy = False
                    self.btn_net_refresh.configure(state="normal")
                    self.btn_net_reset.configure(state="normal", text="⟳  Réinitialiser")
                    messagebox.showerror("Erreur", str(e))
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Panneau Réparation système ────────────────────────────────────────────
    def _build_reparation_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1*(e.delta//120), "units"))

        # ── Titre
        hdr = tk.Frame(inner, bg=BG, pady=16)
        hdr.pack(fill="x", padx=28)
        tk.Label(hdr, text="⚙  Réparation système",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(hdr,
                 text="Diagnostique et répare les fichiers système Windows corrompus.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 0))

        # ── Section SFC ───────────────────────────────────────────────────────
        sfc_sec = tk.Frame(inner, bg=BG, pady=12)
        sfc_sec.pack(fill="x", padx=28)

        tk.Label(sfc_sec, text="SFC — Vérificateur de fichiers système",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sfc_sec,
                 text="Analyse et répare les fichiers système protégés. Durée estimée : 5-10 min.\n"
                      "La progression n'est pas visible en direct — un spinner indique l'activité.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 8))

        sfc_ctrl = tk.Frame(sfc_sec, bg=BG)
        sfc_ctrl.pack(fill="x")
        self.btn_sfc = tk.Button(
            sfc_ctrl, text="▶  Lancer SFC /scannow",
            font=("Segoe UI", 10), bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2", padx=14, pady=7,
            command=lambda: self._repair_run("sfc"),
        )
        self.btn_sfc.pack(side="left")
        self._sfc_status_var = tk.StringVar(value="En attente")
        tk.Label(sfc_ctrl, textvariable=self._sfc_status_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left", padx=(14, 0))

        # Conteneur barre progression (hidden until running)
        self._sfc_bar_frame = tk.Frame(sfc_sec, bg=BG)
        self._sfc_bar_frame.pack(fill="x")
        self._sfc_bar = ttk.Progressbar(
            self._sfc_bar_frame, style="PD.Horizontal.TProgressbar", mode="indeterminate")
        self._sfc_bar.pack(fill="x", ipady=3, pady=(4, 0))
        self._sfc_bar_frame.pack_forget()

        sfc_log_wrap = tk.Frame(sfc_sec, bg=SURFACE,
                                highlightbackground=BORDER, highlightthickness=1, bd=0)
        sfc_log_wrap.pack(fill="x", pady=(8, 0))
        self._sfc_log = tk.Text(
            sfc_log_wrap, bg=SURFACE, fg=FG_DIM,
            font=("Consolas", 9), bd=0, padx=8, pady=8,
            state="disabled", wrap="word", height=6,
        )
        sfc_log_sb = ttk.Scrollbar(sfc_log_wrap, command=self._sfc_log.yview, style="PD.Vertical.TScrollbar")
        self._sfc_log.configure(yscrollcommand=sfc_log_sb.set)
        sfc_log_sb.pack(side="right", fill="y")
        self._sfc_log.pack(fill="both", expand=True)

        self.btn_sfc_log = tk.Button(
            sfc_sec, text="📋  Voir CBS.log",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=10, pady=4, state="disabled",
            command=lambda: self._repair_open_log("C:/Windows/Logs/CBS/CBS.log"),
        )
        self.btn_sfc_log.pack(anchor="w", pady=(6, 0))

        tk.Frame(inner, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(12, 0))

        # ── Section DISM ──────────────────────────────────────────────────────
        dism_sec = tk.Frame(inner, bg=BG, pady=12)
        dism_sec.pack(fill="x", padx=28)

        tk.Label(dism_sec, text="DISM — Réparation de l'image Windows",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(dism_sec,
                 text="Répare l'image Windows via Windows Update. Durée estimée : 15-30 min.\n"
                      "Nécessite une connexion Internet active. La progression s'affiche en direct.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 8))

        dism_ctrl = tk.Frame(dism_sec, bg=BG)
        dism_ctrl.pack(fill="x")
        self.btn_dism = tk.Button(
            dism_ctrl, text="▶  Lancer DISM /RestoreHealth",
            font=("Segoe UI", 10), bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2", padx=14, pady=7,
            command=lambda: self._repair_run("dism-restore"),
        )
        self.btn_dism.pack(side="left")
        self._dism_status_var = tk.StringVar(value="En attente")
        tk.Label(dism_ctrl, textvariable=self._dism_status_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left", padx=(14, 0))

        self._dism_bar_frame = tk.Frame(dism_sec, bg=BG)
        self._dism_bar_frame.pack(fill="x")
        self._dism_bar = ttk.Progressbar(
            self._dism_bar_frame, style="PD.Horizontal.TProgressbar", mode="indeterminate")
        self._dism_bar.pack(fill="x", ipady=3, pady=(4, 0))
        self._dism_bar_frame.pack_forget()

        dism_log_wrap = tk.Frame(dism_sec, bg=SURFACE,
                                 highlightbackground=BORDER, highlightthickness=1, bd=0)
        dism_log_wrap.pack(fill="x", pady=(8, 0))
        self._dism_log = tk.Text(
            dism_log_wrap, bg=SURFACE, fg=FG_DIM,
            font=("Consolas", 9), bd=0, padx=8, pady=8,
            state="disabled", wrap="word", height=8,
        )
        dism_log_sb = ttk.Scrollbar(dism_log_wrap, command=self._dism_log.yview, style="PD.Vertical.TScrollbar")
        self._dism_log.configure(yscrollcommand=dism_log_sb.set)
        dism_log_sb.pack(side="right", fill="y")
        self._dism_log.pack(fill="both", expand=True)

        self.btn_dism_log = tk.Button(
            dism_sec, text="📋  Voir DISM.log",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=10, pady=4, state="disabled",
            command=lambda: self._repair_open_log("C:/Windows/Logs/DISM/dism.log"),
        )
        self.btn_dism_log.pack(anchor="w", pady=(6, 0))

        tk.Frame(inner, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(12, 0))

        # ── Section Effacement des journaux ───────────────────────────────────
        clr_sec = tk.Frame(inner, bg=BG, pady=12)
        clr_sec.pack(fill="x", padx=28)

        tk.Label(clr_sec, text="🗑  Vider les journaux Windows",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(clr_sec,
                 text="Efface les journaux d'événements analysés par le diagnostic (System, Application,\n"
                      "Setup…) pour repartir sur une base propre après réparation. Sinon, un crash ou\n"
                      "une erreur d'avant la réparation reste visible jusqu'à 14-30 jours.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, justify="left").pack(anchor="w", pady=(2, 8))

        # Avertissement action destructive
        warn = tk.Frame(clr_sec, bg=SURFACE, highlightbackground=RED,
                        highlightthickness=1, bd=0)
        warn.pack(fill="x", pady=(0, 8))
        tk.Label(warn,
                 text="⚠  Action irréversible : l'historique des événements effacés est définitivement perdu.",
                 font=("Segoe UI", 9), bg=SURFACE, fg=RED, justify="left",
                 padx=10, pady=6, wraplength=560).pack(anchor="w")

        self._clearlogs_security_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            clr_sec,
            text="Inclure aussi le journal de sécurité (échecs de connexion) — Windows y réécrit un événement 1102",
            variable=self._clearlogs_security_var,
            font=("Segoe UI", 9), bg=BG, fg=FG_DIM, activebackground=BG,
            activeforeground=FG, selectcolor=SURFACE, anchor="w",
            highlightthickness=0, bd=0, wraplength=560, justify="left",
        ).pack(anchor="w", pady=(0, 8))

        clr_ctrl = tk.Frame(clr_sec, bg=BG)
        clr_ctrl.pack(fill="x")
        self.btn_clearlogs = tk.Button(
            clr_ctrl, text="🗑  Vider les journaux Windows",
            font=("Segoe UI", 10), bg=RED, fg=BG,
            activebackground=RED_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2", padx=14, pady=7,
            command=self._clearlogs_run,
        )
        self.btn_clearlogs.pack(side="left")
        self._clearlogs_status_var = tk.StringVar(value="En attente")
        tk.Label(clr_ctrl, textvariable=self._clearlogs_status_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left", padx=(14, 0))

        self._clearlogs_bar_frame = tk.Frame(clr_sec, bg=BG)
        self._clearlogs_bar_frame.pack(fill="x")
        self._clearlogs_bar = ttk.Progressbar(
            self._clearlogs_bar_frame, style="PD.Horizontal.TProgressbar", mode="indeterminate")
        self._clearlogs_bar.pack(fill="x", ipady=3, pady=(4, 0))
        self._clearlogs_bar_frame.pack_forget()

        clr_log_wrap = tk.Frame(clr_sec, bg=SURFACE,
                                highlightbackground=BORDER, highlightthickness=1, bd=0)
        clr_log_wrap.pack(fill="x", pady=(8, 0))
        self._clearlogs_log = tk.Text(
            clr_log_wrap, bg=SURFACE, fg=FG_DIM,
            font=("Consolas", 9), bd=0, padx=8, pady=8,
            state="disabled", wrap="word", height=8,
        )
        clr_log_sb = ttk.Scrollbar(clr_log_wrap, command=self._clearlogs_log.yview, style="PD.Vertical.TScrollbar")
        self._clearlogs_log.configure(yscrollcommand=clr_log_sb.set)
        clr_log_sb.pack(side="right", fill="y")
        self._clearlogs_log.pack(fill="both", expand=True)

    def _clearlogs_run(self):
        if self._repair_busy:
            messagebox.showwarning(
                "Opération en cours",
                "Une opération de réparation est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre.",
            )
            return

        include_security = self._clearlogs_security_var.get()
        extra = ("\n\nLe journal de sécurité sera également vidé."
                 if include_security else "")
        if not messagebox.askyesno(
            "Vider les journaux Windows",
            "Cette opération efface définitivement les journaux d'événements "
            "analysés par le diagnostic (System, Application, Setup…).\n\n"
            "L'historique effacé est irrécupérable." + extra + "\n\nContinuer ?",
            icon="warning", default="no",
        ):
            return

        log_w = self._clearlogs_log
        status_var = self._clearlogs_status_var
        bar_frame, bar = self._clearlogs_bar_frame, self._clearlogs_bar

        self._repair_busy = True
        self.btn_sfc.configure(state="disabled")
        self.btn_dism.configure(state="disabled")
        self.btn_clearlogs.configure(state="disabled")
        status_var.set("En cours…")
        bar_frame.pack(fill="x", pady=(4, 0))
        bar.start(12)

        log_w.configure(state="normal")
        log_w.delete("1.0", "end")
        log_w.configure(state="disabled")

        def _on_line(line: str):
            def _upd():
                log_w.configure(state="normal")
                log_w.insert("end", line + "\n")
                log_w.see("end")
                log_w.configure(state="disabled")
            self.after(0, _upd)

        args = ["-IncludeSecurity"] if include_security else []

        def _worker():
            try:
                exit_code = run_ps_stream(
                    "collectors/clear_logs.ps1",
                    args,
                    on_line=_on_line,
                    timeout=120,
                )
                ok = (exit_code == 0)

                def _done():
                    bar.stop()
                    bar_frame.pack_forget()
                    self._repair_busy = False
                    self.btn_sfc.configure(state="normal")
                    self.btn_dism.configure(state="normal")
                    self.btn_clearlogs.configure(state="normal")
                    if ok:
                        status_var.set("✓ Journaux vidés")
                    else:
                        status_var.set("✗ Échec (droits administrateur ?)")
                        log_w.configure(state="normal")
                        log_w.insert(
                            "end",
                            "\n✗ Aucun journal n'a pu être vidé. "
                            "Vérifiez que l'application est lancée en administrateur.\n",
                        )
                        log_w.see("end")
                        log_w.configure(state="disabled")
                self.after(0, _done)

            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    bar.stop()
                    bar_frame.pack_forget()
                    self._repair_busy = False
                    self.btn_sfc.configure(state="normal")
                    self.btn_dism.configure(state="normal")
                    self.btn_clearlogs.configure(state="normal")
                    status_var.set("✗ Erreur")
                    log_w.configure(state="normal")
                    log_w.insert("end", f"\n✗ Erreur : {e}\n")
                    log_w.see("end")
                    log_w.configure(state="disabled")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _repair_run(self, action: str):
        if self._repair_busy:
            messagebox.showwarning(
                "Réparation en cours",
                "Une opération de réparation est déjà en cours.\n"
                "Attendez qu'elle se termine avant d'en lancer une autre.",
            )
            return

        if action == "sfc":
            btn, bar_frame, bar = self.btn_sfc, self._sfc_bar_frame, self._sfc_bar
            status_var, log_w, log_btn = self._sfc_status_var, self._sfc_log, self.btn_sfc_log
            log_path = Path("C:/Windows/Logs/CBS/CBS.log")
            label = "SFC"
        else:
            btn, bar_frame, bar = self.btn_dism, self._dism_bar_frame, self._dism_bar
            status_var, log_w, log_btn = self._dism_status_var, self._dism_log, self.btn_dism_log
            log_path = Path("C:/Windows/Logs/DISM/dism.log")
            label = "DISM"

        self._repair_busy = True
        self.btn_sfc.configure(state="disabled")
        self.btn_dism.configure(state="disabled")
        status_var.set("En cours…")
        bar_frame.pack(fill="x", pady=(4, 0))
        bar.start(12)

        log_w.configure(state="normal")
        log_w.delete("1.0", "end")
        log_w.insert("end", f"Lancement de {label}…\n")
        log_w.configure(state="disabled")

        def _on_line(line: str):
            def _upd():
                log_w.configure(state="normal")
                log_w.insert("end", line + "\n")
                log_w.see("end")
                log_w.configure(state="disabled")
            self.after(0, _upd)

        def _worker():
            try:
                exit_code = run_ps_stream(
                    "collectors/repair.ps1",
                    ["-Action", action],
                    on_line=_on_line,
                    timeout=1800,
                )
                ok = (exit_code == 0)

                # Lire les dernières lignes du log système
                summary = []
                try:
                    if log_path.exists():
                        from collections import deque
                        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                            summary = [l.rstrip() for l in deque(f, 40) if l.strip()]
                except Exception:
                    pass

                def _done():
                    bar.stop()
                    bar_frame.pack_forget()
                    self._repair_busy = False
                    self.btn_sfc.configure(state="normal")
                    self.btn_dism.configure(state="normal")
                    status_var.set("✓ Terminé" if ok else f"✗ Erreur (code {exit_code})")
                    log_w.configure(state="normal")
                    if summary:
                        log_w.insert("end", "\n── Résumé du journal ──\n")
                        log_w.insert("end", "\n".join(summary[-20:]) + "\n")
                    else:
                        msg = "✓ Terminé sans erreur." if ok else f"✗ Terminé avec erreur (code {exit_code})."
                        log_w.insert("end", "\n" + msg + "\n")
                    log_w.see("end")
                    log_w.configure(state="disabled")
                    log_btn.configure(state="normal")
                self.after(0, _done)

            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    bar.stop()
                    bar_frame.pack_forget()
                    self._repair_busy = False
                    self.btn_sfc.configure(state="normal")
                    self.btn_dism.configure(state="normal")
                    status_var.set("✗ Erreur")
                    log_w.configure(state="normal")
                    log_w.insert("end", f"\n✗ Erreur : {e}\n")
                    log_w.see("end")
                    log_w.configure(state="disabled")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _repair_open_log(self, log_path: str):
        p = Path(log_path)
        if not p.exists():
            messagebox.showwarning(
                "Fichier introuvable",
                f"Le journal n'existe pas encore :\n{log_path}\n\n"
                "Lancez d'abord l'opération de réparation.",
            )
            return
        try:
            os.startfile(str(p))
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le fichier :\n{e}")

    # ── Onglet WiFi ───────────────────────────────────────────────────────────
    def _build_wifi_tab(self, parent: tk.Frame):
        # Canvas scrollable (même pattern que _build_troubleshoot_tab)
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG)
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_configure)

        def _on_canvas_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _on_mousewheel(event):
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # ── Section Profils sauvegardés ───────────────────────────────────────
        sec_p = tk.Frame(inner, bg=BG, pady=16)
        sec_p.pack(fill="x", padx=28)

        tk.Label(sec_p, text="Profils WiFi sauvegardés",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec_p,
                 text="Consultez, supprimez et sauvegardez les profils WiFi enregistrés sur ce PC.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 10))

        profiles_row = tk.Frame(sec_p, bg=BG)
        profiles_row.pack(fill="x")

        profiles_wrap = tk.Frame(profiles_row, bg=SURFACE)
        profiles_wrap.pack(side="left", fill="both", expand=True)

        self.wifi_listbox = tk.Listbox(
            profiles_wrap,
            bg=SURFACE, fg=FG, font=("Segoe UI", 10),
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0, activestyle="none", height=6,
        )
        wifi_sb = ttk.Scrollbar(profiles_wrap, command=self.wifi_listbox.yview, style="PD.Vertical.TScrollbar")
        self.wifi_listbox.configure(yscrollcommand=wifi_sb.set)
        wifi_sb.pack(side="right", fill="y")
        self.wifi_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.wifi_listbox.bind("<<ListboxSelect>>", self._wifi_on_select)

        btns_profiles = tk.Frame(profiles_row, bg=BG)
        btns_profiles.pack(side="left", padx=(10, 0), anchor="n")

        self.btn_wifi_refresh = tk.Button(
            btns_profiles, text="↻  Actualiser",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=8, command=self._wifi_refresh,
        )
        self.btn_wifi_refresh.pack(fill="x", pady=(0, 6))

        self.btn_wifi_show_pwd = tk.Button(
            btns_profiles, text="👁  Voir MDP",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=8, state="disabled", command=self._wifi_show_password,
        )
        self.btn_wifi_show_pwd.pack(fill="x", pady=(0, 6))

        self.btn_wifi_delete = tk.Button(
            btns_profiles, text="✗  Supprimer",
            font=("Segoe UI", 10), bg=RED, fg=BG,
            activebackground=RED_HOVER, relief="flat", cursor="hand2",
            padx=14, pady=8, state="disabled", command=self._wifi_delete_profile,
        )
        self.btn_wifi_delete.pack(fill="x")

        # Sauvegarde / Restauration
        backup_row = tk.Frame(sec_p, bg=BG)
        backup_row.pack(fill="x", pady=(12, 0))

        tk.Label(backup_row, text="Sauvegarde / Restauration",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack(side="left", anchor="w")

        self.btn_wifi_restore = tk.Button(
            backup_row, text="📂  Restaurer",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=7, command=self._wifi_restore,
        )
        self.btn_wifi_restore.pack(side="right", padx=(6, 0))

        self.btn_wifi_backup = tk.Button(
            backup_row, text="💾  Sauvegarder",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=7, command=self._wifi_backup,
        )
        self.btn_wifi_backup.pack(side="right")

        # ── Séparateur ────────────────────────────────────────────────────────
        tk.Frame(inner, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(0, 4))

        # ── Section Réseaux disponibles ───────────────────────────────────────
        sec_n = tk.Frame(inner, bg=BG, pady=16)
        sec_n.pack(fill="x", padx=28)

        scan_hdr = tk.Frame(sec_n, bg=BG)
        scan_hdr.pack(fill="x", pady=(0, 2))

        tk.Label(scan_hdr, text="Réseaux disponibles",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(side="left")

        self.btn_wifi_scan = tk.Button(
            scan_hdr, text="🔍  Scanner",
            font=("Segoe UI", 10), bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
            padx=14, pady=6, command=self._wifi_scan,
        )
        self.btn_wifi_scan.pack(side="right")

        tk.Label(sec_n,
                 text="Sélectionnez un réseau puis cliquez Connecter pour le rejoindre.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 8))

        networks_wrap = tk.Frame(sec_n, bg=SURFACE)
        networks_wrap.pack(fill="x")

        self.wifi_networks_listbox = tk.Listbox(
            networks_wrap,
            bg=SURFACE, fg=FG, font=("Consolas", 9),
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0, activestyle="none", height=6,
        )
        net_sb = ttk.Scrollbar(networks_wrap, command=self.wifi_networks_listbox.yview, style="PD.Vertical.TScrollbar")
        self.wifi_networks_listbox.configure(yscrollcommand=net_sb.set)
        net_sb.pack(side="right", fill="y")
        self.wifi_networks_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.wifi_networks_listbox.bind("<<ListboxSelect>>", self._wifi_on_network_select)

        self.btn_wifi_connect = tk.Button(
            sec_n, text="🔗  Connecter au réseau sélectionné",
            font=("Segoe UI", 10, "bold"), bg=GREEN, fg=BG,
            activebackground=GREEN_HOVER, relief="flat", cursor="hand2",
            padx=14, pady=8, state="disabled", command=self._wifi_connect,
        )
        self.btn_wifi_connect.pack(fill="x", pady=(8, 0))

        # Log WiFi
        self.wifi_log_var = tk.StringVar(value="")
        wifi_log_frame = tk.Frame(sec_n, bg=SURFACE, pady=6, padx=10)
        wifi_log_frame.pack(fill="x", pady=(10, 0))
        tk.Label(wifi_log_frame, textvariable=self.wifi_log_var,
                 font=("Consolas", 9), bg=SURFACE, fg=FG_DIM,
                 justify="left", anchor="w", wraplength=620).pack(fill="x")

        self.after(400, self._wifi_refresh)

    def _wifi_refresh(self):
        if self._wifi_busy:
            return
        self._wifi_busy = True
        self.btn_wifi_refresh.configure(state="disabled")
        self.btn_wifi_show_pwd.configure(state="disabled")
        self.btn_wifi_delete.configure(state="disabled")
        self.wifi_listbox.delete(0, "end")
        self.wifi_listbox.insert("end", "  Chargement…")
        self.wifi_log_var.set("")

        def _worker():
            try:
                data     = run_ps_action("collectors/wifi_manager.ps1", ["-Action", "list-profiles"])
                profiles = data.get("profiles", [])

                def _update():
                    self._wifi_profiles = profiles
                    self.wifi_listbox.delete(0, "end")
                    for p in profiles:
                        self.wifi_listbox.insert("end", f"  {p.get('name', '?')}")
                    if not profiles:
                        self.wifi_listbox.insert("end", "  Aucun profil WiFi trouvé")
                    self._wifi_busy = False
                    self.btn_wifi_refresh.configure(state="normal")
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self.wifi_listbox.delete(0, "end")
                    self.wifi_listbox.insert("end", "  Erreur de chargement")
                    self.wifi_log_var.set(f"Erreur : {e}")
                    self._wifi_busy = False
                    self.btn_wifi_refresh.configure(state="normal")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_on_select(self, event=None):
        sel = self.wifi_listbox.curselection()
        if not sel or not self._wifi_profiles or sel[0] >= len(self._wifi_profiles):
            self.btn_wifi_show_pwd.configure(state="disabled")
            self.btn_wifi_delete.configure(state="disabled")
            return
        self.btn_wifi_show_pwd.configure(state="normal")
        self.btn_wifi_delete.configure(state="normal")

    def _wifi_show_password(self):
        if self._wifi_busy:
            return
        sel = self.wifi_listbox.curselection()
        if not sel or not self._wifi_profiles:
            return
        idx = sel[0]
        if idx >= len(self._wifi_profiles):
            return
        name = self._wifi_profiles[idx].get("name", "")
        if not name:
            return

        if not messagebox.askyesno(
            "Afficher le mot de passe",
            f"Révéler le mot de passe du réseau ?\n\n  {name}\n\n"
            "Cette information est sensible. Continuez ?",
            icon="warning",
        ):
            return

        self._wifi_busy = True
        self.btn_wifi_refresh.configure(state="disabled")
        self.btn_wifi_show_pwd.configure(state="disabled", text="⏳  Chargement…")
        self.btn_wifi_delete.configure(state="disabled")
        self.wifi_log_var.set("Récupération du mot de passe…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/wifi_manager.ps1",
                    ["-Action", "show-password", "-ProfileName", name],
                    timeout=15,
                )
                def _update():
                    self._wifi_busy = False
                    self.btn_wifi_refresh.configure(state="normal")
                    self.btn_wifi_show_pwd.configure(state="normal", text="👁  Voir MDP")
                    self.btn_wifi_delete.configure(state="normal")
                    self.wifi_log_var.set("")
                    if data.get("success"):
                        pwd  = data.get("password")
                        auth = data.get("authentication") or "?"
                        if pwd:
                            msg = f"Réseau : {name}\nAuthentification : {auth}\n\nMot de passe :\n{pwd}"
                        else:
                            msg = f"Réseau : {name}\nAuthentification : {auth}\n\nAucun mot de passe (réseau ouvert)."
                        messagebox.showinfo("Mot de passe WiFi", msg)
                    else:
                        messagebox.showerror("Erreur", data.get("error", "Erreur inconnue"))
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self._wifi_busy = False
                    self.btn_wifi_refresh.configure(state="normal")
                    self.btn_wifi_show_pwd.configure(state="normal", text="👁  Voir MDP")
                    self.btn_wifi_delete.configure(state="normal")
                    self.wifi_log_var.set(f"Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_delete_profile(self):
        if self._wifi_busy:
            return
        sel = self.wifi_listbox.curselection()
        if not sel or not self._wifi_profiles:
            return
        idx = sel[0]
        if idx >= len(self._wifi_profiles):
            return
        name = self._wifi_profiles[idx].get("name", "")
        if not name:
            return

        if not messagebox.askyesno(
            "Supprimer le profil WiFi",
            f"Supprimer définitivement le profil ?\n\n  {name}\n\n"
            "Le PC ne pourra plus se connecter automatiquement à ce réseau.",
            icon="warning",
        ):
            return

        self._wifi_busy = True
        self.btn_wifi_refresh.configure(state="disabled")
        self.btn_wifi_show_pwd.configure(state="disabled")
        self.btn_wifi_delete.configure(state="disabled", text="⏳  Suppression…")
        self.wifi_log_var.set("Suppression en cours…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/wifi_manager.ps1",
                    ["-Action", "delete-profile", "-ProfileName", name],
                    timeout=15,
                )
                def _update():
                    self._wifi_busy = False
                    self.btn_wifi_delete.configure(text="✗  Supprimer")
                    if data.get("success"):
                        self.wifi_log_var.set(f"Profil « {name} » supprimé.")
                        messagebox.showinfo("WiFi", f"Profil « {name} » supprimé avec succès.")
                    else:
                        self.wifi_log_var.set(f"Erreur : {data.get('message', '?')}")
                        messagebox.showerror("Erreur", data.get("message", "Erreur inconnue"))
                    self.after(300, self._wifi_refresh)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self._wifi_busy = False
                    self.btn_wifi_refresh.configure(state="normal")
                    self.btn_wifi_show_pwd.configure(state="normal")
                    self.btn_wifi_delete.configure(state="normal", text="✗  Supprimer")
                    self.wifi_log_var.set(f"Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_scan(self):
        if self._wifi_busy:
            return
        self._wifi_busy = True
        self.btn_wifi_scan.configure(state="disabled", text="⏳  Scan en cours…")
        self.wifi_networks_listbox.delete(0, "end")
        self.wifi_networks_listbox.insert("end", "  Déclenchement du scan… (~5s)")
        self.wifi_log_var.set("Scan WiFi en cours — attente des résultats Windows…")

        def _worker():
            try:
                data     = run_ps_action("collectors/wifi_manager.ps1", ["-Action", "scan"], timeout=35)
                networks = data.get("networks", [])
                if not data.get("success", True):
                    raise RuntimeError(data.get("error", "Erreur inconnue"))

                def _update():
                    self._wifi_networks = networks
                    self.wifi_networks_listbox.delete(0, "end")
                    if networks:
                        self.wifi_networks_listbox.insert(
                            "end",
                            f"  {'SSID':<32} {'Signal':>6}  {'Auth'}"
                        )
                        self.wifi_networks_listbox.insert("end", "  " + "─" * 58)
                        for n in networks:
                            ssid   = (n.get("ssid") or "(masqué)")[:31]
                            sig    = n.get("signal", "")
                            sig_s  = f"{sig}%" if sig else "?"
                            auth   = (n.get("authentication") or "")[:20]
                            self.wifi_networks_listbox.insert(
                                "end",
                                f"  {ssid:<32} {sig_s:>6}  {auth}"
                            )
                    else:
                        self.wifi_networks_listbox.insert("end", "  Aucun réseau détecté")
                    n_found = len(networks)
                    self.wifi_log_var.set(f"{n_found} réseau(x) détecté(s).")
                    self._wifi_busy = False
                    self.btn_wifi_scan.configure(state="normal", text="🔍  Scanner")
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    msg = str(e)
                    self.wifi_networks_listbox.delete(0, "end")
                    self.wifi_networks_listbox.insert("end", "  ✗ Scan impossible")
                    for chunk in [msg[i:i+55] for i in range(0, min(len(msg), 165), 55)]:
                        self.wifi_networks_listbox.insert("end", f"    {chunk}")
                    self.wifi_log_var.set(f"Erreur : {msg}")
                    self._wifi_busy = False
                    self.btn_wifi_scan.configure(state="normal", text="🔍  Scanner")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_on_network_select(self, event=None):
        sel = self.wifi_networks_listbox.curselection()
        if not sel:
            self.btn_wifi_connect.configure(state="disabled")
            return
        idx = sel[0] - 2  # 2 lignes d'en-tête
        if 0 <= idx < len(self._wifi_networks):
            ssid = self._wifi_networks[idx].get("ssid", "")
            self.btn_wifi_connect.configure(state="normal" if ssid else "disabled")
        else:
            self.btn_wifi_connect.configure(state="disabled")

    def _ask_wifi_password(self, ssid: str):
        """Dialog de saisie MDP WiFi. Retourne le MDP saisi ou None si annulé."""
        dialog = tk.Toplevel(self)
        dialog.title("Connexion WiFi")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        result = {"pwd": None}

        tk.Label(dialog, text="Connexion au réseau :",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(padx=24, pady=(18, 2), anchor="w")
        tk.Label(dialog, text=f"  {ssid}",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=FG).pack(padx=24, pady=(0, 14), anchor="w")
        tk.Label(dialog, text="Mot de passe :",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM).pack(padx=24, pady=(0, 4), anchor="w")

        entry_var = tk.StringVar()
        entry = tk.Entry(
            dialog, textvariable=entry_var, show="*",
            font=("Consolas", 11), bg=SURFACE, fg=FG,
            insertbackground=FG, relief="flat", width=28,
        )
        entry.pack(padx=24, pady=(0, 16), ipady=7, ipadx=8, fill="x")
        entry.focus_set()

        def _ok():
            result["pwd"] = entry_var.get()
            dialog.destroy()

        def _cancel():
            dialog.destroy()

        entry.bind("<Return>", lambda e: _ok())
        entry.bind("<Escape>", lambda e: _cancel())

        btn_row = tk.Frame(dialog, bg=BG)
        btn_row.pack(padx=24, pady=(0, 18), fill="x")

        tk.Button(
            btn_row, text="Annuler",
            font=("Segoe UI", 10), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=16, pady=7, command=_cancel,
        ).pack(side="right", padx=(6, 0))
        tk.Button(
            btn_row, text="Connecter",
            font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
            padx=16, pady=7, command=_ok,
        ).pack(side="right")

        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width()  - dialog.winfo_width())  // 2
        y = self.winfo_y() + (self.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        self.wait_window(dialog)
        return result["pwd"]

    def _wifi_connect(self):
        if self._wifi_busy:
            return
        sel = self.wifi_networks_listbox.curselection()
        if not sel or not self._wifi_networks:
            return
        idx = sel[0] - 2  # 2 lignes d'en-tête
        if idx < 0 or idx >= len(self._wifi_networks):
            return

        network = self._wifi_networks[idx]
        ssid    = network.get("ssid", "")
        auth    = network.get("authentication", "")

        if not ssid:
            messagebox.showinfo("WiFi", "Réseau masqué — impossible de se connecter automatiquement.")
            return

        is_open     = "open" in auth.lower() or "ouvert" in auth.lower() or not auth
        has_profile = any(p.get("name") == ssid for p in self._wifi_profiles)

        password = None
        if has_profile:
            # Réseau déjà configuré : confirmation avant connexion
            if not messagebox.askyesno(
                "Réseau déjà enregistré",
                f"Ce réseau est déjà configuré sur ce PC :\n\n  {ssid}\n\n"
                "Se connecter avec le profil existant ?",
            ):
                return
        elif is_open:
            if not messagebox.askyesno(
                "Réseau ouvert",
                f"Connexion à un réseau non sécurisé :\n\n  {ssid}\n\n"
                "Continuer sans mot de passe ?",
                icon="warning",
            ):
                return
        else:
            password = self._ask_wifi_password(ssid)
            if password is None:
                return
            if len(password) < 8:
                messagebox.showerror("Mot de passe invalide",
                                     "Le mot de passe WiFi doit comporter au moins 8 caractères.")
                return

        self._wifi_busy = True
        self.btn_wifi_connect.configure(state="disabled", text="⏳  Connexion…")
        self.btn_wifi_scan.configure(state="disabled")
        self.wifi_log_var.set(f"Connexion à « {ssid} »…")

        args = ["-Action", "connect", "-ProfileName", ssid]
        if password is not None:
            args += ["-Password", password]
        if is_open:
            args += ["-Auth", "open"]

        def _set_verif_msg():
            if self._wifi_busy:
                self.wifi_log_var.set(f"Vérification de la connexion à « {ssid} »…")
        self.after(3000, _set_verif_msg)

        def _worker():
            try:
                data = run_ps_action("collectors/wifi_manager.ps1", args, timeout=45)
                def _update():
                    self._wifi_busy = False
                    self.btn_wifi_connect.configure(
                        state="normal", text="🔗  Connecter au réseau sélectionné")
                    self.btn_wifi_scan.configure(state="normal")
                    if data.get("success"):
                        self.wifi_log_var.set(f"✓ Connecté à « {ssid} ».")
                        messagebox.showinfo(
                            "Connexion WiFi",
                            f"✓ Connecté avec succès à :\n\n  {ssid}",
                        )
                        if data.get("created_profile"):
                            self.after(500, self._wifi_refresh)
                    else:
                        err = data.get("error") or "Erreur de connexion inconnue"
                        self.wifi_log_var.set(f"✗ {err}")
                        messagebox.showerror("Connexion échouée", err)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self._wifi_busy = False
                    self.btn_wifi_connect.configure(
                        state="normal", text="🔗  Connecter au réseau sélectionné")
                    self.btn_wifi_scan.configure(state="normal")
                    self.wifi_log_var.set(f"Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_backup(self):
        if self._wifi_busy:
            return

        if not messagebox.askyesno(
            "Sauvegarder les profils WiFi",
            "Exporter tous les profils WiFi dans un fichier ZIP ?\n\n"
            "⚠  Le fichier contiendra les mots de passe en clair.\n"
            "Conservez-le dans un endroit sûr.",
            icon="warning",
        ):
            return

        zip_path = filedialog.asksaveasfilename(
            title="Enregistrer la sauvegarde WiFi",
            defaultextension=".zip",
            filetypes=[("Archive ZIP", "*.zip")],
            initialfile="wifi_backup.zip",
        )
        if not zip_path:
            return

        safe, reason = is_safe_output_dir(Path(zip_path).parent)
        if not safe:
            messagebox.showerror("Dossier non autorisé", reason)
            return

        self._wifi_busy = True
        self.btn_wifi_backup.configure(state="disabled", text="⏳  Export…")
        self.btn_wifi_restore.configure(state="disabled")
        self.btn_wifi_refresh.configure(state="disabled")
        self.wifi_log_var.set("Sauvegarde en cours…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/wifi_manager.ps1",
                    ["-Action", "backup-all", "-FilePath", zip_path],
                    timeout=120,
                )
                def _update():
                    self._wifi_busy = False
                    self.btn_wifi_backup.configure(state="normal", text="💾  Sauvegarder")
                    self.btn_wifi_restore.configure(state="normal")
                    self.btn_wifi_refresh.configure(state="normal")
                    if data.get("success"):
                        n = data.get("profiles_count", 0)
                        errs = data.get("errors", [])
                        self.wifi_log_var.set(f"{n} profil(s) sauvegardé(s) → {Path(zip_path).name}")
                        msg = f"{n} profil(s) exporté(s) avec succès.\n\n{zip_path}"
                        if errs:
                            msg += "\n\nAvertissements :\n" + "\n".join(errs[:5])
                            messagebox.showwarning("Sauvegarde partielle", msg)
                        else:
                            messagebox.showinfo("Sauvegarde WiFi", msg)
                    else:
                        err = data.get("error", "Erreur inconnue")
                        self.wifi_log_var.set(f"Erreur : {err}")
                        messagebox.showerror("Erreur sauvegarde", err)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self._wifi_busy = False
                    self.btn_wifi_backup.configure(state="normal", text="💾  Sauvegarder")
                    self.btn_wifi_restore.configure(state="normal")
                    self.btn_wifi_refresh.configure(state="normal")
                    self.wifi_log_var.set(f"Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _wifi_restore(self):
        if self._wifi_busy:
            return

        zip_path = filedialog.askopenfilename(
            title="Choisir une sauvegarde WiFi",
            filetypes=[("Archive ZIP", "*.zip")],
        )
        if not zip_path:
            return

        if not messagebox.askyesno(
            "Restaurer les profils WiFi",
            f"Importer les profils depuis :\n\n  {Path(zip_path).name}\n\n"
            "Les profils existants avec le même nom seront écrasés.",
            icon="warning",
        ):
            return

        self._wifi_busy = True
        self.btn_wifi_backup.configure(state="disabled")
        self.btn_wifi_restore.configure(state="disabled", text="⏳  Import…")
        self.btn_wifi_refresh.configure(state="disabled")
        self.wifi_log_var.set("Restauration en cours…")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/wifi_manager.ps1",
                    ["-Action", "restore-all", "-FilePath", zip_path],
                    timeout=120,
                )
                def _update():
                    self._wifi_busy = False
                    self.btn_wifi_backup.configure(state="normal")
                    self.btn_wifi_restore.configure(state="normal", text="📂  Restaurer")
                    self.btn_wifi_refresh.configure(state="normal")
                    if data.get("success"):
                        n    = data.get("imported_count", 0)
                        errs = data.get("errors", [])
                        self.wifi_log_var.set(f"{n} profil(s) restauré(s).")
                        msg = f"{n} profil(s) importé(s) avec succès."
                        if errs:
                            msg += "\n\nAvertissements :\n" + "\n".join(errs[:5])
                            messagebox.showwarning("Restauration partielle", msg)
                        else:
                            messagebox.showinfo("Restauration WiFi", msg)
                        self.after(300, self._wifi_refresh)
                    else:
                        err = data.get("error", "Erreur inconnue")
                        self.wifi_log_var.set(f"Erreur : {err}")
                        messagebox.showerror("Erreur restauration", err)
                self.after(0, _update)
            except Exception as exc:
                _exc = exc
                def _err(e=_exc):
                    self._wifi_busy = False
                    self.btn_wifi_backup.configure(state="normal")
                    self.btn_wifi_restore.configure(state="normal", text="📂  Restaurer")
                    self.btn_wifi_refresh.configure(state="normal")
                    self.wifi_log_var.set(f"Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    # ── Helpers log Analyse ───────────────────────────────────────────────────
    def _log(self, msg: str, tag: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        # Tronquer les lignes les plus anciennes par batch pour éviter la croissance illimitée
        line_count = int(self.log.index("end-1c").split(".")[0])
        if line_count > _LOG_MAX_LINES:
            self.log.delete("1.0", f"{_LOG_MAX_LINES // 10 + 1}.0")
        self.log.insert("end", f"[{ts}] ", "time")
        self.log.insert("end", msg + "\n", tag or "")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_log_file(self):
        log_path = LOG_DIR / "ghisdiag.log"
        if log_path.exists():
            try:
                os.startfile(str(log_path))
            except OSError:
                messagebox.showinfo("Fichier log", str(log_path))
        else:
            messagebox.showinfo("Fichier log", f"Aucun log trouvé dans :\n{LOG_DIR}")

    # ── Actions Analyse ───────────────────────────────────────────────────────
    def _browse(self):
        cur = self.out_dir_var.get()
        ini = cur if Path(cur).exists() else str(Path.home())
        chosen = filedialog.askdirectory(
            title="Choisir le dossier de destination",
            initialdir=ini,
        )
        if chosen:
            self.out_dir_var.set(chosen)
            save_prefs({"output_dir": chosen})
            self._log(f"Dossier : {chosen}", "info")

    def _start(self):
        if self._running:
            return

        raw = self.out_dir_var.get().strip()
        if not raw:
            messagebox.showerror("Erreur", "Veuillez choisir un dossier de destination.")
            return

        out_dir = Path(raw)
        safe, reason = is_safe_output_dir(out_dir)
        if not safe:
            messagebox.showerror("Dossier non autorisé", reason)
            return

        self._stop_tick()
        self._monitor_pause()
        self._running = True
        self._out_dir = out_dir
        self._start_time = datetime.now()

        self.btn_start.configure(state="disabled", text="⏳   Diagnostic en cours…",
                                 bg=SURFACE2, fg=FG)
        self.btn_open.configure(state="disabled")
        self.btn_folder.configure(state="disabled")
        self.pbar["value"] = 0
        self.counter_var.set("")
        self.elapsed_var.set("")
        self.result_lbl.configure(text="")
        self.step_var.set("Démarrage…")

        self._log("Diagnostic lancé", "info")
        self._log(f"Destination : {out_dir}", "dim")
        self._tick_elapsed()

        threading.Thread(target=self._run, daemon=True).start()

    def _tick_elapsed(self):
        if not self._running:
            self._tick_id = None
            return
        elapsed = int((datetime.now() - self._start_time).total_seconds())
        m, s = divmod(elapsed, 60)
        self.elapsed_var.set(f"Durée : {m:02d}:{s:02d}")
        self._tick_id = self.after(1000, self._tick_elapsed)

    def _stop_tick(self):
        if self._tick_id is not None:
            self.after_cancel(self._tick_id)
            self._tick_id = None

    def _on_progress(self, step: str, current: int, total: int, status: str = "running",
                     elapsed: float = 0, ps_errors: list = None):
        def _update():
            self.step_var.set(step)
            self.pbar["value"] = current
            if status == "done":
                self.counter_var.set(f"{total} modules collectés")
                self._log(step, "info")
            elif status == "error":
                self.counter_var.set(f"Module {current} / {total}")
                suffix = f"  ({elapsed:.1f}s)" if elapsed else ""
                self._log(f"✗ {step}{suffix}", "err")
                for e in (ps_errors or []):
                    self._log(f"  └─ {e}", "warn")
            elif status == "warn":
                self.counter_var.set(f"Module {current} / {total}")
                suffix = f"  ({elapsed:.1f}s)" if elapsed else ""
                self._log(f"⚠ {step}{suffix}", "warn")
                for e in (ps_errors or []):
                    self._log(f"  └─ {e}", "warn")
            else:
                self.counter_var.set(f"Module {current} / {total}")
                self._log(step)
        self.after(0, _update)

    def _run(self):
        try:
            orch = DiagnosticOrchestrator(progress_callback=self._on_progress)
            data = orch.run()

            self.after(0, lambda: self._log("Génération du rapport…", "info"))
            gen = ReportGenerator(data, output_dir=self._out_dir)
            html_path, json_path = gen.save()

            self.report_path = html_path
            self.json_path   = json_path
            elapsed          = data["meta"]["elapsed_sec"]
            failed           = data["meta"].get("collectors_fail", [])

            # Vérifier si une clé API est fournie pour le fournisseur IA actif.
            provider_id = self.ai_provider_var.get()
            ai_key = self._active_ai_key().strip()
            if ai_key and _HAS_AI:
                # Lancer l'analyse IA en thread séparé.
                # Copie superficielle suffisante : le worker ne fait que LIRE les dicts
                # imbriqués, et le thread principal ne les mute pas après ce point
                # (le `del data` plus bas ne retire que la liaison locale).
                diagnostic_data_copy = data.copy()
                machine_name = data["meta"].get("machine", "UNKNOWN")
                thread = threading.Thread(
                    target=self._run_ai_analysis,
                    args=(diagnostic_data_copy, provider_id, ai_key, machine_name),
                    daemon=True,
                )
                thread.start()

            del data, gen, orch
            gc.collect()

            def _done():
                self._stop_tick()
                self._running = False
                self.pbar["value"] = TOTAL_MODULES
                self.step_var.set("Diagnostic terminé")
                self.counter_var.set(f"{TOTAL_MODULES} modules collectés")
                self.elapsed_var.set(f"Durée totale : {elapsed}s")

                self.btn_start.configure(
                    state="normal", text="▶   Relancer le diagnostic",
                    bg=ACCENT, fg=BG,
                )
                self.btn_open.configure(state="normal")
                self.btn_folder.configure(state="normal")
                self.result_lbl.configure(text="✔  Rapport prêt", fg=GREEN)

                self._log(f"Rapport HTML : {html_path}", "ok")
                self._log(f"Rapport JSON : {json_path}", "dim")
                if failed:
                    self._log(f"Modules en erreur : {', '.join(failed)}", "warn")
                else:
                    self._log("Tous les modules ont réussi", "ok")

                if self.auto_open_var.get():
                    self.after(300, self._open_html)

                self.after(500, self._monitor_resume)

            self.after(0, _done)

        except Exception as exc:
            logger.exception("Erreur fatale")
            def _err():
                self._stop_tick()
                self._running = False
                self.step_var.set(f"Erreur : {exc}")
                self.btn_start.configure(
                    state="normal", text="▶   Réessayer",
                    bg=ACCENT, fg=BG,
                )
                self._log(f"ERREUR : {exc}", "err")
            self.after(0, _err)

    def _on_auto_open_changed(self, *_):
        prefs = load_prefs()
        prefs["auto_open_browser"] = self.auto_open_var.get()
        save_prefs(prefs)

    # ── Analyse IA : configuration & persistance ──────────────────────────────
    def _active_ai_key(self) -> str:
        """Clé API du fournisseur IA actuellement sélectionné (vide si aucun)."""
        var = self.ai_key_vars.get(self.ai_provider_var.get())
        return var.get() if var else ""

    def _save_ai_prefs(self):
        """Persiste le fournisseur actif et toutes les clés API (chiffrées par prefs)."""
        if not _HAS_AI:
            return
        prefs = load_prefs()
        prefs["ai_provider"] = self.ai_provider_var.get()
        for pid, var in self.ai_key_vars.items():
            prefs[ai_analyzer.PROVIDERS[pid]["key_pref"]] = var.get()
        save_prefs(prefs)

    def _refresh_ai_status(self):
        """Met à jour le libellé d'état du panneau principal (fournisseur + clé)."""
        lbl = getattr(self, "ai_status_lbl", None)
        if lbl is None:
            return
        if not _HAS_AI:
            lbl.configure(text="indisponible (requests/cryptography manquants)", fg=FG_MUTED)
            return
        pid = self.ai_provider_var.get()
        name = ai_analyzer.provider_label(pid)
        if self._active_ai_key().strip():
            lbl.configure(text=f"{name} — un audit IA sera généré après le diagnostic", fg=GREEN)
        else:
            lbl.configure(text=f"{name} — clé non renseignée (cliquez sur Configurer)", fg=FG_MUTED)

    def _on_ai_provider_changed(self, *_):
        self._save_ai_prefs()
        self._refresh_ai_status()
        # Si la fenêtre de config est ouverte, recâbler le champ clé sur le nouveau fournisseur.
        if getattr(self, "_ai_cfg_win", None) and self._ai_cfg_win.winfo_exists():
            self._ai_cfg_bind_provider()

    def _on_ai_key_changed(self, *_):
        self._save_ai_prefs()
        self._refresh_ai_status()

    def _open_ai_config(self):
        """Ouvre la fenêtre de configuration de l'analyse IA (fournisseur + clé + test)."""
        if not _HAS_AI:
            messagebox.showerror(
                "Dépendance manquante",
                "L'analyse IA nécessite les librairies 'requests' et 'cryptography'.\n\n"
                "Exécutez dans un terminal :\n"
                "  py -m pip install requests cryptography",
            )
            return

        # Si déjà ouverte, la ramener au premier plan.
        existing = getattr(self, "_ai_cfg_win", None)
        if existing and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        win = tk.Toplevel(self)
        win.title("Configuration de l'analyse IA")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        self._ai_cfg_win = win

        self.update_idletasks()
        w, h = 520, 360
        px = self.winfo_x() + (self.winfo_width()  - w) // 2
        py = self.winfo_y() + (self.winfo_height() - h) // 2
        win.geometry(f"{w}x{h}+{max(px, 0)}+{max(py, 0)}")

        def _on_close():
            self._ai_cfg_win = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _on_close)

        tk.Label(
            win, text="🤖  Analyse IA après diagnostic",
            font=("Segoe UI", 13, "bold"), bg=BG, fg=ACCENT,
        ).pack(anchor="w", padx=20, pady=(18, 4))

        tk.Label(
            win,
            text="Les données du diagnostic sont transmises au fournisseur choisi pour\n"
                 "produire un audit technique. Confidentialité : ces données quittent\n"
                 "votre machine vers l'API du fournisseur.",
            font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 14))

        # Fournisseur
        row = tk.Frame(win, bg=BG)
        row.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(row, text="Fournisseur :", font=("Segoe UI", 10),
                 bg=BG, fg=FG_DIM, width=12, anchor="w").pack(side="left")

        # Map label ↔ id pour le Combobox.
        self._ai_cfg_label_to_id = {
            ai_analyzer.PROVIDERS[pid]["label"]: pid for pid in ai_analyzer.UI_PROVIDERS
        }
        labels = [ai_analyzer.PROVIDERS[pid]["label"] for pid in ai_analyzer.UI_PROVIDERS]
        self._ai_cfg_combo = ttk.Combobox(
            row, values=labels, state="readonly", font=("Segoe UI", 10),
        )
        self._ai_cfg_combo.set(ai_analyzer.provider_label(self.ai_provider_var.get()))
        self._ai_cfg_combo.pack(side="left", fill="x", expand=True)
        self._ai_cfg_combo.bind("<<ComboboxSelected>>", self._ai_cfg_on_combo)

        # Modèle (figé, informatif)
        self._ai_cfg_model_lbl = tk.Label(
            win, text="", font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, anchor="w",
        )
        self._ai_cfg_model_lbl.pack(fill="x", padx=20, pady=(0, 12))

        # Clé API
        row2 = tk.Frame(win, bg=BG)
        row2.pack(fill="x", padx=20, pady=(0, 6))
        tk.Label(row2, text="Clé API :", font=("Segoe UI", 10),
                 bg=BG, fg=FG_DIM, width=12, anchor="w").pack(side="left")
        self._ai_cfg_key_entry = tk.Entry(
            row2, show="•", font=("Consolas", 10), bg=SURFACE2, fg=FG,
            insertbackground=FG, relief="flat",
        )
        self._ai_cfg_key_entry.pack(side="left", fill="x", expand=True, ipady=3)

        # Boutons test + fermeture
        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=20, pady=(16, 0))
        self._ai_cfg_test_btn = tk.Button(
            btns, text="Tester la clé",
            font=("Segoe UI", 9), bg=ACCENT, fg=BG,
            activebackground=PURPLE, relief="flat", cursor="hand2",
            padx=14, pady=5, command=self._ai_cfg_test_key,
        )
        self._ai_cfg_test_btn.pack(side="left")
        tk.Button(
            btns, text="Fermer",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=14, pady=5, command=_on_close,
        ).pack(side="right")

        # Résultat du test
        self._ai_cfg_result_lbl = tk.Label(
            win, text="", font=("Segoe UI", 9), bg=BG, fg=FG_MUTED,
            anchor="w", justify="left", wraplength=480,
        )
        self._ai_cfg_result_lbl.pack(fill="x", padx=20, pady=(12, 0))

        self._ai_cfg_bind_provider()

    def _ai_cfg_on_combo(self, _event=None):
        """Sélection d'un fournisseur dans le Combobox → met à jour la variable active."""
        pid = self._ai_cfg_label_to_id.get(self._ai_cfg_combo.get())
        if pid and pid != self.ai_provider_var.get():
            self.ai_provider_var.set(pid)   # déclenche _on_ai_provider_changed → _ai_cfg_bind_provider

    def _ai_cfg_bind_provider(self):
        """Recâble le champ clé + le libellé modèle sur le fournisseur actif."""
        pid = self.ai_provider_var.get()
        # Combobox synchronisé (utile si changement provoqué hors combobox).
        self._ai_cfg_combo.set(ai_analyzer.provider_label(pid))
        self._ai_cfg_model_lbl.configure(text=f"Modèle : {ai_analyzer.model_label(pid)}")
        var = self.ai_key_vars.get(pid)
        if var is not None:
            self._ai_cfg_key_entry.configure(textvariable=var)
        self._ai_cfg_result_lbl.configure(text="", fg=FG_MUTED)

    def _ai_cfg_test_key(self):
        """Teste la clé du fournisseur actif (appel réseau déporté hors du thread UI)."""
        pid = self.ai_provider_var.get()
        api_key = self._active_ai_key().strip()
        if not api_key:
            self._ai_cfg_result_lbl.configure(
                text="Veuillez saisir une clé API.", fg=YELLOW)
            return
        self._ai_cfg_test_btn.configure(state="disabled", text="Test en cours…")
        self._ai_cfg_result_lbl.configure(text="Test en cours…", fg=FG_MUTED)
        threading.Thread(
            target=self._ai_cfg_test_worker, args=(pid, api_key), daemon=True
        ).start()

    def _ai_cfg_test_worker(self, provider_id: str, api_key: str):
        """Effectue l'appel de test dans un thread ; restitue le résultat via self.after."""
        kind, message = test_api_key(provider_id, api_key)

        def _show():
            win = getattr(self, "_ai_cfg_win", None)
            if not (win and win.winfo_exists()):
                return
            self._ai_cfg_test_btn.configure(state="normal", text="Tester la clé")
            color = GREEN if kind == "ok" else (RED if kind == "invalid" else YELLOW)
            self._ai_cfg_result_lbl.configure(text=message, fg=color)
        self.after(0, _show)

    # ── Popup d'attente de l'analyse IA ────────────────────────────────────────
    def _open_ai_waiting_popup(self, provider_label: str):
        """Ouvre une fenêtre non bloquante indiquant que l'analyse IA est en cours."""
        popup = tk.Toplevel(self)
        popup.title("Analyse IA")
        popup.configure(bg=SURFACE)
        popup.resizable(False, False)
        popup.grab_set()   # garde le focus mais ne bloque pas le thread principal

        # Centrer sur la fenêtre principale
        self.update_idletasks()
        px = self.winfo_x() + (self.winfo_width()  - 460) // 2
        py = self.winfo_y() + (self.winfo_height() - 180) // 2
        popup.geometry(f"460x180+{px}+{py}")

        # Empêcher la fermeture manuelle pendant l'analyse
        popup.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(
            popup, text="🤖  Analyse IA en cours…",
            font=("Segoe UI", 13, "bold"), bg=SURFACE, fg=ACCENT,
        ).pack(pady=(24, 8))

        tk.Label(
            popup,
            text=f"Les données sont transmises à {provider_label} pour un audit complet.\n"
                 "La génération du rapport peut prendre plusieurs minutes.\n"
                 "Merci de patienter, la fenêtre se fermera automatiquement.",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
            justify="center",
        ).pack(pady=(0, 20))

        self._ai_popup = popup

    def _close_ai_waiting_popup(self):
        """Ferme la popup d'attente si elle est ouverte."""
        popup = getattr(self, "_ai_popup", None)
        if popup and popup.winfo_exists():
            popup.grab_release()
            popup.destroy()
        self._ai_popup = None

    def _run_ai_analysis(self, diagnostic_data: dict, provider_id: str,
                         api_key: str, machine_name: str):
        """Lance l'analyse IA en thread séparé (ne bloque pas l'UI)."""
        name = ai_analyzer.provider_label(provider_id)
        # Ouvrir la popup d'attente depuis le thread UI
        self.after(0, lambda: self._open_ai_waiting_popup(name))
        try:
            self.after(0, lambda: self._log(f"🤖  Analyse IA ({name}) en cours…", "info"))

            progress_msg = lambda m: self.after(0, lambda msg=m: self._log(f"   {msg}", "dim"))
            analysis_text = analyze_diagnostic(
                diagnostic_data, provider_id, api_key, progress_callback=progress_msg
            )

            if not analysis_text:
                self.after(0, self._close_ai_waiting_popup)
                self.after(0, lambda: self._log("⚠ Analyse IA vide", "warn"))
                return

            # Générer le rapport HTML
            html_path = generate_ai_report(
                analysis_text,
                machine_name,
                self._out_dir,
                provider_label=name,
                model_label=ai_analyzer.model_label(provider_id),
                app_version=VERSION,
            )

            self.ai_report_path = html_path

            self.after(0, self._close_ai_waiting_popup)
            self.after(0, lambda: self._log(f"✅  Rapport IA : {html_path}", "ok"))

            if self.auto_open_var.get():
                self.after(600, lambda: self._open_ai_html(html_path))

        except ValueError as e:
            # Clé API invalide / fournisseur inconnu
            self.after(0, self._close_ai_waiting_popup)
            self.after(0, lambda: self._log(f"❌  IA : {str(e)}", "err"))
            self.after(0, lambda: messagebox.showerror("Erreur analyse IA", str(e)))

        except RuntimeError as e:
            # Erreur réseau ou timeout
            self.after(0, self._close_ai_waiting_popup)
            self.after(0, lambda: self._log(f"⚠ IA : {str(e)}", "warn"))
            self.after(0, lambda: messagebox.showwarning(
                "Avertissement", f"Analyse IA non disponible :\n{str(e)}"))

        except Exception as e:
            logger.exception("Erreur lors de l'analyse IA")
            self.after(0, self._close_ai_waiting_popup)
            self.after(0, lambda: self._log(f"❌  Erreur IA : {str(e)}", "err"))

    def _open_ai_html(self, path: Path):
        """Ouvre le rapport IA dans le navigateur."""
        try:
            os.startfile(str(path.resolve()))
        except OSError as e:
            logger.warning(f"Impossible d'ouvrir {path}: {e}")

    def _open_html(self):
        if not (self.report_path and self.report_path.exists()):
            messagebox.showerror("Erreur", "Fichier rapport introuvable.")
            return
        try:
            os.startfile(str(self.report_path.resolve()))
        except OSError as e:
            logger.warning("Impossible d'ouvrir le rapport : %s", e)
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le rapport : {e}")

    def _open_folder(self):
        if not self.report_path or not self.report_path.exists():
            messagebox.showerror("Erreur", "Rapport introuvable.")
            return
        try:
            subprocess.Popen(
                ["explorer.exe", f"/select,{self.report_path.resolve()}"],
                shell=False,
            )
        except OSError as e:
            logger.warning("Impossible d'ouvrir l'explorateur : %s", e)
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le dossier : {e}")

    # ── Moniteur Temps Réel ───────────────────────────────────────────────────
    def _temp_stream_ensure(self):
        """(Re)démarre le flux capteurs persistant pour la température CPU.

        LibreHardwareMonitor est ouvert une seule fois et pousse un échantillon
        par tick : la température CPU se rafraîchit en continu, sans relancer un
        process à chaque cycle. Recrée le flux s'il s'est figé (le watchdog du
        SensorStream l'aura tué)."""
        if not _HAS_STREAM or _lhm_available is None or not _lhm_available():
            return
        st = self._temp_stream
        if st is not None and st.running and not st.stalled:
            return
        if st is not None:
            try:
                st.stop()
            except Exception:
                pass
            self._temp_stream = None
        try:
            st = _SensorStream(interval_ms=2000)
            if st.start():
                self._temp_stream = st
        except Exception as exc:
            logger.debug("Flux capteurs moniteur : %s", exc)
            self._temp_stream = None

    def _temp_stream_stop(self):
        """Arrête le flux capteurs (libère LHM pour le diagnostic / à la fermeture)."""
        if self._temp_stream is not None:
            try:
                self._temp_stream.stop()
            except Exception:
                pass
            self._temp_stream = None

    def _monitor_start(self):
        self._monitor_paused = False
        self._monitor_tick()

    def _monitor_pause(self):
        self._monitor_paused = True
        if self._monitor_tick_id is not None:
            self.after_cancel(self._monitor_tick_id)
            self._monitor_tick_id = None
        # Libère LHM pendant le diagnostic (qui le sonde aussi) ; il repartira au resume.
        self._temp_stream_stop()
        self._mon_status_var.set("(en pause pendant le diagnostic)")

    def _monitor_resume(self):
        self._monitor_paused = False
        self._mon_status_var.set("")
        self._monitor_tick()

    def _monitor_tick(self):
        if self._monitor_paused:
            return
        if _HAS_MONITOR:
            cpu  = get_cpu_percent()
            ram  = get_ram_percent()
            disk = get_disk_io_percent()
        else:
            cpu = ram = disk = None

        for key, val in (("cpu", cpu), ("ram", ram), ("disk", disk)):
            if val is not None:
                self._mon_vals[key].set(f"{val:.0f}%")
                self._mon_bars[key]["value"] = val
            else:
                self._mon_vals[key].set("N/A")
                self._mon_bars[key]["value"] = 0

        # Températures. CPU = flux LHM persistant (continu, ~2s) ; GPU/disques =
        # NVML/smartctl rafraîchis en arrière-plan toutes les 10s (peu coûteux).
        self._temp_stream_ensure()

        self._temp_tick += 1
        if self._temp_tick >= 5 and not self._temp_loading:
            self._temp_tick = 0
            self._temp_loading = True
            threading.Thread(target=self._monitor_fetch_temps, daemon=True).start()

        sample = self._temp_stream.latest() if self._temp_stream is not None else None
        cpu_t  = sample.get("cpu_ref") if sample else None
        if cpu_t is None:
            cpu_t = self._temp_cache.get("cpu")      # repli ACPI (fetch périodique)
        gpu_t  = self._temp_cache.get("gpu")
        if gpu_t is None and sample is not None:
            gpu_t = sample.get("gpu_temp")           # repli GPU via LHM (AMD/Intel)
        disks_t = self._temp_cache.get("disks") or []

        if cpu_t is not None:
            self._mon_temp_cpu_var.set(f"CPU : {cpu_t}°C")
        elif self._sensor_reason:
            # Pas de temp CPU : on dit pourquoi (PawnIO absent, non élevé…).
            self._mon_temp_cpu_var.set(f"CPU : N/A — {self._sensor_reason}")
        else:
            self._mon_temp_cpu_var.set("CPU : N/A")
        self._mon_temp_gpu_var.set(f"GPU : {gpu_t}°C" if gpu_t is not None else "GPU : N/A")
        if disks_t:
            parts = [f"{d.get('model','?')[:12]} : {d.get('temp','?')}°C"
                     for d in disks_t[:2] if isinstance(d, dict)]
            self._mon_temp_disk_var.set("  ".join(parts) if parts else "SSD/HDD : N/A")
        else:
            self._mon_temp_disk_var.set("SSD/HDD : N/A")

        self._monitor_tick_id = self.after(2000, self._monitor_tick)

    def _monitor_fetch_temps(self):
        """Rafraîchit GPU + disques (NVML/smartctl, rapide) en arrière-plan. Le
        CPU vient du flux LHM persistant ; on ne calcule un repli ACPI que si ce
        flux ne fournit pas de température CPU (machine sans PawnIO)."""
        try:
            if not _HAS_MONITOR:
                return
            gd = get_gpu_disk_temps()
            cache = {"cpu": None, "gpu": gd.get("gpu"), "disks": gd.get("disks") or []}

            sample = self._temp_stream.latest() if self._temp_stream is not None else None
            stream_cpu = sample.get("cpu_ref") if sample else None
            if stream_cpu is None:
                # Le flux LHM ne donne pas de temp CPU : repli zone thermique ACPI.
                cache["cpu"] = get_cpu_temp_acpi()
            self._temp_cache = cache

            # Raison à afficher si aucune temp CPU (ni flux, ni ACPI).
            has_cpu = stream_cpu is not None or cache["cpu"] is not None
            if _HAS_SENSOR_HEALTH and not has_cpu:
                try:
                    self._sensor_reason = _sensors_health.cpu_status(probe=False)["label"]
                except Exception:
                    self._sensor_reason = None
            else:
                self._sensor_reason = None
        except Exception as exc:
            logger.debug("Fetch températures : %s", exc)
        finally:
            self._temp_loading = False

    # ══ Onglet Bench thermique ═══════════════════════════════════════════════

    # Correspondances widget -> valeurs moteur
    _BENCH_LABELS   = (("Avant", "avant"), ("Après", "apres"), ("Libre", "libre"))
    _BENCH_INTENS   = (("100 %", 100), ("50 %", 50))
    _BENCH_DURATION = (("Court (2 min)", 120), ("Standard (5 min)", 300),
                       ("Long (10 min)", 600))
    _BENCH_IDLE_SEC = 120
    _BENCH_COOL_SEC = 300
    _BENCH_LABELS_FR = {"avant": "Avant", "apres": "Après", "libre": "Libre"}

    def _build_bench_tab(self, parent: tk.Frame):
        # En-tête
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=28, pady=(14, 2))
        tk.Label(head, text="Bench thermique", font=("Segoe UI", 16, "bold"),
                 bg=BG, fg=FG).pack(anchor="w")
        tk.Label(head,
                 text="Repos → charge CPU → refroidissement. Mesure le gain d'un "
                      "nettoyage ou d'un changement de pâte thermique (avant / après).",
                 font=("Segoe UI", 10), bg=BG, fg=FG_DIM,
                 justify="left").pack(anchor="w")

        # Barre de configuration
        cfg_box = tk.Frame(parent, bg=SURFACE,
                           highlightbackground=BORDER, highlightthickness=1, bd=0)
        cfg_box.pack(fill="x", padx=28, pady=(8, 6))
        cfg = tk.Frame(cfg_box, bg=SURFACE, pady=10, padx=10)
        cfg.pack(fill="x")

        def _combo(label, values, default):
            holder = tk.Frame(cfg, bg=SURFACE)
            holder.pack(side="left", padx=(0, 16))
            tk.Label(holder, text=label, font=("Segoe UI", 9, "bold"),
                     bg=SURFACE, fg=FG_DIM).pack(anchor="w")
            var = tk.StringVar(value=default)
            cb = ttk.Combobox(holder, textvariable=var, values=values,
                              state="readonly", style="PD.TCombobox",
                              font=("Segoe UI", 10), width=max(len(v) for v in values) + 2)
            cb.pack(anchor="w", pady=(2, 0))
            return var, cb

        self._bench_label_var, self._bench_label_cb = _combo(
            "Étiquette", [t for t, _ in self._BENCH_LABELS], "Avant")
        self._bench_intens_var, self._bench_intens_cb = _combo(
            "Intensité", [t for t, _ in self._BENCH_INTENS], "100 %")
        self._bench_dur_var, self._bench_dur_cb = _combo(
            "Durée de charge",
            [t for t, _ in self._BENCH_DURATION] + ["Personnalisé…"],
            "Standard (5 min)")
        # Élargi pour afficher « Personnalisé (NN min) » sans troncature.
        self._bench_dur_cb.config(width=22)
        self._bench_dur_cb.bind("<<ComboboxSelected>>", self._bench_on_duration)
        # Durée de charge custom (secondes) + mémoire du dernier choix valide.
        self._bench_custom_load_sec = None
        self._bench_dur_last = "Standard (5 min)"

        self._bench_btn = tk.Button(
            cfg, text="▶   Démarrer le test",
            font=("Segoe UI", 12, "bold"), bg=ACCENT, fg=BG,
            activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2", padx=22, pady=10,
            command=self._bench_toggle,
        )
        self._bench_btn.pack(side="right", anchor="s")

        # Bandeau de statut (phase + relevés temps réel)
        status = tk.Frame(parent, bg=BG)
        status.pack(fill="x", padx=28, pady=(2, 0))
        self._bench_phase_var = tk.StringVar(value="Prêt")
        self._bench_phase_lbl = tk.Label(status, textvariable=self._bench_phase_var,
                                         font=("Segoe UI", 11, "bold"), bg=BG, fg=FG_DIM)
        self._bench_phase_lbl.pack(side="left")
        self._bench_live_var = tk.StringVar(value="")
        tk.Label(status, textvariable=self._bench_live_var,
                 font=("Consolas", 10), bg=BG, fg=FG).pack(side="right")

        # Graphe temps réel
        chart_box = tk.Frame(parent, bg=SURFACE,
                             highlightbackground=BORDER, highlightthickness=1, bd=0)
        chart_box.pack(fill="both", expand=True, padx=28, pady=(6, 6))
        self._bench_canvas = tk.Canvas(chart_box, bg=BG, highlightthickness=0)
        self._bench_canvas.pack(fill="both", expand=True)
        self._bench_canvas.bind("<Configure>", lambda e: self._bench_redraw())

        # Bas : résultats (gauche) + sessions enregistrées (droite)
        bottom = tk.Frame(parent, bg=BG)
        bottom.pack(fill="x", padx=28, pady=(0, 12))

        res = tk.Frame(bottom, bg=BG)
        res.pack(side="left", fill="x", expand=True, anchor="n")
        tk.Label(res, text="Résultats", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=FG_DIM).pack(anchor="w")
        self._bench_result_var = tk.StringVar(value="Aucun test lancé.")
        tk.Label(res, textvariable=self._bench_result_var, font=("Segoe UI", 10),
                 bg=BG, fg=FG, justify="left", anchor="w").pack(anchor="w", fill="x", pady=(2, 0))

        sess = tk.Frame(bottom, bg=BG)
        sess.pack(side="right", anchor="n", padx=(16, 0))
        sess_hdr = tk.Frame(sess, bg=BG)
        sess_hdr.pack(fill="x")
        tk.Label(sess_hdr, text="Sessions enregistrées", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=FG_DIM).pack(side="left")
        tk.Button(sess_hdr, text="⟳", font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
                  activebackground=SURFACE2, activeforeground=FG, relief="flat",
                  cursor="hand2", padx=6, pady=0,
                  command=self._bench_refresh_sessions).pack(side="right")
        self._bench_sessions_list = tk.Listbox(
            sess, height=5, width=48, bg=SURFACE, fg=FG,
            selectbackground=ACCENT, selectforeground=BG,
            relief="flat", bd=0, highlightthickness=0,
            font=("Consolas", 9), activestyle="none", selectmode="extended",
        )
        self._bench_sessions_list.pack(fill="x", pady=(2, 0))
        self._bench_sessions_list.bind("<Double-Button-1>", self._bench_open_session)

        sess_foot = tk.Frame(sess, bg=BG)
        sess_foot.pack(fill="x")
        tk.Label(sess_foot, text="Double-clic : courbe  ·  2 sélections : comparer",
                 font=("Segoe UI", 8), bg=BG, fg=FG_MUTED).pack(side="left")
        tk.Button(sess_foot, text="Comparer avant / après",
                  font=("Segoe UI", 9), bg=SURFACE2, fg=FG,
                  activebackground=SURFACE, activeforeground=FG, relief="flat",
                  cursor="hand2", padx=10, pady=4,
                  command=self._bench_compare).pack(side="right", pady=(4, 0))

        self._bench_session_files = []
        self._bench_bounds = []
        self._bench_mode = "single"        # single | compare
        self._bench_compare_data = None    # (avant_samples, apres_samples)
        self.after(500, self._bench_refresh_sessions)

    # -- Pilotage du test ------------------------------------------------------

    def _bench_on_duration(self, _event=None):
        """Gère le choix « Personnalisé… » : demande une durée de charge en minutes."""
        sel = self._bench_dur_var.get()
        if sel != "Personnalisé…":
            self._bench_dur_last = sel   # dernier choix valide (preset)
            return

        current_min = max(1, round((self._bench_custom_load_sec or 300) / 60))
        mins = simpledialog.askinteger(
            "Durée personnalisée",
            "Durée de la phase de charge, en minutes (1 à 30).\n\n"
            "Pour une comparaison avant / après valable, utilisez EXACTEMENT la même "
            "durée (et la même intensité) pour les deux tests — sinon la comparaison "
            "sera refusée.",
            parent=self, minvalue=1, maxvalue=30, initialvalue=current_min)

        if mins is None:
            # Annulation : on revient au dernier choix valide.
            self._bench_dur_var.set(self._bench_dur_last)
            return

        self._bench_custom_load_sec = mins * 60
        self._bench_dur_var.set(f"Personnalisé ({mins} min)")
        self._bench_dur_last = self._bench_dur_var.get()

    def _bench_toggle(self):
        if self._bench_running:
            if self._bench is not None:
                self._bench.stop()
            self._bench_btn.config(text="Arrêt en cours…", state="disabled")
            return

        label     = dict(self._BENCH_LABELS)[self._bench_label_var.get()]
        intensity = dict(self._BENCH_INTENS)[self._bench_intens_var.get()]
        # Preset connu, sinon durée personnalisée (repli 300 s si non définie).
        load_sec  = dict(self._BENCH_DURATION).get(
            self._bench_dur_var.get(), self._bench_custom_load_sec or 300)

        total_min = round((self._BENCH_IDLE_SEC + load_sec + self._BENCH_COOL_SEC) / 60)
        if not messagebox.askyesno(
                "⚠ Avertissement — Test de charge thermique",
                f"Ce test sollicite VOLONTAIREMENT le processeur à forte charge "
                f"(intensité {intensity} %) pendant environ {total_min} min, afin de "
                "mesurer son comportement thermique puis son refroidissement.\n\n"
                "Des sécurités sont prévues — arrêt automatique au-delà de 95 °C et "
                "arrêt manuel possible à tout moment. Elles réduisent le risque mais "
                "NE l'éliminent PAS : selon l'état réel du matériel (poussière, pâte "
                "thermique dégradée, ventilateur ou capteur défaillant, composants "
                "vieillissants ou déjà fragilisés), la montée en température peut "
                "endommager le matériel.\n\n"
                "Ne lancez ce test que sur une machine dont l'état le permet. En "
                "cliquant sur « Oui », vous le démarrez en connaissance de cause et "
                "sous votre entière responsabilité ; Ghisdiag et son auteur ne "
                "sauraient être tenus responsables d'un éventuel dommage matériel.\n\n"
                "Fermez les autres applications lourdes pour un résultat fiable.\n\n"
                "Démarrer le test ?",
                icon="warning"):
            return

        out_dir = str(Path(self.out_dir_var.get()) / "thermal")
        cfg = BenchConfig(
            label=label, idle_sec=self._BENCH_IDLE_SEC, load_sec=load_sec,
            cooldown_sec=self._BENCH_COOL_SEC, intensity=intensity,
            sample_interval_ms=2000, output_dir=out_dir,
        ).normalized()

        self._bench_samples   = []
        self._bench_mode = "single"
        self._bench_compare_data = None
        self._bench_total_sec = cfg.idle_sec + cfg.load_sec + cfg.cooldown_sec
        b1 = cfg.idle_sec
        b2 = cfg.idle_sec + cfg.load_sec
        self._bench_bounds = [(0, b1, "idle"), (b1, b2, "load"),
                              (b2, self._bench_total_sec, "cooldown")]

        self._bench = ThermalBench(
            cfg,
            on_sample=self._bench_on_sample,
            on_phase=self._bench_on_phase,
            on_finish=self._bench_on_finish,
            on_error=self._bench_on_error,
        )
        if not self._bench.start():
            self._bench = None
            messagebox.showerror(
                "Bench thermique",
                "Impossible de démarrer les capteurs (LibreHardwareMonitor).")
            return

        self._bench_running = True
        self._bench_set_controls(False)
        self._bench_btn.config(text="■   Arrêter", bg=RED,
                               activebackground=RED_HOVER, state="normal")
        self._bench_result_var.set("Test en cours…")
        self._bench_live_var.set("")
        self._bench_draw_chart()

    def _bench_set_controls(self, enabled: bool):
        state = "readonly" if enabled else "disabled"
        for cb in (self._bench_label_cb, self._bench_intens_cb, self._bench_dur_cb):
            cb.config(state=state)

    def _bench_reset_button(self):
        self._bench_running = False
        self._bench = None
        self._bench_set_controls(True)
        self._bench_btn.config(text="▶   Démarrer le test", bg=ACCENT,
                               activebackground=ACCENT_HOVER, state="normal")

    # -- Callbacks moteur (remarshalés vers le thread tkinter) -----------------

    def _bench_on_sample(self, rec):
        self.after(0, self._bench_consume_sample, rec)

    def _bench_consume_sample(self, rec):
        if not self._bench_running:
            return
        self._bench_samples.append(rec)
        cpu = rec.get("cpu"); gpu = rec.get("gpu"); clk = rec.get("clock")
        parts = [f"CPU {cpu:.0f}°C" if cpu is not None else "CPU —",
                 f"GPU {gpu:.0f}°C" if gpu is not None else "GPU —"]
        if clk:
            parts.append(f"{clk:.0f} MHz")
        self._bench_live_var.set("    ".join(parts))
        self._bench_draw_chart()

    def _bench_on_phase(self, phase, idx, total):
        self.after(0, self._bench_set_phase, phase, idx, total)

    def _bench_set_phase(self, phase, idx, total):
        names = {
            BenchPhase.IDLE:     ("Repos (baseline)", FG_DIM),
            BenchPhase.LOAD:     ("Charge CPU", RED),
            BenchPhase.COOLDOWN: ("Refroidissement", ACCENT),
        }
        label, color = names.get(phase, ("?", FG))
        self._bench_phase_var.set(f"Phase {idx}/{total} — {label}")
        self._bench_phase_lbl.config(fg=color)

    def _bench_on_finish(self, session, path):
        self.after(0, self._bench_finished, session, path)

    def _bench_finished(self, session, path):
        self._bench_reset_button()
        m = session.get("metrics", {})
        self._bench_result_var.set(self._bench_format_metrics(m, session))
        if session.get("aborted"):
            self._bench_phase_var.set("Interrompu")
            self._bench_phase_lbl.config(fg=YELLOW)
        else:
            self._bench_phase_var.set("Terminé")
            self._bench_phase_lbl.config(fg=GREEN)
        self._bench_draw_chart()
        self._bench_refresh_sessions()
        if session.get("emergency"):
            messagebox.showwarning(
                "Arrêt d'urgence",
                "Température CPU au-delà de 95 °C : la charge a été coupée "
                "automatiquement. Le refroidissement a tout de même été mesuré.")

    def _bench_on_error(self, msg):
        self.after(0, self._bench_errored, msg)

    def _bench_errored(self, msg):
        self._bench_reset_button()
        self._bench_phase_var.set("Erreur")
        self._bench_phase_lbl.config(fg=RED)
        messagebox.showerror("Bench thermique", msg)

    # -- Sessions enregistrées -------------------------------------------------

    def _bench_refresh_sessions(self):
        self._bench_sessions_list.delete(0, "end")
        self._bench_session_files = []
        try:
            out = str(Path(self.out_dir_var.get()) / "thermal")
            sessions = bench_list_sessions(out)
        except Exception:
            sessions = []
        if not sessions:
            self._bench_sessions_list.insert("end", "  (aucune session)")
            return
        for s in sessions[:50]:
            lab = self._BENCH_LABELS_FR.get(s.get("label"), s.get("label") or "?")
            when = ""
            try:
                when = datetime.fromisoformat(s["started_at"]).strftime("%d/%m %H:%M")
            except Exception:
                pass
            m = s.get("metrics") or {}
            d = m.get("delta_c"); mx = m.get("load_max_c")
            dt = f"ΔT {d:+.0f}°C" if d is not None else "ΔT —"
            mxs = f"max {mx:.0f}°C" if mx is not None else "max —"
            flag = " (interrompu)" if s.get("aborted") else ""
            self._bench_sessions_list.insert(
                "end", f"[{lab:5}] {when}  {dt}  {mxs}{flag}")
            self._bench_session_files.append(s["file"])

    def _bench_open_session(self, _event=None):
        if self._bench_running:
            return
        sel = self._bench_sessions_list.curselection()
        if not sel or sel[0] >= len(self._bench_session_files):
            return
        session = bench_load_session(self._bench_session_files[sel[0]])
        if not session:
            return
        self._bench_mode = "single"
        self._bench_compare_data = None
        self._bench_samples = session.get("samples", [])
        cfg = session.get("config", {})
        b1 = cfg.get("idle_sec", 0)
        b2 = b1 + cfg.get("load_sec", 0)
        self._bench_total_sec = max(1, b2 + cfg.get("cooldown_sec", 0))
        self._bench_bounds = [(0, b1, "idle"), (b1, b2, "load"),
                              (b2, self._bench_total_sec, "cooldown")]
        lab = self._BENCH_LABELS_FR.get(session.get("label"), "?")
        self._bench_phase_var.set(f"Session affichée — {lab}")
        self._bench_phase_lbl.config(fg=FG_DIM)
        self._bench_live_var.set("")
        self._bench_result_var.set(
            self._bench_format_metrics(session.get("metrics", {}), session))
        self._bench_draw_chart()

    # -- Comparaison avant / après --------------------------------------------

    def _bench_compare(self):
        if self._bench_running:
            messagebox.showinfo("Bench thermique", "Attendez la fin du test en cours.")
            return
        sel = self._bench_sessions_list.curselection()
        files = [self._bench_session_files[i] for i in sel
                 if i < len(self._bench_session_files)]
        if len(files) != 2:
            messagebox.showinfo(
                "Comparaison",
                "Sélectionnez exactement deux sessions (Ctrl+clic pour la seconde).")
            return
        s1 = bench_load_session(files[0])
        s2 = bench_load_session(files[1])
        if not s1 or not s2:
            messagebox.showerror("Comparaison", "Impossible de charger les sessions.")
            return
        cmp = compare_sessions(s1, s2)
        if not cmp["compatible"]:
            messagebox.showwarning(
                "Comparaison impossible",
                "Les deux sessions n'ont pas le même protocole (durée ou intensité "
                "de charge différente). Ne comparez que des tests identiques.")
            return

        before, after = cmp["before"], cmp["after"]

        def total_of(s):
            c = s.get("config", {})
            return c.get("idle_sec", 0) + c.get("load_sec", 0) + c.get("cooldown_sec", 0)

        cfg = after.get("config", {})
        b1 = cfg.get("idle_sec", 0)
        b2 = b1 + cfg.get("load_sec", 0)
        self._bench_total_sec = max(1, total_of(before), total_of(after))
        self._bench_bounds = [(0, b1, "idle"), (b1, b2, "load"),
                              (b2, self._bench_total_sec, "cooldown")]
        self._bench_mode = "compare"
        self._bench_compare_data = (before.get("samples") or [],
                                    after.get("samples") or [])
        self._bench_phase_var.set("Comparaison avant / après")
        self._bench_phase_lbl.config(fg=ACCENT)
        self._bench_live_var.set("")
        self._bench_result_var.set(self._bench_compare_summary(cmp))
        self._bench_redraw()

        try:
            path = generate_comparison_report(
                before, after, self.out_dir_var.get(), cmp)
            os.startfile(str(Path(path).resolve()))
        except Exception as exc:
            logger.exception("Rapport de comparaison")
            messagebox.showerror("Rapport", f"Échec de génération du rapport : {exc}")

    @staticmethod
    def _bench_compare_summary(cmp: dict) -> str:
        g = cmp["gains"]; thr = cmp["throttling"]

        def gtxt(key, unit="°C"):
            d = g[key]["gain"]
            if d is None:
                return "—"
            sign = "−" if d > 0 else ("+" if d < 0 else "±")
            return f"{sign}{abs(d):.0f} {unit}"

        line2 = (f"ΔT {gtxt('delta_c')}    •    plateau {gtxt('load_plateau_c')}"
                 f"    •    max {gtxt('load_max_c')}"
                 f"    •    retour au calme {gtxt('cooldown_sec', 's')}")
        if thr["eliminated"]:
            line2 += "    •    throttling éliminé"
        elif thr["appeared"]:
            line2 += "    •    throttling apparu"
        return f"Verdict : {cmp['verdict']}\n{line2}"

    # -- Mise en forme des métriques ------------------------------------------

    @staticmethod
    def _bench_format_metrics(m: dict, session: dict) -> str:
        def deg(x):
            return f"{x:.0f}°C" if x is not None else "—"
        d   = m.get("delta_c")
        dts = f"{d:+.0f}°C" if d is not None else "—"
        cool = m.get("cooldown_sec")
        cs = f"{cool:.0f} s" if cool is not None else "non atteint"
        thr = "oui" if m.get("throttling") else "non"
        fanl = m.get("fan_load_rpm")
        fans = f"{fanl} tr/min" if fanl else "—"
        line1 = (f"T repos {deg(m.get('idle_c'))}    •    T max {deg(m.get('load_max_c'))}"
                 f"    •    plateau {deg(m.get('load_plateau_c'))}    •    ΔT {dts}")
        line2 = (f"Throttling : {thr}    •    Retour au calme : {cs}"
                 f"    •    Ventilo en charge : {fans}")
        note = ""
        if session.get("emergency"):
            note = "\n⚠ Arrêt d'urgence à 95 °C — résultats partiels."
        elif session.get("aborted"):
            note = "\n⚠ Test interrompu — résultats partiels."
        return f"{line1}\n{line2}{note}"

    # -- Graphe (tk.Canvas) ----------------------------------------------------

    @staticmethod
    def _bench_sample_value(s: dict, key: str):
        if key == "__disk__":
            temps = [d.get("t") for d in (s.get("disks") or [])
                     if isinstance(d, dict) and d.get("t") is not None]
            return max(temps) if temps else None
        return s.get(key)

    @staticmethod
    def _fmt_mmss(sec: float) -> str:
        sec = int(sec)
        return f"{sec // 60}:{sec % 60:02d}"

    def _bench_redraw(self):
        """Dispatcher : redessine selon le mode (live/single ou comparaison)."""
        if self._bench_mode == "compare" and self._bench_compare_data:
            self._bench_draw_compare(*self._bench_compare_data)
        else:
            self._bench_draw_chart()

    def _bench_chart_geom(self):
        """Prépare le canvas (cadre, zones, grille, ligne 95 °C, temps). Retourne
        (canvas, x0, y0, x1, y1, X, Y) ou None si trop petit."""
        c = getattr(self, "_bench_canvas", None)
        if c is None:
            return None
        c.delete("all")
        w = c.winfo_width(); h = c.winfo_height()
        if w < 60 or h < 60:
            return None
        ml, mr, mt, mb = 46, 14, 24, 26
        x0, y0, x1, y1 = ml, mt, w - mr, h - mb
        if x1 - x0 < 10 or y1 - y0 < 10:
            return None
        tmax = 100.0
        total = max(1, self._bench_total_sec)
        pw, ph = x1 - x0, y1 - y0

        def X(t):
            return x0 + (max(0.0, min(t, total)) / total) * pw

        def Y(v):
            return y1 - (max(0.0, min(v, tmax)) / tmax) * ph

        zone = {"idle": ZONE_IDLE, "load": ZONE_LOAD, "cooldown": ZONE_COOL}
        for a, b, name in self._bench_bounds:
            c.create_rectangle(X(a), y0, X(b), y1, fill=zone.get(name, BG), width=0)
        for temp in (0, 25, 50, 75, 100):
            yy = Y(temp)
            c.create_line(x0, yy, x1, yy, fill=BORDER)
            c.create_text(x0 - 6, yy, text=str(temp), anchor="e",
                          fill=FG_MUTED, font=("Segoe UI", 8))
        ye = Y(95)
        c.create_line(x0, ye, x1, ye, fill=RED, dash=(4, 3))
        c.create_text(x1 - 2, ye - 7, text="95 °C", anchor="e",
                      fill=RED, font=("Segoe UI", 8))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            t = total * frac
            c.create_text(X(t), y1 + 4, text=self._fmt_mmss(t), anchor="n",
                          fill=FG_MUTED, font=("Segoe UI", 8))
        c.create_rectangle(x0, y0, x1, y1, outline=BORDER, width=1)
        return c, x0, y0, x1, y1, X, Y

    @staticmethod
    def _bench_polyline(c, samples, key, color, X, Y, getter, dash=None):
        pts = []
        for s in samples:
            v = getter(s, key)
            if v is None:
                continue
            pts.extend((X(s.get("t", 0)), Y(v)))
        if len(pts) >= 4:
            kw = {"dash": dash} if dash else {}
            c.create_line(*pts, fill=color, width=2, smooth=True, **kw)
        elif len(pts) == 2:
            c.create_oval(pts[0] - 2, pts[1] - 2, pts[0] + 2, pts[1] + 2,
                          fill=color, width=0)

    @staticmethod
    def _bench_legend(c, x0, y0, items, dashes=None):
        lx, ly = x0 + 8, y0 + 6
        for i, (color, lbl) in enumerate(items):
            if dashes and dashes[i]:
                c.create_line(lx, ly + 6, lx + 14, ly + 6, fill=color, width=2, dash=dashes[i])
            else:
                c.create_rectangle(lx, ly, lx + 11, ly + 11, fill=color, width=0)
            c.create_text(lx + 17, ly + 6, text=lbl, anchor="w",
                          fill=FG_DIM, font=("Segoe UI", 8))
            lx += 17 + len(lbl) * 7 + 18

    @staticmethod
    def _bench_throttle_ranges(samples, bounds):
        """Detecte les intervalles de throttling pendant la phase de charge, en
        reprenant les seuils de thermal_bench.compute_metrics() (chute de
        frequence vs debut de charge, a temperature elevee) mais echantillon
        par echantillon pour un affichage sur la courbe."""
        load = next(((a, b) for a, b, name in bounds if name == "load"), None)
        if load is None:
            return []
        a, b = load
        load_samples = [s for s in samples if a <= s.get("t", -1) <= b]
        early_end = a + 0.4 * (b - a)
        early_clocks = [s["clock"] for s in load_samples
                         if s.get("clock") and s.get("t", 0) <= early_end]
        if not early_clocks:
            return []
        threshold = max(early_clocks) * (1 - THROTTLE_CLOCK_DROP)
        ranges = []
        cur_start = None
        for s in load_samples:
            clk, temp, t = s.get("clock"), s.get("cpu"), s.get("t", 0)
            hot = (clk is not None and clk < threshold
                   and temp is not None and temp >= THROTTLE_TEMP_FLOOR_C)
            if hot and cur_start is None:
                cur_start = t
            elif not hot and cur_start is not None:
                ranges.append((cur_start, t))
                cur_start = None
        if cur_start is not None:
            ranges.append((cur_start, load_samples[-1].get("t", b)))
        return ranges

    def _bench_draw_chart(self):
        geom = self._bench_chart_geom()
        if geom is None:
            return
        c, x0, y0, x1, y1, X, Y = geom
        series = (("cpu", RED, "CPU"), ("gpu", GREEN, "GPU"), ("__disk__", YELLOW, "Disque"))
        for key, color, _lbl in series:
            self._bench_polyline(c, self._bench_samples, key, color, X, Y,
                                 self._bench_sample_value)
        ranges = self._bench_throttle_ranges(self._bench_samples, self._bench_bounds)
        for ra, rb in ranges:
            c.create_line(X(ra), y1 - 4, X(rb), y1 - 4, fill=ORANGE, width=4)
        legend = [(col, lbl) for _k, col, lbl in series]
        if ranges:
            legend.append((ORANGE, "Throttling"))
        self._bench_legend(c, x0, y0, legend)

    def _bench_draw_compare(self, before_samples, after_samples):
        geom = self._bench_chart_geom()
        if geom is None:
            return
        c, x0, y0, x1, y1, X, Y = geom
        get = lambda s, k: s.get("cpu")
        self._bench_polyline(c, before_samples, "cpu", ORANGE, X, Y, get, dash=(6, 3))
        self._bench_polyline(c, after_samples, "cpu", GREEN, X, Y, get)
        self._bench_legend(c, x0, y0,
                           [(ORANGE, "Avant (CPU)"), (GREEN, "Après (CPU)")],
                           dashes=[(6, 3), None])

    def _on_app_close(self):
        """Arrêt propre : coupe le bench (et son worker de charge) + le flux
        capteurs du moniteur avant de fermer (évite un process LHM orphelin)."""
        try:
            if getattr(self, "_bench", None) is not None:
                self._bench.stop()
        except Exception:
            pass
        try:
            self._temp_stream_stop()
        except Exception:
            pass
        self.destroy()

    # ── Driver PawnIO (température/fréquence CPU) au démarrage ────────────────
    def _ensure_pawnio_startup(self):
        """Installe PawnIO en silence s'il manque (idempotent). Sans lui, LHM ne
        peut pas lire la température ni la fréquence CPU. Échec = temp CPU N/A."""
        try:
            from collectors import pawnio
            result = pawnio.ensure_pawnio()
            logger.info("PawnIO au démarrage : %s", result.get("action"))
        except Exception as exc:
            logger.debug("PawnIO startup : %s", exc)

    # ── Vérification SMART au démarrage ──────────────────────────────────────
    def _smart_startup_check(self):
        try:
            data = run_ps_action("collectors/smart.ps1", [], timeout=20)
            disks = data.get("disks") or []
            bad = [d for d in disks if isinstance(d, dict)
                   and d.get("HealthStatus") not in ("Healthy", "Unknown", None, "")]
            if bad:
                def _show():
                    names = "\n".join(
                        f"  • {d.get('Model', '?')} — {d.get('HealthStatus', '?')}"
                        for d in bad
                    )
                    messagebox.showwarning(
                        "⚠  Alerte disque détectée",
                        f"Problème SMART détecté sur {len(bad)} disque(s) :\n\n"
                        f"{names}\n\nLancez un diagnostic complet pour plus de détails.",
                    )
                self.after(0, _show)
        except Exception as exc:
            logger.debug("SMART startup check : %s", exc)

    # ── Onglet Setup / MAJ ────────────────────────────────────────────────────
    def _build_setup_tab(self, parent: tk.Frame):
        # Bandeau statut admin
        admin_ok = is_admin()
        admin_color = GREEN if admin_ok else YELLOW
        admin_msg   = "✓  Droits administrateur actifs" if admin_ok else "⚠  Droits administrateur requis pour certaines actions"
        admin_bar   = tk.Frame(parent, bg=admin_color, pady=5)
        admin_bar.pack(fill="x")
        tk.Label(admin_bar, text=admin_msg,
                 font=("Segoe UI", 9, "bold"),
                 bg=admin_color, fg=BG).pack()

        # Sous-onglets
        style = ttk.Style()
        style.configure("Setup.TNotebook",
                        background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("Setup.TNotebook.Tab",
                        background=BG, foreground=FG_MUTED,
                        font=("Segoe UI", 10), padding=[16, 8])
        style.map("Setup.TNotebook.Tab",
                  background=[("selected", SURFACE2), ("active", SURFACE)],
                  foreground=[("selected", ACCENT), ("active", FG_DIM)])

        sub_nb = ttk.Notebook(parent, style="Setup.TNotebook")
        sub_nb.pack(fill="both", expand=True)

        comptes_frame  = tk.Frame(sub_nb, bg=BG)
        maj_frame      = tk.Frame(sub_nb, bg=BG)
        pcneuf_frame   = tk.Frame(sub_nb, bg=BG)
        recup_frame    = tk.Frame(sub_nb, bg=BG)

        sub_nb.add(comptes_frame, text="  Comptes  ")
        sub_nb.add(maj_frame,     text="  Mises à jour  ")
        sub_nb.add(pcneuf_frame,  text="  PC Neuf  ")
        sub_nb.add(recup_frame,   text="  Récupération  ")

        self._build_comptes_panel(comptes_frame)
        self._build_maj_panel(maj_frame)
        self._build_pcneuf_panel(pcneuf_frame)
        self._build_recuperation_panel(recup_frame)

    # ── Panneau Comptes ───────────────────────────────────────────────────────
    def _build_comptes_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        pad = {"padx": 28, "pady": 8}

        # ── Créer un compte ───────────────────────────────────────────────────
        sec1 = tk.Frame(inner, bg=BG, pady=16)
        sec1.pack(fill="x", **{"padx": 28})
        tk.Label(sec1, text="👤  Créer un compte utilisateur",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec1, text="Crée un compte local Windows standard ou administrateur.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 12))

        form1 = tk.Frame(sec1, bg=SURFACE, padx=16, pady=14)
        form1.pack(fill="x")

        def _row(parent, label, widget_fn):
            r = tk.Frame(parent, bg=SURFACE)
            r.pack(fill="x", pady=(0, 8))
            tk.Label(r, text=label, font=("Segoe UI", 9),
                     bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
            widget_fn(r)

        self._new_user_var  = tk.StringVar()
        self._new_pwd_var   = tk.StringVar()
        self._new_type_var  = tk.StringVar(value="standard")
        self._no_pwd_var    = tk.BooleanVar(value=False)

        _row(form1, "Nom d'utilisateur :", lambda p: tk.Entry(
            p, textvariable=self._new_user_var,
            font=("Consolas", 10), bg=SURFACE2, fg=FG,
            insertbackground=FG, relief="flat", width=24,
        ).pack(side="left", ipady=5, ipadx=6))

        pwd_row = tk.Frame(form1, bg=SURFACE)
        pwd_row.pack(fill="x", pady=(0, 8))
        tk.Label(pwd_row, text="Mot de passe :", font=("Segoe UI", 9),
                 bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
        self._pwd_entry = tk.Entry(
            pwd_row, textvariable=self._new_pwd_var, show="●",
            font=("Consolas", 10), bg=SURFACE2, fg=FG,
            insertbackground=FG, relief="flat", width=24,
        )
        self._pwd_entry.pack(side="left", ipady=5, ipadx=6)

        def _toggle_no_pwd():
            if self._no_pwd_var.get():
                self._new_pwd_var.set("")
                self._pwd_entry.configure(state="disabled", bg=SURFACE)
            else:
                self._pwd_entry.configure(state="normal", bg=SURFACE2)

        tk.Checkbutton(
            pwd_row, text="Sans mot de passe",
            variable=self._no_pwd_var, command=_toggle_no_pwd,
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
            activebackground=SURFACE, selectcolor=SURFACE2,
            relief="flat",
        ).pack(side="left", padx=(10, 0))

        type_row = tk.Frame(form1, bg=SURFACE)
        type_row.pack(fill="x", pady=(0, 8))
        tk.Label(type_row, text="Type de compte :", font=("Segoe UI", 9),
                 bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
        for val, lbl in (("standard", "Utilisateur standard"), ("admin", "Administrateur")):
            tk.Radiobutton(type_row, text=lbl, variable=self._new_type_var, value=val,
                           font=("Segoe UI", 9), bg=SURFACE, fg=FG,
                           activebackground=SURFACE, selectcolor=SURFACE2,
                           relief="flat").pack(side="left", padx=(0, 16))

        self._comptes_log_var = tk.StringVar(value="")
        btn_row1 = tk.Frame(form1, bg=SURFACE)
        btn_row1.pack(fill="x", pady=(4, 0))
        tk.Button(btn_row1, text="Créer le compte",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=16, pady=8, command=self._comptes_create).pack(side="left")

        tk.Frame(inner, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(4, 4))

        # ── Renommer un compte ────────────────────────────────────────────────
        sec_rn = tk.Frame(inner, bg=BG, pady=16)
        sec_rn.pack(fill="x", padx=28)
        tk.Label(sec_rn, text="✏️  Renommer un compte",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec_rn, text="Change le nom d'un compte local existant (le profil et les données sont conservés).",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 12))

        form_rn = tk.Frame(sec_rn, bg=SURFACE, padx=16, pady=14)
        form_rn.pack(fill="x")

        rn_user_row = tk.Frame(form_rn, bg=SURFACE)
        rn_user_row.pack(fill="x", pady=(0, 8))
        tk.Label(rn_user_row, text="Compte :", font=("Segoe UI", 9),
                 bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
        self._rename_user_var = tk.StringVar()
        self._rename_user_combo = ttk.Combobox(rn_user_row, textvariable=self._rename_user_var,
                                                font=("Segoe UI", 10), width=22, state="readonly",
                                                style="PD.TCombobox")
        self._rename_user_combo.pack(side="left", ipady=3)
        tk.Button(rn_user_row, text="↻", font=("Segoe UI", 10), bg=SURFACE2, fg=FG,
                  relief="flat", cursor="hand2", padx=8,
                  command=self._comptes_load_users).pack(side="left", padx=(6, 0))

        self._rename_new_var = tk.StringVar()
        _row(form_rn, "Nouveau nom :", lambda p: tk.Entry(
            p, textvariable=self._rename_new_var,
            font=("Consolas", 10), bg=SURFACE2, fg=FG,
            insertbackground=FG, relief="flat", width=24,
        ).pack(side="left", ipady=5, ipadx=6))

        btn_row_rn = tk.Frame(form_rn, bg=SURFACE)
        btn_row_rn.pack(fill="x", pady=(4, 0))
        tk.Button(btn_row_rn, text="Renommer",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=16, pady=8, command=self._comptes_rename).pack(side="left")

        tk.Frame(inner, height=1, bg=BORDER).pack(fill="x", padx=20, pady=(4, 4))

        # ── Expiration MDP ────────────────────────────────────────────────────
        sec2 = tk.Frame(inner, bg=BG, pady=16)
        sec2.pack(fill="x", padx=28)
        tk.Label(sec2, text="🔑  Expiration du mot de passe",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec2, text="Définit si le MDP d'un compte expire ou non.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 12))

        form2 = tk.Frame(sec2, bg=SURFACE, padx=16, pady=14)
        form2.pack(fill="x")

        user_row = tk.Frame(form2, bg=SURFACE)
        user_row.pack(fill="x", pady=(0, 8))
        tk.Label(user_row, text="Compte :", font=("Segoe UI", 9),
                 bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
        self._pwd_user_var = tk.StringVar()
        self._pwd_user_combo = ttk.Combobox(user_row, textvariable=self._pwd_user_var,
                                             font=("Segoe UI", 10), width=22, state="readonly",
                                             style="PD.TCombobox")
        self._pwd_user_combo.pack(side="left", ipady=3)
        tk.Button(user_row, text="↻", font=("Segoe UI", 10), bg=SURFACE2, fg=FG,
                  relief="flat", cursor="hand2", padx=8,
                  command=self._comptes_load_users).pack(side="left", padx=(6, 0))

        self._no_expiry_var = tk.BooleanVar(value=True)
        exp_row = tk.Frame(form2, bg=SURFACE)
        exp_row.pack(fill="x", pady=(0, 8))
        tk.Label(exp_row, text="Politique :", font=("Segoe UI", 9),
                 bg=SURFACE, fg=FG_DIM, width=20, anchor="w").pack(side="left")
        tk.Radiobutton(exp_row, text="Sans expiration", variable=self._no_expiry_var, value=True,
                       font=("Segoe UI", 9), bg=SURFACE, fg=FG,
                       activebackground=SURFACE, selectcolor=SURFACE2,
                       relief="flat").pack(side="left", padx=(0, 16))
        tk.Radiobutton(exp_row, text="Activer l'expiration (politique système)",
                       variable=self._no_expiry_var, value=False,
                       font=("Segoe UI", 9), bg=SURFACE, fg=FG,
                       activebackground=SURFACE, selectcolor=SURFACE2,
                       relief="flat").pack(side="left")

        btn_row2 = tk.Frame(form2, bg=SURFACE)
        btn_row2.pack(fill="x", pady=(4, 0))
        tk.Button(btn_row2, text="Appliquer",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=16, pady=8, command=self._comptes_set_policy).pack(side="left")

        # Log commun aux deux sections
        log_frame = tk.Frame(inner, bg=SURFACE, pady=6, padx=12)
        log_frame.pack(fill="x", padx=28, pady=(8, 12))
        tk.Label(log_frame, textvariable=self._comptes_log_var,
                 font=("Consolas", 9), bg=SURFACE, fg=FG_DIM,
                 justify="left", anchor="w", wraplength=560).pack(fill="x")

        self.after(400, self._comptes_load_users)

    def _comptes_load_users(self):
        def _worker():
            try:
                data  = run_ps_action("collectors/user_manager.ps1", ["-Action", "list-users"])
                users = [u.get("Name", "") for u in (data.get("users") or []) if u.get("Enabled")]
                def _update():
                    self._pwd_user_combo["values"] = users
                    self._rename_user_combo["values"] = users
                    if users:
                        if self._pwd_user_var.get() not in users:
                            self._pwd_user_var.set(users[0])
                        if self._rename_user_var.get() not in users:
                            self._rename_user_var.set(users[0])
                self.after(0, _update)
            except Exception as exc:
                logger.debug("load users : %s", exc)
        threading.Thread(target=_worker, daemon=True).start()

    def _comptes_create(self):
        if self._setup_busy:
            return
        name = self._new_user_var.get().strip()
        pwd  = self._new_pwd_var.get()
        typ  = self._new_type_var.get()
        no_pwd = self._no_pwd_var.get()
        if not name:
            self._comptes_log_var.set("Erreur : nom d'utilisateur vide.")
            return
        if not no_pwd and len(pwd) < 8:
            self._comptes_log_var.set("Erreur : mot de passe trop court (min. 8 caractères).")
            return
        if no_pwd:
            pwd = ""
        self._setup_busy = True
        self._comptes_log_var.set("Création en cours…")

        def _worker():
            try:
                data = run_ps_action("collectors/user_manager.ps1",
                                     ["-Action", "create-user",
                                      "-Username", name, "-Password", pwd, "-Type", typ])
                def _update():
                    self._setup_busy = False
                    if data.get("success"):
                        self._comptes_log_var.set(f"✓ {data.get('message', 'Compte créé.')}")
                        self._new_user_var.set("")
                        self._new_pwd_var.set("")
                        self._comptes_load_users()
                    else:
                        self._comptes_log_var.set(f"Erreur : {data.get('error', '?')}")
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._comptes_log_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _comptes_rename(self):
        if self._setup_busy:
            return
        old = self._rename_user_var.get().strip()
        new = self._rename_new_var.get().strip()
        if not old:
            self._comptes_log_var.set("Sélectionnez un compte à renommer.")
            return
        if not new:
            self._comptes_log_var.set("Erreur : nouveau nom vide.")
            return
        if old == new:
            self._comptes_log_var.set("Le nouveau nom est identique à l'ancien.")
            return
        self._setup_busy = True
        self._comptes_log_var.set("Renommage en cours…")

        def _worker():
            try:
                data = run_ps_action("collectors/user_manager.ps1",
                                     ["-Action", "rename-user",
                                      "-Username", old, "-NewName", new])
                def _update():
                    self._setup_busy = False
                    if data.get("success"):
                        self._comptes_log_var.set(f"✓ {data.get('message', 'Compte renommé.')}")
                        self._rename_new_var.set("")
                        self._comptes_load_users()
                    else:
                        self._comptes_log_var.set(f"Erreur : {data.get('error', '?')}")
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._comptes_log_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _comptes_set_policy(self):
        if self._setup_busy:
            return
        username = self._pwd_user_var.get().strip()
        if not username:
            self._comptes_log_var.set("Sélectionnez un compte.")
            return
        self._setup_busy = True
        self._comptes_log_var.set("Application en cours…")
        no_expiry = self._no_expiry_var.get()
        args = ["-Action", "set-password-policy", "-Username", username]
        if no_expiry:
            args.append("-NoExpiry")

        def _worker():
            try:
                data = run_ps_action("collectors/user_manager.ps1", args)
                def _update():
                    self._setup_busy = False
                    if data.get("success"):
                        self._comptes_log_var.set(f"✓ {data.get('message', 'Politique appliquée.')}")
                    else:
                        self._comptes_log_var.set(f"Erreur : {data.get('error', '?')}")
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._comptes_log_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    # ── Panneau Mises à jour ──────────────────────────────────────────────────
    def _build_maj_panel(self, parent: tk.Frame):
        sec = tk.Frame(parent, bg=BG, pady=16)
        sec.pack(fill="both", expand=True, padx=28)

        tk.Label(sec, text="🔄  Mises à jour Windows & Applications",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec, text="Mettez à jour winget et les applications installées.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 12))

        # Barre statut winget
        status_bar = tk.Frame(sec, bg=SURFACE, padx=14, pady=10)
        status_bar.pack(fill="x")
        tk.Label(status_bar, text="winget",
                 font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG_DIM).pack(side="left")
        self._winget_status_var = tk.StringVar(value="Vérification…")
        self._winget_status_lbl = tk.Label(status_bar, textvariable=self._winget_status_var,
                 font=("Segoe UI", 9), bg=SURFACE, fg=FG)
        self._winget_status_lbl.pack(side="left", padx=(8, 0))
        self._winget_badge = tk.Label(status_bar, text="⚠ Mise à jour requise",
                 font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=YELLOW)
        tk.Button(status_bar, text="↻ Vérifier",
                  font=("Segoe UI", 9), bg=SURFACE2, fg=FG,
                  activebackground=BG, relief="flat", cursor="hand2",
                  padx=8, pady=4, command=self._maj_check_winget).pack(side="right")

        # Boutons d'action
        btns = tk.Frame(sec, bg=BG)
        btns.pack(fill="x", pady=(12, 0))

        tk.Button(btns, text="⬆  Mettre à jour winget",
                  font=("Segoe UI", 10), bg=SURFACE, fg=FG,
                  activebackground=SURFACE2, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._maj_update_winget).pack(side="left", padx=(0, 8))

        tk.Button(btns, text="🔍  Lister les MAJ disponibles",
                  font=("Segoe UI", 10), bg=SURFACE, fg=FG,
                  activebackground=SURFACE2, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._maj_list).pack(side="left", padx=(0, 8))

        tk.Button(btns, text="⬆  Tout mettre à jour",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._maj_update_all).pack(side="left")

        # Barre de progression (cachée par défaut, affichée pendant update-all)
        self._maj_bar = ttk.Progressbar(sec, mode="indeterminate")

        # Zone de log
        self._maj_log_wrap = tk.Frame(sec, bg=SURFACE)
        self._maj_log_wrap.pack(fill="both", expand=True, pady=(12, 0))
        self._maj_log = tk.Text(self._maj_log_wrap, bg=SURFACE, fg=FG_DIM,
                                 font=("Consolas", 9), bd=0, padx=10, pady=8,
                                 state="disabled", wrap="word",
                                 selectbackground=SURFACE2)
        maj_sb = ttk.Scrollbar(self._maj_log_wrap, command=self._maj_log.yview, style="PD.Vertical.TScrollbar")
        self._maj_log.configure(yscrollcommand=maj_sb.set)
        maj_sb.pack(side="right", fill="y")
        self._maj_log.pack(fill="both", expand=True)

        self.after(500, self._maj_check_winget)

    def _maj_log_append(self, msg: str, fg: str = None):
        self._maj_log.configure(state="normal")
        self._maj_log.insert("end", msg + "\n")
        if fg:
            start = self._maj_log.index("end-2l")
            end   = self._maj_log.index("end-1c")
            tag   = f"col_{fg.replace('#','')}"
            self._maj_log.tag_config(tag, foreground=fg)
            self._maj_log.tag_add(tag, start, end)
        self._maj_log.see("end")
        self._maj_log.configure(state="disabled")

    def _maj_log_clear(self):
        self._maj_log.configure(state="normal")
        self._maj_log.delete("1.0", "end")
        self._maj_log.configure(state="disabled")

    def _maj_check_winget(self):
        self._winget_status_var.set("Vérification…")
        self._winget_status_lbl.configure(fg=FG)
        self._winget_badge.pack_forget()
        def _worker():
            try:
                data = run_ps_action("collectors/winget_manager.ps1", ["-Action", "check"])
                def _update():
                    if data.get("available"):
                        ver   = data.get("version") or "?"
                        needs = data.get("needs_update", False)
                        self._winget_needs_update = needs
                        if needs:
                            self._winget_status_var.set(f"v{ver}  — version obsolète")
                            self._winget_status_lbl.configure(fg=YELLOW)
                            self._winget_badge.pack(side="left", padx=(10, 0))
                        else:
                            self._winget_status_var.set(f"v{ver}  ✓ Disponible")
                            self._winget_status_lbl.configure(fg=GREEN)
                    else:
                        self._winget_needs_update = True
                        self._winget_status_var.set("Non installé — Windows 10 1809+ requis")
                        self._winget_status_lbl.configure(fg=RED)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._winget_status_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _maj_update_winget(self):
        if self._setup_busy:
            return
        if self._winget_needs_update:
            self._maj_show_winget_update_dialog()
            return
        self._setup_busy = True
        self._maj_log_clear()
        self._maj_log_append("Mise à jour de winget en cours…")

        def _worker():
            try:
                data = run_ps_action("collectors/winget_manager.ps1",
                                     ["-Action", "update-winget"], timeout=120)
                out = data.get("output") or ""
                def _update():
                    self._setup_busy = False
                    self._maj_log_append(out or "(pas de sortie)")
                    self._maj_check_winget()
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._maj_log_append(f"Erreur : {e}", RED)
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _maj_show_winget_update_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Mettre à jour winget")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()
        dlg.geometry("480x220")

        tk.Label(dlg, text="winget obsolète ou absent",
                 font=("Segoe UI", 12, "bold"), bg=BG, fg=YELLOW).pack(pady=(22, 4))
        tk.Label(dlg,
                 text="Votre version de winget est trop ancienne ou absente.\n"
                      "Choisissez comment la mettre à jour :",
                 font=("Segoe UI", 9), bg=BG, fg=FG, justify="center").pack(pady=(0, 18))

        btns = tk.Frame(dlg, bg=BG)
        btns.pack()

        def _via_store():
            dlg.destroy()
            self._maj_update_winget_store()

        def _via_github():
            dlg.destroy()
            self._maj_update_winget_github()

        tk.Button(btns, text="🏪  Via Microsoft Store\n(recommandé)",
                  font=("Segoe UI", 10), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=16, pady=10, command=_via_store).pack(side="left", padx=8)

        tk.Button(btns, text="⬇  Via GitHub\n(téléchargement direct)",
                  font=("Segoe UI", 10), bg=SURFACE, fg=FG,
                  activebackground=SURFACE2, relief="flat", cursor="hand2",
                  padx=16, pady=10, command=_via_github).pack(side="left", padx=8)

        tk.Button(dlg, text="Annuler",
                  font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
                  activebackground=SURFACE2, relief="flat", cursor="hand2",
                  padx=8, pady=4, command=dlg.destroy).pack(pady=(14, 0))

    def _maj_update_winget_store(self):
        try:
            run_ps_action("collectors/winget_manager.ps1", ["-Action", "open-store"])
        except Exception:
            pass
        self._maj_log_clear()
        self._maj_log_append("Microsoft Store ouvert — page App Installer.", GREEN)
        self._maj_log_append("Cliquez sur « Mettre à jour » dans le Store,")
        self._maj_log_append("puis fermez et relancez Ghisdiag.")

    def _maj_update_winget_github(self):
        if self._setup_busy:
            return
        self._setup_busy = True
        self._maj_log_clear()
        self._maj_log_append("Téléchargement et installation de winget depuis GitHub…")
        self._maj_log_append("(peut prendre 1-2 minutes selon votre connexion)\n")
        self._maj_bar.pack(fill="x", pady=(6, 0), before=self._maj_log_wrap)
        self._maj_bar.start(10)

        def _on_line(line):
            color = GREEN if line.startswith("SUCCESS:") else (RED if line.startswith("ERREUR:") else None)
            self.after(0, lambda l=line, c=color: self._maj_log_append(l, c))

        def _worker():
            try:
                rc = run_ps_stream("collectors/winget_manager.ps1",
                                   ["-Action", "install-from-github"], _on_line, timeout=300)
                def _done():
                    self._setup_busy = False
                    self._maj_bar.stop()
                    self._maj_bar.pack_forget()
                    self._maj_log_append("─" * 50)
                    if rc == 0:
                        self._maj_log_append("✓ Relancez Ghisdiag pour utiliser la nouvelle version.", GREEN)
                        self._maj_check_winget()
                    else:
                        self._maj_log_append(f"⚠ Terminé avec code {rc}.", YELLOW)
                self.after(0, _done)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._maj_bar.stop()
                    self._maj_bar.pack_forget()
                    self._maj_log_append(f"Erreur : {e}", RED)
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _maj_list(self):
        if self._setup_busy:
            return
        self._setup_busy = True
        self._maj_log_clear()
        self._maj_log_append("Recherche des mises à jour disponibles…")

        def _worker():
            try:
                data = run_ps_action("collectors/winget_manager.ps1",
                                     ["-Action", "list-upgradable"], timeout=60)
                out = data.get("raw_output") or "(aucune mise à jour disponible)"
                def _update():
                    self._setup_busy = False
                    self._maj_log_clear()
                    self._maj_log_append(out)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._maj_log_append(f"Erreur : {e}", RED)
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _maj_update_all(self):
        if self._setup_busy:
            return
        if not messagebox.askyesno(
            "Mettre à jour toutes les applications",
            "Mettre à jour toutes les applications via winget ?\n\n"
            "Cette opération peut prendre plusieurs minutes.\n"
            "Ne pas éteindre le PC pendant la mise à jour.",
        ):
            return
        self._setup_busy = True
        self._maj_log_clear()
        self._maj_log_append("Mise à jour de toutes les applications en cours…")
        self._maj_log_append("(les lignes apparaissent au fur et à mesure)\n")
        self._maj_bar.pack(fill="x", pady=(6, 0), before=self._maj_log_wrap)
        self._maj_bar.start(10)

        def _on_line(line):
            self.after(0, lambda l=line: self._maj_log_append(l))

        def _worker():
            try:
                rc = run_ps_stream("collectors/winget_manager.ps1",
                                   ["-Action", "stream-update-all"], _on_line, timeout=900)
                def _done():
                    self._setup_busy = False
                    self._maj_bar.stop()
                    self._maj_bar.pack_forget()
                    self._maj_log_append("─" * 50)
                    ok = (rc == 0)
                    color = GREEN if ok else YELLOW
                    self._maj_log_append(
                        "✓ Mises à jour terminées." if ok
                        else f"⚠ Terminé avec code {rc} (vérifier le log ci-dessus).", color)
                self.after(0, _done)
            except Exception as exc:
                def _err(e=exc):
                    self._setup_busy = False
                    self._maj_bar.stop()
                    self._maj_bar.pack_forget()
                    self._maj_log_append(f"Erreur : {e}", RED)
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    # ── Panneau PC Neuf ───────────────────────────────────────────────────────
    _APP_LIST = [
        ("chrome",      "Google Chrome",        "Google.Chrome"),
        ("firefox",     "Mozilla Firefox",       "Mozilla.Firefox"),
        ("adobereader", "Adobe Acrobat Reader",  "Adobe.Acrobat.Reader.64-bit"),
        ("libreoffice", "LibreOffice",           "TheDocumentFoundation.LibreOffice"),
        ("anydesk",     "AnyDesk",               "AnyDesk.AnyDesk"),
        ("xnview",      "XNView MP (visionneuse)", "XnSoft.XnViewMP"),
        ("vlc",         "VLC media player",      "VideoLAN.VLC"),
    ]

    def _build_pcneuf_panel(self, parent: tk.Frame):
        sec = tk.Frame(parent, bg=BG, pady=16)
        sec.pack(fill="both", expand=True, padx=28)

        tk.Label(sec, text="💻  Installation PC Neuf",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec,
                 text="Installe les logiciels essentiels en silence via winget (français, sans interaction).",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 12))

        # Checkboxes
        chk_frame = tk.Frame(sec, bg=SURFACE, padx=16, pady=12)
        chk_frame.pack(fill="x")

        self._pcneuf_vars = {}
        self._pcneuf_status = {}
        for key, name, winget_id in self._APP_LIST:
            row = tk.Frame(chk_frame, bg=SURFACE)
            row.pack(fill="x", pady=(0, 4))
            var = tk.BooleanVar(value=True)
            self._pcneuf_vars[key] = var
            tk.Checkbutton(row, text=name, variable=var,
                           font=("Segoe UI", 10), bg=SURFACE, fg=FG,
                           activebackground=SURFACE, selectcolor=SURFACE2,
                           relief="flat", cursor="hand2").pack(side="left")
            status_var = tk.StringVar(value="")
            self._pcneuf_status[key] = status_var
            tk.Label(row, textvariable=status_var,
                     font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED).pack(side="right")

        # Boutons
        self._pcneuf_btns = tk.Frame(sec, bg=BG)
        self._pcneuf_btns.pack(fill="x", pady=(12, 0))
        tk.Button(self._pcneuf_btns, text="🔍  Vérifier installés",
                  font=("Segoe UI", 10), bg=SURFACE, fg=FG,
                  activebackground=SURFACE2, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._pcneuf_check).pack(side="left", padx=(0, 8))
        tk.Button(self._pcneuf_btns, text="⬇  Installer la sélection",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=BG,
                  activebackground=ACCENT_HOVER, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._pcneuf_install).pack(side="left")

        # Barre de progression (cachée par défaut)
        self._pcneuf_bar = ttk.Progressbar(sec, mode="indeterminate")

        # ── Icônes du bureau ──────────────────────────────────────────────────
        icons_sec = tk.Frame(sec, bg=SURFACE, padx=16, pady=12)
        icons_sec.pack(fill="x", pady=(12, 0))
        tk.Label(icons_sec, text="🖥  Icônes du bureau",
                 font=("Segoe UI", 11, "bold"), bg=SURFACE, fg=FG).pack(anchor="w")
        tk.Label(icons_sec,
                 text="Affiche « Ce PC », les « Fichiers de l'utilisateur » et la « Corbeille » sur le bureau.",
                 font=("Segoe UI", 9), bg=SURFACE, fg=FG_MUTED).pack(anchor="w", pady=(2, 8))
        tk.Button(icons_sec, text="🖥  Ajouter les icônes du bureau",
                  font=("Segoe UI", 10), bg=SURFACE2, fg=FG,
                  activebackground=ACCENT, relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._pcneuf_add_icons).pack(anchor="w")

        # Log
        log_wrap = tk.Frame(sec, bg=SURFACE)
        log_wrap.pack(fill="both", expand=True, pady=(12, 0))
        self._pcneuf_log = tk.Text(log_wrap, bg=SURFACE, fg=FG_DIM,
                                    font=("Consolas", 9), bd=0, padx=10, pady=8,
                                    state="disabled", wrap="word",
                                    selectbackground=SURFACE2)
        pcn_sb = ttk.Scrollbar(log_wrap, command=self._pcneuf_log.yview, style="PD.Vertical.TScrollbar")
        self._pcneuf_log.configure(yscrollcommand=pcn_sb.set)
        pcn_sb.pack(side="right", fill="y")
        self._pcneuf_log.pack(fill="both", expand=True)

        self.after(600, self._pcneuf_check)

    def _pcneuf_log_append(self, msg: str, fg: str = None):
        self._pcneuf_log.configure(state="normal")
        self._pcneuf_log.insert("end", msg + "\n")
        if fg:
            start = self._pcneuf_log.index("end-2l")
            end   = self._pcneuf_log.index("end-1c")
            tag   = f"col_{fg.replace('#','')}"
            self._pcneuf_log.tag_config(tag, foreground=fg)
            self._pcneuf_log.tag_add(tag, start, end)
        self._pcneuf_log.see("end")
        self._pcneuf_log.configure(state="disabled")

    def _pcneuf_check(self):
        if self._setup_busy:
            return
        for var in self._pcneuf_status.values():
            var.set("…")
        self._pcneuf_log_append("Vérification des applications installées…")

        def _worker():
            try:
                data = run_ps_action("collectors/setup_apps.ps1", ["-Action", "check"], timeout=120)
                winget_ok = data.get("winget_available", True)
                apps = data.get("apps") or {}
                def _update():
                    if not winget_ok:
                        for var in self._pcneuf_status.values():
                            var.set("")
                        self._pcneuf_log_append(
                            "⚠ winget est absent ou obsolète sur ce PC.\n"
                            "  → Allez dans l'onglet « Mises à Jour » pour mettre à jour winget.", YELLOW)
                        return
                    nb_installed = 0
                    for key, info in apps.items():
                        if key in self._pcneuf_status:
                            installed = info.get("installed", False)
                            self._pcneuf_status[key].set("✓ Installé" if installed else "✗ Non installé")
                            if installed:
                                nb_installed += 1
                    self._pcneuf_log_append(
                        f"✓ Vérification terminée — {nb_installed} application(s) déjà installée(s).", GREEN)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    for var in self._pcneuf_status.values():
                        var.set("")
                    self._pcneuf_log_append(f"✗ Échec de la vérification : {e}", RED)
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _pcneuf_install(self):
        if self._setup_busy:
            return
        if self._winget_needs_update:
            messagebox.showwarning(
                "winget requis",
                "winget est absent ou obsolète sur ce PC.\n\n"
                "Allez dans l'onglet « Mises à Jour » pour installer / mettre à jour winget d'abord.")
            return
        selected = [key for key, var in self._pcneuf_vars.items() if var.get()]
        if not selected:
            messagebox.showinfo("PC Neuf", "Aucune application sélectionnée.")
            return
        names = [name for key, name, _ in self._APP_LIST if key in selected]
        if not messagebox.askyesno(
            "Installer les applications",
            f"Installer {len(selected)} application(s) ?\n\n"
            + "\n".join(f"  • {n}" for n in names)
            + "\n\nL'installation est silencieuse et peut prendre plusieurs minutes.",
        ):
            return

        self._setup_busy = True
        self._pcneuf_log.configure(state="normal")
        self._pcneuf_log.delete("1.0", "end")
        self._pcneuf_log.configure(state="disabled")
        self._pcneuf_log_append(f"Installation de {len(selected)} application(s)…")
        self._pcneuf_bar.pack(fill="x", pady=(6, 0), after=self._pcneuf_btns)
        self._pcneuf_bar.start(10)

        def _worker():
            total = len(selected)
            for idx, key in enumerate(selected, 1):
                name = next((n for k, n, _ in self._APP_LIST if k == key), key)
                def _progress(n=name, i=idx, t=total, k=key):
                    self._pcneuf_log_append(f"\n[{i}/{t}] → {n}…")
                    self._pcneuf_status[k].set("⏳ en cours…")
                self.after(0, _progress)
                try:
                    data = run_ps_action("collectors/setup_apps.ps1",
                                         ["-Action", "install", "-App", key], timeout=300)
                    already = data.get("already_installed", False)
                    ok      = data.get("success", False)
                    def _result(n=name, ok=ok, already=already, key=key):
                        if already:
                            self._pcneuf_log_append(f"  ✓ {n} — déjà installé", FG_MUTED)
                            self._pcneuf_status[key].set("✓ Installé")
                        elif ok:
                            self._pcneuf_log_append(f"  ✓ {n} — installé avec succès", GREEN)
                            self._pcneuf_status[key].set("✓ Installé")
                        else:
                            err = data.get("error") or "Erreur inconnue"
                            self._pcneuf_log_append(f"  ✗ {n} — {err}", RED)
                            self._pcneuf_status[key].set("✗ Erreur")
                    self.after(0, _result)
                except Exception as exc:
                    def _err(n=name, e=exc, key=key):
                        self._pcneuf_log_append(f"  ✗ {n} — {e}", RED)
                        self._pcneuf_status[key].set("✗ Erreur")
                    self.after(0, _err)

            def _done():
                self._setup_busy = False
                self._pcneuf_bar.stop()
                self._pcneuf_bar.pack_forget()
                self._pcneuf_log_append("\n✓ Traitement terminé.", GREEN)
            self.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _pcneuf_add_icons(self):
        if self._setup_busy:
            return
        self._setup_busy = True
        self._pcneuf_log_append("\nAjout des icônes du bureau…")

        def _worker():
            try:
                data  = run_ps_action("collectors/desktop_icons.ps1", ["-Action", "enable"])
                ok    = data.get("success", False)
                icons = data.get("icons") or []

                def _result():
                    if ok:
                        for ic in icons:
                            name  = ic.get("name", "")
                            if ic.get("added"):
                                self._pcneuf_log_append(f"  ✓ {name} — ajouté", GREEN)
                            else:
                                self._pcneuf_log_append(f"  ✓ {name} — déjà présent", FG_MUTED)
                        self._pcneuf_log_append("✓ Icônes du bureau affichées.", GREEN)
                    else:
                        err = data.get("error") or "Erreur inconnue"
                        self._pcneuf_log_append(f"  ✗ {err}", RED)
                self.after(0, _result)
            except Exception as exc:
                def _err(e=exc):
                    self._pcneuf_log_append(f"  ✗ {e}", RED)
                self.after(0, _err)
            finally:
                self.after(0, lambda: setattr(self, "_setup_busy", False))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Panneau Récupération ──────────────────────────────────────────────────
    def _build_recuperation_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, style="PD.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        cw = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(cw, width=e.width))

        # ── Titre ─────────────────────────────────────────────────────────────
        sec = tk.Frame(inner, bg=BG, pady=16)
        sec.pack(fill="x", padx=28)
        tk.Label(sec, text="Cle de restauration Windows",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec,
                 text="Cree une cle USB bootable permettant de reparer ou reinstaller Windows,",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 0))
        tk.Label(sec,
                 text="meme si Windows ne demarre plus. Utilise l'outil officiel Microsoft.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w")

        # ── Statut WinRE ──────────────────────────────────────────────────────
        winre_bar = tk.Frame(inner, bg=SURFACE, padx=14, pady=10)
        winre_bar.pack(fill="x", padx=28, pady=(0, 8))
        tk.Label(winre_bar, text="WinRE",
                 font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG_DIM).pack(side="left")
        self._winre_status_var = tk.StringVar(value="Vérification…")
        self._winre_status_lbl = tk.Label(winre_bar, textvariable=self._winre_status_var,
                 font=("Segoe UI", 9), bg=SURFACE, fg=FG)
        self._winre_status_lbl.pack(side="left", padx=(8, 0))

        # ── Avertissement ─────────────────────────────────────────────────────
        warn = tk.Frame(inner, bg=YELLOW_BG, padx=16, pady=10)
        warn.pack(fill="x", padx=28, pady=(0, 8))
        tk.Label(warn,
                 text="Toutes les donnees de la cle USB selectionnee dans l'assistant seront effacees.",
                 font=("Segoe UI", 9, "bold"), bg=YELLOW_BG, fg=YELLOW).pack(anchor="w")
        tk.Label(warn,
                 text="Preparez une cle USB vierge d'au moins 16 Go avant de continuer.",
                 font=("Segoe UI", 9), bg=YELLOW_BG, fg=YELLOW).pack(anchor="w", pady=(2, 0))

        # ── Clés USB disponibles (info) ───────────────────────────────────────
        sec2 = tk.Frame(inner, bg=BG)
        sec2.pack(fill="x", padx=28, pady=(0, 8))
        tk.Label(sec2, text="Cles USB disponibles  (a titre indicatif)",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=FG).pack(anchor="w", pady=(0, 6))

        usb_row = tk.Frame(sec2, bg=BG)
        usb_row.pack(fill="x")

        lb_frame = tk.Frame(usb_row, bg=SURFACE, padx=2, pady=2)
        lb_frame.pack(side="left", fill="both", expand=True)
        self._recup_listbox = tk.Listbox(
            lb_frame, bg=SURFACE, fg=FG, selectbackground=ACCENT, selectforeground=BG,
            font=("Segoe UI", 10), height=4, activestyle="none", borderwidth=0,
            highlightthickness=0,
        )
        self._recup_listbox.pack(fill="both", expand=True)

        self._recup_refresh_btn = tk.Button(
            usb_row, text="Actualiser", font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
            activebackground=SURFACE2, activeforeground=FG, relief="flat",
            cursor="hand2", padx=10, pady=6,
            command=self._recup_refresh,
        )
        self._recup_refresh_btn.pack(side="left", padx=(6, 0), anchor="n")

        self._recup_disks = []

        # ── Bouton lancer l'assistant ─────────────────────────────────────────
        btn_row = tk.Frame(inner, bg=BG)
        btn_row.pack(fill="x", padx=28, pady=(4, 0))
        self._recup_btn = tk.Button(
            btn_row,
            text="Lancer l'assistant de creation",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg=BG, activebackground=ACCENT_HOVER, activeforeground=BG,
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=self._recup_launch,
        )
        self._recup_btn.pack(side="left")
        tk.Label(btn_row,
                 text="  L'assistant Windows s'ouvrira — branchez d'abord votre cle USB.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_DIM).pack(side="left")

        # ── Barre de progression ──────────────────────────────────────────────
        self._recup_bar = ttk.Progressbar(inner, mode="indeterminate", length=200)

        # ── Log ───────────────────────────────────────────────────────────────
        log_wrap = tk.Frame(inner, bg=SURFACE)
        log_wrap.pack(fill="both", expand=True, padx=28, pady=(12, 16))
        self._recup_log = tk.Text(
            log_wrap, bg=SURFACE, fg=FG_MUTED,
            font=("Consolas", 9), wrap="word", state="disabled",
            relief="flat", borderwidth=0, height=14,
        )
        log_sb = ttk.Scrollbar(log_wrap, command=self._recup_log.yview, style="PD.Vertical.TScrollbar")
        self._recup_log.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self._recup_log.pack(fill="both", expand=True)

        self._recup_busy = False
        self._recup_refresh()
        self.after(400, self._recup_check_winre)

        # ── Section BitLocker ─────────────────────────────────────────────────
        tk.Frame(inner, bg=SURFACE2, height=1).pack(fill="x", padx=28, pady=20)

        sec_bl = tk.Frame(inner, bg=BG)
        sec_bl.pack(fill="x", padx=28)
        tk.Label(sec_bl, text="Cles de recuperation BitLocker",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(anchor="w")
        tk.Label(sec_bl,
                 text="Windows peut activer BitLocker automatiquement, meme sans compte Microsoft.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 0))
        tk.Label(sec_bl,
                 text="Sans sauvegarde des cles, les donnees sont inaccessibles en cas de panne.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w")

        bl_row = tk.Frame(inner, bg=BG)
        bl_row.pack(fill="x", padx=28, pady=(10, 0))
        tk.Button(
            bl_row, text="Afficher les cles",
            font=("Segoe UI", 9, "bold"), bg=SURFACE, fg=FG,
            activebackground=SURFACE2, activeforeground=FG,
            relief="flat", cursor="hand2", padx=12, pady=7,
            command=self._bl_show,
        ).pack(side="left", padx=(0, 8))
        tk.Button(
            bl_row, text="Exporter dans un fichier...",
            font=("Segoe UI", 9), bg=SURFACE, fg=FG_DIM,
            activebackground=SURFACE2, activeforeground=FG,
            relief="flat", cursor="hand2", padx=12, pady=7,
            command=self._bl_export,
        ).pack(side="left")

        bl_wrap = tk.Frame(inner, bg=SURFACE)
        bl_wrap.pack(fill="both", expand=True, padx=28, pady=(10, 24))
        self._bl_log = tk.Text(
            bl_wrap, bg=SURFACE, fg=FG_MUTED,
            font=("Consolas", 9), wrap="word", state="disabled",
            relief="flat", borderwidth=0, height=10,
        )
        bl_sb = ttk.Scrollbar(bl_wrap, command=self._bl_log.yview, style="PD.Vertical.TScrollbar")
        self._bl_log.configure(yscrollcommand=bl_sb.set)
        bl_sb.pack(side="right", fill="y")
        self._bl_log.pack(fill="both", expand=True)

    def _bl_log_append(self, msg: str, fg: str = None):
        self._bl_log.configure(state="normal")
        self._bl_log.insert("end", msg + "\n")
        if fg:
            tag = f"bl_{fg.strip('#')}"
            start = self._bl_log.index("end-2l")
            end   = self._bl_log.index("end-1c")
            self._bl_log.tag_config(tag, foreground=fg)
            self._bl_log.tag_add(tag, start, end)
        self._bl_log.see("end")
        self._bl_log.configure(state="disabled")

    def _bl_log_clear(self):
        self._bl_log.configure(state="normal")
        self._bl_log.delete("1.0", "end")
        self._bl_log.configure(state="disabled")

    def _bl_show(self):
        self._bl_log_clear()
        self._bl_log_append("Lecture des volumes BitLocker...")

        def _worker():
            try:
                data    = run_ps_action("collectors/bitlocker_manager.ps1", ["-Action", "list"], timeout=20)
                volumes = data.get("volumes", [])

                def _update():
                    self._bl_log_clear()
                    if not volumes:
                        self._bl_log_append("Aucun volume BitLocker detecte sur cette machine.", FG_DIM)
                        return
                    has_keys = False
                    for v in volumes:
                        keys = v.get("recovery_keys", [])
                        if not keys:
                            continue
                        has_keys = True
                        self._bl_log_append(
                            f"Volume : {v.get('mount_point')}  |  "
                            f"{v.get('protection_status')}  |  "
                            f"{v.get('encryption_method')}  {v.get('encryption_pct')}%",
                            ACCENT,
                        )
                        for k in keys:
                            self._bl_log_append(f"  ID  : {k.get('id')}", FG_DIM)
                            self._bl_log_append(f"  Cle : {k.get('password')}", FG)
                        self._bl_log_append("")
                    if not has_keys:
                        self._bl_log_append(
                            "Aucune cle de recuperation trouvee.\n"
                            "BitLocker est peut-etre desactive ou sans cle de recuperation configuree.",
                            YELLOW,
                        )
                self.after(0, _update)
            except Exception as exc:
                self.after(0, lambda e=exc: self._bl_log_append(f"Erreur : {e}", RED))

        threading.Thread(target=_worker, daemon=True).start()

    def _bl_export(self):
        from tkinter import filedialog
        import datetime
        default = f"BitLocker_{os.environ.get('COMPUTERNAME', 'PC')}_{datetime.date.today():%Y%m%d}.txt"
        path = filedialog.asksaveasfilename(
            title="Enregistrer les cles BitLocker",
            defaultextension=".txt",
            filetypes=[("Fichier texte", "*.txt"), ("Tous les fichiers", "*.*")],
            initialfile=default,
        )
        if not path:
            return

        self._bl_log_clear()
        self._bl_log_append("Export des cles BitLocker en cours...")

        def _worker():
            try:
                data = run_ps_action(
                    "collectors/bitlocker_manager.ps1",
                    ["-Action", "export", "-FilePath", path],
                    timeout=20,
                )
                def _done():
                    self._bl_log_clear()
                    if data.get("success"):
                        n = data.get("volumes_count", 0)
                        self._bl_log_append(
                            f"Fichier enregistre : {data.get('file_path')}", GREEN)
                        self._bl_log_append(
                            f"{n} volume(s) avec cle(s) exporte(s).",
                            GREEN if n > 0 else YELLOW)
                    else:
                        self._bl_log_append(f"Erreur : {data.get('error')}", RED)
                self.after(0, _done)
            except Exception as exc:
                self.after(0, lambda e=exc: self._bl_log_append(f"Erreur : {e}", RED))

        threading.Thread(target=_worker, daemon=True).start()

    def _recup_log_append(self, msg: str, fg: str = None):
        self._recup_log.configure(state="normal")
        self._recup_log.insert("end", msg + "\n")
        if fg:
            tag = f"c_{fg.strip('#')}"
            start = self._recup_log.index("end-2l")
            end   = self._recup_log.index("end-1c")
            self._recup_log.tag_config(tag, foreground=fg)
            self._recup_log.tag_add(tag, start, end)
        self._recup_log.see("end")
        self._recup_log.configure(state="disabled")

    def _recup_log_clear(self):
        self._recup_log.configure(state="normal")
        self._recup_log.delete("1.0", "end")
        self._recup_log.configure(state="disabled")

    def _recup_refresh(self):
        if self._recup_busy:
            return
        self._recup_listbox.delete(0, "end")
        self._recup_listbox.insert("end", "  Recherche des cles USB...")
        self._recup_disks = []

        def _worker():
            try:
                data  = run_ps_action("collectors/recovery_drive.ps1", ["-Action", "list-usb"])
                disks = data.get("disks", [])
                def _update():
                    self._recup_listbox.delete(0, "end")
                    self._recup_disks = disks
                    if not disks:
                        self._recup_listbox.insert("end", "  Aucune cle USB detectee")
                        return
                    for d in disks:
                        label = f"  Disque {d.get('disk_number')}  --  {d.get('size_gb')} Go  --  {d.get('model', 'Inconnu')}"
                        if not d.get("enough"):
                            label += "  (< 16 Go — insuffisant)"
                        self._recup_listbox.insert("end", label)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._recup_listbox.delete(0, "end")
                    self._recup_listbox.insert("end", f"  Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _recup_check_winre(self):
        self._winre_status_var.set("Vérification…")
        self._winre_status_lbl.configure(fg=FG)
        def _worker():
            try:
                data = run_ps_action("collectors/recovery_drive.ps1", ["-Action", "check-winre"])
                def _update():
                    if not data.get("recovery_exe_ok"):
                        self._winre_status_var.set("RecoveryDrive.exe absent (Windows LTSC/Server non supporté)")
                        self._winre_status_lbl.configure(fg=RED)
                        self._recup_btn.configure(state="disabled")
                        return
                    if data.get("winre_enabled"):
                        path = data.get("winre_path") or "actif"
                        self._winre_status_var.set(f"✓ Actif — {path}")
                        self._winre_status_lbl.configure(fg=GREEN)
                    else:
                        self._winre_status_var.set("⚠ WinRE désactivé — exécutez : reagentc /enable")
                        self._winre_status_lbl.configure(fg=YELLOW)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._winre_status_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _recup_launch(self):
        if self._recup_busy:
            return
        self._recup_busy = True
        self._recup_btn.configure(state="disabled")
        self._recup_log_clear()
        self._recup_log_append("Lancement de l'assistant de création de clé de restauration Windows…")
        self._recup_bar.pack(fill="x", padx=28, pady=(6, 0),
                             before=self._recup_log.master)
        self._recup_bar.start(10)

        def _worker():
            try:
                data = run_ps_action("collectors/recovery_drive.ps1",
                                     ["-Action", "launch-native"], timeout=15)
                def _done():
                    self._recup_busy = False
                    self._recup_btn.configure(state="normal")
                    self._recup_bar.stop()
                    self._recup_bar.pack_forget()
                    if data.get("success"):
                        self._recup_log_append("✓ Assistant ouvert.", GREEN)
                        self._recup_log_append("")
                        self._recup_log_append("Suivez les étapes dans l'assistant Windows :")
                        self._recup_log_append("  1. Cochez « Sauvegarder les fichiers système » si vous souhaitez")
                        self._recup_log_append("     une restauration complète (nécessite ~32 Go).")
                        self._recup_log_append("  2. Sélectionnez votre clé USB (≥ 16 Go) dans la liste.")
                        self._recup_log_append("  3. Confirmez — TOUTES les données de la clé seront effacées.")
                        self._recup_log_append("  4. Attendez la fin de la création (peut prendre 15-30 min).")
                    else:
                        self._recup_log_append(f"Erreur : {data.get('error', '?')}", RED)
                self.after(0, _done)
            except Exception as exc:
                def _err(e=exc):
                    self._recup_busy = False
                    self._recup_btn.configure(state="normal")
                    self._recup_bar.stop()
                    self._recup_bar.pack_forget()
                    self._recup_log_append(f"Erreur : {e}", RED)
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()


# ── Point d'entrée ────────────────────────────────────────────────────────────
# Indicateur interne : en version compilee (PyInstaller --onefile), sys.executable
# pointe vers Ghisdiag.exe lui-meme (pas un interpreteur Python). Le generateur de
# charge CPU (collectors/cpu_load.py) relance donc l'exe avec ce flag pour basculer
# en mode "worker" sans GUI, plutot que d'ouvrir une nouvelle fenetre de l'app.
_CPU_LOAD_WORKER_FLAG = "--ghisdiag-cpu-load-worker"


def main():
    # Windows : déclarer un AppUserModelID explicite pour que la barre des tâches
    # regroupe l'app sous sa propre identité et affiche SON icône — sans ça, lancé
    # depuis les sources, c'est l'icône de python.exe qui s'affiche.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ghisdiag.Diag.1")
    except Exception:
        pass
    if not is_admin() and "--no-uac" not in sys.argv:
        request_elevation()
    GhisdiagApp().mainloop()

if __name__ == "__main__":
    import multiprocessing as mp
    mp.freeze_support()
    if _CPU_LOAD_WORKER_FLAG in sys.argv:
        sys.argv.remove(_CPU_LOAD_WORKER_FLAG)
        mp.set_start_method("spawn", force=True)
        from collectors.cpu_load import main as _cpu_load_main
        _cpu_load_main()
        sys.exit(0)
    main()
