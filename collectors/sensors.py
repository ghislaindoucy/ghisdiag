"""
PlanetDiag - Source de temperatures unifiee (LibreHardwareMonitor)

Pilote collectors/sensors.ps1, qui charge LibreHardwareMonitorLib.dll embarquee
et expose les capteurs (CPU / GPU / disques / ventilateurs) en JSON normalise.

Trois usages :
  - read_once(timeout)        : un echantillon ponctuel (moniteur temps reel).
  - SensorStream(...)         : daemon persistant, un echantillon par tick,
                                pour le bench thermique (echantillonnage serre).
  - get_temperatures()        : adaptateur au format historique {cpu, gpu, disks}
                                pour brancher directement sur realtime_monitor.

Sur une machine non elevee, les capteurs CPU/carte mere (driver ring0) sont
vides ; GPU et disques remontent quand meme. L'exe PlanetDiag tourne sous UAC.
"""

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Schema d'un echantillon (cle -> type) tel qu'emis par sensors.ps1 :
#   ts, ok, cpu_pkg, cpu_max, cpu_avg, cpu_ref, cpu_load, cpu_clock_max,
#   gpu_temp, gpu_hotspot, gpu_load, gpu_fan, fans[int], disks[{n, t}]


def _base_path() -> Path:
    """Repertoire de base — supporte PyInstaller --onefile (_MEIPASS)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    # collectors/sensors.py -> racine du projet
    return Path(__file__).parent.parent.resolve()


def _resolve_powershell() -> str:
    """Chemin absolu verifie de powershell.exe (evite le PATH hijacking)."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(candidate) if candidate.is_file() else "powershell.exe"


_PS_EXE      = _resolve_powershell()
_SCRIPT_PATH = _base_path() / "collectors" / "sensors.ps1"
_DLL_PATH    = _base_path() / "tools" / "LibreHardwareMonitorLib.dll"

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def lhm_available() -> bool:
    """La DLL et le script sont-ils presents (condition necessaire) ?"""
    return _SCRIPT_PATH.is_file() and _DLL_PATH.is_file()


def _ps_args(extra: list[str]) -> list[str]:
    return [
        _PS_EXE, "-NonInteractive", "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(_SCRIPT_PATH), *extra,
    ]


def read_once(timeout: float = 10.0) -> Optional[dict]:
    """Lit un echantillon unique. Retourne le dict, ou None si indisponible."""
    if not lhm_available():
        return None
    try:
        proc = subprocess.run(
            _ps_args(["-Once"]),
            capture_output=True, timeout=timeout, shell=False,
            creationflags=_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if not out:
            return None
        # -Once n'emet qu'une ligne ; par prudence on prend la derniere non vide.
        line = [l for l in out.splitlines() if l.strip()][-1]
        sample = json.loads(line)
        if isinstance(sample, dict) and sample.get("ok"):
            return sample
        return None
    except Exception as exc:
        logger.debug("sensors.read_once : %s", exc)
        return None


class SensorStream:
    """Daemon de capteurs persistant : lance sensors.ps1 en streaming et lit
    les echantillons ligne par ligne dans un thread de fond.

    on_sample(dict) est appele pour chaque echantillon (dans le thread lecteur).
    latest() retourne le dernier echantillon recu (thread-safe), ou None.
    """

    def __init__(self, interval_ms: int = 2000, duration_sec: int = 0,
                 on_sample: Optional[Callable[[dict], None]] = None):
        self.interval_ms  = max(250, int(interval_ms))
        self.duration_sec = max(0, int(duration_sec))
        self.on_sample    = on_sample
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._lock    = threading.Lock()
        self._latest: Optional[dict] = None
        self._running = False

    def start(self) -> bool:
        if not lhm_available():
            logger.warning("SensorStream : LHM indisponible")
            return False
        if self._running:
            return True
        args = _ps_args([
            "-IntervalMs", str(self.interval_ms),
            "-DurationSec", str(self.duration_sec),
        ])
        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                shell=False, creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            logger.error("SensorStream : echec lancement — %s", exc)
            return False
        self._running = True
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()
        return True

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for raw in self._proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    sample = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not (isinstance(sample, dict) and sample.get("ok")):
                    continue
                with self._lock:
                    self._latest = sample
                if self.on_sample is not None:
                    try:
                        self.on_sample(sample)
                    except Exception:
                        logger.exception("SensorStream : on_sample a leve")
        finally:
            self._running = False

    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._latest

    @property
    def running(self) -> bool:
        return self._running

    def stop(self, timeout: float = 3.0) -> None:
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=timeout)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def __enter__(self) -> "SensorStream":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()


def get_temperatures() -> Optional[dict]:
    """Adaptateur au format historique attendu par realtime_monitor :
        {"cpu": float|None, "gpu": float|None,
         "disks": [{"model": str, "temp": float}]}
    Retourne None si LHM indisponible (l'appelant bascule sur le fallback WMI).
    """
    sample = read_once()
    if sample is None:
        return None
    disks = []
    for d in sample.get("disks") or []:
        if isinstance(d, dict) and d.get("t") is not None:
            disks.append({"model": d.get("n", "?"), "temp": d.get("t")})
    return {
        "cpu":   sample.get("cpu_ref"),
        "gpu":   sample.get("gpu_temp"),
        "disks": disks,
    }
