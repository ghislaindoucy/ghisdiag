"""
Ghisdiag - Moteur de bench thermique (Phase 1)

Objective un nettoyage / changement de pate thermique en mesurant le
comportement en temperature d'une machine selon un protocole reproductible :

    repos (baseline) -> charge CPU -> refroidissement

Le moteur s'appuie sur collectors.sensors.SensorStream (LibreHardwareMonitor)
pour l'echantillonnage et sur collectors/cpu_load.ps1 pour generer la charge.
Il calcule les metriques utiles (T idle, T max, T plateau, deltaT, temps de
retour au calme, throttling), declenche un arret d'urgence au-dela d'un seuil,
et sauvegarde la session en JSON horodate dans Documents\\Ghisdiag_Reports\\thermal.

Conception : moteur pur (sans UI). Il expose des callbacks (on_sample, on_phase,
on_finish, on_error) appeles depuis des threads de fond ; l'UI (Phase 2) devra
les remarshaller vers le thread tkinter via .after().
"""

import json
import logging
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from collectors.sensors import SensorStream, lhm_available

logger = logging.getLogger(__name__)

# --- Constantes de protocole / metriques -----------------------------------

SCHEMA_VERSION = 1

# Seuil d'arret d'urgence (temperature CPU de reference, en degres C).
DEFAULT_EMERGENCY_TEMP_C = 95.0

# Marge de "retour au calme" : le refroidissement est considere termine quand la
# temperature redescend a T_idle + cette marge.
RECOVERY_MARGIN_C = 5.0

# Marge de securite ajoutee a la duree de charge passee au worker : si le moteur
# disparait, le worker s'auto-arrete quand meme (garde-fou anti-charge infinie).
LOAD_SAFETY_MARGIN_SEC = 30

# Delai d'attente d'un premier echantillon CPU exploitable avant de lancer le
# protocole. Si les capteurs ne repondent pas (backend fige, CPU non supporte),
# on renonce proprement avec un message plutot que de bencher dans le vide.
STREAM_WARMUP_SEC = 20.0

# Detection de throttling : chute relative de frequence entre debut et fin de
# charge, a temperature elevee.
THROTTLE_CLOCK_DROP    = 0.05   # 5 %
THROTTLE_TEMP_FLOOR_C  = 80.0

VALID_LABELS = ("avant", "apres", "libre")


class BenchPhase(Enum):
    IDLE     = "idle"
    LOAD     = "load"
    COOLDOWN = "cooldown"


@dataclass
class BenchConfig:
    """Parametres d'une session de bench."""
    label: str               = "libre"          # avant | apres | libre
    idle_sec: int            = 120               # repos / baseline
    load_sec: int            = 300               # charge CPU
    cooldown_sec: int        = 300               # refroidissement
    intensity: int           = 100               # rapport cyclique 1..100
    threads: int             = 0                 # 0 = tous les coeurs logiques
    kernel: str              = "python"          # python (FPU) | avx (stress numpy)
    sample_interval_ms: int  = 2000              # periode d'echantillonnage
    emergency_temp_c: float  = DEFAULT_EMERGENCY_TEMP_C
    output_dir: Optional[str] = None             # None = dossier standard

    def normalized(self) -> "BenchConfig":
        """Retourne une copie aux valeurs bornees / validees."""
        label = self.label if self.label in VALID_LABELS else "libre"
        kernel = self.kernel if self.kernel in ("python", "avx") else "python"
        return BenchConfig(
            label=label,
            idle_sec=max(0, int(self.idle_sec)),
            load_sec=max(1, int(self.load_sec)),
            cooldown_sec=max(0, int(self.cooldown_sec)),
            intensity=min(100, max(1, int(self.intensity))),
            threads=max(0, int(self.threads)),
            kernel=kernel,
            sample_interval_ms=max(500, int(self.sample_interval_ms)),
            emergency_temp_c=float(self.emergency_temp_c),
            output_dir=self.output_dir,
        )


# --- Resolution des chemins (compatible PyInstaller --onefile) --------------

def _base_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()


def _resolve_python() -> str:
    """Retourne le chemin de Python, ou sys.executable en fallback."""
    return sys.executable


# En version compilee (PyInstaller --onefile), sys.executable pointe vers
# Ghisdiag.exe lui-meme et non un interpreteur Python : lancer
# "Ghisdiag.exe collectors/cpu_load.py ..." ouvrirait une seconde fenetre de
# l'app (les arguments inconnus sont ignores par le point d'entree), pas le
# generateur de charge. Il faut donc relancer l'exe avec un indicateur interne
# (gere dans main.py) qui bascule vers le mode worker sans GUI.
_FROZEN = getattr(sys, "frozen", False)
_CPU_LOAD_WORKER_FLAG = "--ghisdiag-cpu-load-worker"

