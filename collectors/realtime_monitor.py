"""
Ghisdiag - Moniteur temps reel
CPU %, RAM %, Disk I/O % via psutil
Temperatures CPU/GPU/disques via PowerShell WMI (appel ponctuel toutes les 10s)
"""

import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False
    logger.warning("psutil non disponible — moniteur temps reel limite")

# Source de temperatures preferentielle : LibreHardwareMonitor (fiable, capteurs
# CPU/GPU/disques/ventilateurs). On retombe sur la chaine WMI/OHM historique si
# la DLL est absente ou echoue.
try:
    from collectors import sensors as _sensors
    _HAS_LHM = True
except Exception:
    _sensors = None
    _HAS_LHM = False
    logger.debug("collectors.sensors (LHM) indisponible — fallback WMI")

# Sources maison (sans LHM) : GPU NVIDIA via NVML, disques via smartctl. On les
# prefere a LHM la ou elles s'appliquent ; LHM reste le repli (GPU AMD/Intel...).
try:
    from collectors import gpu as _gpu
    _HAS_GPU = True
except Exception:
    _gpu = None
    _HAS_GPU = False

try:
    from collectors import disk_temp as _disk
    _HAS_DISK = True
except Exception:
    _disk = None
    _HAS_DISK = False


def _ps_exe() -> str:
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else "powershell.exe"


_PS_EXE = _ps_exe()

# Cache pour le calcul de disk I/O %
_last_disk_io = None
_last_disk_ts: float | None = None

# Commande PowerShell pour les temperatures (construite une seule fois)
_TEMP_PS_SCRIPT = r"""
$out = @{ cpu=$null; gpu=$null; disks=@() }
try {
    $z = Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace "root/wmi" -EA Stop
    $c = ($z | ForEach-Object { [math]::Round($_.CurrentTemperature/10-273.15,1) } |
          Measure-Object -Maximum).Maximum
    if ($c -gt 0 -and $c -lt 120) { $out.cpu = $c }
} catch {}
try {
    $s = Get-WmiObject -Namespace "root/OpenHardwareMonitor" -Class Sensor -EA Stop |
         Where-Object { $_.SensorType -eq "Temperature" -and $_.Identifier -match "/gpu" }
    if ($s) { $out.gpu = [math]::Round(($s | Measure-Object Value -Maximum).Maximum, 1) }
} catch {}
try {
    $dd = @(Get-PhysicalDisk -EA Stop | ForEach-Object {
        try {
            $r = $_ | Get-StorageReliabilityCounter -EA Stop
            if ($r.Temperature -and $r.Temperature -gt 0) {
                @{ model=$_.FriendlyName; temp=$r.Temperature }
            }
        } catch {}
    } | Where-Object { $_ -ne $null })
    if ($dd.Count -gt 0) { $out.disks = $dd }
} catch {}
$out | ConvertTo-Json -Depth 3
"""

_TEMP_PS_CMD = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$OutputEncoding=[System.Text.Encoding]::UTF8; "
    + _TEMP_PS_SCRIPT
)

# Repli CPU seul : zone thermique ACPI uniquement (pas de probing disque, qui
# peut figer sur certaines machines). Rapide (~1s). Emet la temperature ou rien.
_CPU_TEMP_PS_SCRIPT = r"""
$c = $null
try {
    $z = Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace "root/wmi" -EA Stop
    $c = ($z | ForEach-Object { [math]::Round($_.CurrentTemperature/10-273.15,1) } |
          Measure-Object -Maximum).Maximum
} catch {}
if ($c -gt 0 -and $c -lt 120) { $c } else { "" }
"""

_CPU_TEMP_PS_CMD = (
    "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
    "$OutputEncoding=[System.Text.Encoding]::UTF8; "
    + _CPU_TEMP_PS_SCRIPT
)


def get_cpu_percent() -> float | None:
    if not _HAS_PSUTIL:
        return None
    return psutil.cpu_percent(interval=None)


def get_ram_percent() -> float | None:
    if not _HAS_PSUTIL:
        return None
    return psutil.virtual_memory().percent


