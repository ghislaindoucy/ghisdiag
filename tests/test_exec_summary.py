"""
Tests du résumé exécutif « Ce qui ralentit ce PC » (report/exec_summary.py).

Vérifie :
  - chaque règle se déclenche sur son cas nominal (et pas en dessous du seuil) ;
  - les garde-fous honnêteté : HDD seul = verdict fort, HDD + SSD = conditionnel,
    disque USB exclu ; collecteur en échec (_status != ok) = règle muette ;
  - la priorisation : tri par score décroissant, severity dérivée du score ;
  - la robustesse : données vides / dégénérées ne lèvent jamais ;
  - l'intégration générateur : section HTML présente, findings injectés dans le JSON.

Lancement :  py -m unittest discover -s tests -v
"""

import json
import tempfile
import unittest
from pathlib import Path

from report.exec_summary import compute_findings
from report.generator import ReportGenerator


def _keys(findings):
    return [f["key"] for f in findings]


def _healthy_data():
    """Machine saine : aucune règle ne doit se déclencher."""
    return {
        "system_info": {
            "_status": "ok",
            "ram": {"total_gb": 16, "usage_percent": 40},
            "disks": {
                "physical": [{"model": "Samsung SSD 870", "media_type": "SSD",
                              "interface": "SCSI"}],
                "volumes": [{"drive_letter": "C:", "free_gb": 200,
                             "used_percent": 55, "low_space": False}],
            },
        },
        "performance": {
            "_status": "ok",
            "cpu": {"load_percent": 12, "top_processes": [{"name": "chrome", "cpu_sec": 40}]},
            "ram": {"usage_percent": 40, "top_processes": [{"name": "chrome", "ram_mb": 900}]},
        },
        "events": {"_status": "ok", "diag_perf": [], "disk_events": [], "ntfs_events": []},
        "sensors": {"_status": "ok", "cpu_temp": 45, "ok": True},
        "security": {"_status": "ok",
                     "antivirus": [{"name": "Defender", "realtime_enabled": True}]},
        "startup": {"_status": "ok", "startup_programs": [{"name": f"p{i}"} for i in range(4)]},
        "software": {"_status": "ok", "drivers": {"errors_count": 0}},
        "smart": {"_status": "ok", "available": True,
                  "disks": [{"model": "Samsung SSD 870", "smart_passed": True}]},
    }


