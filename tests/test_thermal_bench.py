"""
Tests du moteur de bench thermique (cibles CPU et GPU).

Smoke tests SANS materiel ni capteurs : SensorStream, generateurs de charge et
lecture NVML sont remplaces par des fakes (monkeypatch des noms module-level de
thermal_bench). Verifie :

  - bench CPU complet -> retro-compatibilite stricte (memes cles de metriques,
    generateur CPU choisi, pas de bloc GPU) ;
  - bench GPU complet -> generateur GPU sur l'adaptateur resolu, echantillons
    enrichis NVML (clock NVML prioritaire sur LHM), bloc de metriques GPU,
    adaptateur dans le JSON de session ;
  - urgence GPU : seuil dynamique (slowdown NVML - marge) et raison de
    throttling NVML confirmee par la temperature — mais PAS le bit
    `throttle_thermal` seul a froid (faux positif atelier) ;
  - compute_metrics : detection de throttling GPU sur chute de clock a chaud ;
  - throttling en TRI-ETAT : sans frequence exploitable le resultat est
    `None` (indetermine) et surtout pas `False` — l'outil ne doit pas certifier
    l'absence d'un defaut qu'il n'a pas cherche. Y compris a la relecture des
    sessions archivees au schema v1 (throttling_state).

Lancement :  py -m unittest discover -s tests -v
"""

import os
import tempfile
import threading
import time
import unittest
from dataclasses import asdict
from pathlib import Path

import thermal_bench
from thermal_bench import BenchConfig, ThermalBench, compute_metrics


# --- Fakes -------------------------------------------------------------------

def _base_sample() -> dict:
    return {
        "cpu_ref": 50.0, "cpu_pkg": 50.0, "cpu_max": 52.0, "cpu_load": 15.0,
        "cpu_clock_max": 3600.0,
        "gpu_temp": 41.0, "gpu_load": 4.0, "gpu_fan": 900,
        "gpu_hotspot": 52.0, "gpu_core_clock": 300.0, "gpu_power": 8.0,
        "fans": [800], "disks": [],
    }


class FakeStream:
    """SensorStream factice : emet un echantillon toutes les 50 ms."""

    sample_fn = staticmethod(_base_sample)   # surchargeable par test

    def __init__(self, interval_ms, on_sample=None, on_stall=None):
        self._on_sample = on_sample
        self._stop_evt = threading.Event()
        self._latest = None
        self._thread = None

    def start(self) -> bool:
        def loop():
            while not self._stop_evt.wait(0.05):
                s = dict(type(self).sample_fn())
                self._latest = s
                if self._on_sample:
                    self._on_sample(s)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return True

    def wait_first_sample(self, timeout=20.0, require_cpu_temp=False) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._latest is not None:
                return True
            time.sleep(0.01)
        return False

    def latest(self):
        return self._latest

    @property
    def stalled(self) -> bool:
        return False

    @property
    def stall_reason(self) -> str:
        return ""

    def stop(self, timeout=3.0) -> None:
        self._stop_evt.set()


class FakeGenerator:
    """Generateur de charge factice : ne lance aucun processus."""

    def __init__(self):
        self.started = False
        self.stopped = False

    def available(self) -> bool:
        return True

    def start(self) -> bool:
        self.started = True
        return True

    def stop(self, timeout=5.0) -> None:
        self.stopped = True


_NVML_DEFAULT = {
    "temp": 60.0, "load": 97.0, "clock_sm_mhz": 1800, "power_w": 55.0,
    "temp_slowdown_c": 93.0, "throttle_reasons": [],
    "throttle_thermal": False, "throttle_power": False,
}


class FakeNvmlSampler:
    """_NvmlGpuSampler factice ; `data` surchargeable par test (None = pas de
    NVML, comme sur AMD/Intel)."""

    data = dict(_NVML_DEFAULT)

    def __init__(self, adapter_name):
        self.adapter_name = adapter_name
        self.opened = False
        self.closed = False

    def open(self) -> bool:
        self.opened = True
        return type(self).data is not None

    def read(self):
        d = type(self).data
        return dict(d) if d is not None else None

    def close(self) -> None:
        self.closed = True


_FAKE_ADAPTER = {"index": 1, "name": "Fake GPU 9000", "vendor": "NVIDIA",
                 "vendor_id": 0x10DE, "device_id": 0, "vram_mb": 8192,
                 "luid": 42, "is_software": False}


# --- Base commune ------------------------------------------------------------

