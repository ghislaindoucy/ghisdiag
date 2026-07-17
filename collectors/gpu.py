"""
Ghisdiag - Lecture GPU NVIDIA via NVML (sans LibreHardwareMonitor).

NVML (`nvml.dll`, livre avec le pilote NVIDIA) expose temperature, charge,
ventilateur, puissance, frequences ET la raison exacte d'un bridage
(thermique / puissance) en mode utilisateur, sans driver ni elevation. C'est la
source la plus fiable et la plus a jour pour les GPU NVIDIA — on s'affranchit
donc de LHM pour cette partie.

GPU AMD / Intel : non couverts par NVML. Le repli passe par LibreHardwareMonitor
(flux `sensors.ps1`, qui expose temp/hotspot/charge/ventilo/clock/power) — voir
`list_gpus()` plus bas et `collectors.realtime_monitor`.

API :
    available()      -> bool                 nvml.dll chargeable ?
    read()           -> list[dict]           GPU NVIDIA enrichis (NVML seul)
    list_gpus()      -> list[dict]            NVIDIA (NVML) sinon repli LHM
    hottest_temp()   -> float | None          temperature du GPU le plus chaud

Aucune exception ne remonte : indisponibilite => liste vide / None.

Le bench thermique GPU (chantier GPU_BENCH_PROGRESS.md) s'appuie sur :
  - `list_gpus()` pour ENUMERER et IDENTIFIER l'adaptateur a stresser/mesurer
    (le champ `name` est la cle de jointure avec l'adaptateur DXGI cote charge) ;
  - `throttle_thermal` / `throttle_reasons` comme signal de bridage FIABLE
    (plus sur qu'un simple seuil de temperature).
"""

import ctypes
import logging
import os
from ctypes import byref, c_uint, c_ulonglong, c_void_p
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

NVML_SUCCESS = 0
NVML_TEMPERATURE_GPU = 0

# Types d'horloge (nvmlClockType_t).
NVML_CLOCK_GRAPHICS = 0
NVML_CLOCK_SM       = 1
NVML_CLOCK_MEM      = 2

# Seuils de temperature (nvmlTemperatureThresholds_t).
NVML_TEMPERATURE_THRESHOLD_SHUTDOWN = 0
NVML_TEMPERATURE_THRESHOLD_SLOWDOWN = 1

# Raisons de bridage des horloges (bitmask nvmlClocksThrottleReasons).
# On regroupe ensuite en deux familles utiles au bench : thermique vs puissance.
_THROTTLE_BITS = {
    "gpu_idle":            0x0000000000000001,
    "app_clocks_setting":  0x0000000000000002,
    "sw_power_cap":        0x0000000000000004,
    "hw_slowdown":         0x0000000000000008,
    "sync_boost":          0x0000000000000010,
    "sw_thermal":          0x0000000000000020,
    "hw_thermal":          0x0000000000000040,
    "hw_power_brake":      0x0000000000000080,
    "display_clocks":      0x0000000000000100,
}
_THROTTLE_THERMAL_MASK = 0x0000000000000060  # sw_thermal | hw_thermal
_THROTTLE_POWER_MASK   = 0x0000000000000084  # sw_power_cap | hw_power_brake


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
    """Premiere fonction existante parmi names (gere les variantes _v2 / renommees)."""
    for n in names:
        f = getattr(lib, n, None)
        if f is not None:
            return f
    return None


def available() -> bool:
    return _load_nvml() is not None


# --- Lecteurs elementaires (chacun tolere l'absence de la fonction) ----------

def _u_get(fn, handle, *extra) -> Optional[int]:
    """Appelle fn(handle, *extra, &uint) et retourne l'entier, ou None."""
    if fn is None:
        return None
    val = c_uint(0)
    try:
        if fn(handle, *extra, byref(val)) == NVML_SUCCESS:
            return int(val.value)
    except Exception:
        return None
    return None


