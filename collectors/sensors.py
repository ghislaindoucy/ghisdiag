"""
Ghisdiag - Source de temperatures unifiee (LibreHardwareMonitor)

Pilote collectors/sensors.ps1, qui charge LibreHardwareMonitorLib.dll embarquee
et expose les capteurs (CPU / GPU / disques / ventilateurs) en JSON normalise.

Trois usages :
  - read_once(timeout)        : un echantillon ponctuel (moniteur temps reel).
  - SensorStream(...)         : daemon persistant, un echantillon par tick,
                                pour le bench thermique (echantillonnage serre).
  - get_temperatures()        : adaptateur au format historique {cpu, gpu, disks}
                                pour brancher directement sur realtime_monitor.

Sur une machine non elevee, les capteurs CPU/carte mere (driver ring0) sont
vides ; GPU et disques remontent quand meme. L'exe Ghisdiag tourne sous UAC.
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
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

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Le dossier des DLL (LibreHardwareMonitor) est resolu dynamiquement par
# lhm_backend : on peut deposer une version plus recente (override) sans
# recompiler, indispensable pour les CPU trop recents pour la DLL livree.
from collectors import lhm_backend


def active_tools_dir() -> Path:
    """Dossier 'tools' actif (override le plus prioritaire, sinon embarque)."""
    return lhm_backend.active_tools_dir()


def lhm_available() -> bool:
    """La DLL et le script sont-ils presents (condition necessaire) ?"""
    return _SCRIPT_PATH.is_file() and (active_tools_dir() / lhm_backend.LIB_NAME).is_file()


def _ps_args(extra: list[str]) -> list[str]:
    # -ToolsDir : impose au script PowerShell le backend resolu cote Python (un
    # seul endroit decide quel jeu de DLL est charge).
    return [
        _PS_EXE, "-NonInteractive", "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(_SCRIPT_PATH), "-ToolsDir", str(active_tools_dir()), *extra,
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

    Un chien de garde (watchdog) surveille le flux : si le backend se fige
    (aucune sortie pendant trop longtemps — cas d'un Open()/Update() bloque sur
    un CPU non supporte), il tue le process et signale l'arret via on_stall, au
    lieu de laisser l'appelant attendre indefiniment.
    """

    def __init__(self, interval_ms: int = 2000, duration_sec: int = 0,
                 on_sample: Optional[Callable[[dict], None]] = None,
                 on_stall: Optional[Callable[[str], None]] = None,
                 startup_grace_sec: float = 25.0,
                 stall_timeout_sec: Optional[float] = None):
        self.interval_ms  = max(250, int(interval_ms))
        self.duration_sec = max(0, int(duration_sec))
        self.on_sample    = on_sample
        self.on_stall     = on_stall
        self._startup_grace = max(5.0, float(startup_grace_sec))
        # Delai sans la moindre sortie au-dela duquel on considere le backend
        # fige (apres demarrage). Defaut : 4 intervalles, minimum 8 s.
        self._stall_timeout = (float(stall_timeout_sec)
                               if stall_timeout_sec is not None
                               else max(8.0, self.interval_ms / 1000.0 * 4))
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._wdog:   Optional[threading.Thread] = None
        self._lock      = threading.Lock()
        self._proc_lock = threading.Lock()
        self._latest: Optional[dict] = None
        self._running = False
        self._stalled = False
        self._stall_reason = ""
        self._start_ts = 0.0
        self._last_line_ts: Optional[float] = None   # derniere sortie (liveness)

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
        self._stalled = False
        self._stall_reason = ""
        self._start_ts = time.monotonic()
        self._last_line_ts = None
        self._thread = threading.Thread(target=self._reader, name="SensorStream", daemon=True)
        self._thread.start()
        self._wdog = threading.Thread(target=self._watchdog, name="SensorWatchdog", daemon=True)
        self._wdog.start()
        return True

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for raw in self._proc.stdout:
                # Toute sortie = backend vivant (meme une ligne invalide).
                self._last_line_ts = time.monotonic()
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
        except Exception:
            logger.debug("SensorStream : lecteur interrompu", exc_info=True)
        finally:
            self._running = False

    def _watchdog(self) -> None:
        """Tue le backend s'il cesse de produire (figeage)."""
        while self._running:
            time.sleep(0.5)
            if not self._running:
                return
            now = time.monotonic()
            if self._last_line_ts is None:
                # Aucune sortie encore : on laisse le delai de demarrage.
                if now - self._start_ts > self._startup_grace:
                    self._trigger_stall(
                        f"aucune donnee capteur en {self._startup_grace:.0f}s "
                        "(backend fige ?)")
                    return
            elif now - self._last_line_ts > self._stall_timeout:
                self._trigger_stall(
                    f"flux interrompu ({self._stall_timeout:.0f}s sans donnee, "
                    "backend fige ?)")
                return

    def _trigger_stall(self, reason: str) -> None:
        if self._stalled:
            return
        self._stalled = True
        self._stall_reason = reason
        logger.warning("SensorStream : %s — arret du backend", reason)
        self._terminate_proc()
        self._running = False
        if self.on_stall is not None:
            try:
                self.on_stall(reason)
            except Exception:
                logger.exception("SensorStream : on_stall a leve")

    def _terminate_proc(self) -> None:
        """Termine le process backend, idempotent et thread-safe."""
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def wait_first_sample(self, timeout: float = 20.0,
                          require_cpu_temp: bool = False) -> bool:
        """Bloque jusqu'au premier echantillon exploitable, ou jusqu'a timeout.

        require_cpu_temp=True exige en plus une temperature CPU (cpu_ref).
        Retourne False si le delai expire ou si le backend s'est fige : permet a
        l'appelant de renoncer proprement plutot que de lancer un long protocole
        sur des capteurs muets.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if self._stalled:
                return False
            s = self.latest()
            if s is not None and (not require_cpu_temp or s.get("cpu_ref") is not None):
                return True
            time.sleep(0.2)
        return False

    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._latest

    @property
    def running(self) -> bool:
        return self._running

    @property
    def stalled(self) -> bool:
        return self._stalled

    @property
    def stall_reason(self) -> str:
        return self._stall_reason

    def stop(self, timeout: float = 3.0) -> None:
        self._running = False
        self._terminate_proc()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._wdog is not None:
            self._wdog.join(timeout=timeout)
            self._wdog = None

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
