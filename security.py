"""
PlanetDiag - Utilitaires sécurité (UAC, validation de chemins).
"""
import ctypes
import os
import sys
from pathlib import Path

_FORBIDDEN_OUTPUT_ROOTS = [
    Path(os.environ.get("SystemRoot",        r"C:\Windows")).resolve(),
    Path(os.environ.get("ProgramFiles",      r"C:\Program Files")).resolve(),
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")).resolve(),
]


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


def is_safe_output_dir(path: Path) -> tuple[bool, str]:
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
