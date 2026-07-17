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
  - compute_metrics : detection de throttling GPU sur chute de clock a chaud.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import threading
import time
import unittest
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
    "gpu_idle_c", "gpu_max_c", "fan_idle_rpm", "fan_load_rpm",
    "clock_max_mhz", "clock_drop_pct", "throttling", "power_limited",
    "cooldown_sec", "recovery_margin_c",
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
