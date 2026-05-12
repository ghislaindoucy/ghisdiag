"""
PlanetDiag - Orchestrateur
Exécute les collecteurs PowerShell et agrège les données.
"""

import subprocess
import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

COLLECTORS = [
    ("system_info",  "Système & Matériel",  "collectors/system_info.ps1"),
    ("performance",  "Performance",          "collectors/performance.ps1"),
    ("startup",      "Démarrage Windows",    "collectors/startup.ps1"),
    ("events",       "Événements Windows",   "collectors/events.ps1"),
    ("network",      "Réseau",               "collectors/network.ps1"),
    ("security",     "Sécurité",             "collectors/security.ps1"),
    ("software",     "Logiciels & Drivers",  "collectors/software.ps1"),
]

VERSION = "1.1.0"
AUTHORS = "Ghislain DOUCY & Claude Code"

# Limite de taille de sortie d'un collecteur PowerShell (protection mémoire/DoS)
MAX_STDOUT_BYTES = 40 * 1024 * 1024   # 40 Mo
DEFAULT_TIMEOUT  = 120


def get_base_path() -> Path:
    """Répertoire de base — supporte PyInstaller --onefile."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()


def _resolve_powershell() -> str:
    """Retourne le chemin absolu et vérifié de powershell.exe (évite le PATH hijacking)."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    # Fallback silencieux : laisse Windows résoudre via PATH
    return "powershell.exe"


_PS_EXE = _resolve_powershell()


def _validate_script_path(script_path: Path, base_path: Path) -> bool:
    """Vérifie que le script est sous base_path (protection path-traversal / symlink)."""
    try:
        resolved = script_path.resolve(strict=True)
        resolved.relative_to(base_path)
        return resolved.is_file() and resolved.suffix.lower() == ".ps1"
    except (ValueError, OSError):
        return False