_PYTHON_EXE   = _resolve_python()
_LOAD_SCRIPT  = _base_path() / "collectors" / "cpu_load.py"
_NO_WINDOW    = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _resolve_taskkill() -> str:
    """Chemin absolu verifie de taskkill.exe (evite le PATH hijacking)."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(sysroot) / "System32" / "taskkill.exe"
    return str(candidate) if candidate.is_file() else "taskkill"


_TASKKILL_EXE = _resolve_taskkill()


def default_output_dir() -> Path:
    """Dossier standard des sessions de bench."""
    return (Path(os.path.expanduser("~")) / "Documents"
            / "Ghisdiag_Reports" / "thermal")


# --- Generateur de charge CPU -----------------------------------------------

class _LoadGenerator:
    """Pilote collectors/cpu_load.py dans un processus dedie."""

    def __init__(self, intensity: int, threads: int, max_duration_sec: int,
                 kernel: str = "python"):
        self.intensity        = intensity
        self.threads          = threads
        self.max_duration_sec = max_duration_sec
        self.kernel           = kernel
        self._proc: Optional[subprocess.Popen] = None

    def available(self) -> bool:
        return _FROZEN or _LOAD_SCRIPT.is_file()

    def start(self) -> bool:
        if not self.available():
            logger.error("cpu_load.py introuvable : %s", _LOAD_SCRIPT)
            return False
        if _FROZEN:
            args = [_PYTHON_EXE, _CPU_LOAD_WORKER_FLAG]
        else:
            args = [_PYTHON_EXE, str(_LOAD_SCRIPT)]
        args += [
            "--threads", str(self.threads),
            "--intensity", str(self.intensity),
            "--duration", str(self.max_duration_sec),
            "--kernel", self.kernel,
        ]
        try:
            self._proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                shell=False, creationflags=_NO_WINDOW,
            )
        except OSError as exc:
            logger.error("Generateur de charge : echec lancement — %s", exc)
            return False
        return True

    def stop(self, timeout: float = 5.0) -> None:
        if self._proc is None:
            return
        pid = self._proc.pid
        try:
            # Tuer tout l'ARBRE de processus. Le worker a lance N sous-processus
            # multiprocessing (les vrais calculateurs) : terminer le seul parent
            # les laisse orphelins, et ils continuent a chauffer le CPU jusqu'a
            # leur echeance (la charge deborderait sur le refroidissement et
            # fausserait les mesures). taskkill /T tue le parent ET ses enfants.
            if os.name == "nt":
                subprocess.run(
                    [_TASKKILL_EXE, "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=timeout, creationflags=_NO_WINDOW,
                )
            else:
                self._proc.terminate()
            self._proc.wait(timeout=timeout)
        except Exception:
            try:
                self._proc.kill()   # ultime recours (ne tue que le parent)
            except Exception:
                pass
        finally:
            self._proc = None


# --- Calcul des metriques (fonctions pures, testables) ----------------------

def _vals(samples: list[dict], key: str) -> list[float]:
    return [s[key] for s in samples if s.get(key) is not None]


def _median(values: list[float]) -> Optional[float]:
    return round(statistics.median(values), 1) if values else None


def _mean(values: list[float]) -> Optional[float]:
    return round(statistics.fmean(values), 1) if values else None


def _max_fan(sample: dict) -> Optional[int]:
    """Ventilateur le plus rapide vu sur l'echantillon (mobo + GPU)."""
    candidates = list(sample.get("fans") or [])
    if sample.get("gpu_fan") is not None:
        candidates.append(sample["gpu_fan"])
    return max(candidates) if candidates else None


def _slice_by_fraction(samples: list[dict], start_f: float, end_f: float) -> list[dict]:
    """Sous-liste d'echantillons par fenetre relative [start_f, end_f] de leur
    temps (t). Utilise pour isoler regime etabli / fin de charge."""
    times = [s["t"] for s in samples]
    if not times:
        return []
    t0, t1 = times[0], times[-1]
    span = t1 - t0
    if span <= 0:
        return list(samples)
    lo = t0 + span * start_f
    hi = t0 + span * end_f
    return [s for s in samples if lo <= s["t"] <= hi]


