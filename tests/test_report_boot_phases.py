"""
Tests M3 v1.8.0 — décomposition du démarrage par phase (Event ID 100).

Vérifie :
  - le bloc apparaît dès que boot_phases est présent (informative même si boot normal) ;
  - la piste de diagnostic n'apparaît que si boot lent ET phase dominante (>=40%) ;
  - rétro-compatibilité : anciens rapports sans boot_phases = pas de bloc, pas d'erreur ;
  - c'est le démarrage le plus récent qui est décomposé.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from report.generator import ReportGenerator


def _phases(main_ms, drivers_ms=1000, profile_ms=1000, **kw):
    ph = {"main_path_ms": main_ms, "total_ms": main_ms + 30000,
          "kernel_ms": 1500, "smss_ms": 800, "prefetch_ms": 0, "autochk_ms": 0,
          "drivers_ms": drivers_ms, "devices_ms": 500, "services_ms": 900,
          "user_profile_ms": profile_ms, "machine_profile_ms": 200,
          "explorer_ms": 1200, "postboot_ms": 30000, "startup_apps": 9}
    ph.update(kw)
    return ph


def _report(diag_perf):
    return {"meta": {"machine": "TESTPC", "collected_at": "2026-07-19 10:00",
                     "collectors_ok": 8, "collectors_fail": []},
            "data": {"events": {"_status": "ok", "diag_perf": diag_perf}}}


def _html(diag_perf):
    with tempfile.TemporaryDirectory() as tmp:
        html_path, _ = ReportGenerator(_report(diag_perf), output_dir=Path(tmp)).save()
        return html_path.read_text(encoding="utf-8")


class TestBootPhases(unittest.TestCase):

    def test_boot_normal_bloc_present_sans_piste(self):
        html = _html([{"category": "boot", "time_created": "2026-07-18 08:00:00",
                       "duration_ms": 32000, "boot_phases": _phases(32000)}])
        self.assertIn("phase par phase", html)
        self.assertIn("Pilotes &amp; périphériques", html)
        self.assertNotIn("Phase dominante", html)

    def test_boot_lent_phase_dominante_pilotes(self):
        # drivers = 40 s sur 70 s de main path → dominant, piste affichée
        html = _html([{"category": "boot", "time_created": "2026-07-18 08:00:00",
                       "duration_ms": 70000,
                       "boot_phases": _phases(70000, drivers_ms=40000)}])
        self.assertIn("Phase dominante", html)
        self.assertIn("pilote traîne au chargement", html)
        self.assertIn("application(s) au démarrage", html)

    def test_boot_lent_sans_phase_dominante_pas_de_piste(self):
        # lent mais réparti : aucune famille >= 40%
        html = _html([{"category": "boot", "time_created": "2026-07-18 08:00:00",
                       "duration_ms": 70000,
                       "boot_phases": _phases(70000, drivers_ms=15000, profile_ms=15000,
                                              explorer_ms=15000, kernel_ms=12000,
                                              services_ms=12000)}])
        self.assertNotIn("Phase dominante", html)

    def test_ancien_rapport_sans_phases_pas_de_bloc(self):
        html = _html([{"category": "boot", "time_created": "2026-07-18 08:00:00",
                       "duration_ms": 152000}])
        self.assertNotIn("phase par phase", html)

    def test_dernier_demarrage_retenu(self):
        html = _html([
            {"category": "boot", "time_created": "2026-07-10 08:00:00",
             "boot_phases": _phases(90000, drivers_ms=60000)},
            {"category": "boot", "time_created": "2026-07-18 09:00:00",
             "boot_phases": _phases(25000)},
        ])
        # le boot du 18 (25 s, normal) est affiché, pas la piste du vieux boot lent
        self.assertIn("2026-07-18 09:00:00", html)
        self.assertNotIn("Phase dominante", html)

    def test_phases_degenerees_sans_erreur(self):
        html = _html([{"category": "boot", "time_created": "x",
                       "boot_phases": {"main_path_ms": 0}},
                      {"category": "boot", "time_created": "y",
                       "boot_phases": {"drivers_ms": "abc", "main_path_ms": None}}])
        self.assertNotIn("Phase dominante", html)


if __name__ == "__main__":
    unittest.main()