def get_disk_io_percent() -> float | None:
    """Calcule le % d'utilisation disque (temps actif sur la periode ecoulee)."""
    global _last_disk_io, _last_disk_ts
    if not _HAS_PSUTIL:
        return None
    try:
        counters = psutil.disk_io_counters()
        if counters is None:
            return None
        now = time.monotonic()
        if _last_disk_io is None or _last_disk_ts is None:
            _last_disk_io = counters
            _last_disk_ts = now
            return 0.0
        delta_t = now - _last_disk_ts
        if delta_t <= 0:
            return 0.0
        # read_time + write_time sont en millisecondes
        delta_busy_ms = (
            counters.read_time + counters.write_time
            - _last_disk_io.read_time - _last_disk_io.write_time
        )
        pct = min(100.0, (delta_busy_ms / 1000.0 / delta_t) * 100.0)
        _last_disk_io = counters
        _last_disk_ts = now
        return round(pct, 1)
    except Exception:
        return None


def get_temperatures() -> dict:
    """Temperatures CPU/GPU/disques.

    CPU via LibreHardwareMonitor (seul a lire la die CPU) ; GPU via NVML maison ;
    disques via smartctl maison ; repli LHM puis WMI/OHM historique si une source
    manque.
    Retourne {"cpu": float|None, "gpu": float|None, "disks": [{"model", "temp"}]}
    """
    result: dict = {"cpu": None, "gpu": None, "disks": []}

    lhm = None
    if _HAS_LHM and _sensors is not None:
        try:
            lhm = _sensors.get_temperatures()
        except Exception as exc:
            logger.debug("Temperatures LHM : %s", exc)

    # CPU : LHM uniquement (NVML/smartctl ne lisent pas le CPU).
    if lhm is not None:
        result["cpu"] = lhm.get("cpu")

    # GPU : NVML maison d'abord, sinon ce qu'a vu LHM.
    gpu_c = None
    if _HAS_GPU and _gpu is not None:
        try:
            gpu_c = _gpu.hottest_temp()
        except Exception as exc:
            logger.debug("Temperatures GPU NVML : %s", exc)
    if gpu_c is None and lhm is not None:
        gpu_c = lhm.get("gpu")
    result["gpu"] = gpu_c

    # Disques : smartctl maison d'abord, sinon ce qu'a vu LHM.
    disks: list = []
    if _HAS_DISK and _disk is not None:
        try:
            disks = [{"model": d["model"], "temp": d["temp"]}
                     for d in _disk.read_all() if d.get("temp") is not None]
        except Exception as exc:
            logger.debug("Temperatures disques smartctl : %s", exc)
    if not disks and lhm is not None:
        disks = lhm.get("disks") or []
    result["disks"] = disks

    # Repli CPU independant : la temperature CPU peut venir de la zone thermique
    # ACPI meme quand LHM ne la lit pas (PawnIO inactif, CPU non mappe...). On ne
    # conditionne PAS ce repli a un vide total : sinon, des qu'un GPU ou un disque
    # est detecte (NVML / smartctl), le CPU restait a None alors que l'ACPI
    # l'aurait fourni — c'est la regression vs la chaine WMI historique (1.6.4).
    if result["cpu"] is None:
        result["cpu"] = _get_cpu_temp_wmi()

    # Tout vide malgre tout : dernier recours, chaine WMI/OHM historique complete.
    if result["cpu"] is None and result["gpu"] is None and not result["disks"]:
        return _get_temperatures_wmi()
    return result


def _get_cpu_temp_wmi() -> float | None:
    """Temperature CPU via la zone thermique ACPI (repli leger, sans probing
    disque). Acces admin requis sur la plupart des machines. None si indisponible."""
    try:
        proc = subprocess.run(
            [_PS_EXE, "-NonInteractive", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-Command", _CPU_TEMP_PS_CMD],
            capture_output=True,
            timeout=6,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        return float(out) if out else None
    except Exception as exc:
        logger.debug("CPU temp ACPI/WMI : %s", exc)
        return None


def _get_temperatures_wmi() -> dict:
    """Fallback historique : temperatures via PowerShell WMI (bloquant ~3-5s)."""
    result: dict = {"cpu": None, "gpu": None, "disks": []}
    try:
        proc = subprocess.run(
            [_PS_EXE, "-NonInteractive", "-NoProfile",
             "-ExecutionPolicy", "Bypass", "-Command", _TEMP_PS_CMD],
            capture_output=True,
            timeout=8,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace").strip()
        if stdout:
            data = json.loads(stdout)
            if isinstance(data, dict):
                result["cpu"] = data.get("cpu")
                result["gpu"] = data.get("gpu")
                disks = data.get("disks")
                if isinstance(disks, list):
                    result["disks"] = disks
                elif isinstance(disks, dict):
                    result["disks"] = [disks]
    except Exception as exc:
        logger.debug("Temperatures WMI : %s", exc)
    return result