class TestRules(unittest.TestCase):

    def test_machine_saine_aucun_finding(self):
        self.assertEqual(compute_findings(_healthy_data()), [])

    # ── HDD : garde-fous honnêteté ────────────────────────────────────────────
    def test_hdd_seul_disque_interne_verdict_fort(self):
        d = _healthy_data()
        d["system_info"]["disks"]["physical"] = [
            {"model": "WDC WD10EZEX", "media_type": "HDD", "interface": "SCSI"}]
        f = compute_findings(d)
        self.assertIn("hdd_system", _keys(f))
        self.assertNotIn("hdd_present", _keys(f))
        self.assertEqual(f[0]["severity"], "crit")

    def test_hdd_plus_ssd_verdict_conditionnel(self):
        d = _healthy_data()
        d["system_info"]["disks"]["physical"] = [
            {"model": "NVMe ADATA", "media_type": "SSD", "interface": "SCSI"},
            {"model": "WDC WD10EZEX", "media_type": "HDD", "interface": "SCSI"}]
        f = compute_findings(d)
        self.assertIn("hdd_present", _keys(f))
        self.assertNotIn("hdd_system", _keys(f))

    def test_hdd_usb_exclu(self):
        d = _healthy_data()
        d["system_info"]["disks"]["physical"] = [
            {"model": "Samsung SSD 870", "media_type": "SSD", "interface": "SCSI"},
            {"model": "Seagate Expansion", "media_type": "HDD", "interface": "USB"}]
        self.assertEqual(compute_findings(d), [])

    def test_collecteur_en_echec_regle_muette(self):
        d = _healthy_data()
        d["system_info"] = {"_status": "error", "error": "boom"}
        self.assertNotIn("hdd_system", _keys(compute_findings(d)))

    # ── RAM ───────────────────────────────────────────────────────────────────
    def test_ram_4gb_insuffisante(self):
        d = _healthy_data()
        d["system_info"]["ram"] = {"total_gb": 4, "usage_percent": 70}
        f = compute_findings(d)
        self.assertIn("ram_insufficient", _keys(f))
        # la règle quantité absorbe la règle saturation
        self.assertNotIn("ram_saturated", _keys(f))

    def test_ram_saturee(self):
        d = _healthy_data()
        d["performance"]["ram"]["usage_percent"] = 93
        f = compute_findings(d)
        self.assertIn("ram_saturated", _keys(f))
        ram = next(x for x in f if x["key"] == "ram_saturated")
        self.assertIn("chrome", ram["constat"])  # top consommateur nommé

    def test_ram_8gb_a_l_etroit(self):
        d = _healthy_data()
        d["system_info"]["ram"]["total_gb"] = 8
        d["performance"]["ram"]["usage_percent"] = 87
        self.assertIn("ram_tight", _keys(compute_findings(d)))

    # ── Disques ───────────────────────────────────────────────────────────────
    def test_disque_systeme_plein(self):
        d = _healthy_data()
        d["system_info"]["disks"]["volumes"] = [
            {"drive_letter": "C:", "free_gb": 6, "used_percent": 97, "low_space": True},
            {"drive_letter": "D:", "free_gb": 2, "used_percent": 99, "low_space": True}]
        f = compute_findings(d)
        # seul C: compte (un volume data plein ne ralentit pas Windows)
        self.assertEqual(_keys(f).count("disk_system_full"), 1)

    def test_smart_en_echec_prioritaire(self):
        d = _healthy_data()
        d["smart"]["disks"][0]["smart_passed"] = False
        d["system_info"]["ram"]["total_gb"] = 4  # score 85 < 88
        f = compute_findings(d)
        self.assertEqual(f[0]["key"], "disk_failing")

    def test_erreurs_disque_sans_smart_fail(self):
        d = _healthy_data()
        d["events"]["disk_events"] = [{"event_id": 153}] * 4
        f = compute_findings(d)
        self.assertIn("disk_io_errors", _keys(f))
        self.assertNotIn("disk_failing", _keys(f))

    # ── Boot / chauffe / AV / CPU / démarrage / drivers ──────────────────────
    def test_boot_lent_avec_coupables(self):
        d = _healthy_data()
        d["events"]["diag_perf"] = [
            {"category": "boot", "duration_ms": 152_000},
            {"category": "boot", "duration_ms": 30_000},  # normal, ignoré
            {"category": "boot-app", "app_name": "OneDrive.exe"},
            {"category": "boot-app", "app_name": "OneDrive.exe"},
        ]
        f = compute_findings(d)
        boot = next(x for x in f if x["key"] == "slow_boot")
        self.assertIn("152", boot["constat"])
        self.assertIn("OneDrive.exe", boot["constat"])

    def test_boot_normal_ignore(self):
        d = _healthy_data()
        d["events"]["diag_perf"] = [{"category": "boot", "duration_ms": 42_000}]
        self.assertNotIn("slow_boot", _keys(compute_findings(d)))

    def test_surchauffe_cpu(self):
        d = _healthy_data()
        d["sensors"]["cpu_temp"] = 94
        self.assertIn("cpu_overheat", _keys(compute_findings(d)))
        d["sensors"]["cpu_temp"] = 80
        self.assertNotIn("cpu_overheat", _keys(compute_findings(d)))

    def test_antivirus_multiples(self):
        d = _healthy_data()
        d["security"]["antivirus"] = [
            {"name": "Defender", "realtime_enabled": True},
            {"name": "Avast", "realtime_enabled": True}]
        self.assertIn("av_multiple", _keys(compute_findings(d)))

    def test_cpu_sature_instantane(self):
        d = _healthy_data()
        d["performance"]["cpu"]["load_percent"] = 92
        f = compute_findings(d)
        cpu = next(x for x in f if x["key"] == "cpu_busy")
        self.assertIn("chrome", cpu["constat"])

    def test_demarrage_encombre(self):
        d = _healthy_data()
        d["startup"]["startup_programs"] = [{"name": f"p{i}"} for i in range(15)]
        self.assertIn("startup_bloat", _keys(compute_findings(d)))

    def test_drivers_en_erreur(self):
        d = _healthy_data()
        d["software"]["drivers"]["errors_count"] = 2
        self.assertIn("drivers_error", _keys(compute_findings(d)))

    # ── Priorisation & robustesse ─────────────────────────────────────────────
    def test_tri_par_score_decroissant(self):
        d = _healthy_data()
        d["system_info"]["disks"]["physical"] = [
            {"model": "WDC", "media_type": "HDD", "interface": "SCSI"}]
        d["software"]["drivers"]["errors_count"] = 1
        d["performance"]["cpu"]["load_percent"] = 95
        f = compute_findings(d)
        scores = [x["score"] for x in f]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(f[0]["key"], "hdd_system")

    def test_donnees_vides_ou_degenerees(self):
        self.assertEqual(compute_findings({}), [])
        self.assertEqual(compute_findings(None), [])
        # collecteurs sérialisés bizarrement (PS5.1) : ne doit pas lever
        compute_findings({"system_info": "err", "events": [1, 2],
                          "performance": {"cpu": "x"}, "smart": {"disks": "?"}})


class TestIntegrationGenerateur(unittest.TestCase):

    def _report(self, data):
        return {"meta": {"machine": "TESTPC", "collected_at": "2026-07-19 10:00",
                         "collectors_ok": 8, "collectors_fail": []},
                "data": data}

    def test_html_contient_top3_et_json_les_findings(self):
        data = _healthy_data()
        data["system_info"]["disks"]["physical"] = [
            {"model": "WDC WD10EZEX", "media_type": "HDD", "interface": "SCSI"}]
        with tempfile.TemporaryDirectory() as tmp:
            gen = ReportGenerator(self._report(data), output_dir=Path(tmp))
            html_path, json_path = gen.save()
            html = html_path.read_text(encoding="utf-8")
            self.assertIn("Ce qui ralentit ce PC", html)
            self.assertIn("disque dur mécanique", html)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["executive_summary"][0]["key"], "hdd_system")

    def test_html_machine_saine_message_positif(self):
        with tempfile.TemporaryDirectory() as tmp:
            gen = ReportGenerator(self._report(_healthy_data()), output_dir=Path(tmp))
            html_path, json_path = gen.save()
            self.assertIn("Aucun frein majeur", html_path.read_text(encoding="utf-8"))
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["executive_summary"], [])


if __name__ == "__main__":
    unittest.main()
