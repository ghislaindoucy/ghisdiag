"""
Tests M4 v1.8.0 — historique des diagnostics (diag_compare).

Vérifie :
  - garde-fou identité : série BIOS prioritaire (hostname renommé toléré),
    machines différentes = incompatible ;
  - rôles avant/après par date, quel que soit l'ordre de sélection ;
  - diff des freins : résolus / apparus / persistants, y compris recalcul
    depuis les données pour les vieux rapports sans executive_summary ;
  - verdict : amélioration (frein résolu), dégradation (SMART qui se dégrade),
    stable ; les mesures instantanées n'influencent pas le verdict ;
  - SMART : appariement par n° de série, disque remplacé ignoré, seuil
    d'usure 5 points ;
  - rapport HTML généré avec les bons blocs.

Lancement :  py -m unittest discover -s tests -v
"""

import tempfile
import unittest
from pathlib import Path

from diag_compare import compare_reports, generate_history_report, load_report


def _mk_report(collected="2026-07-01 10:00:00", machine="PC-TEST", serial="SN123",
               data_extra=None, exec_summary=None):
    data = {
        "system_info": {
            "_status": "ok",
            "bios": {"serial_number": serial},
            "ram": {"total_gb": 16, "usage_percent": 40},
            "disks": {
                "physical": [{"model": "SSD", "media_type": "SSD", "interface": "SCSI"}],
                "volumes": [{"drive_letter": "C:", "free_gb": 120,
                             "used_percent": 50, "low_space": False}],
            },
        },
        "performance": {"_status": "ok",
                        "cpu": {"load_percent": 10, "top_processes": []},
                        "ram": {"usage_percent": 40, "top_processes": []}},
        "events": {"_status": "ok", "diag_perf": [], "crash_events": [],
                   "whea_events": [], "disk_events": [], "ntfs_events": [],
                   "total_errors": 5},
        "startup": {"_status": "ok", "startup_programs": [{"name": "a"}] * 4},
        "software": {"_status": "ok", "drivers": {"errors_count": 0}},
        "smart": {"_status": "ok", "available": True, "disks": [
            {"serial": "DSK1", "model": "Samsung SSD", "smart_passed": True,
             "wear_percent": 10, "reallocated_sectors": 0, "pending_sectors": 0}]},
        "security": {"_status": "ok",
                     "antivirus": [{"name": "Defender", "realtime_enabled": True}]},
        "sensors": {"_status": "ok", "cpu_temp": 45},
    }
    if data_extra:
        for k, v in data_extra.items():
            if isinstance(v, dict) and isinstance(data.get(k), dict):
                data[k].update(v)
            else:
                data[k] = v
    rep = {"meta": {"machine": machine, "collected_at": collected,
                    "collectors_ok": 8, "collectors_fail": []},
           "data": data}
    if exec_summary is not None:
        rep["executive_summary"] = exec_summary
    return rep


class TestIdentite(unittest.TestCase):

    def test_meme_serie_hostname_renomme_compatible(self):
        r1 = _mk_report(machine="ANCIEN-NOM")
        r2 = _mk_report("2026-07-15 10:00:00", machine="NOUVEAU-NOM")
        self.assertTrue(compare_reports(r1, r2)["compatible"])

    def test_series_differentes_incompatible(self):
        r1 = _mk_report(serial="SN-AAA")
        r2 = _mk_report("2026-07-15 10:00:00", serial="SN-BBB")
        self.assertFalse(compare_reports(r1, r2)["compatible"])

    def test_serie_placeholder_repli_hostname(self):
        r1 = _mk_report(serial="To Be Filled By O.E.M.")
        r2 = _mk_report("2026-07-15 10:00:00", serial=None)
        self.assertTrue(compare_reports(r1, r2)["compatible"])
        r3 = _mk_report("2026-07-20 10:00:00", serial=None, machine="AUTRE-PC")
        self.assertFalse(compare_reports(r1, r3)["compatible"])

    def test_ordre_de_selection_indifferent(self):
        old = _mk_report("2026-06-01 08:00:00")
        new = _mk_report("2026-07-15 10:00:00")
        cmp = compare_reports(new, old)  # sélection inversée
        self.assertEqual(cmp["date_before"], "2026-06-01 08:00:00")
        self.assertEqual(cmp["date_after"], "2026-07-15 10:00:00")


