"""
Tests de la comparaison avant/après (thermal_compare) — cibles CPU et GPU.

Vérifie :
  - rétro-compatibilité CPU : gains sourcés sur les métriques historiques,
    mêmes clés génériques, verdict inchangé ;
  - comparaison GPU : gains sourcés sur les métriques gpu_*, throttling sur
    gpu_throttling, extras GPU (hotspot / clock / power) ;
  - garde-fous : cible différente = incompatible ; adaptateur GPU différent
    = incompatible (avant/après sur le même matériel uniquement) ;
  - rapport HTML : généré, nom suffixé _gpu, contient carte + seuil 90 °C.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from thermal_compare import compare_sessions, generate_comparison_report


def _mk_session(label, target="cpu", metrics=None, adapter=None,
                started="2026-07-17T10:00:00", samples=None):
    s = {
        "version": 1, "label": label, "started_at": started,
        "machine": {"hostname": "TEST", "cpu": "TestCPU", "cores": 8},
        "config": {"label": label, "idle_sec": 60, "load_sec": 120,
                   "cooldown_sec": 60, "intensity": 100, "target": target},
        "aborted": False, "emergency": False,
        "metrics": metrics or {},
        "samples": samples or [],
    }
    if adapter is not None:
        s["gpu_adapter"] = {"index": 0, "name": adapter, "vendor": "NVIDIA",
                            "vram_mb": 4096}
    return s


_CPU_BEFORE = {"idle_c": 40.0, "load_max_c": 92.0, "load_plateau_c": 90.0,
               "delta_c": 50.0, "cooldown_sec": 120.0, "throttling": True}
_CPU_AFTER  = {"idle_c": 38.0, "load_max_c": 80.0, "load_plateau_c": 78.0,
               "delta_c": 40.0, "cooldown_sec": 60.0, "throttling": False}

_GPU_BEFORE = {"gpu_idle_c": 45.0, "gpu_max_c": 88.0, "gpu_plateau_c": 86.0,
               "gpu_delta_c": 41.0, "gpu_cooldown_sec": 90.0,
               "gpu_throttling": True, "gpu_hotspot_max_c": 102.0,
               "gpu_clock_drop_pct": 12.0, "gpu_power_max_w": 95.0,
               # métriques CPU ambiantes, ne doivent PAS servir aux gains
               "delta_c": 5.0, "load_plateau_c": 50.0}
_GPU_AFTER  = {"gpu_idle_c": 44.0, "gpu_max_c": 74.0, "gpu_plateau_c": 72.0,
               "gpu_delta_c": 28.0, "gpu_cooldown_sec": 35.0,
               "gpu_throttling": False, "gpu_hotspot_max_c": 84.0,
               "gpu_clock_drop_pct": 1.0, "gpu_power_max_w": 99.0,
               "delta_c": 5.0, "load_plateau_c": 50.0}


class TestCpuCompare(unittest.TestCase):
    """Rétro-compatibilité : la comparaison CPU historique est inchangée."""

    def test_cpu_gains_and_verdict(self):
        cmp = compare_sessions(
            _mk_session("avant", metrics=_CPU_BEFORE),
            _mk_session("apres", metrics=_CPU_AFTER,
                        started="2026-07-17T12:00:00"))
        self.assertTrue(cmp["compatible"])
        self.assertEqual(cmp["target"], "cpu")
        self.assertIsNone(cmp["gpu_extras"])
        self.assertEqual(cmp["gains"]["load_plateau_c"]["gain"], 12.0)
        self.assertEqual(cmp["gains"]["delta_c"]["gain"], 10.0)
        self.assertTrue(cmp["throttling"]["eliminated"])
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_cpu_vs_gpu_incompatible(self):
        cmp = compare_sessions(
            _mk_session("avant", metrics=_CPU_BEFORE),
            _mk_session("apres", target="gpu", metrics=_GPU_AFTER,
                        adapter="FakeGPU"))
        self.assertFalse(cmp["compatible"])


class TestGpuCompare(unittest.TestCase):
    def _cmp(self, before_adapter="RTX Test 4060", after_adapter="RTX Test 4060"):
        return compare_sessions(
            _mk_session("avant", target="gpu", metrics=_GPU_BEFORE,
                        adapter=before_adapter),
            _mk_session("apres", target="gpu", metrics=_GPU_AFTER,
                        adapter=after_adapter,
                        started="2026-07-17T12:00:00"))

    def test_gpu_gains_use_gpu_metrics(self):
        cmp = self._cmp()
        self.assertTrue(cmp["compatible"])
        self.assertEqual(cmp["target"], "gpu")
        # Gains sur gpu_* — pas sur les métriques CPU ambiantes (delta_c=5).
        self.assertEqual(cmp["gains"]["delta_c"]["gain"], 13.0)
        self.assertEqual(cmp["gains"]["load_plateau_c"]["gain"], 14.0)
        self.assertEqual(cmp["gains"]["load_max_c"]["gain"], 14.0)
        self.assertEqual(cmp["gains"]["cooldown_sec"]["gain"], 55.0)
        # Throttling GPU éliminé -> verdict positif.
        self.assertTrue(cmp["throttling"]["eliminated"])
        self.assertEqual(cmp["verdict_level"], "ok")
        self.assertIn("°C", cmp["verdict"])

    def test_gpu_extras(self):
        extras = self._cmp()["gpu_extras"]
        self.assertEqual(extras["hotspot_max_c"]["gain"], 18.0)
        self.assertEqual(extras["clock_drop_pct"]["gain"], 11.0)
        self.assertEqual(extras["power_max_w"]["before"], 95.0)

    def test_adapter_mismatch_incompatible(self):
        cmp = self._cmp(after_adapter="GTX Autre 1060")
        self.assertFalse(cmp["compatible"])
        self.assertTrue(cmp["adapter_mismatch"])
        self.assertEqual(cmp["adapter_before"], "RTX Test 4060")
        self.assertEqual(cmp["adapter_after"], "GTX Autre 1060")

    def test_adapter_unknown_tolerated(self):
        """Vieille session sans gpu_adapter : pas de blocage."""
        cmp = compare_sessions(
            _mk_session("avant", target="gpu", metrics=_GPU_BEFORE),
            _mk_session("apres", target="gpu", metrics=_GPU_AFTER,
                        adapter="RTX Test 4060",
                        started="2026-07-17T12:00:00"))
        self.assertTrue(cmp["compatible"])
        self.assertFalse(cmp["adapter_mismatch"])


class TestGpuReport(unittest.TestCase):
    def test_report_written_with_gpu_content(self):
        before = _mk_session(
            "avant", target="gpu", metrics=_GPU_BEFORE, adapter="RTX Test 4060",
            samples=[{"t": t, "phase": "load", "gpu": 60.0 + t / 10,
                      "cpu": 50.0} for t in range(0, 240, 10)])
        after = _mk_session(
            "apres", target="gpu", metrics=_GPU_AFTER, adapter="RTX Test 4060",
            started="2026-07-17T12:00:00",
            samples=[{"t": t, "phase": "load", "gpu": 50.0 + t / 20,
                      "cpu": 50.0} for t in range(0, 240, 10)])
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_comparison_report(before, after, tmp)
            self.assertTrue(Path(path).is_file())
            self.assertIn("_gpu_", Path(path).name)
            doc = Path(path).read_text(encoding="utf-8")
        self.assertIn("Bench thermique GPU", doc)
        self.assertIn("RTX Test 4060", doc)
        self.assertIn("90 °C", doc)          # seuil GPU, pas 95
        self.assertIn("Avant (GPU)", doc)    # légende des courbes
        self.assertIn("Hotspot max", doc)
        self.assertIn("Chute de clock", doc)

    def test_cpu_report_unchanged(self):
        before = _mk_session("avant", metrics=_CPU_BEFORE)
        after = _mk_session("apres", metrics=_CPU_AFTER,
                            started="2026-07-17T12:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_comparison_report(before, after, tmp)
            self.assertNotIn("_gpu_", Path(path).name)
            doc = Path(path).read_text(encoding="utf-8")
        self.assertIn("Bench thermique CPU", doc)
        self.assertIn("95 °C", doc)
        self.assertNotIn("Hotspot max", doc)


if __name__ == "__main__":
    unittest.main()