class BenchTestCase(unittest.TestCase):
    """Patch SensorStream / generateurs / NVML et fournit run_bench()."""

    def setUp(self):
        self._saved = {
            "SensorStream": thermal_bench.SensorStream,
            "lhm_available": thermal_bench.lhm_available,
            "_make_generator": thermal_bench._make_generator,
            "_resolve_gpu_adapter": thermal_bench._resolve_gpu_adapter,
            "_NvmlGpuSampler": thermal_bench._NvmlGpuSampler,
        }
        self.generator = FakeGenerator()
        self.gen_calls = []

        def fake_make_generator(cfg, gpu_info=None):
            self.gen_calls.append((cfg.target, gpu_info))
            return self.generator

        thermal_bench.SensorStream = FakeStream
        thermal_bench.lhm_available = lambda: True
        thermal_bench._make_generator = fake_make_generator
        thermal_bench._resolve_gpu_adapter = lambda sel: dict(_FAKE_ADAPTER)
        thermal_bench._NvmlGpuSampler = FakeNvmlSampler

        FakeStream.sample_fn = staticmethod(_base_sample)
        FakeNvmlSampler.data = dict(_NVML_DEFAULT)

        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        for name, val in self._saved.items():
            setattr(thermal_bench, name, val)
        self._tmp.cleanup()

    def make_config(self, **kw) -> BenchConfig:
        kw.setdefault("idle_sec", 1)
        kw.setdefault("load_sec", 1)
        kw.setdefault("cooldown_sec", 1)
        kw.setdefault("output_dir", self._tmp.name)
        return BenchConfig(**kw)

    def run_bench(self, config: BenchConfig):
        """Lance un bench et attend sa fin. Retourne (session, path, erreurs)."""
        done = threading.Event()
        result = {"session": None, "path": None, "errors": []}

        def on_finish(session, path):
            result["session"] = session
            result["path"] = path
            done.set()

        def on_error(msg):
            result["errors"].append(msg)
            done.set()

        bench = ThermalBench(config, on_finish=on_finish, on_error=on_error)
        self.assertTrue(bench.start())
        self.assertTrue(done.wait(timeout=30), "bench non termine en 30 s")
        bench.join(timeout=5)
        return result["session"], result["path"], result["errors"]


# --- Cles de metriques d'un bench CPU AVANT la generalisation GPU ------------

_LEGACY_CPU_METRIC_KEYS = {
    "idle_c", "load_max_c", "load_plateau_c", "delta_c", "cpu_load_avg",
    "load_truncated", "load_sec_real", "load_ramp_sec",
    "gpu_idle_c", "gpu_max_c", "fan_idle_rpm", "fan_load_rpm",
    "clock_max_mhz", "clock_drop_pct", "clock_burst_drop_pct", "clock_samples",
    "throttling", "power_limited", "cooldown_sec", "recovery_margin_c",
}


class TestCpuBench(BenchTestCase):
    """Smoke test : bench CPU inchange (retro-compatibilite)."""

    def test_cpu_bench_full_session(self):
        session, path, errors = self.run_bench(self.make_config())
        self.assertEqual(errors, [])
        self.assertIsNotNone(session)
        self.assertFalse(session["aborted"])
        self.assertFalse(session["emergency"])
        self.assertEqual(session["config"]["target"], "cpu")
        self.assertNotIn("gpu_adapter", session)

        # Generateur : CPU, sans info d'adaptateur.
        self.assertEqual(self.gen_calls, [("cpu", None)])
        self.assertTrue(self.generator.started)
        self.assertTrue(self.generator.stopped)

        # Les 3 phases ont echantillonne.
        phases = {s["phase"] for s in session["samples"]}
        self.assertEqual(phases, {"idle", "load", "cooldown"})

        # Metriques : exactement le schema historique (aucun bloc GPU).
        self.assertEqual(set(session["metrics"].keys()), _LEGACY_CPU_METRIC_KEYS)
        self.assertAlmostEqual(session["metrics"]["idle_c"], 50.0)

        # JSON ecrit et relisible.
        self.assertIsNotNone(path)
        self.assertTrue(Path(path).is_file())
        reloaded = thermal_bench.load_session(str(path))
        self.assertEqual(reloaded["config"]["target"], "cpu")

    def test_cpu_emergency_still_works(self):
        FakeStream.sample_fn = staticmethod(
            lambda: {**_base_sample(), "cpu_ref": 97.0})
        session, _, errors = self.run_bench(self.make_config(load_sec=5))
        self.assertEqual(errors, [])
        self.assertTrue(session["emergency"])
        self.assertFalse(session["aborted"])   # poursuit vers le refroidissement