class TestFreinsEtVerdict(unittest.TestCase):

    def test_frein_resolu_amelioration(self):
        # avant : RAM saturée ; après : rien → amélioration
        before = _mk_report(data_extra={
            "performance": {"ram": {"usage_percent": 93, "top_processes": []}}})
        after = _mk_report("2026-07-15 10:00:00")
        cmp = compare_reports(before, after)
        self.assertEqual([f["key"] for f in cmp["resolved"]], ["ram_saturated"])
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_vieux_rapport_sans_executive_summary_recalcule(self):
        # executive_summary absent des deux → findings recalculés depuis data
        before = _mk_report(data_extra={
            "performance": {"ram": {"usage_percent": 93, "top_processes": []}}})
        after = _mk_report("2026-07-15 10:00:00")
        self.assertNotIn("executive_summary", before)
        cmp = compare_reports(before, after)
        self.assertEqual(len(cmp["resolved"]), 1)

    def test_executive_summary_stocke_prioritaire(self):
        before = _mk_report(exec_summary=[
            {"key": "hdd_system", "score": 90, "severity": "crit",
             "title": "HDD", "constat": "x", "action": "y"}])
        after = _mk_report("2026-07-15 10:00:00", exec_summary=[])
        cmp = compare_reports(before, after)
        self.assertEqual([f["key"] for f in cmp["resolved"]], ["hdd_system"])

    def test_frein_apparu_et_persistant(self):
        before = _mk_report(data_extra={
            "software": {"drivers": {"errors_count": 2}}})
        after = _mk_report("2026-07-15 10:00:00", data_extra={
            "software": {"drivers": {"errors_count": 2}},
            "system_info": {"disks": {
                "physical": [{"model": "WD HDD", "media_type": "HDD", "interface": "SCSI"}],
                "volumes": [{"drive_letter": "C:", "free_gb": 120,
                             "used_percent": 50, "low_space": False}]}}})
        cmp = compare_reports(before, after)
        self.assertEqual([f["key"] for f in cmp["appeared"]], ["hdd_system"])
        self.assertEqual([f["key"] for f in cmp["persistent"]], ["drivers_error"])
        self.assertEqual(cmp["verdict_level"], "crit")

    def test_stable(self):
        cmp = compare_reports(_mk_report(), _mk_report("2026-07-15 10:00:00"))
        self.assertEqual(cmp["verdict_level"], "stable")

    def test_mesure_instantanee_hors_verdict(self):
        # CPU chargé au moment du 2e diag (< seuil de frein) : pas de dégradation
        after = _mk_report("2026-07-15 10:00:00", data_extra={
            "performance": {"cpu": {"load_percent": 75, "top_processes": []},
                            "ram": {"usage_percent": 70, "top_processes": []}}})
        cmp = compare_reports(_mk_report(), after)
        self.assertEqual(cmp["verdict_level"], "stable")
        cpu = next(m for m in cmp["metrics"] if m["key"] == "cpu_pct")
        self.assertFalse(cpu["durable"])
        self.assertEqual(cpu["trend"], "worsened")


class TestSmart(unittest.TestCase):

    def test_disque_qui_se_degrade_verdict_crit(self):
        after = _mk_report("2026-07-15 10:00:00", data_extra={
            "smart": {"disks": [
                {"serial": "DSK1", "model": "Samsung SSD", "smart_passed": True,
                 "wear_percent": 10, "reallocated_sectors": 8, "pending_sectors": 2}]}})
        cmp = compare_reports(_mk_report(), after)
        self.assertTrue(cmp["smart"][0]["worsened"])
        self.assertEqual(cmp["verdict_level"], "crit")
        self.assertIn("SMART", cmp["verdict"])

    def test_usure_normale_pas_degrade(self):
        after = _mk_report("2026-07-15 10:00:00", data_extra={
            "smart": {"disks": [
                {"serial": "DSK1", "model": "Samsung SSD", "smart_passed": True,
                 "wear_percent": 12, "reallocated_sectors": 0, "pending_sectors": 0}]}})
        cmp = compare_reports(_mk_report(), after)
        self.assertFalse(cmp["smart"][0]["worsened"])
        self.assertEqual(cmp["verdict_level"], "stable")

    def test_disque_remplace_ignore(self):
        after = _mk_report("2026-07-15 10:00:00", data_extra={
            "smart": {"disks": [
                {"serial": "AUTRE", "model": "Nouveau SSD", "smart_passed": True,
                 "wear_percent": 0, "reallocated_sectors": 0, "pending_sectors": 0}]}})
        cmp = compare_reports(_mk_report(), after)
        self.assertEqual(cmp["smart"], [])


class TestMetriquesEtRapport(unittest.TestCase):

    def test_boot_plus_rapide_detecte(self):
        before = _mk_report(data_extra={"events": {"diag_perf": [
            {"category": "boot", "time_created": "2026-06-30", "duration_ms": 95000}]}})
        after = _mk_report("2026-07-15 10:00:00", data_extra={"events": {"diag_perf": [
            {"category": "boot", "time_created": "2026-07-14", "duration_ms": 30000}]}})
        cmp = compare_reports(before, after)
        boot = next(m for m in cmp["metrics"] if m["key"] == "boot_ms")
        self.assertEqual(boot["trend"], "improved")
        self.assertEqual(cmp["verdict_level"], "ok")

    def test_rapport_html_genere(self):
        before = _mk_report(data_extra={
            "performance": {"ram": {"usage_percent": 93, "top_processes": []}}})
        after = _mk_report("2026-07-15 10:00:00")
        cmp = compare_reports(before, after)
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_history_report(cmp, tmp)
            html = path.read_text(encoding="utf-8")
        self.assertIn("Historique des diagnostics", html)
        self.assertIn("Amélioration nette", html)
        self.assertIn("Résolus (1)", html)
        self.assertIn("n'influencent pas le verdict", html)

    def test_rapport_machines_differentes_avertit(self):
        r1 = _mk_report(serial="SN-AAA", machine="PC-A")
        r2 = _mk_report("2026-07-15 10:00:00", serial="SN-BBB", machine="PC-B")
        cmp = compare_reports(r1, r2)
        with tempfile.TemporaryDirectory() as tmp:
            html = generate_history_report(cmp, tmp).read_text(encoding="utf-8")
        self.assertIn("Machines différentes", html)

    def test_load_report_robuste(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{pas du json", encoding="utf-8")
            self.assertIsNone(load_report(bad))
            notrep = Path(tmp) / "notrep.json"
            notrep.write_text('{"foo": 1}', encoding="utf-8")
            self.assertIsNone(load_report(notrep))
            ok = Path(tmp) / "ok.json"
            import json as _json
            ok.write_text(_json.dumps(_mk_report()), encoding="utf-8")
            self.assertIsNotNone(load_report(ok))


if __name__ == "__main__":
    unittest.main()
