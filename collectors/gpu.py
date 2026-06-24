"""
Ghisdiag - Lecture GPU NVIDIA via NVML (sans LibreHardwareMonitor).

NVML (`nvml.dll`, livre avec le pilote NVIDIA) expose temperature, charge et
ventilateur en mode utilisateur, sans driver ni elevation. C'est la source la
plus fiable et la plus a jour pour les GPU NVIDIA — on s'affranchit donc de LHM
pour cette partie.

GPU AMD / Intel : non couverts ici (API ADL/IGCL fragmentees par generation).
L'appelant garde LHM en repli pour ces cas — voir realtime_monitor.

API : available() -> bool ; read() -> list[dict] ; hottest_temp() -> float|None.
Aucune exception ne remonte : indisponibilite => liste vide / None.
"""

import ctypes
import logging
import os
from ctypes import POINTER, byref, c_char, c_uint, c_void_p
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

NVML_SUCCESS = 0
NVML_TEMPERATURE_GPU = 0


class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", c_uint), ("memory", c_uint)]


def _nvml_paths() -> list[str]:
    """Emplacements probables de nvml.dll (ordre de preference)."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    return [
        str(Path(sysroot) / "System32" / "nvml.dll"),
        str(Path(pf) / "NVIDIA Corporation" / "NVSMI" / "nvml.dll"),
        "nvml.dll",  # PATH
    ]


def _load_nvml() -> Optional[ctypes.CDLL]:
    for p in _nvml_paths():
        try:
            return ctypes.CDLL(p)
        except OSError:
            continue
    return None


def _fn(lib, *names):
    """Premiere fonction existante parmi names (gere les variantes _v2)."""
    for n in names:
        f = getattr(lib, n, None)
        if f is not None:
            return f
    return None


def available() -> bool:
    return _load_nvml() is not None


def read() -> list[dict]:
    """Liste des GPU NVIDIA : {vendor, name, temp, load, fan}. [] si indisponible."""
    lib = _load_nvml()
    if lib is None:
        return []

    init = _fn(lib, "nvmlInit_v2", "nvmlInit")
    shutdown = _fn(lib, "nvmlShutdown")
    get_count = _fn(lib, "nvmlDeviceGetCount_v2", "nvmlDeviceGetCount")
    get_handle = _fn(lib, "nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex")
    get_name = _fn(lib, "nvmlDeviceGetName")
    get_temp = _fn(lib, "nvmlDeviceGetTemperature")
    get_util = _fn(lib, "nvmlDeviceGetUtilizationRates")
    get_fan = _fn(lib, "nvmlDeviceGetFanSpeed")
    if not (init and get_count and get_handle and get_temp):
        return []

    out: list[dict] = []
    try:
        if init() != NVML_SUCCESS:
            return []
        try:
            count = c_uint(0)
            if get_count(byref(count)) != NVML_SUCCESS:
                return []
            for i in range(count.value):
                handle = c_void_p()
                if get_handle(c_uint(i), byref(handle)) != NVML_SUCCESS:
                    continue

                name = None
                if get_name is not None:
                    buf = ctypes.create_string_buffer(96)
                    if get_name(handle, buf, c_uint(96)) == NVML_SUCCESS:
                        name = buf.value.decode("utf-8", "replace") or None

                temp = c_uint(0)
                t = (temp.value if get_temp(handle, NVML_TEMPERATURE_GPU,
                                            byref(temp)) == NVML_SUCCESS else None)

                load = None
                if get_util is not None:
                    u = _Utilization()
                    if get_util(handle, byref(u)) == NVML_SUCCESS:
                        load = float(u.gpu)

                fan = None
                if get_fan is not None:
                    f = c_uint(0)
                    if get_fan(handle, byref(f)) == NVML_SUCCESS:
                        fan = int(f.value)

                out.append({
                    "vendor": "NVIDIA",
                    "name":   name or f"GPU {i}",
                    "temp":   float(t) if t is not None else None,
                    "load":   load,
                    "fan":    fan,   # % (NVML donne un pourcentage, pas des RPM)
                })
        finally:
            if shutdown is not None:
                shutdown()
    except Exception as exc:
        logger.debug("gpu.read : %s", exc)
        return out
    return out


def hottest_temp() -> Optional[float]:
    """Temperature du GPU NVIDIA le plus chaud, ou None."""
    temps = [g["temp"] for g in read() if g.get("temp") is not None]
    return max(temps) if temps else None