def _decode_throttle(mask: int) -> dict:
    """Decode le bitmask de bridage en listes/booleens exploitables."""
    reasons = [name for name, bit in _THROTTLE_BITS.items()
               if mask & bit and name not in ("gpu_idle",)]
    return {
        "throttle_reasons":  reasons,
        "throttle_thermal":  bool(mask & _THROTTLE_THERMAL_MASK),
        "throttle_power":    bool(mask & _THROTTLE_POWER_MASK),
    }


def read() -> list[dict]:
    """Liste des GPU NVIDIA enrichis. [] si nvml.dll indisponible.

    Chaque entree :
        vendor, name, index, uuid,
        temp, hotspot(=None sur NVML), mem_temp(=None),
        load, fan (%),
        power_w, clock_sm_mhz, clock_mem_mhz, temp_slowdown_c,
        throttle_reasons[list], throttle_thermal, throttle_power,
        source="nvml"

    hotspot / mem_temp restent None ici : NVML ne les expose pas de facon fiable
    sur les GPU grand public. Ils remontent via LHM (`sensors.ps1` -> gpu_hotspot)
    pendant le bench. Les cles restent presentes pour une forme homogene.
    """
    lib = _load_nvml()
    if lib is None:
        return []

    init       = _fn(lib, "nvmlInit_v2", "nvmlInit")
    shutdown   = _fn(lib, "nvmlShutdown")
    get_count  = _fn(lib, "nvmlDeviceGetCount_v2", "nvmlDeviceGetCount")
    get_handle = _fn(lib, "nvmlDeviceGetHandleByIndex_v2", "nvmlDeviceGetHandleByIndex")
    get_name   = _fn(lib, "nvmlDeviceGetName")
    get_uuid   = _fn(lib, "nvmlDeviceGetUUID")
    get_temp   = _fn(lib, "nvmlDeviceGetTemperature")
    get_thresh = _fn(lib, "nvmlDeviceGetTemperatureThreshold")
    get_util   = _fn(lib, "nvmlDeviceGetUtilizationRates")
    get_fan    = _fn(lib, "nvmlDeviceGetFanSpeed")
    get_power  = _fn(lib, "nvmlDeviceGetPowerUsage")
    get_clock  = _fn(lib, "nvmlDeviceGetClockInfo")
    get_thr    = _fn(lib, "nvmlDeviceGetCurrentClocksThrottleReasons",
                     "nvmlDeviceGetCurrentClocksEventReasons")
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

                uuid = None
                if get_uuid is not None:
                    ubuf = ctypes.create_string_buffer(96)
                    if get_uuid(handle, ubuf, c_uint(96)) == NVML_SUCCESS:
                        uuid = ubuf.value.decode("utf-8", "replace") or None

                temp = c_uint(0)
                t = (temp.value if get_temp(handle, NVML_TEMPERATURE_GPU,
                                            byref(temp)) == NVML_SUCCESS else None)

                load = None
                if get_util is not None:
                    u = _Utilization()
                    if get_util(handle, byref(u)) == NVML_SUCCESS:
                        load = float(u.gpu)

                fan = _u_get(get_fan, handle)

                power_mw = _u_get(get_power, handle)
                power_w = round(power_mw / 1000.0, 1) if power_mw is not None else None

                clk_sm  = _u_get(get_clock, handle, c_uint(NVML_CLOCK_SM))
                clk_mem = _u_get(get_clock, handle, c_uint(NVML_CLOCK_MEM))

                t_slow = _u_get(get_thresh, handle,
                                c_uint(NVML_TEMPERATURE_THRESHOLD_SLOWDOWN))

                throttle = {"throttle_reasons": [], "throttle_thermal": None,
                            "throttle_power": None}
                if get_thr is not None:
                    mask = c_ulonglong(0)
                    try:
                        if get_thr(handle, byref(mask)) == NVML_SUCCESS:
                            throttle = _decode_throttle(int(mask.value))
                    except Exception:
                        pass

                entry = {
                    "vendor": "NVIDIA",
                    "name":   name or f"GPU {i}",
                    "index":  i,
                    "uuid":   uuid,
                    "temp":   float(t) if t is not None else None,
                    "hotspot": None,     # via LHM pendant le bench
                    "mem_temp": None,    # via LHM si dispo
                    "load":   load,
                    "fan":    fan,       # % (NVML donne un pourcentage, pas des RPM)
                    "power_w":       power_w,
                    "clock_sm_mhz":  clk_sm,
                    "clock_mem_mhz": clk_mem,
                    "temp_slowdown_c": float(t_slow) if t_slow is not None else None,
                    "source": "nvml",
                }
                entry.update(throttle)
                out.append(entry)
        finally:
            if shutdown is not None:
                shutdown()
    except Exception as exc:
        logger.debug("gpu.read : %s", exc)
        return out
    return out