class TestGpuBench(BenchTestCase):
    """Smoke test : bench GPU complet."""

    def test_gpu_bench_full_session(self):
        session, path, errors = self.run_bench(
            self.make_config(target="gpu", gpu_adapter="Fake"))
        self.assertEqual(errors, [])
        self.assertIsNotNone(session)
        self.assertFalse(session["aborted"])
        self.assertFalse(session["emergency"])
        self.assertEqual(session["config"]["target"], "gpu")

        # Generateur GPU instancie avec l'adaptateur resolu.
        self.assertEqual(len(self.gen_calls), 1)
        target, gpu_info = self.gen_calls[0]
        self.assertEqual(target, "gpu")
        self.assertEqual(gpu_info["index"], 1)
        self.assertTrue(self.generator.stopped)

        # Adaptateur dans la session.
        self.assertEqual(session["gpu_adapter"]["name"], "Fake GPU 9000")
        self.assertEqual(session["gpu_adapter"]["vendor"], "NVIDIA")

        # Echantillons enrichis : clock/power/temp NVML prioritaires sur LHM
        # (LHM annonce 300 MHz fige, NVML 1800 : la lecon atelier RTX 4060).
        s = session["samples"][-1]
        self.assertEqual(s["gpu_clock"], 1800)
        self.assertEqual(s["gpu_power"], 55.0)
        self.assertEqual(s["gpu"], 60.0)
        self.assertEqual(s["gpu_slowdown_c"], 93.0)

        # Bloc de metriques GPU present et coherent.
        m = session["metrics"]
        self.assertIn("gpu_plateau_c", m)
        self.assertAlmostEqual(m["gpu_plateau_c"], 60.0)
        self.assertEqual(m["gpu_clock_max_mhz"], 1800)
        self.assertFalse(m["gpu_throttling"])
        self.assertEqual(m["gpu_power_max_w"], 55.0)
        self.assertEqual(m["gpu_slowdown_c"], 93.0)
        # Les cles CPU historiques restent presentes (contexte ambiant).
        self.assertTrue(_LEGACY_CPU_METRIC_KEYS <= set(m.keys()))

        self.assertIsNotNone(path)

    def test_gpu_bench_without_nvml_uses_lhm(self):
        """AMD/Intel : pas de NVML -> repli sur le flux LHM."""
        FakeNvmlSampler.data = None
        session, _, errors = self.run_bench(self.make_config(target="gpu"))
        self.assertEqual(errors, [])
        s = session["samples"][-1]
        self.assertEqual(s["gpu"], 41.0)          # gpu_temp LHM
        self.assertEqual(s["gpu_clock"], 300.0)   # gpu_core_clock LHM
        self.assertNotIn("gpu_throttle", s)

    def test_gpu_bench_refused_without_gpu_temp(self):
        """iGPU sans temperature GPU : refus propre, pas de bench dans le vide."""
        FakeNvmlSampler.data = None
        FakeStream.sample_fn = staticmethod(
            lambda: {**_base_sample(), "gpu_temp": None})
        session, _, errors = self.run_bench(self.make_config(target="gpu"))
        self.assertIsNone(session)
        self.assertEqual(len(errors), 1)
        self.assertIn("temperature GPU", errors[0])

    def test_gpu_bench_refused_without_adapter(self):
        thermal_bench._resolve_gpu_adapter = lambda sel: None
        session, _, errors = self.run_bench(self.make_config(target="gpu"))
        self.assertIsNone(session)
        self.assertEqual(len(errors), 1)
        self.assertIn("adaptateur", errors[0])


