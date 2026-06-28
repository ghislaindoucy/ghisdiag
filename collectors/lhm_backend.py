"""
Ghisdiag - Resolution et mise a jour du backend capteurs (LibreHardwareMonitor).

Permet de remplacer le jeu de DLL embarque par une version plus recente SANS
recompiler Ghisdiag : on depose simplement les DLL dans un dossier 'override'.
Indispensable pour les CPU trop recents pour la DLL livree (ex. Zen 5), qu'on
debloque alors d'un simple remplacement de fichier.

Resolution du dossier 'tools' actif, par ordre de priorite (le premier qui
contient LibreHardwareMonitorLib.dll gagne) :

    1. $GHISDIAG_TOOLS_DIR              override explicite (tests, cas avances)
    2. <dossier de l'exe>\\tools         depot manuel, portable / cle USB [frozen]
    3. %LOCALAPPDATA%\\Ghisdiag\\tools    gere par le mode mise a jour
    4. <embarque>\\tools                 toujours present, fallback

Le script PowerShell (sensors.ps1) recoit ce dossier via -ToolsDir : il n'y a
donc qu'un seul endroit qui decide quel backend est utilise.
"""

import ctypes
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from ctypes import wintypes
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LIB_NAME = "LibreHardwareMonitorLib.dll"

# Jeu de DLL connu (ordre de chargement = feuilles d'abord). Utilise pour valider
# / copier une mise a jour. Toute *.dll supplementaire de l'archive est copiee
# aussi (au cas ou une version recente renomme/ajoute une dependance).
KNOWN_DLLS = (
    "System.Runtime.CompilerServices.Unsafe.dll",
    "System.Numerics.Vectors.dll",
    "System.Memory.dll",
    "HidSharp.dll",
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "LibreHardwareMonitorLib.dll",
)

# Source amont pour l'auto-mise a jour (LHM est upstream, non modifie).
_GITHUB_LATEST = ("https://api.github.com/repos/"
                  "LibreHardwareMonitor/LibreHardwareMonitor/releases/latest")


# --- Resolution des dossiers ------------------------------------------------

def _base_path() -> Path:
    """Repertoire embarque — supporte PyInstaller --onefile (_MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.parent.resolve()


def embedded_tools_dir() -> Path:
    return _base_path() / "tools"


def user_tools_dir() -> Path:
    """Dossier inscriptible gere par la mise a jour (%LOCALAPPDATA%\\Ghisdiag)."""
    return (Path(os.path.expanduser("~")) / "AppData" / "Local"
            / "Ghisdiag" / "tools")


def exe_tools_dir() -> Optional[Path]:
    """Dossier 'tools' a cote de l'exe (depot manuel portable). None hors frozen."""
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent / "tools"
        except Exception:
            return None
    return None


def _candidate_dirs() -> list[Path]:
    cands: list[Optional[Path]] = []
    env = os.environ.get("GHISDIAG_TOOLS_DIR")
    if env:
        cands.append(Path(env))
    cands.append(exe_tools_dir())
    cands.append(user_tools_dir())
    cands.append(embedded_tools_dir())
    # Dedup en gardant l'ordre, ignore None.
    seen: set[str] = set()
    out: list[Path] = []
    for c in cands:
        if c is None:
            continue
        key = str(c).lower()
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _has_lib(d: Path) -> bool:
    try:
        return (d / LIB_NAME).is_file()
    except OSError:
        return False


def active_tools_dir() -> Path:
    """Premier dossier candidat contenant la DLL, sinon l'embarque (fallback)."""
    for d in _candidate_dirs():
        if _has_lib(d):
            return d
    return embedded_tools_dir()


def override_active() -> bool:
    """Un override (non embarque) est-il utilise ?"""
    try:
        return active_tools_dir().resolve() != embedded_tools_dir().resolve()
    except OSError:
        return False


# --- Version d'un fichier DLL (sans charger .NET) ---------------------------

class _VSFixedFileInfo(ctypes.Structure):
    _fields_ = [("dwSignature", wintypes.DWORD),
                ("dwStrucVersion", wintypes.DWORD),
                ("dwFileVersionMS", wintypes.DWORD),
                ("dwFileVersionLS", wintypes.DWORD),
                ("dwProductVersionMS", wintypes.DWORD),
                ("dwProductVersionLS", wintypes.DWORD),
                ("dwFileFlagsMask", wintypes.DWORD),
                ("dwFileFlags", wintypes.DWORD),
                ("dwFileOS", wintypes.DWORD),
                ("dwFileType", wintypes.DWORD),
                ("dwFileSubtype", wintypes.DWORD),
                ("dwFileDateMS", wintypes.DWORD),
                ("dwFileDateLS", wintypes.DWORD)]


