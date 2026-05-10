"""
PlanetDiag - Interface graphique principale
"""

import ctypes
import sys
import os
import gc
import threading
import json
import logging
import logging.handlers
import subprocess
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ── UAC ───────────────────────────────────────────────────────────────────────
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def request_elevation():
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, ""
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    sys.exit(0)

# ── Logging (avec rotation pour éviter la croissance illimitée) ──────────────
LOG_DIR    = Path(os.path.expanduser("~")) / "AppData" / "Local" / "PlanetDiag"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PREFS_FILE = LOG_DIR / "prefs.json"

_log_handler = logging.handlers.RotatingFileHandler(
    LOG_DIR / "planetdiag.log",
    maxBytes=2 * 1024 * 1024,   # 2 Mo par fichier
    backupCount=3,
    encoding="utf-8",
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[_log_handler],
)
logger = logging.getLogger(__name__)

from orchestrator import DiagnosticOrchestrator, VERSION, AUTHORS, COLLECTORS, get_base_path, _PS_EXE, _validate_script_path
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

TOTAL_MODULES = len(COLLECTORS)

_PREFS_MAX_BYTES = 16 * 1024

def _load_prefs() -> dict:
    try:
        if PREFS_FILE.stat().st_size > _PREFS_MAX_BYTES:
            logger.warning("prefs.json dépasse %d octets, ignoré", _PREFS_MAX_BYTES)
            return {}
        raw = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out = {}
        val = raw.get("output_dir")
        if isinstance(val, str) and len(val) < 4096:
            out["output_dir"] = val
        return out
    except (OSError, ValueError):
        return {}

def _save_prefs(prefs: dict):
    try:
        tmp = PREFS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(PREFS_FILE)
    except OSError as e:
        logger.warning("Impossible de sauvegarder prefs : %s", e)


_FORBIDDEN_OUTPUT_ROOTS = [
    Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve(),
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
]

def _is_safe_output_dir(path: Path) -> tuple[bool, str]:
    try:
        resolved = path.resolve()
    except OSError as e:
        return False, f"Chemin invalide : {e}"

    for forbidden in _FORBIDDEN_OUTPUT_ROOTS:
        try:
            resolved.relative_to(forbidden)
            return False, f"Écriture interdite dans : {forbidden}"
        except ValueError:
            continue
    return True, ""


def _run_ps_action(script_rel: str, extra_args: list[str], timeout: int = 60) -> dict:
    """
    Exécute un script PowerShell de l'onglet Dépannage et retourne le JSON parsé.
    Utilise -Command + forçage UTF-8 (même pattern que l'orchestrateur) pour éviter
    les problèmes d'encodage CP850/OEM de PS 5.1 quand stdout est capturé.
    """
    base     = get_base_path()
    script_p = (base / script_rel).resolve()

    if not _validate_script_path(script_p, base):
        raise RuntimeError(f"Chemin de script invalide : {script_rel}")

    escaped_path = str(script_p).replace("'", "''")

    # Les flags (-Action, -AdapterName) sont passés tels quels ;
    # les valeurs sont single-quotées avec échappement des apostrophes internes.
    args_parts = []
    for arg in extra_args:
        if arg.startswith("-"):
            args_parts.append(arg)
        else:
            args_parts.append(f"'{arg.replace(chr(39), chr(39) * 2)}'")
    args_str = " ".join(args_parts)

    ps_cmd = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$OutputEncoding=[System.Text.Encoding]::UTF8; "
        f"& '{escaped_path}' {args_str}"
    )

    result = subprocess.run(
        [_PS_EXE, "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", ps_cmd],
        capture_output=True,
        timeout=timeout,
        shell=False,
    )

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(f"Pas de sortie du script. Stderr : {stderr}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON invalide : {e}\nSortie : {stdout[:300]}")


class PlanetDiagApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PlanetDiag")
        self.resizable(True, True)
        self.minsize(700, 580)
        self.configure(bg=BG)

        self._running    = False
        self.report_path = None
        self.json_path   = None

        prefs     = _load_prefs()
        saved_dir = prefs.get("output_dir", "")
        self.out_dir_var = tk.StringVar(
            value=saved_dir if saved_dir and Path(saved_dir).exists()
                  else str(DEFAULT_REPORTS_DIR)
        )

        # Spooler state
        self._spooler_busy     = False
        self._spooler_printers = []   # [{"name":…, "jobs":[…], …}]
        self._spooler_jobs     = []   # jobs de l'imprimante sélectionnée

        # Network state
        self._network_busy     = False
        self._network_adapters = []  # [{"name":…, "status":…, …}]

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

        self._build_analyse_tab(analyse_frame)
        self._build_troubleshoot_tab(troubleshoot_frame)

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
                data     = _run_ps_action("collectors/spooler_fix.ps1", ["-Action", "printers"])
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
                data = _run_ps_action(
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
                data    = _run_ps_action(
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
                data    = _run_ps_action("collectors/spooler_fix.ps1", ["-Action", "fix"], timeout=90)
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
        detail_frame.pack(side="left", fill="y", padx=(8, 0))
        detail_frame.pack_propagate(False)

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
                data     = _run_ps_action("collectors/network_cards.ps1", ["-Action", "list"])
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
                data    = _run_ps_action(
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

    # ── Helpers log Analyse ───────────────────────────────────────────────────
    def _log(self, msg: str, tag: str = ""):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
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
            _save_prefs({"output_dir": chosen})
            self._log(f"Dossier : {chosen}", "info")

    def _start(self):
        if self._running:
            return

        raw = self.out_dir_var.get().strip()
        if not raw:
            messagebox.showerror("Erreur", "Veuillez choisir un dossier de destination.")
            return

        out_dir = Path(raw)
        safe, reason = _is_safe_output_dir(out_dir)
        if not safe:
            messagebox.showerror("Dossier non autorisé", reason)
            return

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
            return
        elapsed = int((datetime.now() - self._start_time).total_seconds())
        m, s = divmod(elapsed, 60)
        self.elapsed_var.set(f"Durée : {m:02d}:{s:02d}")
        self.after(1000, self._tick_elapsed)

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

            self.after(0, _done)

        except Exception as exc:
            logger.exception("Erreur fatale")
            def _err():
                self._running = False
                self.step_var.set(f"Erreur : {exc}")
                self.btn_start.configure(
                    state="normal", text="▶   Réessayer",
                    bg=ACCENT, fg="#1e1e2e",
                )
                self._log(f"ERREUR : {exc}", "err")
            self.after(0, _err)

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


# ── Point d'entrée ────────────────────────────────────────────────────────────
def main():
    if not is_admin() and "--no-uac" not in sys.argv:
        request_elevation()
    PlanetDiagApp().mainloop()

if __name__ == "__main__":
    main()