# --- Repli / identite fabricant ---------------------------------------------

def _vendor_from_name(name: Optional[str]) -> str:
    n = (name or "").lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n or "gtx" in n:
        return "NVIDIA"
    if "radeon" in n or "amd" in n or "vega" in n:
        return "AMD"
    if "intel" in n or "arc" in n or "iris" in n or "uhd" in n or "hd graphics" in n:
        return "Intel"
    return "?"


def _lhm_gpu() -> Optional[dict]:
    """Un GPU agrege lu via LibreHardwareMonitor (repli AMD/Intel, ou NVIDIA sans
    nvml.dll). Homogene avec les entrees de read(). None si rien d'exploitable."""
    try:
        from collectors import sensors
        s = sensors.read_once()
    except Exception as exc:
        logger.debug("gpu._lhm_gpu : %s", exc)
        return None
    if not s:
        return None
    # On garde le GPU des qu'un signal exploitable existe. Les iGPU Intel (et
    # certains APU AMD) n'exposent NI temperature NI charge via LHM — seulement
    # clock/power : il faut quand meme les enumerer (le moniteur et la config du
    # bench les affichent, quitte a signaler "temperature indisponible" ; un GPU
    # sans temperature n'est simplement pas benchable thermiquement).
    if not any(s.get(k) is not None for k in
               ("gpu_temp", "gpu_load", "gpu_core_clock", "gpu_power")):
        return None
    name = s.get("gpu_name") or "GPU"
    return {
        "vendor": _vendor_from_name(name),
        "name":   name,
        "index":  0,
        "uuid":   None,
        "temp":     s.get("gpu_temp"),
        "hotspot":  s.get("gpu_hotspot"),
        "mem_temp": None,
        "load":     s.get("gpu_load"),
        "fan":      s.get("gpu_fan"),
        "power_w":       s.get("gpu_power"),
        "clock_sm_mhz":  s.get("gpu_core_clock"),
        "clock_mem_mhz": None,
        "temp_slowdown_c": None,
        "throttle_reasons": [],
        "throttle_thermal": None,   # non expose par LHM
        "throttle_power":   None,
        "source": "lhm",
    }


def list_gpus(lhm_fallback: bool = True) -> list[dict]:
    """Enumeration unifiee des GPU pour le bench / le moniteur.

    NVIDIA via NVML (riche, avec raison de bridage). Si aucun GPU NVML et
    `lhm_fallback`, un GPU agrege via LibreHardwareMonitor (AMD/Intel...).

    Note : le repli LHM lance un process PowerShell ponctuel (~1-3 s) — reserve
    a une enumeration (config du bench, moniteur), pas a une boucle serree.
    """
    gpus = read()
    if gpus or not lhm_fallback:
        return gpus
    lhm = _lhm_gpu()
    return [lhm] if lhm is not None else []


def hottest_temp() -> Optional[float]:
    """Temperature du GPU NVIDIA le plus chaud, ou None."""
    temps = [g["temp"] for g in read() if g.get("temp") is not None]
    return max(temps) if temps else None


# --- Test manuel : `python -m collectors.gpu` -------------------------------

if __name__ == "__main__":
    import json
    print("nvml.dll disponible :", available())
    gpus = list_gpus()
    if not gpus:
        print("Aucun GPU detecte (ni NVML ni LHM).")
    for g in gpus:
        print(json.dumps(g, ensure_ascii=False, indent=2))
