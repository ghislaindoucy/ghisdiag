"""
Tests de la détection GPU du bench thermique (main.py).

Contexte : la détection tourne en tâche de fond puis publie son résultat sur le
thread tkinter via `after()`. Or `after()` appelé depuis un autre thread AVANT
le démarrage de `mainloop()` lève RuntimeError après ~1 s d'attente — le
résultat était alors perdu DÉFINITIVEMENT et la cible GPU restait bloquée sur
« Détection des cartes graphiques en cours… » (constaté en atelier sur une
machine NVIDIA : détection NVML en ~50 ms, donc terminée pendant la
construction de l'UI).

Vérifie :
  - le résultat est publié même si les premiers `after()` échouent (réessais) ;
  - en cas d'échec total, l'indicateur « détection en cours » est relâché pour
    qu'une relance reste possible ;
  - `_bench_start_gpu_detect` relance une détection perdue mais n'en empile pas
    une seconde quand une détection tourne déjà.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main : son import installe un handler sur
# le journal REEL de l'utilisateur. Sans cette redirection, chaque execution de
# la suite y deversait ses faux incidents (« Fake GPU 9000 », JSON invalides
# volontaires, seuils aberrants) et poussait dehors, par rotation, les lignes de
# vrai diagnostic. Toute future importation de main depuis les tests doit faire
# de meme — c'est le seul module qui configure le journal.
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import unittest
from unittest import mock

import main

ADAPTER = {"index": 0, "name": "NVIDIA GeForce RTX 4060", "vendor": "NVIDIA",
           "vram_mb": 8188, "is_software": False}


class _FakeCombo:
    def __init__(self):
        self.values = None

    def config(self, **kw):
        self.values = kw.get("values")


class _FakeApp:
    """Instance minimale portant les seules méthodes testées."""

    _BENCH_GPU_AUTO = main.GhisdiagApp._BENCH_GPU_AUTO
    _bench_detect_gpus = main.GhisdiagApp._bench_detect_gpus
    _bench_start_gpu_detect = main.GhisdiagApp._bench_start_gpu_detect

    def __init__(self, after_failures: int = 0):
        self._after_failures = after_failures
        self.after_calls = 0
        self._bench_gpu_detect = None
        self._bench_gpu_detect_running = True
        self._bench_gpu_cb = _FakeCombo()

    def after(self, _delay, func=None, *args):
        self.after_calls += 1
        if self.after_calls <= self._after_failures:
            raise RuntimeError("main thread is not in main loop")
        func(*args)


def _patched_hardware():
    """Neutralise les accès matériels : GPU NVIDIA avec température lisible."""
    return (
        mock.patch("collectors.gpu_load.available", return_value=True),
        mock.patch("collectors.gpu_load.list_adapters", return_value=[ADAPTER]),
        mock.patch("collectors.gpu.list_gpus", return_value=[{"temp": 47.0}]),
        mock.patch("main.time.sleep"),      # pas d'attente réelle entre essais
    )


class DetectPublishesResultTests(unittest.TestCase):
    def _run_detect(self, after_failures):
        app = _FakeApp(after_failures=after_failures)
        patches = _patched_hardware()
        for p in patches:
            p.start()
        try:
            app._bench_detect_gpus()
        finally:
            for p in patches:
                p.stop()
        return app

    def test_publishes_when_ui_ready(self):
        app = self._run_detect(after_failures=0)
        self.assertIsNotNone(app._bench_gpu_detect)
        self.assertEqual(app._bench_gpu_detect["adapters"], [ADAPTER])
        self.assertTrue(app._bench_gpu_detect["temp_ok"])
        self.assertEqual(app._bench_gpu_cb.values,
                         [main.GhisdiagApp._BENCH_GPU_AUTO,
                          "[0] NVIDIA GeForce RTX 4060"])
        self.assertFalse(app._bench_gpu_detect_running)

    def test_retries_until_mainloop_is_running(self):
        # Boucle tkinter démarrée tardivement : les premiers after() échouent.
        app = self._run_detect(after_failures=5)
        self.assertIsNotNone(app._bench_gpu_detect)      # résultat NON perdu
        self.assertEqual(app.after_calls, 6)
        self.assertFalse(app._bench_gpu_detect_running)

    def test_gives_up_but_allows_a_new_detection(self):
        # Échec permanent : on abandonne, mais sans laisser l'indicateur armé
        # (sinon aucune relance ne serait plus possible).
        app = self._run_detect(after_failures=10_000)
        self.assertIsNone(app._bench_gpu_detect)
        self.assertFalse(app._bench_gpu_detect_running)


class StartDetectTests(unittest.TestCase):
    def test_starts_a_thread_when_idle(self):
        app = _FakeApp()
        app._bench_gpu_detect_running = False
        with mock.patch("main.threading.Thread") as thread_cls:
            app._bench_start_gpu_detect()
        thread_cls.assert_called_once()
        thread_cls.return_value.start.assert_called_once()
        self.assertTrue(app._bench_gpu_detect_running)

    def test_does_not_stack_a_second_detection(self):
        app = _FakeApp()
        app._bench_gpu_detect_running = True
        with mock.patch("main.threading.Thread") as thread_cls:
            app._bench_start_gpu_detect()
        thread_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
