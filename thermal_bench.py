"""
Ghisdiag - Moteur de bench thermique

Objective un nettoyage / changement de pate thermique en mesurant le
comportement en temperature d'une machine selon un protocole reproductible :

    repos (baseline) -> charge (CPU ou GPU) -> refroidissement

Le moteur s'appuie sur collectors.sensors.SensorStream (LibreHardwareMonitor)
pour l'echantillonnage et sur un generateur de charge selon la cible :
collectors/cpu_load.py (multiprocessing) ou collectors/gpu_load.py (compute
D3D11). En cible GPU, les echantillons sont enrichis via NVML quand disponible
(clock/power/raison de bridage fiables sous charge, la ou LHM peut rester fige
sur NVIDIA). Il calcule les metriques utiles (T idle, T max, T plateau, deltaT,
temps de retour au calme, throttling), declenche un arret d'urgence au-dela d'un
seuil (dynamique cote GPU : seuil slowdown NVML), et sauvegarde la session en
JSON horodate dans Documents\\Ghisdiag_Reports\\thermal.

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

# v2 : `throttling` / `power_limited` (et leurs equivalents GPU) sont passes en
# TRI-ETAT — True / False / None, None = pas mesurable. En v1 ils valaient False
# par defaut, y compris quand aucune frequence n'avait ete relevee. Les sessions
# v1 restent lisibles : throttling_state() requalifie ce False-par-defaut.
SCHEMA_VERSION = 2

# Seuil d'arret d'urgence (temperature CPU de reference, en degres C).
DEFAULT_EMERGENCY_TEMP_C = 95.0

# Surcharge d'atelier du seuil d'urgence, par variable d'environnement.
#
# Pourquoi : sur un portable Intel P-series, le CPU passe sa premiere minute de
# charge dans sa fenetre turbo (PL2), bien au-dessus de sa puissance soutenue —
# vu en atelier : 40 W pour un PL1 de 28 W, 96 C atteints en 31 s sur un
# i5-1240P dont le TjMax est 100. Couper a 95 C interdit alors d'atteindre le
# regime etabli, c'est-a-dire precisement ce que le bench doit mesurer.
#
# Borne haute a 99 C : on reste sous le TjMax des CPU actuels (100 C). Le CPU se
# protege seul de toute facon (bridage a TjMax, coupure materielle au-dela) —
# cette surcharge ne desactive aucune securite materielle, elle repousse
# seulement le garde-fou LOGICIEL de Ghisdiag.
EMERGENCY_TEMP_ENV     = "GHISDIAG_EMERGENCY_TEMP_C"
EMERGENCY_TEMP_MIN_C   = 60.0
EMERGENCY_TEMP_MAX_C   = 99.0


def _default_emergency_temp() -> float:
    """Seuil d'urgence CPU : valeur par defaut, ou surcharge d'environnement
    bornee. Toute valeur illisible ou hors bornes retombe sur le defaut."""
    raw = os.environ.get(EMERGENCY_TEMP_ENV, "").strip()
    if not raw:
        return DEFAULT_EMERGENCY_TEMP_C
    try:
        val = float(raw.replace(",", "."))
    except ValueError:
        logger.warning("%s=%r illisible — seuil par defaut (%.0f C).",
                       EMERGENCY_TEMP_ENV, raw, DEFAULT_EMERGENCY_TEMP_C)
        return DEFAULT_EMERGENCY_TEMP_C
    if not (EMERGENCY_TEMP_MIN_C <= val <= EMERGENCY_TEMP_MAX_C):
        logger.warning("%s=%.0f hors bornes [%.0f, %.0f] — seuil par defaut.",
                       EMERGENCY_TEMP_ENV, val,
                       EMERGENCY_TEMP_MIN_C, EMERGENCY_TEMP_MAX_C)
        return DEFAULT_EMERGENCY_TEMP_C
    logger.warning("Seuil d'arret d'urgence force a %.0f C par %s.",
                   val, EMERGENCY_TEMP_ENV)
    return val

# Seuil d'arret d'urgence GPU par defaut. Quand NVML expose le seuil slowdown du
# GPU (`temp_slowdown_c`), le seuil effectif devient min(ce plafond, slowdown -
# GPU_SLOWDOWN_MARGIN_C) : on coupe AVANT que la carte ne se bride d'elle-meme.
DEFAULT_GPU_EMERGENCY_TEMP_C = 90.0
GPU_SLOWDOWN_MARGIN_C = 3.0

# Le bit NVML `throttle_thermal` peut etre TRUE au repos sur certaines cartes
# (vu en atelier : RTX 4060 a 47 C / 0 % de charge). On ne le croit que si la
# temperature est PROCHE du seuil slowdown : slowdown - GPU_THROTTLE_PROX_C,
# ou a defaut (slowdown inconnu) au-dessus d'un plancher absolu.
GPU_THROTTLE_PROX_C         = 10.0
GPU_THROTTLE_TEMP_FLOOR_C   = 75.0

# Classification des raisons de bridage NVML pour le bench. hw_slowdown (clocks
# divisees par 2 par un signal materiel) est range cote THERMIQUE : c'est
# precisement le "clock qui chute" qu'on cherche — mais comme sw/hw_thermal, il
# n'est cru que temperature a l'appui (voir _gpu_throttle_floor). Unique source
# de verite pour l'urgence ET les metriques (pas le bool throttle_thermal de
# collectors.gpu, qui exclut hw_slowdown).
GPU_THERMAL_REASONS = frozenset({"sw_thermal", "hw_thermal", "hw_slowdown"})
GPU_POWER_REASONS   = frozenset({"sw_power_cap", "hw_power_brake"})


def _gpu_throttle_floor(slowdown_c) -> float:
    """Temperature minimale pour CROIRE un signal thermique NVML (le bit peut
    etre vrai au repos). slowdown_c falsy (None ou 0 = valeur invalide d'un
    driver) -> plancher absolu. Partage entre urgence et metriques : les deux
    doivent qualifier « proche du slowdown » de la meme facon."""
    return slowdown_c - GPU_THROTTLE_PROX_C if slowdown_c else GPU_THROTTLE_TEMP_FLOOR_C


# Fenetres relatives de decoupage de la phase de charge, partagees CPU/GPU :
# regime etabli (plateau / fin de charge) et debut etabli (apres la montee).
STEADY_WINDOW = (0.66, 1.0)
EARLY_WINDOW  = (0.10, 0.40)

# Debut BRUT de la charge : la fenetre turbo (Intel PL2, "tau"), avant que le CPU
# ne retombe sur sa puissance soutenue. EARLY_WINDOW commence deja apres — c'est
# voulu pour la detection de throttling thermique, mais ca rend la limite de
# PUISSANCE invisible : sur une charge de 300 s, a 10 % (30 s) le CPU est deja
# retombe a PL1. Il faut donc comparer le regime etabli a CETTE fenetre-ci.
BURST_WINDOW  = (0.0, 0.10)

# Fraction de la duree de charge PREVUE en dessous de laquelle la phase de charge
# est jugee ecourtee : le regime etabli n'a pas eu le temps de s'installer, et
# tout ce qu'on appellerait « plateau » n'est que le sommet d'une rampe.
LOAD_COMPLETE_FRACTION = 0.9

# Charge CPU (%) a partir de laquelle le generateur est considere comme
# reellement en train de tourner. Le lancement n'est PAS instantane : vu en
# atelier sur un MSI (Core Ultra), 39 s se sont ecoulees entre le debut de la
# phase et la premiere seconde a 100 % — le CPU y etait a 603 MHz, au repos.
# Decouper les fenetres de frequence sur le debut de la PHASE ferait alors
# porter le « burst turbo » sur une machine inactive.
LOAD_ACTIVE_PCT = 90.0

# Retard de demarrage au-dela duquel il vaut la peine de le signaler : le temps
# perdu ampute d'autant le regime etabli reellement observe.
LOAD_RAMP_WARN_SEC = 10.0

# Charge CPU (%) au-dela de laquelle la phase de repos ne mesure plus un repos.
#
# Vu en atelier (Altyk, 27/07/2026) : 16,5 % de charge CPU mediane pendant la
# phase de reference — maintenance Windows post-demarrage, analyse Defender. La
# temperature dite « de repos » en ressort surevaluee, donc le deltaT
# sous-evalue, et rien ne le signalait : c'est le point de depart de TOUTES les
# comparaisons du bench qui etait fausse en silence.
#
# 10 % : une machine reellement au repos tourne sous les 5 % ; au-dela de 10 %
# quelque chose travaille, et la reference n'est plus une reference.
IDLE_LOAD_MAX_PCT = 10.0

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

# Detection de throttling THERMIQUE : chute relative de frequence entre debut et
# fin de charge, a temperature elevee.
#
# Le plancher de temperature doit rester PROCHE du TjMax (~100 C sur Intel/AMD
# recents) : sinon on confond le throttling thermique (vrai probleme de
# refroidissement) avec la baisse de frequence NORMALE de fin de turbo court
# (Intel PL2->PL1, "Tau"), qui survient apres ~30 s de charge a n'importe quelle
# temperature. A 75-85 C un CPU n'est pas thermiquement limite : il applique sa
# limite de puissance soutenue, ce n'est pas un defaut.
THROTTLE_CLOCK_DROP    = 0.05   # 5 %
THROTTLE_TEMP_FLOOR_C  = 90.0   # en-dessous : limite de puissance, pas thermique

VALID_LABELS  = ("avant", "apres", "libre")
VALID_TARGETS = ("cpu", "gpu")


class BenchPhase(Enum):
    IDLE     = "idle"
    LOAD     = "load"
    COOLDOWN = "cooldown"


@dataclass
class BenchConfig:
    """Parametres d'une session de bench."""
    label: str               = "libre"          # avant | apres | libre
    idle_sec: int            = 120               # repos / baseline
    load_sec: int            = 300               # charge
    cooldown_sec: int        = 300               # refroidissement
    intensity: int           = 100               # rapport cyclique 1..100
    threads: int             = 0                 # 0 = tous les coeurs logiques (cpu)
    kernel: str              = "python"          # python (FPU) | avx (stress numpy)
    sample_interval_ms: int  = 2000              # periode d'echantillonnage
    # default_factory : la surcharge d'environnement doit etre lue au moment ou
    # la config est construite, pas a l'import du module.
    emergency_temp_c: float  = field(default_factory=_default_emergency_temp)
    output_dir: Optional[str] = None             # None = dossier standard
    target: str              = "cpu"             # cpu | gpu
    gpu_adapter: Optional[str] = None            # index ou sous-chaine du nom
                                                 # (None = dGPU le plus gros)
    gpu_emergency_temp_c: float = DEFAULT_GPU_EMERGENCY_TEMP_C

    def normalized(self) -> "BenchConfig":
        """Retourne une copie aux valeurs bornees / validees."""
        label = self.label if self.label in VALID_LABELS else "libre"
        kernel = self.kernel if self.kernel in ("python", "avx") else "python"
        target = self.target if self.target in VALID_TARGETS else "cpu"
        return BenchConfig(
            label=label,
            idle_sec=max(0, int(self.idle_sec)),
            load_sec=max(1, int(self.load_sec)),
            cooldown_sec=max(0, int(self.cooldown_sec)),
            intensity=min(100, max(1, int(self.intensity))),
            threads=max(0, int(self.threads)),
            kernel=kernel,
            sample_interval_ms=max(500, int(self.sample_interval_ms)),
            # Borne aussi une valeur passee explicitement : personne ne doit
            # pouvoir demander un garde-fou au-dela du TjMax.
            emergency_temp_c=min(EMERGENCY_TEMP_MAX_C,
                                 max(EMERGENCY_TEMP_MIN_C,
                                     float(self.emergency_temp_c))),
            output_dir=self.output_dir,
            target=target,
            gpu_adapter=self.gpu_adapter,
            gpu_emergency_temp_c=float(self.gpu_emergency_temp_c),
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
_GPU_LOAD_WORKER_FLAG = "--ghisdiag-gpu-load-worker"

_PYTHON_EXE      = _resolve_python()
_LOAD_SCRIPT     = _base_path() / "collectors" / "cpu_load.py"
_GPU_LOAD_SCRIPT = _base_path() / "collectors" / "gpu_load.py"
_NO_WINDOW       = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


# --- Generateurs de charge (CPU / GPU) ---------------------------------------

class _ILoadGenerator:
    """Interface d'un generateur de charge : un processus worker dedie.

    Les implementations fournissent available() et _build_args() ; le
    lancement (Popen sans fenetre) et l'arret (taskkill de l'ARBRE de
    processus) sont communs.
    """

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None

    def available(self) -> bool:
        raise NotImplementedError

    def _build_args(self) -> list[str]:
        raise NotImplementedError

    def _unavailable_hint(self) -> str:
        return ""

    def start(self) -> bool:
        if not self.available():
            logger.error("%s : generateur de charge indisponible. %s",
                         type(self).__name__, self._unavailable_hint())
            return False
        try:
            self._proc = subprocess.Popen(
                self._build_args(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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


class _CpuLoadGenerator(_ILoadGenerator):
    """Pilote collectors/cpu_load.py (multiprocessing, un worker par coeur)."""

    def __init__(self, intensity: int, threads: int, max_duration_sec: int,
                 kernel: str = "python"):
        super().__init__()
        self.intensity        = intensity
        self.threads          = threads
        self.max_duration_sec = max_duration_sec
        self.kernel           = kernel

    def available(self) -> bool:
        return _FROZEN or _LOAD_SCRIPT.is_file()

    def _unavailable_hint(self) -> str:
        return f"Script attendu : {_LOAD_SCRIPT}"

    def _build_args(self) -> list[str]:
        if _FROZEN:
            args = [_PYTHON_EXE, _CPU_LOAD_WORKER_FLAG]
        else:
            args = [_PYTHON_EXE, str(_LOAD_SCRIPT)]
        return args + [
            "--threads", str(self.threads),
            "--intensity", str(self.intensity),
            "--duration", str(self.max_duration_sec),
            "--kernel", self.kernel,
        ]


# Retro-compatibilite : ancien nom du generateur CPU.
_LoadGenerator = _CpuLoadGenerator


class _GpuLoadGenerator(_ILoadGenerator):
    """Pilote collectors/gpu_load.py (compute D3D11, processus unique).

    `adapter_selector` : index DXGI (resolu en amont par le moteur pour
    stresser exactement l'adaptateur mesure) ou sous-chaine du nom.
    """

    def __init__(self, intensity: int, adapter_selector, max_duration_sec: int):
        super().__init__()
        self.intensity        = intensity
        self.adapter_selector = adapter_selector
        self.max_duration_sec = max_duration_sec

    def available(self) -> bool:
        if not (_FROZEN or _GPU_LOAD_SCRIPT.is_file()):
            return False
        try:
            from collectors import gpu_load
            return gpu_load.available()
        except Exception:
            return False

    def _unavailable_hint(self) -> str:
        return (f"Script attendu : {_GPU_LOAD_SCRIPT} + DLL systeme "
                "d3d11/dxgi/d3dcompiler_47")

    def _build_args(self) -> list[str]:
        if _FROZEN:
            args = [_PYTHON_EXE, _GPU_LOAD_WORKER_FLAG]
        else:
            args = [_PYTHON_EXE, str(_GPU_LOAD_SCRIPT)]
        args += [
            "--intensity", str(self.intensity),
            "--duration", str(self.max_duration_sec),
        ]
        if self.adapter_selector is not None and str(self.adapter_selector) != "":
            args += ["--adapter", str(self.adapter_selector)]
        return args


def _make_generator(cfg: "BenchConfig", gpu_info: Optional[dict] = None) -> _ILoadGenerator:
    """Instancie le generateur correspondant a la cible du bench."""
    max_duration = cfg.load_sec + LOAD_SAFETY_MARGIN_SEC
    if cfg.target == "gpu":
        selector = gpu_info["index"] if gpu_info is not None else cfg.gpu_adapter
        return _GpuLoadGenerator(cfg.intensity, selector, max_duration)
    return _CpuLoadGenerator(cfg.intensity, cfg.threads, max_duration,
                             kernel=cfg.kernel)


# --- Cible GPU : resolution d'adaptateur + lecture NVML ----------------------

def _resolve_gpu_adapter(selector) -> Optional[dict]:
    """Adaptateur DXGI MATERIEL a bencher (index/nom/None = auto).
    None si la charge D3D11 est indisponible ou aucun adaptateur materiel."""
    try:
        from collectors import gpu_load
        if not gpu_load.available():
            return None
        sel = selector
        if isinstance(sel, str) and sel.isdigit():
            sel = int(sel)
        return gpu_load._match_adapter(gpu_load.list_adapters(), sel)
    except Exception as exc:
        logger.debug("thermal_bench._resolve_gpu_adapter : %s", exc)
        return None


class _NvmlGpuSampler:
    """Lecture NVML du GPU cible, appelee a chaque echantillon.

    Sous charge NVIDIA, la clock lue par LHM peut rester FIGEE (vu en atelier :
    RTX 4060 lue a 100 MHz malgre 99 % de charge) : clock/power/raison de
    bridage doivent venir de NVML. open() etablit UNE session NVML persistante
    (collectors.gpu.NvmlDevice : jointure par nom DXGI<->NVML, handle fige) —
    pas de rechargement DLL / nvmlInit a chaque sample sur le thread capteurs.
    Sur AMD/Intel (pas de NVML), open() echoue et read() rend None : le moteur
    retombe sur le flux LHM.
    """

    def __init__(self, adapter_name: str):
        self._name = adapter_name or ""
        self._dev = None
        self._warned = False

    def open(self) -> bool:
        try:
            from collectors import gpu as gpu_mod
            self._dev = gpu_mod.NvmlDevice.open_matching(self._name)
        except Exception as exc:
            logger.debug("NvmlGpuSampler.open : %s", exc)
            self._dev = None
        return self._dev is not None

    def read(self) -> Optional[dict]:
        if self._dev is None:
            return None
        try:
            return self._dev.sample()
        except Exception as exc:
            # Panne NVML en cours de bench : signaler UNE fois (sinon le repli
            # LHM silencieux masquerait une integration cassee), puis continuer.
            if not self._warned:
                self._warned = True
                logger.warning("Lecture NVML echouee en cours de bench (%s) — "
                               "repli sur les capteurs LHM.", exc)
            return None

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None


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


def _effective_load(load: list[dict]) -> list[dict]:
    """Echantillons a partir du moment ou le CPU est REELLEMENT charge.

    Toutes les fenetres de frequence (burst / debut etabli / regime etabli) se
    decoupent la-dessus, et non sur la phase de charge brute : le generateur
    peut mettre des dizaines de secondes a demarrer, et ces secondes-la ne
    disent rien de la machine sous charge.

    Repli sur la phase entiere si aucun echantillon n'atteint le seuil (charge
    CPU non lue, ou generateur qui n'a jamais demarre) : mieux vaut une fenetre
    imparfaite que pas de mesure du tout.
    """
    for i, s in enumerate(load):
        if (s.get("cpu_load") or 0) >= LOAD_ACTIVE_PCT:
            return load[i:]
    return load


def phase_duration(samples: list[dict], phase: str) -> Optional[float]:
    """Duree REELLE d'une phase, mesuree sur les echantillons — par opposition a
    la config, qui ne dit que ce qui etait prevu. None si moins de 2 points."""
    ts = [s["t"] for s in samples
          if s.get("phase") == phase and s.get("t") is not None]
    return round(max(ts) - min(ts), 1) if len(ts) >= 2 else None


def idle_load_pct(samples: list[dict]) -> Optional[float]:
    """Charge CPU mediane pendant la REFERENCE de repos, en %.

    Meme fenetre que `idle_c` (seconde moitie de la phase de repos) : la
    question posee est « la temperature de reference a-t-elle ete prise sur une
    machine reellement au repos ? ». Fonction publique : la comparaison s'en
    sert pour requalifier les sessions archivees, qui n'ont pas la metrique.
    """
    idle = [s for s in samples if s.get("phase") == BenchPhase.IDLE.value]
    return _median(_vals(_slice_by_fraction(idle, 0.5, 1.0) or idle, "cpu_load"))


def idle_polluted(load_pct: Optional[float]) -> bool:
    """True si la phase de repos etait trop chargee pour servir de reference.

    Unique lecture autorisee du seuil : UI, comparaison et metriques passent
    toutes par ici, pour qu'un seul chiffre fasse foi.
    """
    return bool(load_pct is not None and load_pct > IDLE_LOAD_MAX_PCT)


def _time_to_recover(cool: list[dict], baseline_c: Optional[float],
                     key: str) -> Optional[float]:
    """Delai (s) depuis le debut du refroidissement pour repasser sous
    baseline + RECOVERY_MARGIN_C sur la cle `key`. None si jamais atteint."""
    if baseline_c is None or not cool:
        return None
    target = baseline_c + RECOVERY_MARGIN_C
    t_start = cool[0]["t"]
    for s in cool:
        if s.get(key) is not None and s[key] <= target:
            return round(s["t"] - t_start, 1)
    return None


def compute_metrics(samples: list[dict], config: BenchConfig) -> dict:
    """Derive les metriques de la session a partir des echantillons tagges."""
    idle = [s for s in samples if s["phase"] == BenchPhase.IDLE.value]
    load = [s for s in samples if s["phase"] == BenchPhase.LOAD.value]
    cool = [s for s in samples if s["phase"] == BenchPhase.COOLDOWN.value]

    # T idle : regime etabli (seconde moitie de la phase de repos).
    idle_steady = _slice_by_fraction(idle, 0.5, 1.0) or idle
    idle_c = _median(_vals(idle_steady, "cpu"))

    # REPOS POLLUE : la reference n'en est pas une.
    #
    # Tout le bench se lit par rapport a cette temperature de depart. Si la
    # machine travaillait pendant qu'on la mesurait (maintenance Windows,
    # analyse antivirus, application restee ouverte), `idle_c` est trop haut et
    # le deltaT trop bas — la mesure existe, mais elle decrit autre chose que ce
    # qu'on croit lire. On garde les valeurs (le deltaT reste un MINORANT
    # exploitable, contrairement au plateau d'une charge ecourtee qui, lui,
    # n'a jamais existe) et on le dit.
    idle_load_avg_pct = idle_load_pct(samples)
    idle_dirty = idle_polluted(idle_load_avg_pct)

    # Charge.
    load_cpu = _vals(load, "cpu")
    load_max_c     = round(max(load_cpu), 1) if load_cpu else None
    load_plateau_c = _median(_vals(_slice_by_fraction(load, *STEADY_WINDOW) or load, "cpu"))
    cpu_load_avg   = _mean(_vals(load, "cpu_load"))

    delta_c = (round(load_plateau_c - idle_c, 1)
               if (load_plateau_c is not None and idle_c is not None) else None)

    # CHARGE ECOURTEE : plateau et deltaT n'ont plus de sens.
    #
    # STEADY_WINDOW prend le dernier tiers de la phase de charge. Sur une charge
    # menee a son terme, c'est le regime etabli. Sur une charge coupee au bout de
    # 25 s sur 300 prevues (arret d'urgence, vu en atelier), ce « dernier tiers »
    # n'est que le sommet d'une rampe 62 -> 96 C : le publier comme « plateau »
    # revient a inventer un regime etabli qui n'a jamais existe — et deltaT en
    # herite. On les met a None plutot que de mentir. load_max_c, lui, RESTE
    # valide : le pic a bien ete atteint, c'est meme lui qui a coupe le test.
    load_sec_cfg  = int(getattr(config, "load_sec", 0) or 0)
    load_sec_real = phase_duration(samples, BenchPhase.LOAD.value)
    load_truncated = bool(load_sec_real is not None and load_sec_cfg > 0
                          and load_sec_real < load_sec_cfg * LOAD_COMPLETE_FRACTION)
    if load_truncated:
        load_plateau_c = None
        delta_c = None

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
    # (dernier tiers) de la charge REELLE — voir _effective_load.
    load_eff = _effective_load(load)
    load_ramp_sec = (round(load_eff[0]["t"] - load[0]["t"], 1)
                     if load and load_eff and load_eff is not load else 0.0)
    clock_early = _median(_vals(_slice_by_fraction(load_eff, *EARLY_WINDOW), "clock"))
    clock_late  = _median(_vals(_slice_by_fraction(load_eff, *STEADY_WINDOW), "clock"))
    clock_vals  = _vals(load_eff, "clock")
    clock_max_mhz = round(max(clock_vals)) if clock_vals else None

    # TRI-ETAT VOULU : None = "on n'a pas pu mesurer", et surtout PAS False.
    # Ces deux drapeaux se deduisent UNIQUEMENT d'une comparaison de frequences ;
    # sans frequence exploitable il n'y a rien a conclure. Ils valaient False par
    # defaut jusqu'ici : sur une machine qui ne remonte aucune frequence (vu en
    # atelier sur Alder Lake-P, `clock: null` du debut a la fin), le rapport
    # affirmait « throttling : non » sans avoir rien mesure — un outil de
    # diagnostic qui rassure a tort. Tout consommateur doit distinguer les trois
    # cas (oui / non / indetermine) et ne jamais faire `bool(...)` dessus.
    throttling: Optional[bool] = None
    power_limited: Optional[bool] = None
    clock_drop_pct = None
    if clock_early and clock_late:
        throttling = False
        power_limited = False
        clock_drop_pct = round((clock_early - clock_late) / clock_early * 100, 1)
        if clock_late < clock_early * (1 - THROTTLE_CLOCK_DROP):
            # Chute de frequence soutenue. A haute temperature (proche du TjMax)
            # = throttling THERMIQUE (vrai souci de refroidissement). A
            # temperature moderee = limite de PUISSANCE (Intel PL1 / TDP, AMD
            # PPT) : le CPU bride sa puissance soutenue, c'est NORMAL et ca
            # explique pourquoi la temperature plafonne sans monter davantage.
            if (load_max_c or 0) >= THROTTLE_TEMP_FLOOR_C:
                throttling = True
            else:
                power_limited = True

    # Limite de puissance (PL1 / TDP) : comparer le BURST turbo au regime etabli.
    #
    # La comparaison ci-dessus (debut etabli vs fin) ne peut PAS la voir : a 10 %
    # d'une charge de 300 s, le CPU est deja retombe sur sa puissance soutenue,
    # donc les deux fenetres montrent la meme frequence et `clock_drop_pct` vaut
    # 0. Mesure atelier sur i5-1240P : 2715 MHz pendant le burst, 2112 MHz en
    # regime etabli (-22 %) a 28,1 W pile — soit son PL1 — et HWiNFO signalait la
    # limite de puissance sur 100 % du regime etabli quand Ghisdiag rendait
    # `power_limited: false`.
    #
    # La temperature de reference est celle du PLATEAU, pas le maximum : le pic
    # appartient au burst turbo, le classer thermique ferait passer un bridage de
    # puissance parfaitement normal pour un defaut de refroidissement.
    clock_burst = _median(_vals(_slice_by_fraction(load_eff, *BURST_WINDOW), "clock"))
    clock_burst_drop_pct = None
    if clock_burst and clock_late:
        clock_burst_drop_pct = round((clock_burst - clock_late) / clock_burst * 100, 1)
        if (power_limited is False and not throttling
                and clock_late < clock_burst * (1 - THROTTLE_CLOCK_DROP)
                and load_plateau_c is not None
                and load_plateau_c < THROTTLE_TEMP_FLOOR_C):
            power_limited = True

    # Temps de retour au calme : depuis le debut du refroidissement, delai pour
    # repasser sous T_idle + marge. None si jamais atteint dans la fenetre.
    cooldown_sec = _time_to_recover(cool, idle_c, "cpu")

    metrics = {
        "idle_c":          idle_c,
        "idle_load_pct":   idle_load_avg_pct,  # charge CPU pendant la reference
        "idle_polluted":   idle_dirty,         # True = repos non representatif
        "load_max_c":      load_max_c,
        "load_plateau_c":  load_plateau_c,
        "delta_c":         delta_c,
        "load_truncated":  load_truncated,   # True = plateau/deltaT invalides
        "load_sec_real":   load_sec_real,
        "load_ramp_sec":   load_ramp_sec,    # retard de demarrage du generateur
        "cpu_load_avg":    cpu_load_avg,
        "gpu_idle_c":      gpu_idle_c,
        "gpu_max_c":       gpu_max_c,
        "fan_idle_rpm":    fan_idle_rpm,
        "fan_load_rpm":    fan_load_rpm,
        "clock_max_mhz":   clock_max_mhz,
        "clock_drop_pct":  clock_drop_pct,
        "clock_burst_drop_pct": clock_burst_drop_pct,  # turbo -> regime etabli
        "clock_samples":   len(clock_vals),   # 0 = throttling indeterminable
        "throttling":      throttling,
        "power_limited":   power_limited,
        "cooldown_sec":    cooldown_sec,
        "recovery_margin_c": RECOVERY_MARGIN_C,
    }

    # Bloc GPU : uniquement en cible GPU, pour laisser la sortie des benches
    # CPU strictement identique (retro-compatibilite comparaison / rapport).
    if getattr(config, "target", "cpu") == "gpu":
        metrics.update(_gpu_metrics(idle_steady, load, cool, gpu_idle_c))

    return metrics


def _gpu_metrics(idle_steady: list[dict], load: list[dict], cool: list[dict],
                 gpu_idle_c: Optional[float]) -> dict:
    """Metriques propres au bench GPU (echantillons deja decoupes par phase).

    Toutes les valeurs de clock viennent de la cle `gpu_clock` des echantillons,
    alimentee en priorite par NVML (LHM peut rester figee sous charge NVIDIA).
    """
    gpu_load_avg  = _mean(_vals(load, "gpu_load"))
    gpu_plateau_c = _median(_vals(_slice_by_fraction(load, *STEADY_WINDOW) or load, "gpu"))
    gpu_delta_c = (round(gpu_plateau_c - gpu_idle_c, 1)
                   if (gpu_plateau_c is not None and gpu_idle_c is not None) else None)

    power_vals = _vals(load, "gpu_power")
    gpu_power_max_w = round(max(power_vals), 1) if power_vals else None
    hot_vals = _vals(load, "gpu_hotspot")
    gpu_hotspot_max_c = round(max(hot_vals), 1) if hot_vals else None

    # Clock : memes fenetres que le CPU (debut etabli vs dernier tiers).
    clk_early = _median(_vals(_slice_by_fraction(load, *EARLY_WINDOW), "gpu_clock"))
    clk_late  = _median(_vals(_slice_by_fraction(load, *STEADY_WINDOW), "gpu_clock"))
    clk_vals  = _vals(load, "gpu_clock")
    gpu_clock_max_mhz = round(max(clk_vals)) if clk_vals else None
    gpu_clock_drop_pct = (round((clk_early - clk_late) / clk_early * 100, 1)
                          if clk_early and clk_late else None)

    # Raison de bridage NVML observee pendant la charge — meme qualification
    # que l'urgence (_check_gpu_emergency) : un signal thermique n'est cru que
    # temperature proche du slowdown a l'appui (bit parasite a froid sinon).
    slowdown_vals = _vals(load, "gpu_slowdown_c")
    gpu_slowdown_c = slowdown_vals[0] if slowdown_vals else None
    floor = _gpu_throttle_floor(gpu_slowdown_c)
    thermal_reason_seen = any(
        (set(s.get("gpu_throttle") or ()) & GPU_THERMAL_REASONS)
        and (s.get("gpu") or 0) >= floor
        for s in load)
    power_reason_seen = any(
        set(s.get("gpu_throttle") or ()) & GPU_POWER_REASONS
        for s in load)

    gpu_vals_load = _vals(load, "gpu")
    gpu_max = max(gpu_vals_load) if gpu_vals_load else None

    # Meme tri-etat que cote CPU (None = indetermine). Cote GPU on dispose de
    # DEUX sources : les raisons de bridage NVML (la cle `gpu_throttle` n'est
    # posee sur l'echantillon que si NVML a repondu) et la chute de clock. Il
    # suffit de l'une des deux pour pouvoir conclure ; sans aucune des deux
    # (AMD/Intel sans NVML et clock illisible), on ne conclut pas.
    nvml_answered = any("gpu_throttle" in s for s in load)
    measurable = nvml_answered or gpu_clock_drop_pct is not None
    gpu_throttling: Optional[bool] = False if measurable else None
    gpu_power_limited: Optional[bool] = False if measurable else None
    if measurable:
        if thermal_reason_seen:
            gpu_throttling = True
        if gpu_clock_drop_pct is not None and clk_late < clk_early * (1 - THROTTLE_CLOCK_DROP):
            # Chute de clock soutenue : thermique si chaud (ou raison NVML),
            # sinon limite de puissance (normale : power cap constructeur).
            if gpu_throttling or (gpu_max or 0) >= floor:
                gpu_throttling = True
            else:
                gpu_power_limited = True
        elif power_reason_seen and not gpu_throttling:
            gpu_power_limited = True

    # Retour au calme de la temperature GPU.
    gpu_cooldown_sec = _time_to_recover(cool, gpu_idle_c, "gpu")

    return {
        "gpu_plateau_c":      gpu_plateau_c,
        "gpu_delta_c":        gpu_delta_c,
        "gpu_load_avg":       gpu_load_avg,
        "gpu_power_max_w":    gpu_power_max_w,
        "gpu_hotspot_max_c":  gpu_hotspot_max_c,
        "gpu_clock_max_mhz":  gpu_clock_max_mhz,
        "gpu_clock_drop_pct": gpu_clock_drop_pct,
        "gpu_clock_samples":  len(clk_vals),
        "gpu_slowdown_c":     gpu_slowdown_c,
        "gpu_throttling":     gpu_throttling,
        "gpu_power_limited":  gpu_power_limited,
        "gpu_cooldown_sec":   gpu_cooldown_sec,
    }


def throttling_state(metrics: dict, target: str = "cpu") -> Optional[bool]:
    """Throttling thermique REELLEMENT mesure : True / False / None.

    Unique lecture autorisee du drapeau `throttling` (ou `gpu_throttling`) par
    l'UI et la comparaison : un simple `bool(metrics["throttling"])` ecraserait
    l'indetermine en « non », c'est-a-dire en affirmation d'absence de defaut.

    Retro-compatibilite schema v1 : le drapeau y valait False par defaut, meme
    sur une session ou aucune frequence n'avait ete relevee. On requalifie donc
    ce False en None quand la session ne contient AUCUNE frequence de charge —
    sans frequence, le False n'a jamais ete mesure. (Les sessions v2 ecrivent
    deja None dans ce cas ; ce repli ne sert qu'aux sessions archivees.)
    """
    gpu = (target == "gpu")
    val = metrics.get("gpu_throttling" if gpu else "throttling")
    if val is None:
        return None

    # CHARGE ECOURTEE : un False n'a pas ete observe assez longtemps pour valoir
    # comme absence. Sur l'HP Omen (2026-08-01) la charge est coupee a 23 s sur
    # 300 prevues par l'arret d'urgence : les frequences relevees pendant cette
    # rampe ne montrent aucune chute — evidemment, le regime etabli n'a jamais
    # commence. Rendre « non » ici revient a certifier l'absence d'un defaut sur
    # un test qui n'est pas alle assez loin pour le voir.
    #
    # Un True reste un True : une detection positive sur une fenetre courte
    # reste une detection (Altyk du 2026-07-27, throttling vu sur 30 s de burst
    # et confirme independamment par HWiNFO).
    #
    # Requalification a la LECTURE, comme le repli v1 ci-dessous : les sessions
    # deja enregistrees se corrigent sans etre rejouees.
    if not val and metrics.get("load_truncated"):
        return None

    if ("gpu_clock_samples" if gpu else "clock_samples") in metrics:
        return bool(val)      # session v2 : le drapeau est deja tri-etat
    if not val and not metrics.get("gpu_clock_max_mhz" if gpu else "clock_max_mhz"):
        return None           # session v1 sans aucune frequence : non mesure
    return bool(val)          # un True v1 reste un True (raison NVML cote GPU)


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
            "target":      (data.get("config") or {}).get("target", "cpu"),
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
        self._load:   Optional[_ILoadGenerator] = None
        self._gpu_info: Optional[dict] = None            # adaptateur DXGI cible
        self._gpu_nvml: Optional[_NvmlGpuSampler] = None  # lecture NVML (cible gpu)

        self._cancel = threading.Event()
        self._sensor_stalled = threading.Event()  # backend capteurs fige (watchdog)
        self._sensor_gap = threading.Event()      # trou du flux, backend relance
        self._stall_msg = ""
        self._stream_gaps: list[dict] = []
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
            # Cible GPU : resoudre l'adaptateur AVANT de demarrer les capteurs
            # (echec immediat plutot qu'apres 20 s de warmup).
            if cfg.target == "gpu":
                self._gpu_info = _resolve_gpu_adapter(cfg.gpu_adapter)
                if self._gpu_info is None:
                    self._error("Bench GPU impossible : aucun adaptateur graphique "
                                "materiel utilisable (D3D11/DXGI indisponibles, "
                                "adaptateur introuvable, ou seul WARP present).")
                    return
                self._gpu_nvml = _NvmlGpuSampler(self._gpu_info["name"])
                self._gpu_nvml.open()   # False = pas de NVML -> repli LHM

            self._stream = SensorStream(cfg.sample_interval_ms,
                                        on_sample=self._record,
                                        on_stall=self._on_stall,
                                        on_gap=self._on_gap)
            if not self._stream.start():
                self._error("Echec du demarrage des capteurs.")
                return

            # Verifier que les capteurs repondent AVANT le protocole : un premier
            # echantillon avec temperature CPU exploitable (cible cpu). Sinon on
            # renonce avec un message clair (backend fige, CPU recent non
            # supporte...) plutot que de lancer 10 minutes de bench dans le vide.
            if not self._stream.wait_first_sample(STREAM_WARMUP_SEC,
                                                  require_cpu_temp=(cfg.target == "cpu")):
                self._stream.stop()
                # Le backend explique souvent lui-meme son refus (DLL absente,
                # Computer.Open() en echec...). Ce message etait jeté : on le
                # remonte tel quel, c'est le seul qui designe la vraie cause.
                cause = getattr(self._stream, "backend_error", "")
                if self._stream.stalled:
                    self._error("Capteurs figes : " + (self._stream.stall_reason
                                or "backend bloque")
                                + ". Lance diagnose_sensors.py pour la cause.")
                elif cause:
                    self._error(f"Capteurs indisponibles — {cause}")
                elif self._stream.latest() is not None:
                    self._error("Capteurs detectes mais aucune temperature CPU "
                                "exploitable sur cette machine (cpu_ref absent) : "
                                "bench impossible. Voir diagnose_sensors.py / "
                                "diagnose_probe.py.")
                else:
                    self._error("Les capteurs ne repondent pas (aucune donnee en "
                                f"{STREAM_WARMUP_SEC:.0f}s). Voir diagnose_sensors.py.")
                return

            # Cible GPU : exiger une temperature GPU exploitable (NVML ou LHM).
            # Sans elle, ni surveillance d'urgence ni metriques : on renonce
            # (cas typique : iGPU Intel, aucune temp GPU exposee -> non
            # benchable thermiquement, c'est normal).
            if cfg.target == "gpu" and not self._gpu_temp_available():
                self._stream.stop()
                self._error("Bench GPU impossible : aucune temperature GPU "
                            f"disponible pour « {self._gpu_info['name']} » "
                            "(typique d'un GPU integre). Le bench thermique GPU "
                            "n'a de sens que sur une carte dediee avec capteur.")
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
            self._load = _make_generator(cfg, self._gpu_info)
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
            if reason == "gap":
                # Le flux s'est tu un instant PUIS est reparti. La charge vient
                # d'etre coupee par securite (surveillance d'urgence aveugle
                # pendant le silence), mais tout n'est pas perdu : le
                # refroidissement se mesure encore, et la charge ecourtee sera
                # signalee comme telle par les metriques. Avant, ce cas jetait
                # dix minutes de test deja faites.
                self._sensor_gap.clear()
                logger.warning("ThermalBench : charge ecourtee apres un trou du "
                               "flux capteurs — poursuite vers le refroidissement")
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
            if self._gpu_nvml is not None:
                self._gpu_nvml.close()
            self._running = False

    def _wait(self, seconds: int, watch_emergency: bool) -> str:
        """Attend `seconds`, interruptible.
        Retourne 'done' | 'cancel' | 'emergency' | 'stall' | 'gap'."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._cancel.wait(timeout=0.2):
                return "cancel"
            if self._sensor_stalled.is_set():
                return "stall"
            # Un trou du flux n'interrompt que la CHARGE (watch_emergency) :
            # pendant ce silence, la surveillance d'urgence etait aveugle sur un
            # CPU a 100 %. Au repos ou en refroidissement, il n'y a rien a
            # proteger : on continue, quitte a avoir des echantillons manquants.
            if watch_emergency and self._sensor_gap.is_set():
                return "gap"
            if watch_emergency and self._emergency:
                return "emergency"
        return "done"

    def _on_stall(self, reason: str) -> None:
        """Callback SensorStream : figeage DEFINITIF (relances epuisees)."""
        self._stall_msg = reason
        self._sensor_stalled.set()
        logger.warning("ThermalBench : capteurs figes — %s", reason)

    def _on_gap(self, gap: dict) -> None:
        """Callback SensorStream : trou dans le flux, backend relance ou non.

        On garde la trace horodatee sur l'echelle du bench (`t`) et la phase :
        un trou pendant le repos et un trou pendant la charge n'ont pas les
        memes consequences, et le lecteur du JSON doit pouvoir en juger.
        """
        entry = {
            "t":         round(time.monotonic() - self._t0, 1) if self._t0 else 0.0,
            "phase":     self._phase.value,
            "reason":    gap.get("reason", ""),
            "recovered": bool(gap.get("recovered")),
        }
        self._stream_gaps.append(entry)
        if entry["recovered"]:
            self._sensor_gap.set()
            logger.warning("ThermalBench : trou du flux capteurs pendant %s "
                           "(%s) — backend relance", entry["phase"], entry["reason"])

    def _enter_phase(self, phase: BenchPhase) -> None:
        # Le drapeau « trou du flux » ne vaut que pour la phase EN COURS : sans
        # ce reset, un trou survenu pendant le repos couperait la charge des sa
        # premiere seconde, alors que le flux est revenu depuis longtemps.
        self._sensor_gap.clear()
        self._phase = phase
        idx = self._PHASE_ORDER.index(phase) + 1
        self._invoke(self._cb.on_phase, phase, idx, len(self._PHASE_ORDER))

    def _gpu_temp_available(self) -> bool:
        """Une temperature GPU est-elle lisible (NVML ou flux LHM) ?"""
        nv = self._gpu_nvml.read() if self._gpu_nvml is not None else None
        if nv is not None and nv.get("temp") is not None:
            return True
        s = self._stream.latest() if self._stream is not None else None
        return bool(s) and s.get("gpu_temp") is not None

    @staticmethod
    def _first(*vals):
        """Premiere valeur non-None (0 et 0.0 sont des valeurs valides)."""
        return next((v for v in vals if v is not None), None)

    def _record(self, sample: dict) -> None:
        """Callback SensorStream (thread lecteur) : tag + stockage + emergency."""
        if not self._running:
            return
        # Cible GPU : lecture NVML synchrone du GPU cible (clock/power/throttle
        # fiables sous charge). None sur AMD/Intel -> repli sur le flux LHM.
        nv = self._gpu_nvml.read() if self._gpu_nvml is not None else None
        rec = {
            "t":        round(time.monotonic() - self._t0, 2),
            "phase":    self._phase.value,
            "cpu":      sample.get("cpu_ref"),
            "cpu_pkg":  sample.get("cpu_pkg"),
            "cpu_max":  sample.get("cpu_max"),
            "cpu_load": sample.get("cpu_load"),
            "clock":    sample.get("cpu_clock_max"),
            "gpu":      self._first(nv.get("temp") if nv else None,
                                    sample.get("gpu_temp")),
            "gpu_load": self._first(nv.get("load") if nv else None,
                                    sample.get("gpu_load")),
            "gpu_fan":  sample.get("gpu_fan"),   # LHM (RPM) — le % NVML n'est
                                                 # pas melange (unites differentes)
            "gpu_hotspot": sample.get("gpu_hotspot"),
            "gpu_clock":   self._first(nv.get("clock_sm_mhz") if nv else None,
                                       sample.get("gpu_core_clock")),
            "gpu_power":   self._first(nv.get("power_w") if nv else None,
                                       sample.get("gpu_power")),
            "fans":     list(sample.get("fans") or []),
            "disks":    sample.get("disks") or [],
        }
        if nv is not None:
            rec["gpu_throttle"]   = list(nv.get("throttle_reasons") or [])
            rec["gpu_slowdown_c"] = nv.get("temp_slowdown_c")
        self._samples.append(rec)

        # Arret d'urgence : seuil franchi pendant la charge.
        if self._phase == BenchPhase.LOAD:
            if self.config.target == "gpu":
                self._check_gpu_emergency(rec)
            elif (rec["cpu"] is not None
                    and rec["cpu"] >= self.config.emergency_temp_c):
                self._emergency = True

        self._invoke(self._cb.on_sample, rec)

    def _check_gpu_emergency(self, rec: dict) -> None:
        """Urgence GPU : pas un simple seuil fixe (lecons atelier).

        1. Plafond de temperature : min(seuil configure, slowdown NVML - marge)
           — on coupe avant que la carte ne se bride elle-meme.
        2. Raison de bridage thermique NVML (GPU_THERMAL_REASONS, y compris
           hw_slowdown = clocks divisees) : fiable UNIQUEMENT si la temperature
           est proche du seuil slowdown (le bit peut etre vrai au repos sur
           certaines cartes). Meme classification que _gpu_metrics.
        """
        t = rec.get("gpu")
        if t is None:
            return
        slowdown = rec.get("gpu_slowdown_c")
        cap = self.config.gpu_emergency_temp_c
        if slowdown:   # falsy voulu : 0 = valeur invalide (driver), pas un seuil
            cap = min(cap, slowdown - GPU_SLOWDOWN_MARGIN_C)
        if t >= cap:
            self._emergency = True
            return
        if (set(rec.get("gpu_throttle") or ()) & GPU_THERMAL_REASONS
                and t >= _gpu_throttle_floor(slowdown)):
            self._emergency = True

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
            # Trous du flux de capteurs : une mesure a trous n'est pas une
            # mesure continue, et le silence sur ce point a deja coute un bench
            # entier (27/07). `sensor_max_gap_sec` est le signal avant-coureur :
            # il monte bien avant que le chien de garde ne coupe.
            "stream_gaps": list(self._stream_gaps),
            "sensor_max_gap_sec": (self._stream.max_gap_sec
                                   if self._stream is not None else None),
            "metrics":     metrics,
            "samples":     self._samples,
        }
        if self._gpu_info is not None:
            session["gpu_adapter"] = {
                "index":   self._gpu_info.get("index"),
                "name":    self._gpu_info.get("name"),
                "vendor":  self._gpu_info.get("vendor"),
                "vram_mb": self._gpu_info.get("vram_mb"),
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