class TestGpuEmergency(BenchTestCase):
    """Urgence GPU : seuil dynamique + raison de throttling NVML."""

    def test_emergency_on_temp_near_slowdown(self):
        # 91 C avec slowdown 93 : seuil effectif = min(90, 93-3) = 90 -> urgence.
        FakeNvmlSampler.data = {**_NVML_DEFAULT, "temp": 91.0}
        session, _, errors = self.run_bench(
            self.make_config(target="gpu", load_sec=5))
        self.assertEqual(errors, [])
        self.assertTrue(session["emergency"])
        self.assertFalse(session["aborted"])   # refroidissement mene a bien

    def test_emergency_on_thermal_throttle_confirmed_by_temp(self):
        # 85 C (sous le plafond 90) mais throttle_thermal ET temp >= 93-10=83.
        FakeNvmlSampler.data = {**_NVML_DEFAULT, "temp": 85.0,
                                "throttle_thermal": True,
                                "throttle_reasons": ["sw_thermal"]}
        session, _, errors = self.run_bench(
            self.make_config(target="gpu", load_sec=5))
        self.assertEqual(errors, [])
        self.assertTrue(session["emergency"])

    def test_no_emergency_on_spurious_throttle_bit_when_cool(self):
        # Lecon atelier (RTX 4060) : throttle_thermal peut etre TRUE a froid.
        # 60 C avec le bit leve NE doit PAS declencher l'urgence.
        FakeNvmlSampler.data = {**_NVML_DEFAULT, "temp": 60.0,
                                "throttle_thermal": True,
                                "throttle_reasons": ["sw_thermal"]}
        session, _, errors = self.run_bench(self.make_config(target="gpu"))
        self.assertEqual(errors, [])
        self.assertFalse(session["emergency"])


class TestGpuMetrics(unittest.TestCase):
    """compute_metrics : detection de bridage GPU (fonction pure)."""

    @staticmethod
    def _mk_samples(clock_late, temp_load, throttle=(), slowdown=93.0):
        """Sessions synthetiques : 10 min repos, 10 min charge, 10 min repos."""
        samples = []
        for t in range(0, 600, 10):        # idle : GPU a 40 C
            samples.append({"t": t, "phase": "idle", "cpu": 45.0, "gpu": 40.0,
                            "gpu_clock": 300, "gpu_load": 2.0})
        for t in range(600, 1200, 10):     # load
            frac = (t - 600) / 600.0
            clock = 1800 if frac < 0.5 else clock_late
            samples.append({"t": t, "phase": "load", "cpu": 60.0,
                            "gpu": temp_load, "gpu_clock": clock,
                            "gpu_load": 99.0, "gpu_power": 100.0,
                            "gpu_throttle": list(throttle),
                            "gpu_slowdown_c": slowdown})
        for t in range(1200, 1800, 10):    # cooldown : redescend vite
            samples.append({"t": t, "phase": "cooldown", "cpu": 46.0,
                            "gpu": 40.0 if t > 1250 else 60.0})
        return samples

    def test_throttling_detected_on_hot_clock_drop(self):
        samples = self._mk_samples(clock_late=1400, temp_load=90.0,
                                   throttle=["sw_thermal"])
        m = compute_metrics(samples, BenchConfig(target="gpu"))
        self.assertTrue(m["gpu_throttling"])
        self.assertFalse(m["gpu_power_limited"])
        self.assertGreater(m["gpu_clock_drop_pct"], 5.0)
        self.assertAlmostEqual(m["gpu_delta_c"], 50.0)
        self.assertIsNotNone(m["gpu_cooldown_sec"])

    def test_power_limit_not_confused_with_thermal(self):
        # Chute de clock a 65 C (loin du slowdown 93) avec raison power :
        # limite de puissance normale, PAS un souci de refroidissement.
        samples = self._mk_samples(clock_late=1400, temp_load=65.0,
                                   throttle=["sw_power_cap"])
        m = compute_metrics(samples, BenchConfig(target="gpu"))
        self.assertFalse(m["gpu_throttling"])
        self.assertTrue(m["gpu_power_limited"])

    def test_healthy_gpu_no_flags(self):
        samples = self._mk_samples(clock_late=1790, temp_load=70.0)
        m = compute_metrics(samples, BenchConfig(target="gpu"))
        self.assertFalse(m["gpu_throttling"])
        self.assertFalse(m["gpu_power_limited"])

    def test_cpu_config_yields_no_gpu_block(self):
        samples = self._mk_samples(clock_late=1800, temp_load=70.0)
        m = compute_metrics(samples, BenchConfig())    # target cpu par defaut
        self.assertNotIn("gpu_throttling", m)
        self.assertNotIn("gpu_plateau_c", m)