def compute_metrics(samples: list[dict], config: BenchConfig) -> dict:
    """Derive les metriques de la session a partir des echantillons tagges."""
    idle = [s for s in samples if s["phase"] == BenchPhase.IDLE.value]
    load = [s for s in samples if s["phase"] == BenchPhase.LOAD.value]
    cool = [s for s in samples if s["phase"] == BenchPhase.COOLDOWN.value]

    # T idle : regime etabli (seconde moitie de la phase de repos).
    idle_steady = _slice_by_fraction(idle, 0.5, 1.0) or idle
    idle_c = _median(_vals(idle_steady, "cpu"))

    # Charge.
    load_cpu = _vals(load, "cpu")
    load_max_c     = round(max(load_cpu), 1) if load_cpu else None
    load_plateau_c = _median(_vals(_slice_by_fraction(load, 0.66, 1.0) or load, "cpu"))
    cpu_load_avg   = _mean(_vals(load, "cpu_load"))

    delta_c = (round(load_plateau_c - idle_c, 1)
               if (load_plateau_c is not None and idle_c is not None) else None)

    # GPU (secondaire).
    gpu_idle_c = _median(_vals(idle_steady, "gpu"))
    gpu_vals   = _vals(load, "gpu")
    gpu_max_c  = round(max(gpu_vals), 1) if gpu_vals else None

    # Ventilateurs : repos vs charge (encrassement du ventirad).
    fan_idle_rpm = max((f for s in idle_steady if (f := _max_fan(s)) is not None),
                       default=None)
    fan_load_rpm = max((f for s in load if (f := _max_fan(s)) is not None),
                       default=None)

    # Frequence / throttling : on compare le debut etabli (10-40 %) a la fin
    # (dernier tiers) de la phase de charge.
    clock_early = _median(_vals(_slice_by_fraction(load, 0.10, 0.40), "clock"))
    clock_late  = _median(_vals(_slice_by_fraction(load, 0.66, 1.0), "clock"))
    clock_vals  = _vals(load, "clock")
    clock_max_mhz = round(max(clock_vals)) if clock_vals else None

    throttling = False
    clock_drop_pct = None
    if clock_early and clock_late:
        clock_drop_pct = round((clock_early - clock_late) / clock_early * 100, 1)
        if (clock_late < clock_early * (1 - THROTTLE_CLOCK_DROP)
                and (load_max_c or 0) >= THROTTLE_TEMP_FLOOR_C):
            throttling = True

    # Temps de retour au calme : depuis le debut du refroidissement, delai pour
    # repasser sous T_idle + marge. None si jamais atteint dans la fenetre.
    cooldown_sec = None
    if idle_c is not None and cool:
        target = idle_c + RECOVERY_MARGIN_C
        t_start = cool[0]["t"]
        for s in cool:
            if s.get("cpu") is not None and s["cpu"] <= target:
                cooldown_sec = round(s["t"] - t_start, 1)
                break

    return {
        "idle_c":          idle_c,
        "load_max_c":      load_max_c,
        "load_plateau_c":  load_plateau_c,
        "delta_c":         delta_c,
        "cpu_load_avg":    cpu_load_avg,
        "gpu_idle_c":      gpu_idle_c,
        "gpu_max_c":       gpu_max_c,
        "fan_idle_rpm":    fan_idle_rpm,
        "fan_load_rpm":    fan_load_rpm,
        "clock_max_mhz":   clock_max_mhz,
        "clock_drop_pct":  clock_drop_pct,
        "throttling":      throttling,
        "cooldown_sec":    cooldown_sec,
        "recovery_margin_c": RECOVERY_MARGIN_C,
    }


def _machine_info() -> dict:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "?"
    return {
        "hostname": hostname,
        "cpu":      os.environ.get("PROCESSOR_IDENTIFIER", "?"),
        "cores":    os.cpu_count(),
    }


# --- Persistance ------------------------------------------------------------

