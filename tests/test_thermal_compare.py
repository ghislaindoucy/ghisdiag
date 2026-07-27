"""
Tests de la comparaison avant/après (thermal_compare) — cibles CPU et GPU.

Vérifie :
  - rétro-compatibilité CPU : gains sourcés sur les métriques historiques,
    mêmes clés génériques, verdict inchangé ;
  - comparaison GPU : gains sourcés sur les métriques gpu_*, throttling sur
    gpu_throttling, extras GPU (hotspot / clock / power) ;
  - garde-fous : cible différente = incompatible ; adaptateur GPU différent
    = incompatible (avant/après sur le même matériel uniquement) ; noyau de
    charge différent = incompatible ;
  - conditions de mesure : arrêt d'urgence, interruption, charge écourtée et
    refroidissement tronqué sont signalés, et bloquent le chiffrage du gain ;
  - throttling non mesuré : ni « éliminé », ni « absent » — y compris sur une
    session archivée v1 dont le `False` était une valeur par défaut ;
  - rapport HTML : généré, nom suffixé _gpu, contient carte + seuil 90 °C.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from thermal_compare import (compare_sessions, generate_comparison_report,
                             _protocol_diff)


def _load_samples(sec=120, step=10, start=60):
    """Échantillons d'une phase de charge menée à son terme."""
    return [{"t": t, "phase": "load", "cpu": 80.0, "gpu": 70.0}
            for t in range(start, start + sec + 1, step)]


def _mk_session(label, target="cpu", metrics=None, adapter=None,
                started="2026-07-17T10:00:00", samples=None, **extra):
    s = {
        "version": 2, "label": label, "started_at": started,
        "machine": {"hostname": "TEST", "cpu": "TestCPU", "cores": 8},
        "config": {"label": label, "idle_sec": 60, "load_sec": 120,
                   "cooldown_sec": 60, "intensity": 100, "target": target,
                   "kernel": "avx"},
        "aborted": False, "emergency": False,
        "metrics": metrics or {},
        "samples": _load_samples() if samples is None else samples,
    }
    s.update(extra)      # emergency / aborted / cooldown_truncated par test
    if adapter is not None:
        s["gpu_adapter"] = {"index": 0, "name": adapter, "vendor": "NVIDIA",
                            "vram_mb": 4096}
    return s


# `clock_max_mhz` / `gpu_clock_max_mhz` présents = le throttling a bien été
# MESURÉ (sans fréquence relevée, throttling_state() le requalifie en
# indéterminé — voir TestThrottlingUnknown).
_CPU_BEFORE = {"idle_c": 40.0, "load_max_c": 92.0, "load_plateau_c": 90.0,
               "delta_c": 50.0, "cooldown_sec": 120.0, "throttling": True,
               "clock_max_mhz": 3600, "clock_samples": 120}
_CPU_AFTER  = {"idle_c": 38.0, "load_max_c": 80.0, "load_plateau_c": 78.0,
               "delta_c": 40.0, "cooldown_sec": 60.0, "throttling": False,
               "clock_max_mhz": 3600, "clock_samples": 120}

_GPU_BEFORE = {"gpu_idle_c": 45.0, "gpu_max_c": 88.0, "gpu_plateau_c": 86.0,
               "gpu_delta_c": 41.0, "gpu_cooldown_sec": 90.0,
               "gpu_throttling": True, "gpu_hotspot_max_c": 102.0,
               "gpu_clock_drop_pct": 12.0, "gpu_power_max_w": 95.0,
               "gpu_clock_max_mhz": 1800, "gpu_clock_samples": 120,
               # métriques CPU ambiantes, ne doivent PAS servir aux gains
               "delta_c": 5.0, "load_plateau_c": 50.0}
