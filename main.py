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

from orchestrator import DiagnosticOrchestrator, VERSION, AUTHORS, COLLECTORS
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

_PREFS_MAX_BYTES = 16 * 1024   # prefs.json ne devrait jamais dépasser 16 Ko

def _load_prefs() -> dict:
    """Charge prefs.json avec validation de type et limite de taille."""
    try:
        if PREFS_FILE.stat().st_size > _PREFS_MAX_BYTES:
            logger.warning("prefs.json dépasse %d octets, ignoré", _PREFS_MAX_BYTES)
            return {}
        raw = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        # Ne garde que les clés de type attendu (liste blanche)
        out = {}
        val = raw.get("output_dir")
        if isinstance(val, str) and len(val) < 4096:
            out["output_dir"] = val
        return out
    except (OSError, ValueError):
        return {}

def _save_prefs(prefs: dict):
    """Sauvegarde atomique des préférences."""
    try:
        tmp = PREFS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(PREFS_FILE)
    except OSError as e:
        logger.warning("Impossible de sauvegarder prefs : %s", e)


# Dossiers système où il est dangereux d'écrire des rapports
_FORBIDDEN_OUTPUT_ROOTS = [
    Path(os.environ.get("SystemRoot", r"C:\Windows")).resolve(),
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")).resolve(),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
]

def _is_safe_output_dir(path: Path) -> tuple[bool, str]:
    """Vérifie que le dossier de sortie n'est pas un chemin système."""
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


class PlanetDiagApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PlanetDiag")
        self.resizable(True, True)
        self.minsize(640, 560)
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

        self._build_ui()
        self._set_icon()
        self.update_idletasks()
        self.geometry("700x600")
        x = (self.winfo_screenwidth()  - 700) // 2
        y = (self.winfo_screenheight() - 600) // 2
        self.geometry(f"700x600+{x}+{y}")

    def _set_icon(self):
        try:
            ico = Path(__file__).parent / "assets" / "icon.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── En-tête ──────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG, pady=18)
        hdr.pack(fill="x", padx=0)

        tk.Label(hdr, text="PlanetDiag", font=("Segoe UI", 26, "bold"),
                 bg=BG, fg=ACCENT).pack()
        tk.Label(hdr, text="Outil de diagnostic Windows",
                 font=("Segoe UI", 12), bg=BG, fg=FG).pack(pady=(2, 0))
        tk.Label(hdr, text=f"Version {VERSION}  •  Droits administrateur requis",
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED).pack(pady=(2, 0))
        tk.Label(hdr, text=f"Développé par {AUTHORS}",
                 font=("Segoe UI", 9, "italic"), bg=BG, fg=FG_MUTED).pack(pady=(1, 0))

        ttk.Separator(self).pack(fill="x", padx=20, pady=(4, 0))

        # ── Dossier de destination ────────────────────────────────────────────
        dest = tk.Frame(self, bg=BG, pady=12)
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

        ttk.Separator(self).pack(fill="x", padx=20, pady=(8, 0))

        # ── Bouton principal ──────────────────────────────────────────────────
        btn_zone = tk.Frame(self, bg=BG, pady=16)
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

        # ── Zone de progression ───────────────────────────────────────────────
        prog_zone = tk.Frame(self, bg=BG, pady=0)
        prog_zone.pack(fill="x", padx=28)

        # Étape actuelle
        self.step_var = tk.StringVar(value="En attente…")
        self.step_lbl = tk.Label(
            prog_zone, textvariable=self.step_var,
            font=("Segoe UI", 11), bg=BG, fg=FG, anchor="w",
        )
        self.step_lbl.pack(fill="x", pady=(0, 6))

        # Barre de progression
        style = ttk.Style()
        style.theme_use("default")
        style.configure("PD.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=SURFACE,
                        bordercolor=SURFACE, lightcolor=ACCENT, darkcolor=ACCENT)
        self.pbar = ttk.Progressbar(
            prog_zone, style="PD.Horizontal.TProgressbar",
            mode="determinate", maximum=TOTAL_MODULES,
        )
        self.pbar.pack(fill="x", ipady=4, pady=(0, 4))

        # Compteur modules  +  durée
        counter_row = tk.Frame(prog_zone, bg=BG)
        counter_row.pack(fill="x")
        self.counter_var = tk.StringVar(value="")
        tk.Label(counter_row, textvariable=self.counter_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, anchor="w").pack(side="left")
        self.elapsed_var = tk.StringVar(value="")
        tk.Label(counter_row, textvariable=self.elapsed_var,
                 font=("Segoe UI", 9), bg=BG, fg=FG_MUTED, anchor="e").pack(side="right")

        ttk.Separator(self).pack(fill="x", padx=20, pady=(12, 0))

        # ── Journal d'activité ────────────────────────────────────────────────
        log_hdr = tk.Frame(self, bg=BG)
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

        log_wrap = tk.Frame(self, bg=SURFACE, bd=0)
        log_wrap.pack(fill="both", expand=True, padx=28, pady=(0, 8))

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

        # Tags couleur dans le log
        self.log.tag_config("ok",   foreground=GREEN)
        self.log.tag_config("warn", foreground=YELLOW)
        self.log.tag_config("err",  foreground=RED)
        self.log.tag_config("info", foreground=ACCENT)
        self.log.tag_config("dim",  foreground=FG_MUTED)
        self.log.tag_config("time", foreground="#7480c2")

        # ── Boutons bas ───────────────────────────────────────────────────────
        foot = tk.Frame(self, bg=BG, pady=10)
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

    # ── Helpers log ───────────────────────────────────────────────────────────
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

    # ── Actions ───────────────────────────────────────────────────────────────
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

            # Libère la mémoire : les dicts volumineux ne sont plus utiles
            # (tout est déjà écrit sur disque)
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
                self.result_lbl.configure(
                    text=f"✔  Rapport prêt", fg=GREEN,
                )

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
        """Ouvre le rapport HTML avec l'application par défaut."""
        if not (self.report_path and self.report_path.exists()):
            messagebox.showerror("Erreur", "Fichier rapport introuvable.")
            return
        try:
            os.startfile(str(self.report_path.resolve()))
        except OSError as e:
            logger.warning("Impossible d'ouvrir le rapport : %s", e)
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le rapport : {e}")

    def _open_folder(self):
        """Ouvre l'Explorateur avec le rapport sélectionné (args en liste — pas de shell)."""
        if not self.report_path or not self.report_path.exists():
            messagebox.showerror("Erreur", "Rapport introuvable.")
            return
        try:
            # Liste d'arguments → pas d'interprétation shell, pas d'injection possible
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