def run_collector(name: str, script_path: Path, base_path: Path,
                  timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Exécute un script PowerShell et retourne les données JSON parsées."""
    start = time.time()

    if not _validate_script_path(script_path, base_path):
        return {"collector": name, "status": "invalid_path",
                "error": "Chemin de script invalide ou hors du répertoire de base"}

    try:
        # Force UTF-8 en sortie PowerShell (PS 5.1 utilise CP850/OEM par défaut
        # sur Windows français, ce qui corrompt les accents dans le JSON).
        escaped_path = str(script_path.resolve()).replace("'", "''")
        ps_cmd = (
            "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
            "$OutputEncoding=[System.Text.Encoding]::UTF8; "
            f"& '{escaped_path}'"
        )

        result = subprocess.run(
            [
                _PS_EXE,
                "-NonInteractive",
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", ps_cmd,
            ],
            capture_output=True,
            timeout=timeout,
            shell=False,
        )

        elapsed = round(time.time() - start, 2)

        # Protection : rejeter les sorties monstrueuses
        if len(result.stdout) > MAX_STDOUT_BYTES:
            return {"collector": name, "status": "too_large",
                    "error": f"Sortie du script > {MAX_STDOUT_BYTES // (1024*1024)} Mo",
                    "elapsed_sec": elapsed}

        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()

        if result.returncode != 0 and not stdout:
            return {"collector": name, "status": "error",
                    "error": (stderr[:500] or "Exit code non nul"),
                    "elapsed_sec": elapsed}

        if not stdout:
            return {"collector": name, "status": "empty",
                    "error": "Aucune sortie du script", "elapsed_sec": elapsed}

        data = json.loads(stdout)
        if not isinstance(data, dict):
            return {"collector": name, "status": "bad_format",
                    "error": "Le collecteur n'a pas retourné un objet JSON",
                    "elapsed_sec": elapsed}

        data["_status"]      = "ok"
        data["_elapsed_sec"] = elapsed
        return data

    except subprocess.TimeoutExpired:
        return {"collector": name, "status": "timeout",
                "error": f"Timeout après {timeout}s"}
    except json.JSONDecodeError as e:
        return {"collector": name, "status": "json_error",
                "error": f"{e.msg} (ligne {e.lineno})"}
    except OSError as e:
        return {"collector": name, "status": "os_error", "error": str(e)}
    except Exception as e:
        logger.exception("Erreur inattendue dans run_collector(%s)", name)
        return {"collector": name, "status": "exception", "error": str(e)}


class DiagnosticOrchestrator:
    def __init__(self, progress_callback: Optional[Callable] = None):
        self.base_path       = get_base_path()
        self.progress_cb     = progress_callback or (lambda *a, **kw: None)
        self.results         = {}
        self.collection_time = None
        self.machine_name    = os.environ.get("COMPUTERNAME", "UNKNOWN")

    def _notify(self, step: str, current: int, total: int, status: str = "running",
                elapsed: float = 0, ps_errors: list = None):
        self.progress_cb(step=step, current=current, total=total, status=status,
                         elapsed=elapsed, ps_errors=ps_errors or [])

    def run(self) -> dict:
        """Lance tous les collecteurs et retourne les données agrégées."""
        total          = len(COLLECTORS)
        self.results   = {}
        start_time     = datetime.now()

        self._notify("Initialisation…", 0, total)

        for idx, (name, label, rel_path) in enumerate(COLLECTORS, start=1):
            script_path = self.base_path / rel_path
            self._notify(f"Collecte : {label}", idx - 1, total)

            if not script_path.exists():
                logger.warning("Script introuvable : %s", script_path)
                self.results[name] = {
                    "collector": name,
                    "status":    "missing",
                    "error":     f"Script introuvable : {rel_path}",
                }
                continue

            logger.info(">>> Collecteur [%s] démarrage…", name)
            data = run_collector(name, script_path, self.base_path)
            self.results[name] = data

            elapsed  = data.get("_elapsed_sec", 0)
            ps_errs  = data.get("collector_errors") or []
            ps_times = data.get("collector_timings") or {}

            if data.get("_status") != "ok":
                logger.warning("<<< Collecteur [%s] ECHEC (%.1fs) — statut=%s — %s",
                               name, elapsed, data.get("status"), data.get("error", ""))
                self._notify(f"Échec : {label}", idx, total,
                             status="error", elapsed=elapsed,
                             ps_errors=[f"statut={data.get('status')} — {data.get('error','')}"])
            else:
                logger.info("<<< Collecteur [%s] OK (%.1fs)", name, elapsed)
                if ps_times:
                    detail = ", ".join(f"{k}={v}s" for k, v in ps_times.items())
                    logger.info("    Timings internes [%s] : %s", name, detail)

                ps_notes = data.get("collector_notes") or []
                if ps_notes:
                    logger.debug("    Notes [%s] : %s", name, "; ".join(ps_notes))

                notify_status = "warn" if ps_errs else "running"
                self._notify(f"✓ {label}  ({elapsed:.1f}s)", idx, total,
                             status=notify_status, elapsed=elapsed, ps_errors=ps_errs)

        self.collection_time = datetime.now()
        elapsed_total = round((self.collection_time - start_time).total_seconds(), 1)

        self._notify("Finalisation du rapport…", total, total, status="done")

        return self._build_report(start_time, elapsed_total)

    def _build_report(self, start_time: datetime, elapsed_total: float) -> dict:
        """Construit le rapport agrégé final."""
        failed = [
            name for name, data in self.results.items()
            if data.get("_status") != "ok"
        ]

        return {
            "meta": {
                "version":         VERSION,
                "authors":         AUTHORS,
                "tool":            "PlanetDiag",
                "machine":         self.machine_name,
                "collected_at":    self.collection_time.strftime("%Y-%m-%d %H:%M:%S"),
                "started_at":      start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_sec":     elapsed_total,
                "collectors_ok":   len(COLLECTORS) - len(failed),
                "collectors_fail": failed,
            },
            "data": self.results,
        }
