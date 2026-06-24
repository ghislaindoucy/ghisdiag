"""
Ghisdiag - Temperatures disques via smartctl (sans LibreHardwareMonitor).

smartctl (smartmontools, deja embarque dans ..\tools) est la source disque la
plus tout-terrain : SATA, NVMe, et la plupart des ponts USB, avec sortie JSON
stable. On s'affranchit donc de LHM pour les disques.

Lecture SMART : droits admin requis sur Windows (comme le reste de Ghisdiag,
qui tourne sous UAC). Sans elevation, smartctl peut ne rien remonter.

API : available() -> bool ; read_all() -> list[dict] {model, temp, name, proto}.
Un cache court (TTL) evite de solliciter les disques a chaque tick du moniteur.
Aucune exception ne remonte : indisponibilite => liste vide.
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_CACHE_TTL = 30.0  # s : la temperature disque evolue lentement

_cache: Optional[list[dict]] = None
_cache_ts: float = 0.0


def _base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.parent.resolve()


def _smartctl() -> Optional[str]:
    """Chemin de smartctl.exe : embarque en priorite, sinon PATH."""
    embedded = _base_path() / "tools" / "smartctl.exe"
    if embedded.is_file():
        return str(embedded)
    from shutil import which
    return which("smartctl")


def available() -> bool:
    return _smartctl() is not None


def _run_json(args: list[str], timeout: float) -> Optional[dict]:
    exe = _smartctl()
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, *args, "-j"],
            capture_output=True, timeout=timeout, shell=False,
            creationflags=_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if not out:
            return None
        return json.loads(out)
    except Exception as exc:
        logger.debug("disk_temp._run_json %s : %s", args, exc)
        return None


def _scan() -> list[dict]:
    """Liste des disques : {name, type}."""
    data = _run_json(["--scan"], timeout=8.0)
    devices = (data or {}).get("devices") or []
    out = []
    for d in devices:
        name = d.get("name")
        if name:
            out.append({"name": name, "type": d.get("type")})
    return out


def _read_one(name: str, dtype: Optional[str]) -> Optional[dict]:
    args = ["-A", "-i", name]
    if dtype:
        args += ["-d", dtype]
    data = _run_json(args, timeout=10.0)
    if not data:
        return None
    temp = (data.get("temperature") or {}).get("current")
    if temp is None:
        return None
    return {
        "name":  name,
        "model": data.get("model_name") or name,
        "temp":  round(float(temp), 1),
        "proto": data.get("device", {}).get("protocol"),
    }


def read_all(use_cache: bool = True) -> list[dict]:
    """Temperatures de tous les disques detectes. [] si indisponible."""
    global _cache, _cache_ts
    now = time.monotonic()
    if use_cache and _cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    out: list[dict] = []
    for dev in _scan():
        rec = _read_one(dev["name"], dev.get("type"))
        if rec is not None:
            out.append(rec)

    _cache = out
    _cache_ts = now
    return out


def invalidate_cache() -> None:
    global _cache
    _cache = None
