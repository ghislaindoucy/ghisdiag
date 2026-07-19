"""
Tests M2 v1.8.0 — pilotes non signés / anciens dans le rapport.

Vérifie :
  - garde-fou bruit : 1-2 pilotes anciens anodins = pas d'alerte ; alerte si
    GPU/réseau concerné, ou à partir de 3 pilotes ;
  - pilote non signé = alerte, avec les périphériques nommés ;
  - rendu HTML : tableaux présents, colonne « Où mettre à jour » sourcée par
    classe de périphérique.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from report.generator import ReportGenerator, _driver_update_source


def _report(drivers):
    return {
        "meta": {"machine": "TESTPC", "collected_at": "2026-07-19 10:00",
                 "collectors_ok": 8, "collectors_fail": []},
        "data": {"software": {"_status": "ok", "software": {"count": 0, "items": []},
                              "drivers": drivers}},
    }


def _drv(name, cls, date="2018-01-01", **kw):
    d = {"device_name": name, "device_class": cls, "manufacturer": "ACME",
         "driver_version": "1.0", "driver_date": date, "inf_name": "oem1.inf"}
    d.update(kw)
    return d


def _alert_titles(gen):
    gen._analyse()
    return [t for _, t, _ in gen.alerts]


class TestAlertesDrivers(unittest.TestCase):

    def test_deux_pilotes_anciens_anodins_pas_d_alerte(self):
        gen = ReportGenerator(_report({
            "outdated_drivers": [_drv("Card Reader", "USB"), _drv("SATA AHCI", "HDC")]}))
        titles = _alert_titles(gen)
        self.assertNotIn("Pilotes anciens", titles)
        self.assertNotIn("Pilote graphique/réseau ancien", titles)

    def test_pilote_display_ancien_alerte(self):
        gen = ReportGenerator(_report({
            "outdated_drivers": [_drv("NVIDIA GeForce GT 710", "DISPLAY")]}))
        gen._analyse()
        match = [a for a in gen.alerts if a[1] == "Pilote graphique/réseau ancien"]
        self.assertEqual(len(match), 1)
        self.assertIn("GT 710", match[0][2])

    def test_trois_pilotes_anciens_alerte_generique(self):
        gen = ReportGenerator(_report({
            "outdated_drivers": [_drv(f"Dev{i}", "USB") for i in range(3)]}))
        self.assertIn("Pilotes anciens", _alert_titles(gen))

    def test_pilote_non_signe_alerte(self):
        gen = ReportGenerator(_report({
            "unsigned_drivers": [_drv("Mystery Device", "USB", is_signed=False)]}))
        gen._analyse()
        match = [a for a in gen.alerts if a[1] == "Pilotes non signés"]
        self.assertEqual(len(match), 1)
        self.assertIn("Mystery Device", match[0][2])

    def test_donnees_absentes_ou_degenerees(self):
        for drivers in ({}, None, "err", []):
            gen = ReportGenerator(_report(drivers))
            gen._analyse()  # ne doit pas lever


class TestRenduSectionDrivers(unittest.TestCase):

    def test_source_de_mise_a_jour_par_classe(self):
        self.assertIn("NVIDIA", _driver_update_source("DISPLAY"))
        self.assertIn("constructeur", _driver_update_source("NET"))
        self.assertIn("Windows Update", _driver_update_source("PRINTER"))
        self.assertIn("Windows Update", _driver_update_source(None))

    def test_html_tableaux_presents(self):
        rep = _report({
            "errors_count": 0, "recent_count": 0, "total": 10,
            "unsigned_drivers": [_drv("Mystery Device", "USB")],
            "outdated_drivers": [_drv("NVIDIA GeForce GT 710", "DISPLAY", date="2017-05-01")],
        })
        with tempfile.TemporaryDirectory() as tmp:
            html_path, _ = ReportGenerator(rep, output_dir=Path(tmp)).save()
            html = html_path.read_text(encoding="utf-8")
        self.assertIn("Pilotes non signés sur du matériel actif", html)
        self.assertIn("Mystery Device", html)
        self.assertIn("Pilotes anciens", html)
        self.assertIn("GT 710", html)
        self.assertIn("Où mettre à jour", html)
        self.assertIn("NVIDIA / AMD / Intel", html)

    def test_html_sans_probleme_pas_de_tableaux(self):
        rep = _report({"errors_count": 0, "recent_count": 0, "total": 10,
                       "unsigned_drivers": [], "outdated_drivers": []})
        with tempfile.TemporaryDirectory() as tmp:
            html_path, _ = ReportGenerator(rep, output_dir=Path(tmp)).save()
            html = html_path.read_text(encoding="utf-8")
        self.assertNotIn("Pilotes non signés sur du matériel actif", html)
        self.assertNotIn("Où mettre à jour", html)


if __name__ == "__main__":
    unittest.main()