class TestThrottlingIndeterminate(unittest.TestCase):
    """Le throttling ne doit JAMAIS etre annonce absent sans avoir ete mesure.

    Cas reel (atelier, 27/07/2026) : un portable Alder Lake-P ne remonte aucune
    frequence CPU (`clock: null` du debut a la fin du bench). Le rapport
    affirmait pourtant « throttling : non », ce qui a fait suspecter un defaut
    materiel inexistant sur une autre machine.
    """

    @staticmethod
    def _cpu_samples(clock=None):
        """Repos 10 min / charge 10 min / refroidissement 10 min, cible CPU."""
        samples = []
        for t in range(0, 600, 10):
            samples.append({"t": t, "phase": "idle", "cpu": 45.0, "cpu_load": 3.0})
        for t in range(600, 1200, 10):
            s = {"t": t, "phase": "load", "cpu": 88.0, "cpu_load": 99.0}
            if clock is not None:
                s["clock"] = clock
            samples.append(s)
        for t in range(1200, 1800, 10):
            samples.append({"t": t, "phase": "cooldown", "cpu": 46.0})
        return samples

    def test_no_clock_yields_indeterminate_not_false(self):
        m = compute_metrics(self._cpu_samples(clock=None), BenchConfig())
        self.assertIsNone(m["throttling"])
        self.assertIsNone(m["power_limited"])
        self.assertIsNone(m["clock_drop_pct"])
        self.assertEqual(m["clock_samples"], 0)
        # Les temperatures, elles, restent parfaitement exploitables.
        self.assertEqual(m["load_plateau_c"], 88.0)

    def test_stable_clock_yields_measured_false(self):
        m = compute_metrics(self._cpu_samples(clock=3600), BenchConfig())
        self.assertIs(m["throttling"], False)
        self.assertIs(m["power_limited"], False)
        self.assertGreater(m["clock_samples"], 0)

    def test_gpu_without_clock_nor_nvml_is_indeterminate(self):
        """AMD/Intel sans NVML et sans clock lisible : aucune des deux sources."""
        samples = TestGpuMetrics._mk_samples(clock_late=1800, temp_load=70.0)
        for s in samples:
            s.pop("gpu_clock", None)
            s.pop("gpu_throttle", None)
        m = compute_metrics(samples, BenchConfig(target="gpu"))
        self.assertIsNone(m["gpu_throttling"])
        self.assertIsNone(m["gpu_power_limited"])
        self.assertEqual(m["gpu_clock_samples"], 0)

    def test_gpu_nvml_alone_suffices_to_conclude(self):
        """NVML a repondu (cle gpu_throttle posee) sans raison de bridage :
        « pas de throttling » est alors une vraie mesure, pas un defaut."""
        samples = TestGpuMetrics._mk_samples(clock_late=1800, temp_load=70.0)
        for s in samples:
            s.pop("gpu_clock", None)
        m = compute_metrics(samples, BenchConfig(target="gpu"))
        self.assertIs(m["gpu_throttling"], False)
        self.assertIs(m["gpu_power_limited"], False)


class TestTruncatedLoad(unittest.TestCase):
    """Charge ecourtee : pas de plateau, donc pas de « plateau ».

    Cas reel (atelier, 27/07/2026) : arret d'urgence a 25,5 s sur 300 s prevues.
    Le rapport annoncait « plateau 94 C, deltaT 50 » calcules sur le dernier
    tiers d'une RAMPE 62 -> 96 C. Aucun regime etabli n'avait existe.
    """

    @staticmethod
    def _samples(load_sec, step=5.0):
        """Repos 120 s, puis une charge en RAMPE de `load_sec` secondes."""
        out = [{"t": t, "phase": "idle", "cpu": 45.0, "cpu_load": 2.0,
                "clock": 1600}
               for t in range(0, 120, 5)]
        n = max(2, int(load_sec / step))
        for i in range(n):
            out.append({"t": 120 + i * step, "phase": "load",
                        "cpu": 62.0 + (96.0 - 62.0) * i / (n - 1),
                        "cpu_load": 100.0, "clock": 2700})
        out.append({"t": 120 + load_sec + 5, "phase": "cooldown",
                    "cpu": 50.0, "cpu_load": 2.0, "clock": 1600})
        return out

    def test_truncated_load_invalidates_plateau_and_delta(self):
        m = compute_metrics(self._samples(25.5),
                            BenchConfig(idle_sec=120, load_sec=300))
        self.assertTrue(m["load_truncated"])
        self.assertIsNone(m["load_plateau_c"])
        self.assertIsNone(m["delta_c"])
        # Le pic, lui, a bien ete atteint : c'est meme lui qui a coupe le test.
        self.assertEqual(m["load_max_c"], 96.0)
        self.assertAlmostEqual(m["load_sec_real"], 25.0, delta=6)

    def test_complete_load_keeps_plateau(self):
        m = compute_metrics(self._samples(300),
                            BenchConfig(idle_sec=120, load_sec=300))
        self.assertFalse(m["load_truncated"])
        self.assertIsNotNone(m["load_plateau_c"])
        self.assertIsNotNone(m["delta_c"])

    def test_slightly_short_load_still_valid(self):
        """295 s sur 300 : l'arrondi de fin de phase ne doit rien invalider."""
        m = compute_metrics(self._samples(295),
                            BenchConfig(idle_sec=120, load_sec=300))
        self.assertFalse(m["load_truncated"])
        self.assertIsNotNone(m["load_plateau_c"])


