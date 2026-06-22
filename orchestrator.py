"""
Ghisdiag - Orchestrateur
Exécute les collecteurs PowerShell et agrège les données.
"""

import subprocess
import json
import os
import sys
import time
import logging
import threading
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)

COLLECTORS = [
    ("system_info",  "Système & Matériel",   "collectors/system_info.ps1",  120),
    ("performance",  "Performance",           "collectors/performance.ps1",  120),
    ("startup",      "Démarrage Windows",     "collectors/startup.ps1",      120),
    ("events",       "Événements Windows",    "collectors/events.ps1",       120),
    ("network",      "Réseau",                "collectors/network.ps1",      120),
    ("security",     "Sécurité",             "collectors/security.ps1",     120),
    ("software",     "Logiciels & Drivers",   "collectors/software.ps1",     120),
    ("smart",        "Santé disques (SMART)", "collectors/smart.ps1",         75),
]

VERSION = "1.6.4"
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
            creationflags=subprocess.CREATE_NO_WINDOW,
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


def run_ps_action(script_rel: str, extra_args: list[str], timeout: int = 60) -> dict:
    """Exécute un script PowerShell de dépannage et retourne le JSON parsé.
    Même forçage UTF-8 que run_collector pour éviter les problèmes CP850/OEM."""
    base     = get_base_path()
    script_p = (base / script_rel).resolve()

    if not _validate_script_path(script_p, base):
        raise RuntimeError(f"Chemin de script invalide : {script_rel}")

    escaped_path = str(script_p).replace("'", "''")

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
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    if not stdout:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()[:500]
        raise RuntimeError(f"Pas de sortie du script. Stderr : {stderr}")

    try:
        return json.loads(stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"JSON invalide : {e}\nSortie : {stdout[:300]}")


def run_ps_stream(script_rel: str, extra_args: list[str], on_line, timeout: int = 900) -> int:
    """Exécute un script PS1 et appelle on_line(text) pour chaque ligne stdout (streaming)."""
    base     = get_base_path()
    script_p = (base / script_rel).resolve()

    if not _validate_script_path(script_p, base):
        raise RuntimeError(f"Chemin de script invalide : {script_rel}")

    escaped_path = str(script_p).replace("'", "''")

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

    proc = subprocess.Popen(
        [_PS_EXE, "-NonInteractive", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", ps_cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.strip():
                on_line(line)
    finally:
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    return proc.returncode


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
        """Lance tous les collecteurs en parallèle et retourne les données agrégées."""
        total      = len(COLLECTORS)
        self.results = {}
        start_time = datetime.now()
        lock       = threading.Lock()
        completed  = 0

        self._notify("Lancement des collecteurs…", 0, total)

        # Résolution préalable des chemins (séquentielle, triviale)
        missing = {}
        runnable = []
        for name, label, rel_path, timeout in COLLECTORS:
            script_path = self.base_path / rel_path
            if not script_path.exists():
                logger.warning("Script introuvable : %s", script_path)
                missing[name] = {
                    "collector": name,
                    "status":    "missing",
                    "error":     f"Script introuvable : {rel_path}",
                }
            else:
                runnable.append((name, label, script_path, timeout))

        self.results.update(missing)

        max_workers = min(4, len(runnable)) if runnable else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(run_collector, name, script_path, self.base_path, timeout): (name, label)
                for name, label, script_path, timeout in runnable
            }
            logger.info(">>> %d collecteurs lancés en parallèle (workers=%d)",
                        len(runnable), max_workers)

            for future in concurrent.futures.as_completed(future_map):
                name, label = future_map[future]
                data = future.result()

                with lock:
                    self.results[name] = data
                    completed += 1
                    current = completed

                elapsed  = data.get("_elapsed_sec", 0)
                ps_errs  = data.get("collector_errors") or []
                ps_times = data.get("collector_timings") or {}

                if data.get("_status") != "ok":
                    logger.warning("<<< Collecteur [%s] ECHEC (%.1fs) — statut=%s — %s",
                                   name, elapsed, data.get("status"), data.get("error", ""))
                    self._notify(f"Échec : {label}", current, total,
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
                    self._notify(f"✓ {label}  ({elapsed:.1f}s)", current, total,
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
                "tool":            "Ghisdiag",
                "machine":         self.machine_name,
                "collected_at":    self.collection_time.strftime("%Y-%m-%d %H:%M:%S"),
                "started_at":      start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_sec":     elapsed_total,
                "collectors_ok":   len(COLLECTORS) - len(failed),
                "collectors_fail": failed,
            },
            "data": self.results,
        }