_GPU_AFTER  = {"gpu_idle_c": 44.0, "gpu_max_c": 74.0, "gpu_plateau_c": 72.0,
               "gpu_delta_c": 28.0, "gpu_cooldown_sec": 35.0,
               "gpu_throttling": False, "gpu_hotspot_max_c": 84.0,
               "gpu_clock_drop_pct": 1.0, "gpu_power_max_w": 99.0,
               "gpu_clock_max_mhz": 1800, "gpu_clock_samples": 120,
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


class TestConditions(unittest.TestCase):
    """Les CONDITIONS de déroulement doivent être comparées, pas seulement le
    protocole demandé. Cas réel (atelier, 27/07/2026) : un run noyau `python`
    coupé à 25 s sur 300 s comparé à un run noyau `avx` complet ne déclenchait
    aucun avertissement — l'écart de température ne devait pourtant rien à
    l'intervention.
    """

    def _cmp(self, before_kw=None, after_kw=None):
        return compare_sessions(
            _mk_session("avant", metrics=_CPU_BEFORE, **(before_kw or {})),
            _mk_session("apres", metrics=_CPU_AFTER,
                        started="2026-07-17T12:00:00", **(after_kw or {})))

    def test_clean_pair_has_no_blocking_issue(self):
        cmp = self._cmp()
        self.assertFalse(cmp["blocking"])
        self.assertEqual([i for i in cmp["issues"] if i["blocking"]], [])
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_kernel_mismatch_is_incompatible_and_reported(self):
        after = _mk_session("apres", metrics=_CPU_AFTER,
                            started="2026-07-17T12:00:00")
        after["config"]["kernel"] = "python"
        cmp = compare_sessions(_mk_session("avant", metrics=_CPU_BEFORE), after)
        self.assertFalse(cmp["compatible"])
        self.assertTrue(cmp["blocking"])
        self.assertIn("noyau de charge", _protocol_diff(cmp))
        self.assertTrue(any("Noyaux de charge différents" in i["text"]
                            for i in cmp["issues"]))
        self.assertIn("non concluante", cmp["verdict"])

    def test_emergency_run_blocks_the_verdict(self):
        # Charge coupée à 25 s sur 120 s prévues, arrêt d'urgence.
        cmp = self._cmp(before_kw={"emergency": True,
                                   "samples": _load_samples(sec=25, step=5)})
        self.assertTrue(cmp["blocking"])
        self.assertTrue(cmp["conditions_before"]["emergency"])
        self.assertTrue(cmp["conditions_before"]["load_truncated"])
        self.assertEqual(cmp["conditions_before"]["load_sec_real"], 25.0)
        issue = next(i for i in cmp["issues"] if i["blocking"])
        self.assertIn("arrêt d'urgence", issue["text"])
        self.assertIn("25 s sur 120 s", issue["text"])
        # Le protocole demandé reste identique : c'est bien le DÉROULÉ qui bloque.
        self.assertTrue(cmp["compatible"])
        self.assertEqual(cmp["verdict_level"], "warn")
        self.assertIn("non concluante", cmp["verdict"])

    def test_truncated_load_without_emergency_still_blocks(self):
        cmp = self._cmp(after_kw={"samples": _load_samples(sec=30, step=5)})
        self.assertTrue(cmp["blocking"])
        self.assertTrue(any("régime établi" in i["text"] for i in cmp["issues"]))

    def test_aborted_run_blocks(self):
        cmp = self._cmp(before_kw={"aborted": True})
        self.assertTrue(cmp["blocking"])
        self.assertTrue(any("interrompu" in i["text"] for i in cmp["issues"]))

    def test_truncated_cooldown_warns_without_blocking(self):
        cmp = self._cmp(after_kw={"cooldown_truncated": True})
        self.assertFalse(cmp["blocking"])
        warn = next(i for i in cmp["issues"] if "retour au calme" in i["text"])
        self.assertEqual(warn["level"], "warn")
        self.assertFalse(warn["blocking"])
        # Un simple bémol ne doit pas effacer le gain mesuré.
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_conditions_reach_the_report(self):
        cmp = self._cmp(before_kw={"emergency": True,
                                   "samples": _load_samples(sec=25, step=5)})
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_comparison_report(cmp["before"], cmp["after"], tmp, cmp)
            doc = Path(path).read_text(encoding="utf-8")
        self.assertIn("conditions de mesure", doc)
        self.assertIn("Ce qui s'est réellement passé", doc)
        self.assertIn("arrêt d&#x27;urgence", doc)   # texte échappé
        self.assertIn("25 s tenues sur 120 s prévues", doc)
        self.assertIn("noyau avx", doc)


class TestThrottlingUnknown(unittest.TestCase):
    """Throttling non mesuré : ni « oui », ni « non »."""

    _NO_CLOCK_BEFORE = {**_CPU_BEFORE, "throttling": None,
                        "clock_max_mhz": None, "clock_samples": 0}
    _NO_CLOCK_AFTER  = {**_CPU_AFTER, "throttling": None,
                        "clock_max_mhz": None, "clock_samples": 0}

    def _cmp(self):
        return compare_sessions(
            _mk_session("avant", metrics=self._NO_CLOCK_BEFORE),
            _mk_session("apres", metrics=self._NO_CLOCK_AFTER,
                        started="2026-07-17T12:00:00"))

    def test_unknown_is_not_eliminated_nor_absent(self):
        thr = self._cmp()["throttling"]
        self.assertFalse(thr["measured"])
        self.assertIsNone(thr["before"])
        self.assertIsNone(thr["after"])
        self.assertFalse(thr["eliminated"])
        self.assertFalse(thr["appeared"])

    def test_unknown_is_flagged_without_blocking(self):
        cmp = self._cmp()
        issue = next(i for i in cmp["issues"] if "Throttling non mesuré" in i["text"])
        self.assertFalse(issue["blocking"])
        self.assertFalse(cmp["blocking"])      # les températures restent valables
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_report_says_not_measured(self):
        cmp = self._cmp()
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_comparison_report(cmp["before"], cmp["after"], tmp, cmp)
            doc = Path(path).read_text(encoding="utf-8")
        self.assertIn("Non mesuré", doc)
        self.assertNotIn("Absent dans les deux cas", doc)

    def test_legacy_session_without_clock_is_requalified(self):
        """Session v1 archivée : `throttling: False` sans aucune fréquence
        relevée n'était pas une mesure — la comparaison ne doit pas le croire."""
        legacy_before = {"idle_c": 40.0, "load_max_c": 92.0,
                         "load_plateau_c": 90.0, "delta_c": 50.0,
                         "throttling": False, "clock_max_mhz": None}
        cmp = compare_sessions(
            _mk_session("avant", metrics=legacy_before),
            _mk_session("apres", metrics=_CPU_AFTER,
                        started="2026-07-17T12:00:00"))
        self.assertFalse(cmp["throttling"]["measured"])
        self.assertIsNone(cmp["throttling"]["before"])


if __name__ == "__main__":
    unittest.main()
