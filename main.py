"""
PlanetDiag - Interface graphique principale
"""

import os
import subprocess
import sys
import gc
import threading
import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from collectors.realtime_monitor import (
        get_cpu_percent, get_ram_percent, get_disk_io_percent, get_temperatures,
    )
    _HAS_MONITOR = True
except Exception:
    _HAS_MONITOR = False

from prefs    import LOG_DIR, load_prefs, save_prefs
from security import is_admin, request_elevation, is_safe_output_dir

# ── Logging (avec rotation pour éviter la croissance illimitée) ──────────────
_log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "planetdiag.log",
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

# ── Palette ───────────────────────────────────────────────────────────────────
BG        = "#1e1e2e"
SURFACE   = "#313244"
SURFACE2  = "#45475a"
FG        = "#cdd6f4"
FG_DIM    = "#9399b2"
FG_MUTED  = "#6c7086"
ACCENT    = "#89b4fa"
GREEN     = "#a6e3a1"
RED       = "#f38ba8"
YELLOW    = "#f9e2af"

TOTAL_MODULES  = len(COLLECTORS)
_LOG_MAX_LINES = 500


class PlanetDiagApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PlanetDiag")
        self.resizable(True, True)
        self.minsize(700, 580)
        self.configure(bg=BG)

        self._running    = False
        self._tick_id    = None
        self.report_path = None
        self.json_path   = None

        # Moniteur temps réel
        self._monitor_paused  = False
        self._monitor_tick_id = None
        self._temp_cache      = {"cpu": None, "gpu": None, "disks": []}
        self._temp_loading    = False
        self._temp_tick       = 0

        # Setup/MAJ state
        self._setup_busy = False

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

        # Spooler state
        self._spooler_busy     = False
        self._spooler_printers = []   # [{"name":…, "jobs":[…], …}]
        self._spooler_jobs     = []   # jobs de l'imprimante sélectionnée

        # Network state
        self._network_busy     = False
        self._network_adapters = []  # [{"name":…, "status":…, …}]

        # WiFi state
        self._wifi_busy     = False
        self._wifi_profiles = []  # [{"name":…}]
        self._wifi_networks = []  # [{"ssid":…, "signal":…, …}]

        self._build_ui()
        self._set_icon()
        self.update_idletasks()
        self.geometry("740x640")
        x = (self.winfo_screenwidth()  - 740) // 2
        y = (self.winfo_screenheight() - 640) // 2
        self.geometry(f"740x640+{x}+{y}")

    def _set_icon(self):
        try:
            ico = Path(__file__).parent / "assets" / "icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

    # ── UI principale ─────────────────────────────────────────────────────────
    def _build_ui(self):
        # En-tête commun (hors onglets)
        hdr = tk.Frame(self, bg=BG, pady=14)
        hdr.pack(fill="x")

        tk.Label(hdr, text="PlanetDiag", font=("Segoe UI", 24, "bold"),
                 bg=BG, fg=ACCENT).pack()
        tk.Label(hdr, text="Outil de diagnostic Windows",
                 font=("Segoe UI", 11), bg=BG, fg=FG).pack(pady=(2, 0))
        tk.Label(hdr, text=f"Version {VERSION}  •  Droits administrateur requis",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(pady=(2, 0))
        tk.Label(hdr, text=f"Développé par {AUTHORS}",
                 font=("Segoe UI", 9, "italic"), bg=BG, fg=FG_MUTED).pack(pady=(1, 0))

        ttk.Separator(self).pack(fill="x", padx=20, pady=(6, 0))

        # Style des onglets
        style = ttk.Style()
        style.theme_use("default")
        style.configure("PD.TNotebook",
                        background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("PD.TNotebook.Tab",
                        background=SURFACE, foreground=FG_DIM,
                        font=("Segoe UI", 10),
                        padding=[18, 8])
        style.map("PD.TNotebook.Tab",
                  background=[("selected", SURFACE2)],
                  foreground=[("selected", FG)])
        style.configure("PD.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=SURFACE,
                        bordercolor=SURFACE, lightcolor=ACCENT, darkcolor=ACCENT)

        # Notebook
        nb = ttk.Notebook(self, style="PD.TNotebook")
        nb.pack(fill="both", expand=True)

        analyse_frame = tk.Frame(nb, bg=BG)
        nb.add(analyse_frame, text="  Analyse  ")

        troubleshoot_frame = tk.Frame(nb, bg=BG)
        nb.add(troubleshoot_frame, text="  Dépannage  ")

        wifi_frame = tk.Frame(nb, bg=BG)
        nb.add(wifi_frame, text="  WiFi  ")

        setup_frame = tk.Frame(nb, bg=BG)
        nb.add(setup_frame, text="  Setup / MAJ  ")

        self._build_analyse_tab(analyse_frame)
        self._build_troubleshoot_tab(troubleshoot_frame)
        self._build_wifi_tab(wifi_frame)
        self._build_setup_tab(setup_frame)

        # Démarrage du moniteur et vérification SMART au lancement
        self.after(800, self._monitor_start)
        self.after(1200, lambda: threading.Thread(
            target=self._smart_startup_check, daemon=True).start())

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

        ttk.Separator(parent).pack(fill="x", padx=20, pady=(4, 0))

        # Bouton principal
        btn_zone = tk.Frame(parent, bg=BG, pady=14)
        btn_zone.pack(fill="x", padx=28)

        self.btn_start = tk.Button(
            btn_zone,
            text="▶   Lancer le diagnostic",
            font=("Segoe UI", 14, "bold"),
            bg=ACCENT, fg="#1e1e2e",
            activebackground="#74a8e8", activeforeground="#1e1e2e",
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

        ttk.Separator(parent).pack(fill="x", padx=20, pady=(10, 0))

        # ── Moniteur Temps Réel ───────────────────────────────────────────────
        mon_outer = tk.Frame(parent, bg=BG)
        mon_outer.pack(fill="x", padx=28, pady=(8, 0))

        mon_hdr_row = tk.Frame(mon_outer, bg=BG)
        mon_hdr_row.pack(fill="x")
        tk.Label(mon_hdr_row, text="Moniteur Temps Réel",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack(side="left")
        self._mon_status_var = tk.StringVar(value="")
        tk.Label(mon_hdr_row, textvariable=self._mon_status_var,
                 font=("Segoe UI", 8), bg=BG, fg=FG_MUTED).pack(side="right")

        mon_box = tk.Frame(mon_outer, bg=SURFACE, pady=8, padx=4)
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
                     font=("Segoe UI", 8, "bold"), bg=SURFACE, fg=FG_DIM).pack(side="left")
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
                 font=("Segoe UI", 8, "bold"), bg=SURFACE, fg=FG_DIM).pack(anchor="w")
        self._mon_temp_cpu_var  = tk.StringVar(value="CPU : —")
        self._mon_temp_gpu_var  = tk.StringVar(value="GPU : —")
        self._mon_temp_disk_var = tk.StringVar(value="SSD/HDD : —")
        for var in (self._mon_temp_cpu_var, self._mon_temp_gpu_var, self._mon_temp_disk_var):
            tk.Label(temp_col, textvariable=var,
                     font=("Segoe UI", 8), bg=SURFACE, fg=FG_MUTED).pack(anchor="w")

        ttk.Separator(parent).pack(fill="x", padx=20, pady=(0, 0))

        # Journal d'activité
        log_hdr = tk.Frame(parent, bg=BG)
        log_hdr.pack(fill="x", padx=28, pady=(8, 4))
        tk.Label(log_hdr, text="Journal d'activité",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=FG_DIM).pack(side="left")
        tk.Button(
            log_hdr, text="Effacer",
            font=("Segoe UI", 8), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=8, pady=2, command=self._clear_log,
        ).pack(side="right")
        tk.Button(
            log_hdr, text="Voir le fichier log",
            font=("Segoe UI", 8), bg=SURFACE, fg=FG_MUTED,
            activebackground=SURFACE2, relief="flat", cursor="hand2",
            padx=8, pady=2, command=self._open_log_file,
        ).pack(side="right", padx=(0, 6))

        log_wrap = tk.Frame(parent, bg=SURFACE, bd=0)
        log_wrap.pack(fill="both", expand=True, padx=28, pady=(0, 6))

        self.log = tk.Text(
            log_wrap,
            bg=SURFACE, fg=FG_DIM,
            font=("Consolas", 10),
            bd=0, padx=10, pady=10,
            state="disabled", wrap="word",
            selectbackground=SURFACE2,
        )
        sb = tk.Scrollbar(log_wrap, command=self.log.yview, bg=SURFACE2)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True)

        self.log.tag_config("ok",   foreground=GREEN)
        self.log.tag_config("warn", foreground=YELLOW)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("info", foreground=ACCENT)
        self.log.tag_config("dim",  foreground=FG_MUTED)
        self.log.tag_config("time", foreground="#7480c2")

        # Boutons bas
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

    # ── Onglet Dépannage ──────────────────────────────────────────────────────
    def _build_troubleshoot_tab(self, parent: tk.Frame):
        # Conteneur scrollable
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview, bg=SURFACE2)
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

        self._build_spooler_section(inner)
        ttk.Separator(inner).pack(fill="x", padx=20, pady=(0, 4))
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
            font=("Segoe UI", 10), bg=RED, fg="#1e1e2e",
            activebackground="#e07070", relief="flat", cursor="hand2",
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
            selectbackground=ACCENT, selectforeground="#1e1e2e",
            relief="flat", bd=0, activestyle="none", height=5,
        )
        pr_sb = tk.Scrollbar(printer_wrap, command=self.printer_listbox.yview, bg=SURFACE2)
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
            selectbackground=ACCENT, selectforeground="#1e1e2e",
            relief="flat", bd=0, activestyle="none", height=5,
        )
        job_sb = tk.Scrollbar(job_wrap, command=self.job_listbox.yview, bg=SURFACE2)
        self.job_listbox.configure(yscrollcommand=job_sb.set)
        job_sb.pack(side="right", fill="y")
        self.job_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.job_listbox.bind("<<ListboxSelect>>", self._spooler_on_job_select)

        # ── Boutons d'action sur les travaux ──────────────────────────────────
        job_btns = tk.Frame(section, bg=BG)
        job_btns.pack(fill="x", pady=(8, 0))

        self.btn_cancel_job = tk.Button(
            job_btns, text="✗  Annuler ce travail",
            font=("Segoe UI", 10), bg=YELLOW, fg="#1e1e2e",
            activebackground="#d4be82", relief="flat", cursor="hand2",
            padx=12, pady=6, state="disabled", command=self._spooler_cancel_job,
        )
        self.btn_cancel_job.pack(side="left", padx=(0, 6))

        self.btn_cancel_all = tk.Button(
            job_btns, text="✗  Annuler tous les travaux",
            font=("Segoe UI", 10), bg=YELLOW, fg="#1e1e2e",
            activebackground="#d4be82", relief="flat", cursor="hand2",
            padx=12, pady=6, state="disabled", command=self._spooler_cancel_all,
        )
        self.btn_cancel_all.pack(side="left")

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
            selectbackground=ACCENT, selectforeground="#1e1e2e",
            relief="flat", bd=0,
            activestyle="none",
            height=7,
        )
        lb_scroll = tk.Scrollbar(list_frame, command=self.network_listbox.yview, bg=SURFACE2)
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
                     font=("Segoe UI", 8), bg=SURFACE2, fg=FG_DIM,
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
            font=("Segoe UI", 10), bg=YELLOW, fg="#1e1e2e",
            activebackground="#d4be82", relief="flat", cursor="hand2",
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

    # ── Onglet WiFi ───────────────────────────────────────────────────────────
    def _build_wifi_tab(self, parent: tk.Frame):
        # Canvas scrollable (même pattern que _build_troubleshoot_tab)
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview, bg=SURFACE2)
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
            selectbackground=ACCENT, selectforeground="#1e1e2e",
            relief="flat", bd=0, activestyle="none", height=6,
        )
        wifi_sb = tk.Scrollbar(profiles_wrap, command=self.wifi_listbox.yview, bg=SURFACE2)
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
            font=("Segoe UI", 10), bg=RED, fg="#1e1e2e",
            activebackground="#e07070", relief="flat", cursor="hand2",
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
        ttk.Separator(inner).pack(fill="x", padx=20, pady=(0, 4))

        # ── Section Réseaux disponibles ───────────────────────────────────────
        sec_n = tk.Frame(inner, bg=BG, pady=16)
        sec_n.pack(fill="x", padx=28)

        scan_hdr = tk.Frame(sec_n, bg=BG)
        scan_hdr.pack(fill="x", pady=(0, 2))

        tk.Label(scan_hdr, text="Réseaux disponibles",
                 font=("Segoe UI", 13, "bold"), bg=BG, fg=FG).pack(side="left")

        self.btn_wifi_scan = tk.Button(
            scan_hdr, text="🔍  Scanner",
            font=("Segoe UI", 10), bg=ACCENT, fg="#1e1e2e",
            activebackground="#74a8e8", relief="flat", cursor="hand2",
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
            selectbackground=ACCENT, selectforeground="#1e1e2e",
            relief="flat", bd=0, activestyle="none", height=6,
        )
        net_sb = tk.Scrollbar(networks_wrap, command=self.wifi_networks_listbox.yview, bg=SURFACE2)
        self.wifi_networks_listbox.configure(yscrollcommand=net_sb.set)
        net_sb.pack(side="right", fill="y")
        self.wifi_networks_listbox.pack(fill="both", expand=True, padx=4, pady=4)
        self.wifi_networks_listbox.bind("<<ListboxSelect>>", self._wifi_on_network_select)

        self.btn_wifi_connect = tk.Button(
            sec_n, text="🔗  Connecter au réseau sélectionné",
            font=("Segoe UI", 10, "bold"), bg=GREEN, fg="#1e1e2e",
            activebackground="#80c87e", relief="flat", cursor="hand2",
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
            font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#1e1e2e",
            activebackground="#74a8e8", relief="flat", cursor="hand2",
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
        log_path = LOG_DIR / "planetdiag.log"
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
                    bg=ACCENT, fg="#1e1e2e",
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
                    bg=ACCENT, fg="#1e1e2e",
                )
                self._log(f"ERREUR : {exc}", "err")
            self.after(0, _err)

    def _on_auto_open_changed(self, *_):
        prefs = load_prefs()
        prefs["auto_open_browser"] = self.auto_open_var.get()
        save_prefs(prefs)

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
    def _monitor_start(self):
        self._monitor_paused = False
        self._monitor_tick()

    def _monitor_pause(self):
        self._monitor_paused = True
        if self._monitor_tick_id is not None:
            self.after_cancel(self._monitor_tick_id)
            self._monitor_tick_id = None
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

        # Températures : mise à jour depuis le cache, fetch toutes les 10s
        self._temp_tick += 1
        if self._temp_tick >= 5 and not self._temp_loading:
            self._temp_tick = 0
            self._temp_loading = True
            threading.Thread(target=self._monitor_fetch_temps, daemon=True).start()

        t = self._temp_cache
        cpu_t  = t.get("cpu")
        gpu_t  = t.get("gpu")
        disks_t = t.get("disks") or []

        self._mon_temp_cpu_var.set(f"CPU : {cpu_t}°C" if cpu_t is not None else "CPU : N/A")
        self._mon_temp_gpu_var.set(f"GPU : {gpu_t}°C" if gpu_t is not None else "GPU : N/A")
        if disks_t:
            parts = [f"{d.get('model','?')[:12]} : {d.get('temp','?')}°C"
                     for d in disks_t[:2] if isinstance(d, dict)]
            self._mon_temp_disk_var.set("  ".join(parts) if parts else "SSD/HDD : N/A")
        else:
            self._mon_temp_disk_var.set("SSD/HDD : N/A")

        self._monitor_tick_id = self.after(2000, self._monitor_tick)

    def _monitor_fetch_temps(self):
        try:
            if _HAS_MONITOR:
                self._temp_cache = get_temperatures()
        except Exception as exc:
            logger.debug("Fetch températures : %s", exc)
        finally:
            self._temp_loading = False

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
                 bg=admin_color, fg="#1e1e2e").pack()

        # Sous-onglets
        style = ttk.Style()
        style.configure("Setup.TNotebook",
                        background=BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("Setup.TNotebook.Tab",
                        background=SURFACE, foreground=FG_DIM,
                        font=("Segoe UI", 10), padding=[16, 7])
        style.map("Setup.TNotebook.Tab",
                  background=[("selected", SURFACE2)],
                  foreground=[("selected", FG)])

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
        sb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview, bg=SURFACE2)
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
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#1e1e2e",
                  activebackground="#74a8e8", relief="flat", cursor="hand2",
                  padx=16, pady=8, command=self._comptes_create).pack(side="left")

        ttk.Separator(inner).pack(fill="x", padx=20, pady=(4, 4))

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
                                             font=("Segoe UI", 10), width=22, state="readonly")
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
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#1e1e2e",
                  activebackground="#74a8e8", relief="flat", cursor="hand2",
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
                    if users:
                        self._pwd_user_var.set(users[0])
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
        tk.Label(status_bar, textvariable=self._winget_status_var,
                 font=("Segoe UI", 9), bg=SURFACE, fg=FG).pack(side="left", padx=(8, 0))
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
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#1e1e2e",
                  activebackground="#74a8e8", relief="flat", cursor="hand2",
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
        maj_sb = tk.Scrollbar(self._maj_log_wrap, command=self._maj_log.yview, bg=SURFACE2)
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
        def _worker():
            try:
                data = run_ps_action("collectors/winget_manager.ps1", ["-Action", "check"])
                def _update():
                    if data.get("available"):
                        ver = data.get("version") or "?"
                        self._winget_status_var.set(f"v{ver}  ✓ Disponible")
                    else:
                        self._winget_status_var.set("Non installé — Windows 10 1809+ requis")
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._winget_status_var.set(f"Erreur : {e}")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _maj_update_winget(self):
        if self._setup_busy:
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
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="#1e1e2e",
                  activebackground="#74a8e8", relief="flat", cursor="hand2",
                  padx=14, pady=8, command=self._pcneuf_install).pack(side="left")

        # Barre de progression (cachée par défaut)
        self._pcneuf_bar = ttk.Progressbar(sec, mode="indeterminate")

        # Log
        log_wrap = tk.Frame(sec, bg=SURFACE)
        log_wrap.pack(fill="both", expand=True, pady=(12, 0))
        self._pcneuf_log = tk.Text(log_wrap, bg=SURFACE, fg=FG_DIM,
                                    font=("Consolas", 9), bd=0, padx=10, pady=8,
                                    state="disabled", wrap="word",
                                    selectbackground=SURFACE2)
        pcn_sb = tk.Scrollbar(log_wrap, command=self._pcneuf_log.yview, bg=SURFACE2)
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
        def _worker():
            try:
                data = run_ps_action("collectors/setup_apps.ps1", ["-Action", "check"])
                apps = data.get("apps") or {}
                def _update():
                    for key, info in apps.items():
                        if key in self._pcneuf_status:
                            installed = info.get("installed", False)
                            self._pcneuf_status[key].set("✓ Installé" if installed else "")
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    for var in self._pcneuf_status.values():
                        var.set("")
                self.after(0, _err)
        threading.Thread(target=_worker, daemon=True).start()

    def _pcneuf_install(self):
        if self._setup_busy:
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

    # ── Panneau Récupération ──────────────────────────────────────────────────
    def _build_recuperation_panel(self, parent: tk.Frame):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview, bg=SURFACE2)
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
                 text="Cree une cle USB bootable permettant de reparer ou reinstaller Windows.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w", pady=(2, 0))
        tk.Label(sec,
                 text="La cle sera utilisable meme si Windows ne demarre plus.",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(anchor="w")

        # ── Avertissement ─────────────────────────────────────────────────────
        warn = tk.Frame(inner, bg="#3d2e00", padx=16, pady=10)
        warn.pack(fill="x", padx=28, pady=(0, 8))
        tk.Label(warn,
                 text="Toutes les donnees de la cle selectionnee seront definitivement effacees.",
                 font=("Segoe UI", 9, "bold"), bg="#3d2e00", fg=YELLOW).pack(anchor="w")
        tk.Label(warn,
                 text="La mise en veille sera desactivee pendant toute la duree de l'operation.",
                 font=("Segoe UI", 9), bg="#3d2e00", fg=YELLOW).pack(anchor="w", pady=(2, 0))

        # ── Sélection de la clé USB ───────────────────────────────────────────
        sec2 = tk.Frame(inner, bg=BG)
        sec2.pack(fill="x", padx=28, pady=(0, 8))
        tk.Label(sec2, text="Selectionner la cle USB cible",
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

        # ── Bouton créer ──────────────────────────────────────────────────────
        btn_row = tk.Frame(inner, bg=BG)
        btn_row.pack(fill="x", padx=28, pady=(4, 0))
        self._recup_btn = tk.Button(
            btn_row,
            text="Creer la cle de restauration",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg=BG, activebackground="#6c9fd8", activeforeground=BG,
            relief="flat", cursor="hand2", padx=16, pady=8,
            command=self._recup_create,
        )
        self._recup_btn.pack(side="left")

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
        log_sb = tk.Scrollbar(log_wrap, command=self._recup_log.yview, bg=SURFACE2)
        self._recup_log.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self._recup_log.pack(fill="both", expand=True)

        self._recup_busy = False
        self._recup_refresh()

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
        bl_sb = tk.Scrollbar(bl_wrap, command=self._bl_log.yview, bg=SURFACE2)
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
                            label += "  (< 8 Go)"
                        self._recup_listbox.insert("end", label)
                self.after(0, _update)
            except Exception as exc:
                def _err(e=exc):
                    self._recup_listbox.delete(0, "end")
                    self._recup_listbox.insert("end", f"  Erreur : {e}")
                self.after(0, _err)

        threading.Thread(target=_worker, daemon=True).start()

    def _recup_create(self):
        if self._recup_busy:
            return
        sel = self._recup_listbox.curselection()
        if not sel:
            messagebox.showwarning("Selection requise", "Selectionnez une cle USB dans la liste.")
            return
        idx  = sel[0]
        disk = self._recup_disks[idx] if idx < len(self._recup_disks) else None
        if not disk:
            return
        if not disk.get("enough"):
            messagebox.showerror(
                "Capacite insuffisante",
                f"La cle selectionnee ({disk.get('size_gb')} Go) est trop petite.\n"
                "8 Go minimum sont necessaires.",
            )
            return

        model    = disk.get("model", "Inconnu")
        size_gb  = disk.get("size_gb")
        disk_num = str(disk.get("disk_number"))

        if not messagebox.askyesno(
            "Confirmer la creation",
            f"Creer une cle de restauration sur :\n\n"
            f"  Disque {disk_num}  --  {size_gb} Go  --  {model}\n\n"
            "TOUTES LES DONNEES DE CETTE CLE SERONT EFFACEES.\n\n"
            "La mise en veille sera desactivee pendant l'operation.\n"
            "Continuer ?",
        ):
            return

        self._recup_busy = True
        self._recup_btn.configure(state="disabled")
        self._recup_log_clear()
        self._recup_log_append(f"Creation de la cle de restauration -- Disque {disk_num} ({size_gb} Go)")
        self._recup_log_append("-" * 55)
        self._recup_bar.pack(fill="x", padx=28, pady=(6, 0),
                             before=self._recup_log.master)
        self._recup_bar.start(10)

        def _on_line(line: str):
            if line.startswith("SUCCESS:"):
                self.after(0, lambda l=line[8:].strip(): self._recup_log_append(l, GREEN))
            elif line.startswith("ERREUR:"):
                self.after(0, lambda l=line[7:].strip(): self._recup_log_append(l, RED))
            else:
                self.after(0, lambda l=line: self._recup_log_append(l))

        def _worker():
            try:
                rc = run_ps_stream(
                    "collectors/recovery_drive.ps1",
                    ["-Action", "create", "-DiskNumber", disk_num],
                    _on_line, timeout=600,
                )
                def _done():
                    self._recup_busy = False
                    self._recup_btn.configure(state="normal")
                    self._recup_bar.stop()
                    self._recup_bar.pack_forget()
                    self._recup_log_append("-" * 55)
                    if rc == 0:
                        self._recup_log_append("Operation terminee avec succes.", GREEN)
                    else:
                        self._recup_log_append(
                            f"Operation echouee (code {rc}). Verifiez le log ci-dessus.", RED)
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
def main():
    if not is_admin() and "--no-uac" not in sys.argv:
        request_elevation()
    PlanetDiagApp().mainloop()

if __name__ == "__main__":
    main()
