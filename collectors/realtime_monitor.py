"""
PlanetDiag - Moniteur temps reel
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
    """Recupere les temperatures via PowerShell WMI (bloquant ~3-5s).
    Retourne {"cpu": float|None, "gpu": float|None, "disks": [{"model": str, "temp": float}]}
    """
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