def save_session(session: dict, output_dir: Optional[str] = None) -> Path:
    """Ecrit la session en JSON horodate. Retourne le chemin du fichier."""
    base = Path(output_dir) if output_dir else default_output_dir()
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.fromisoformat(session["started_at"]).strftime("%Y%m%d_%H%M%S")
    fname = f"{session.get('label', 'libre')}_{ts}.json"
    path = base / fname
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def list_sessions(output_dir: Optional[str] = None) -> list[dict]:
    """Liste les sessions sauvegardees (resume : fichier, label, date, metriques)."""
    base = Path(output_dir) if output_dir else default_output_dir()
    if not base.is_dir():
        return []
    out = []
    for p in sorted(base.glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({
            "file":        str(p),
            "label":       data.get("label"),
            "started_at":  data.get("started_at"),
            "metrics":     data.get("metrics", {}),
            "aborted":     data.get("aborted", False),
            "emergency":   data.get("emergency", False),
        })
    return out


def load_session(path: str) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- Moteur -----------------------------------------------------------------

@dataclass
class _Callbacks:
    on_sample: Optional[Callable[[dict], None]] = None
    on_phase:  Optional[Callable[[BenchPhase, int, int], None]] = None
    on_finish: Optional[Callable[[dict, Optional[Path]], None]] = None
    on_error:  Optional[Callable[[str], None]] = None


class ThermalBench:
    """Orchestre une session de bench dans un thread de fond.

    Cycle de vie :
        bench = ThermalBench(config, on_sample=..., on_phase=..., on_finish=...)
        bench.start()      # non bloquant
        bench.stop()       # arret demande par l'utilisateur (asynchrone)
    """

    _PHASE_ORDER = (BenchPhase.IDLE, BenchPhase.LOAD, BenchPhase.COOLDOWN)

    def __init__(self, config: BenchConfig,
                 on_sample: Optional[Callable[[dict], None]] = None,
                 on_phase:  Optional[Callable[[BenchPhase, int, int], None]] = None,
                 on_finish: Optional[Callable[[dict, Optional[Path]], None]] = None,
                 on_error:  Optional[Callable[[str], None]] = None):
        self.config = config.normalized()
        self._cb = _Callbacks(on_sample, on_phase, on_finish, on_error)

        self._thread: Optional[threading.Thread] = None
        self._stream: Optional[SensorStream] = None
        self._load:   Optional[_LoadGenerator] = None

        self._cancel = threading.Event()
        self._sensor_stalled = threading.Event()  # backend capteurs fige (watchdog)
        self._stall_msg = ""
        self._emergency = False           # seuil franchi pendant la charge
        self._cooldown_truncated = False
        self._t0 = 0.0
        self._phase = BenchPhase.IDLE
        self._samples: list[dict] = []
        self._started_at = ""
        self._running = False

    # -- API publique --------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True
        if not lhm_available():
            self._error("Capteurs indisponibles (LibreHardwareMonitor absent).")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._run, name="ThermalBench", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        """Demande l'arret. Retour immediat ; finalisation dans le thread."""
        self._cancel.set()

    def join(self, timeout: Optional[float] = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # -- Boucle interne ------------------------------------------------------

    def _run(self) -> None:
        cfg = self.config
        self._t0 = time.monotonic()
        self._started_at = datetime.now().isoformat(timespec="seconds")
        try:
            self._stream = SensorStream(cfg.sample_interval_ms,
                                        on_sample=self._record,
                                        on_stall=self._on_stall)
            if not self._stream.start():
                self._error("Echec du demarrage des capteurs.")
                return

            # Verifier que les capteurs repondent AVANT le protocole : un premier
            # echantillon avec temperature CPU exploitable. Sinon on renonce avec
            # un message clair (backend fige, CPU recent non supporte...) plutot
            # que de lancer 10 minutes de bench dans le vide.
            if not self._stream.wait_first_sample(STREAM_WARMUP_SEC, require_cpu_temp=True):
                self._stream.stop()
                if self._stream.stalled:
                    self._error("Capteurs figes : " + (self._stream.stall_reason
                                or "backend bloque")
                                + ". Lance diagnose_sensors.py pour la cause.")
                elif self._stream.latest() is not None:
                    self._error("Capteurs detectes mais aucune temperature CPU "
                                "exploitable sur cette machine (cpu_ref absent) : "
                                "bench impossible. Voir diagnose_sensors.py / "
                                "diagnose_probe.py.")
                else:
                    self._error("Les capteurs ne repondent pas (aucune donnee en "
                                f"{STREAM_WARMUP_SEC:.0f}s). Voir diagnose_sensors.py.")
                return

            # Phase repos
            self._enter_phase(BenchPhase.IDLE)
            r = self._wait(cfg.idle_sec, watch_emergency=False)
            if r == "cancel":
                self._finalize(aborted=True, reason="Annule pendant le repos")
                return
            if r == "stall":
                self._finalize(aborted=True, reason="Capteurs figes pendant le repos : "
                               + (self._stall_msg or "backend bloque"))
                return

            # Phase charge
            self._enter_phase(BenchPhase.LOAD)
            self._load = _LoadGenerator(
                cfg.intensity, cfg.threads, cfg.load_sec + LOAD_SAFETY_MARGIN_SEC,
                kernel=cfg.kernel)
            if not self._load.start():
                self._finalize(aborted=True, reason="Echec du generateur de charge")
                return
            reason = self._wait(cfg.load_sec, watch_emergency=True)
            self._load.stop()
            if reason == "cancel":
                self._finalize(aborted=True, reason="Annule pendant la charge")
                return
            if reason == "stall":
                # Plus de capteurs sous charge : la charge vient d'etre coupee, on
                # renonce — impossible de surveiller la temperature en securite.
                self._finalize(aborted=True, reason="Capteurs figes pendant la charge : "
                               + (self._stall_msg or "backend bloque"))
                return
            # En arret d'urgence on poursuit vers le refroidissement : la
            # remontee a froid est une donnee precieuse et c'est plus sur.

            # Phase refroidissement
            self._enter_phase(BenchPhase.COOLDOWN)
            if self._wait(cfg.cooldown_sec, watch_emergency=False) in ("cancel", "stall"):
                self._cooldown_truncated = True

            self._finalize(aborted=False, reason=None)

        except Exception as exc:  # garde-fou : on coupe la charge dans le finally
            logger.exception("ThermalBench : erreur interne")
            self._error(f"Erreur interne du bench : {exc}")
        finally:
            if self._load is not None:
                self._load.stop()
            if self._stream is not None:
                self._stream.stop()
            self._running = False

    def _wait(self, seconds: int, watch_emergency: bool) -> str:
        """Attend `seconds`, interruptible.
        Retourne 'done' | 'cancel' | 'emergency' | 'stall'."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._cancel.wait(timeout=0.2):
                return "cancel"
            if self._sensor_stalled.is_set():
                return "stall"
            if watch_emergency and self._emergency:
                return "emergency"
        return "done"

    def _on_stall(self, reason: str) -> None:
        """Callback SensorStream : le backend capteurs s'est fige."""
        self._stall_msg = reason
        self._sensor_stalled.set()
        logger.warning("ThermalBench : capteurs figes — %s", reason)

    def _enter_phase(self, phase: BenchPhase) -> None:
        self._phase = phase
        idx = self._PHASE_ORDER.index(phase) + 1
        self._invoke(self._cb.on_phase, phase, idx, len(self._PHASE_ORDER))

    def _record(self, sample: dict) -> None:
        """Callback SensorStream (thread lecteur) : tag + stockage + emergency."""
        if not self._running:
            return
        rec = {
            "t":        round(time.monotonic() - self._t0, 2),
            "phase":    self._phase.value,
            "cpu":      sample.get("cpu_ref"),
            "cpu_pkg":  sample.get("cpu_pkg"),
            "cpu_max":  sample.get("cpu_max"),
            "cpu_load": sample.get("cpu_load"),
            "clock":    sample.get("cpu_clock_max"),
            "gpu":      sample.get("gpu_temp"),
            "gpu_load": sample.get("gpu_load"),
            "gpu_fan":  sample.get("gpu_fan"),
            "fans":     list(sample.get("fans") or []),
            "disks":    sample.get("disks") or [],
        }
        self._samples.append(rec)

        # Arret d'urgence : seuil franchi pendant la charge.
        if (self._phase == BenchPhase.LOAD and rec["cpu"] is not None
                and rec["cpu"] >= self.config.emergency_temp_c):
            self._emergency = True

        self._invoke(self._cb.on_sample, rec)

    def _finalize(self, aborted: bool, reason: Optional[str]) -> None:
        metrics = compute_metrics(self._samples, self.config)
        session = {
            "version":     SCHEMA_VERSION,
            "label":       self.config.label,
            "started_at":  self._started_at,
            "duration_sec": round(time.monotonic() - self._t0, 1),
            "machine":     _machine_info(),
            "config":      asdict(self.config),
            "aborted":     aborted,
            "emergency":   self._emergency,
            "cooldown_truncated": self._cooldown_truncated,
            "abort_reason": reason,
            "metrics":     metrics,
            "samples":     self._samples,
        }
        path = None
        try:
            path = save_session(session, self.config.output_dir)
        except OSError as exc:
            logger.warning("Bench : echec sauvegarde session — %s", exc)
        self._invoke(self._cb.on_finish, session, path)

    # -- Utilitaire callbacks ------------------------------------------------

    @staticmethod
    def _invoke(cb, *args) -> None:
        if cb is None:
            return
        try:
            cb(*args)
        except Exception:
            logger.exception("ThermalBench : callback a leve")

    def _error(self, message: str) -> None:
        self._running = False
        logger.error("ThermalBench : %s", message)
        self._invoke(self._cb.on_error, message)