def file_version(path: Path) -> Optional[str]:
    """Version 'a.b.c.d' d'un PE via l'API version.dll. None si indisponible."""
    try:
        p = str(path)
        ver = ctypes.windll.version
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        size = ver.GetFileVersionInfoSizeW(ctypes.c_wchar_p(p), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(ctypes.c_wchar_p(p), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not ver.VerQueryValueW(buf, ctypes.c_wchar_p("\\"),
                                  ctypes.byref(ptr), ctypes.byref(length)):
            return None
        ffi = ctypes.cast(ptr, ctypes.POINTER(_VSFixedFileInfo)).contents
        ms, ls = ffi.dwFileVersionMS, ffi.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception as exc:
        logger.debug("file_version(%s) : %s", path, exc)
        return None


def lib_version(tools_dir: Optional[Path] = None) -> Optional[str]:
    d = tools_dir or active_tools_dir()
    return file_version(d / LIB_NAME)


def info() -> dict:
    """Resume pour le diagnostic / l'UI."""
    active = active_tools_dir()
    return {
        "active_dir":   str(active),
        "version":      lib_version(active),
        "override":     override_active(),
        "embedded_dir": str(embedded_tools_dir()),
        "user_dir":     str(user_tools_dir()),
        "exe_dir":      str(exe_tools_dir()) if exe_tools_dir() else None,
        "candidates":   [str(c) for c in _candidate_dirs()],
    }


# --- Installation d'une mise a jour -----------------------------------------

def _collect_dlls_from_zip(zf: zipfile.ZipFile) -> dict[str, str]:
    """basename(lower) -> nom de membre, pour chaque *.dll de l'archive."""
    found: dict[str, str] = {}
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        base = os.path.basename(name)
        if base.lower().endswith(".dll"):
            # Premiere occurrence gagne (evite les doublons net8/net472 plus bas).
            found.setdefault(base.lower(), name)
    return found


def install_from_zip(zip_path, dest: Optional[Path] = None) -> dict:
    """Installe un jeu de DLL LHM depuis une archive zip vers le dossier override.

    Valide la presence de LibreHardwareMonitorLib.dll, copie toutes les *.dll de
    l'archive (a plat) dans un dossier temporaire, puis bascule atomiquement vers
    `dest` (par defaut user_tools_dir). Ne leve jamais : retourne un dict statut.
    """
    dest = Path(dest) if dest else user_tools_dir()
    result = {"ok": False, "action": "", "dest": str(dest),
              "version": None, "copied": [], "error": None}
    try:
        with zipfile.ZipFile(zip_path) as zf:
            dlls = _collect_dlls_from_zip(zf)
            if LIB_NAME.lower() not in dlls:
                result["action"] = "invalid"
                result["error"] = f"{LIB_NAME} absent de l'archive"
                return result

            staging = Path(tempfile.mkdtemp(prefix="ghisdiag_lhm_"))
            try:
                for base, member in dlls.items():
                    target = staging / os.path.basename(member)
                    with zf.open(member) as src, open(target, "wb") as out:
                        shutil.copyfileobj(src, out)
                result["copied"] = sorted(p.name for p in staging.glob("*.dll"))
                result["version"] = file_version(staging / LIB_NAME)

                # Bascule atomique vers dest.
                dest.parent.mkdir(parents=True, exist_ok=True)
                new_dir = dest.parent / (dest.name + ".new")
                old_dir = dest.parent / (dest.name + ".old")
                if new_dir.exists():
                    shutil.rmtree(new_dir, ignore_errors=True)
                shutil.move(str(staging), str(new_dir))
                staging = None  # deplace
                if dest.exists():
                    if old_dir.exists():
                        shutil.rmtree(old_dir, ignore_errors=True)
                    os.replace(dest, old_dir)
                os.replace(new_dir, dest)
                if old_dir.exists():
                    shutil.rmtree(old_dir, ignore_errors=True)
            finally:
                if staging is not None:
                    shutil.rmtree(staging, ignore_errors=True)

        result["ok"] = True
        result["action"] = "installed"
        logger.info("Backend LHM installe dans %s (v%s, %d DLL)",
                    dest, result["version"], len(result["copied"]))
        return result
    except zipfile.BadZipFile:
        result["action"] = "invalid"
        result["error"] = "archive zip illisible"
        return result
    except Exception as exc:
        result["action"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning("install_from_zip : %s", exc)
        return result


def _pick_asset(assets: list[dict]) -> Optional[dict]:
    """Choisit l'asset zip net472 (sinon un zip LHM generique)."""
    zips = [a for a in assets if str(a.get("name", "")).lower().endswith(".zip")]
    for a in zips:
        if "net472" in a["name"].lower():
            return a
    for a in zips:
        n = a["name"].lower()
        if "librehardwaremonitor" in n and not any(
                x in n for x in ("net6", "net7", "net8", "net9")):
            return a
    return zips[0] if zips else None


def update_from_github(timeout: float = 30.0, dest: Optional[Path] = None) -> dict:
    """Telecharge la derniere release LHM et l'installe dans le dossier override.

    Opt-in (jamais automatique au demarrage) : reseau requis. Ne leve jamais ;
    degrade proprement (no_network / error) en pointant vers l'installation
    manuelle si l'amont a change de structure.
    """
    import json as _json
    import urllib.request

    result = {"ok": False, "action": "", "tag": None, "asset": None,
              "version": None, "error": None}
    try:
        req = urllib.request.Request(
            _GITHUB_LATEST,
            headers={"User-Agent": "Ghisdiag", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            meta = _json.loads(resp.read().decode("utf-8"))
        result["tag"] = meta.get("tag_name")
        asset = _pick_asset(meta.get("assets") or [])
        if not asset:
            result["action"] = "no_asset"
            result["error"] = "aucune archive zip dans la release amont"
            return result
        result["asset"] = asset.get("name")

        url = asset["browser_download_url"]
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            dl = urllib.request.Request(url, headers={"User-Agent": "Ghisdiag"})
            with urllib.request.urlopen(dl, timeout=timeout) as resp, \
                    open(tmp_path, "wb") as out:
                shutil.copyfileobj(resp, out)
            inst = install_from_zip(tmp_path, dest=dest)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        result["ok"] = inst["ok"]
        result["version"] = inst["version"]
        result["action"] = inst["action"] if inst["ok"] else ("install_" + inst["action"])
        result["error"] = inst["error"]
        return result
    except (OSError, ValueError) as exc:
        # urllib leve URLError(OSError) hors-ligne / DNS / TLS.
        result["action"] = "no_network"
        result["error"] = f"{type(exc).__name__}: {exc}"
        logger.info("update_from_github indisponible : %s", exc)
        return result