class TestPowerLimitDetection(unittest.TestCase):
    """Limite de puissance PL1 : invisible en comparant debut etabli et fin.

    Cas reel (atelier, i5-1240P) : 2715 MHz pendant le burst turbo, 2112 MHz en
    regime etabli a 28,1 W — soit son PL1 pile — et 85 C. HWiNFO signalait la
    limite de puissance sur 100 % du regime etabli ; Ghisdiag rendait
    `power_limited: false` parce que la chute a lieu AVANT EARLY_WINDOW.
    """

    @staticmethod
    def _samples(clock_burst, clock_steady, temp_steady, temp_peak=None):
        out = [{"t": t, "phase": "idle", "cpu": 44.0, "cpu_load": 2.0,
                "clock": 1600} for t in range(0, 120, 5)]
        # 300 s de charge, echantillon toutes les 3 s.
        for i in range(100):
            t = 120 + i * 3
            frac = i / 99.0
            if frac < 0.08:            # burst turbo
                clock, temp = clock_burst, (temp_peak or temp_steady)
            else:                      # regime etabli
                clock, temp = clock_steady, temp_steady
            out.append({"t": t, "phase": "load", "cpu": temp,
                        "cpu_load": 100.0, "clock": clock})
        out.append({"t": 425, "phase": "cooldown", "cpu": 50.0, "clock": 1600})
        return out

    def _metrics(self, **kw):
        return compute_metrics(self._samples(**kw),
                               BenchConfig(idle_sec=120, load_sec=300))

    def test_power_limit_detected_from_burst_drop(self):
        m = self._metrics(clock_burst=2715, clock_steady=2112,
                          temp_steady=85.0, temp_peak=96.0)
        self.assertIs(m["power_limited"], True)
        self.assertIs(m["throttling"], False)
        self.assertGreater(m["clock_burst_drop_pct"], 20)
        # La comparaison historique, elle, ne voit toujours rien : c'est normal,
        # les deux fenetres sont dans le regime etabli.
        self.assertEqual(m["clock_drop_pct"], 0.0)

    def test_hot_plateau_stays_thermal_not_power(self):
        """Meme chute, mais plateau brulant : c'est le refroidissement, pas PL1."""
        m = self._metrics(clock_burst=2715, clock_steady=2112,
                          temp_steady=93.0, temp_peak=96.0)
        self.assertIs(m["power_limited"], False)

    def test_no_burst_drop_no_power_limit(self):
        """Frequence tenue de bout en bout : rien a signaler."""
        m = self._metrics(clock_burst=2700, clock_steady=2690, temp_steady=75.0)
        self.assertIs(m["power_limited"], False)
        self.assertIs(m["throttling"], False)

    def test_truncated_run_claims_no_power_limit(self):
        """Sans regime etabli, on ne peut rien affirmer sur la puissance."""
        samples = self._samples(clock_burst=2715, clock_steady=2112,
                                temp_steady=85.0, temp_peak=96.0)
        court = [s for s in samples
                 if s["phase"] != "load" or s["t"] < 150]   # ~30 s de charge
        m = compute_metrics(court, BenchConfig(idle_sec=120, load_sec=300))
        self.assertTrue(m["load_truncated"])
        self.assertIs(m["power_limited"], False)


