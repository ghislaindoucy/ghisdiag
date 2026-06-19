"""
Ghisdiag - Gestion du driver PawnIO (acces MSR -> temperature/frequence CPU).

LibreHardwareMonitor lit la temperature et la frequence du CPU (et les
ventilateurs de la carte mere) via les registres MSR, accessibles uniquement
par un driver kernel. LHM 0.9.x utilise PawnIO : un driver signe (namazso),
hors liste de blocage Windows 11 (contrairement a l'ancien WinRing0).

Sans PawnIO : GPU, disques, ventilateur GPU et charge CPU remontent ; mais la
temperature CPU, la frequence CPU et les ventilateurs carte mere restent N/A.

Ce module detecte PawnIO et l'installe silencieusement depuis l'installeur signe
embarque (tools\\PawnIO_setup.exe -install -silent). Ghisdiag tournant deja
sous UAC en production, aucune elevation supplementaire n'est necessaire.
"""

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.parent.resolve()


_INSTALLER = _base_path() / "tools" / "PawnIO_setup.exe"
# PawnIO s'installe dans %ProgramFiles%\PawnIO ; PawnIOLib.dll est le marqueur.
_INSTALL_DIR = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "PawnIO"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def pawnio_installed() -> bool:
    """PawnIO est-il installe ? (presence de PawnIOLib.dll dans Program Files)."""
    try:
        return (_INSTALL_DIR / "PawnIOLib.dll").is_file()
    except OSError:
        return False


def installer_available() -> bool:
    return _INSTALLER.is_file()


def ensure_pawnio(timeout: int = 120) -> dict:
    """Installe PawnIO silencieusement s'il manque. Idempotent.

    Retourne {"installed": bool, "action": str, "error": str|None} ou action vaut
    "already" / "installed" / "no_installer" / "needs_admin" / "failed".
    Ne leve jamais : un echec laisse simplement la temperature CPU en N/A.
    """
    if pawnio_installed():
        return {"installed": True, "action": "already", "error": None}

    if not installer_available():
        logger.info("PawnIO absent et installeur non embarque — temp CPU indisponible")
        return {"installed": False, "action": "no_installer", "error": None}

    # L'installeur cree un service kernel : droits admin requis. En production
    # l'app est elevee ; en dev (--no-uac) on s'abstient plutot que de declencher
    # une elevation surprise.
    if not is_admin():
        logger.info("PawnIO : installation differee (pas de droits admin)")
        return {"installed": False, "action": "needs_admin", "error": None}

    try:
        proc = subprocess.run(
            [str(_INSTALLER), "-install", "-silent"],
            capture_output=True, timeout=timeout, shell=False,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return {"installed": False, "action": "failed", "error": f"timeout {timeout}s"}
    except OSError as exc:
        return {"installed": False, "action": "failed", "error": str(exc)}

    if proc.returncode == 0 and pawnio_installed():
        logger.info("PawnIO installe avec succes (temp CPU desormais disponible)")
        return {"installed": True, "action": "installed", "error": None}

    err = proc.stderr.decode("utf-8", errors="replace").strip()[:300] if proc.stderr else ""
    logger.warning("PawnIO : echec installation (exit=%s) %s", proc.returncode, err)
    return {"installed": False, "action": "failed",
            "error": f"exit={proc.returncode} {err}".strip()}