class TestSlowLoadStart(unittest.TestCase):
    """Le generateur de charge ne demarre pas toujours tout de suite.

    Cas reel (atelier, 28/07/2026, MSI Core Ultra) : 39 s se sont ecoulees
    entre le debut de la phase de charge et la premiere seconde a 100 %. Le
    CPU y etait a 603 MHz, au repos. La fenetre « burst turbo » tombait donc
    sur une machine inactive et rendait une chute de -225 %.
    """

    @staticmethod
    def _samples(retard_sec, clock_repos=600, clock_burst=4500,
                 clock_steady=3600, step=2.5):
        out = [{"t": t, "phase": "idle", "cpu": 48.0, "cpu_load": 12.0,
                "clock": clock_repos} for t in range(0, 120, 5)]
        t = 120.0
        # Phase de charge : le generateur dort d'abord `retard_sec`.
        while t < 120 + retard_sec:
            out.append({"t": t, "phase": "load", "cpu": 48.0,
                        "cpu_load": 12.0, "clock": clock_repos})
            t += step
        fin = 120 + 300
        debut_reel = t
        while t < fin:
            frac = (t - debut_reel) / max(1.0, fin - debut_reel)
            clock = clock_burst if frac < 0.08 else clock_steady
            out.append({"t": t, "phase": "load", "cpu": 89.0,
                        "cpu_load": 100.0, "clock": clock})
            t += step
        out.append({"t": fin + 5, "phase": "cooldown", "cpu": 55.0,
                    "cpu_load": 3.0, "clock": clock_repos})
        return out

    def test_slow_start_does_not_poison_the_burst_window(self):
        m = compute_metrics(self._samples(39),
                            BenchConfig(idle_sec=120, load_sec=300))
        self.assertAlmostEqual(m["load_ramp_sec"], 39, delta=3)
        # La chute burst -> etabli doit rester plausible, jamais negative de
        # plusieurs centaines de pourcents.
        self.assertGreater(m["clock_burst_drop_pct"], 0)
        self.assertLess(m["clock_burst_drop_pct"], 50)
        self.assertIs(m["power_limited"], True)
        # Le repos a 600 MHz ne doit pas etre pris pour la frequence maximale.
        self.assertEqual(m["clock_max_mhz"], 4500)

    def test_immediate_start_reports_no_ramp(self):
        m = compute_metrics(self._samples(0),
                            BenchConfig(idle_sec=120, load_sec=300))
        self.assertEqual(m["load_ramp_sec"], 0.0)

    def test_load_never_reaching_full_falls_back(self):
        """Charge CPU jamais lue ou generateur mort : on ne plante pas."""
        s = self._samples(0)
        for x in s:
            x["cpu_load"] = None
        m = compute_metrics(s, BenchConfig(idle_sec=120, load_sec=300))
        self.assertEqual(m["load_ramp_sec"], 0.0)
        self.assertIsNotNone(m["load_plateau_c"])


class TestThrottlingState(unittest.TestCase):
    """throttling_state() : lecture unique du drapeau, y compris archives v1."""

    def test_v2_value_trusted(self):
        v2 = {"throttling": False, "clock_samples": 150, "clock_max_mhz": 3600}
        self.assertIs(thermal_bench.throttling_state(v2), False)

    def test_v2_none_stays_none(self):
        v2 = {"throttling": None, "clock_samples": 0, "clock_max_mhz": None}
        self.assertIsNone(thermal_bench.throttling_state(v2))

    def test_v1_false_without_clock_requalified(self):
        # Session archivee AVANT le tri-etat : False y etait la valeur par
        # defaut, pas une mesure.
        v1 = {"throttling": False, "clock_max_mhz": None}
        self.assertIsNone(thermal_bench.throttling_state(v1))

    def test_v1_false_with_clock_is_a_real_measure(self):
        v1 = {"throttling": False, "clock_max_mhz": 3600}
        self.assertIs(thermal_bench.throttling_state(v1), False)

    def test_v1_true_kept_even_without_clock(self):
        # Cote GPU un True peut venir d'une raison NVML seule : on ne l'efface pas.
        v1 = {"gpu_throttling": True, "gpu_clock_max_mhz": None}
        self.assertIs(thermal_bench.throttling_state(v1, "gpu"), True)

    # -- Charge ecourtee : un « non » n'a pas eu le temps d'etre vrai ----------

    def test_truncated_false_is_undetermined(self):
        # HP Omen (01/08/2026) : 25 frequences relevees, aucune chute, mais la
        # charge est coupee a 23 s sur 300 par l'arret d'urgence. Le regime
        # etabli n'a jamais commence : « non » serait un certificat de bonne
        # sante delivre sans examen.
        m = {"throttling": False, "clock_samples": 25, "clock_max_mhz": 3400,
             "load_truncated": True}
        self.assertIsNone(thermal_bench.throttling_state(m))

    def test_truncated_true_stays_true(self):
        # Altyk (27/07/2026) : throttling detecte sur 30 s de burst, confirme
        # independamment par HWiNFO. Une detection courte reste une detection.
        m = {"throttling": True, "clock_samples": 12, "clock_max_mhz": 2917,
             "load_truncated": True}
        self.assertIs(thermal_bench.throttling_state(m), True)

    def test_complete_false_stays_false(self):
        m = {"throttling": False, "clock_samples": 150, "clock_max_mhz": 3600,
             "load_truncated": False}
        self.assertIs(thermal_bench.throttling_state(m), False)

    def test_truncated_gpu_false_is_undetermined(self):
        m = {"gpu_throttling": False, "gpu_clock_samples": 30,
             "gpu_clock_max_mhz": 1800, "load_truncated": True}
        self.assertIsNone(thermal_bench.throttling_state(m, "gpu"))

    def test_v1_session_without_truncation_flag_unchanged(self):
        # Les sessions archivees v1 n'ont pas `load_truncated` : leur lecture ne
        # doit pas bouger d'un pouce.
        v1 = {"throttling": False, "clock_max_mhz": 3600}
        self.assertIs(thermal_bench.throttling_state(v1), False)


class TestEmergencyTempOverride(unittest.TestCase):
    """Seuil d'arret d'urgence surchargeable en atelier.

    Motif (atelier, 27/07/2026) : sur un i5-1240P, le CPU passe sa premiere
    minute de charge en fenetre turbo PL2 (40 W pour un PL1 de 28 W) et atteint
    96 C alors que son TjMax est 100. Couper a 95 C empeche d'atteindre le
    regime etabli — donc de mesurer ce que le bench est cense mesurer.
    """

    def setUp(self):
        self._saved = os.environ.get(thermal_bench.EMERGENCY_TEMP_ENV)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(thermal_bench.EMERGENCY_TEMP_ENV, None)
        else:
            os.environ[thermal_bench.EMERGENCY_TEMP_ENV] = self._saved

    def _set(self, value):
        os.environ[thermal_bench.EMERGENCY_TEMP_ENV] = value

    def test_no_override_keeps_default(self):
        os.environ.pop(thermal_bench.EMERGENCY_TEMP_ENV, None)
        self.assertEqual(BenchConfig().emergency_temp_c,
                         thermal_bench.DEFAULT_EMERGENCY_TEMP_C)

    def test_override_applied(self):
        self._set("99")
        self.assertEqual(BenchConfig().emergency_temp_c, 99.0)

    def test_override_accepts_comma_decimal(self):
        self._set("97,5")
        self.assertEqual(BenchConfig().emergency_temp_c, 97.5)

    def test_override_above_tjmax_refused(self):
        # 105 depasserait le TjMax : on ne desarme pas le garde-fou.
        self._set("105")
        self.assertEqual(BenchConfig().emergency_temp_c,
                         thermal_bench.DEFAULT_EMERGENCY_TEMP_C)

    def test_garbage_falls_back_to_default(self):
        self._set("chaud")
        self.assertEqual(BenchConfig().emergency_temp_c,
                         thermal_bench.DEFAULT_EMERGENCY_TEMP_C)

    def test_explicit_value_is_clamped_too(self):
        os.environ.pop(thermal_bench.EMERGENCY_TEMP_ENV, None)
        cfg = BenchConfig(emergency_temp_c=200).normalized()
        self.assertEqual(cfg.emergency_temp_c, thermal_bench.EMERGENCY_TEMP_MAX_C)

    def test_override_is_recorded_in_the_session(self):
        """Le seuil retenu doit figurer dans le JSON : l'UI l'affiche depuis la
        session, elle ne doit jamais reecrire « 95 °C » en dur."""
        self._set("99")
        cfg = BenchConfig(idle_sec=1, load_sec=1, cooldown_sec=1).normalized()
        self.assertEqual(asdict(cfg)["emergency_temp_c"], 99.0)


class TestConfigNormalization(unittest.TestCase):
    def test_invalid_target_falls_back_to_cpu(self):
        cfg = BenchConfig(target="npu").normalized()
        self.assertEqual(cfg.target, "cpu")

    def test_gpu_fields_preserved(self):
        cfg = BenchConfig(target="gpu", gpu_adapter="NVIDIA",
                          gpu_emergency_temp_c=85).normalized()
        self.assertEqual(cfg.target, "gpu")
        self.assertEqual(cfg.gpu_adapter, "NVIDIA")
        self.assertEqual(cfg.gpu_emergency_temp_c, 85.0)


if __name__ == "__main__":
    unittest.main()
