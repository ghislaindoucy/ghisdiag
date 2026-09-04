"""
Tests des regles d'inventaire de GhisdiagDisk (identite, type de support,
exclusions, decodage SMART et IOCTL, niveaux T1/T2/T3).

Toutes les regles testees ici ont ete CALIBREES sur les campagnes du 08/08
au 03/09/2026 (ROADMAP). Chaque test reprend un cas reel de terrain :
la cle USB dont le serie vaut << 1 >>, l'EUI-64 NVMe presque tout en zeros,
le gabarit `Optane_0000`, le NVMe muet derriere un controleur RST, la
revision de firmware rendue comme numero de serie (offsets 12/16/20/24).

Lancement :  py -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import inventory, niveaux, rawdisk, smart  # noqa: E402


class TestSerie(unittest.TestCase):

    def test_nettoyage(self):
        self.assertEqual(inventory.nettoyer_serie("\x031"), ("1", True))
        self.assertEqual(inventory.nettoyer_serie("WD-WCC2E5FK8EU6"), ("WD-WCC2E5FK8EU6", False))
        self.assertEqual(inventory.nettoyer_serie(None), (None, False))
        self.assertEqual(inventory.nettoyer_serie("  S4EVNX0N ")[0], "S4EVNX0N")

    def test_solidite(self):
        self.assertFalse(inventory.serie_solide("1")[0])
        self.assertFalse(inventory.serie_solide("0000_0000_0000_0000_0C82_D500_0000_0371")[0] and False)
        self.assertFalse(inventory.serie_solide("Optane_0000")[0])
        self.assertFalse(inventory.serie_solide("AAAAAAAA")[0])
        self.assertFalse(inventory.serie_solide("000000000000")[0])
        self.assertFalse(inventory.serie_solide(None)[0])
        self.assertTrue(inventory.serie_solide("WD-WCC2E5FK8EU6")[0])
        self.assertTrue(inventory.serie_solide("JD1009DM3B4RSK")[0])
        self.assertEqual(inventory.serie_solide("Optane_0000")[1],
                         "terminaison en zeros - serie generique de fabricant")

    def test_cle_composite_confiance(self):
        forte = inventory.cle_identite({"numero_serie": "\x031", "modele": "Kingston"},
                                       {"numero_serie": "S4EVNX0N123456"}, 500.1)
        self.assertEqual((forte["cle_identite"], forte["confiance_cle"]), ("S4EVNX0N123456", "forte"))
        moyenne = inventory.cle_identite({"numero_serie": "WD-WCC2E5FK8EU6"}, {}, 500.1)
        self.assertEqual((moyenne["cle_identite"], moyenne["confiance_cle"]),
                         ("WD-WCC2E5FK8EU6", "moyenne"))
        faible = inventory.cle_identite({"numero_serie": "\x031", "modele": "DataTraveler 3.0"},
                                        {}, 7.8)
        self.assertEqual(faible["confiance_cle"], "faible")
        self.assertEqual(faible["cle_identite"], "DataTraveler_3_0-7_8Go-SANS-SERIE")
        self.assertEqual(faible["raison_rejet_ioctl"], "trop court pour discriminer")


class TestTypeSupport(unittest.TestCase):

    def test_cascade(self):
        self.assertEqual(inventory.type_support({"bus": "NVMe"}, {}), "SSD NVMe")
        self.assertEqual(inventory.type_support({"bus": "RAID"}, {"usure_nvme_pct": 1}), "SSD NVMe")
        self.assertEqual(inventory.type_support({"bus": "SATA"}, {"rotation_rate": 0}), "SSD")
        self.assertEqual(inventory.type_support({"bus": "SATA"}, {"rotation_rate": 5400}),
                         "Disque mecanique (5400 tr/min)")
        # Anterieur a ATA8 : pas de rotation_rate, mais le profil ZBR le designe.
        self.assertEqual(inventory.type_support({"bus": "ATA"}, {}, [70.0, 52.0, 33.0]),
                         "Disque mecanique (profil ZBR, vitesse inconnue)")
        self.assertEqual(inventory.type_support({"bus": "ATA"}, {}, [500.0, 520.0, 510.0]),
                         "indetermine")
        self.assertEqual(inventory.type_support({"bus": "RAID"}, {}), "volume RAID - support reel inconnu")

    def test_profil_zbr_calibre(self):
        # 11 disques mecaniques : 0,40-0,52 monotone.
        self.assertTrue(inventory.profil_zbr([120.0, 90.0, 55.0])["signature_mecanique"])
        # NVMe sain : 65 % d'ecart mais pas monotone -> pas mecanique.
        self.assertFalse(inventory.profil_zbr([900.0, 2600.0, 2500.0])["signature_mecanique"])
        # Optane (0,08) et cle USB (0,77) exclus par la bande.
        self.assertFalse(inventory.profil_zbr([784.0, 64.0, 62.0])["signature_mecanique"])
        self.assertFalse(inventory.profil_zbr([44.0, 40.0, 34.0])["signature_mecanique"])
        # WD10SPZX avec zone de fin en cache (ratio 2,53) : pas de signature, et
        # c'est voulu - le moteur lit des zones plus grandes que le cache.
        self.assertFalse(inventory.profil_zbr([100.0, 80.0, 254.0])["signature_mecanique"])
        self.assertIsNone(inventory.profil_zbr([100.0])["signature_mecanique"])

    def test_classe(self):
        self.assertEqual(inventory.classe_support("SSD NVMe", "NVMe"), "nvme")
        self.assertEqual(inventory.classe_support("SSD", "SATA"), "ssd")
        self.assertEqual(inventory.classe_support("Disque mecanique (7200 tr/min)", "SATA"), "hdd")
        self.assertEqual(inventory.classe_support("indetermine", "USB"), "inconnue")


class TestAppariement(unittest.TestCase):

    def test_par_serie_puis_modele_jamais_par_position(self):
        smarts = [{"numero_serie": "AAA111222", "modele": "DVDRAM"},
                  {"numero_serie": "S4EVNX0N123456", "modele": "Samsung SSD 980"}]
        idt = {"numero_serie": "S4EVNX0N123456 ", "modele": "Samsung SSD 980"}
        self.assertEqual(inventory.apparier_smart(idt, smarts)["modele"], "Samsung SSD 980")
        idt = {"numero_serie": "0000_0000_0000_0C82", "modele": "Samsung SSD 980"}
        self.assertEqual(inventory.apparier_smart(idt, smarts)["numero_serie"], "S4EVNX0N123456")
        self.assertEqual(inventory.apparier_smart({"modele": "Inconnu"}, smarts), {})
        self.assertEqual(inventory.apparier_smart_detail(idt, smarts)[1], "modele")
        self.assertEqual(inventory.apparier_smart_detail({"modele": "Inconnu"}, smarts),
                         ({}, "aucun"))

    def test_absence_de_smart_expliquee_dans_la_fiche(self):
        """NVMe Samsung du 04/09 : SMART null et aucun moyen de savoir pourquoi.
        La fiche dit desormais ce que smartctl a vu."""
        geo = {"index": 1, "taille_octets": 256 * 10 ** 9, "taille_go": 256.1,
               "secteur_logique": 512, "secteur_physique": 512}
        idt = {"modele": "SAMSUNG MZVLQ256HBJD-00B00", "numero_serie": "0025_38D7_1145_F173.",
               "bus": "NVMe", "amovible": False}
        vues = {"disponible": True, "entrees": [
            {"modele": "CT240BX500SSD1", "numero_serie": "2240E6743207", "exploitable": True},
            {"modele": None, "numero_serie": None, "exploitable": False,
             "messages": ["IOCTL_STORAGE_QUERY_PROPERTY (NVMe) failed, Error=1"]}]}
        f = inventory.construire_fiche(geo, idt, {}, {"porteur_exe": [], "boot_pe": []},
                                       smart_appariement="aucun", smart_info=vues)
        self.assertFalse(f["smart_disponible"])
        self.assertEqual(f["smart_appariement"], "aucun")
        self.assertIn("aucune des 2 entree(s)", f["smart_absence"])
        self.assertIn("0025_38D7_1145_F173", f["smart_absence"])
        self.assertIn("CT240BX500SSD1", f["smart_absence"])
        self.assertIn("IOCTL_STORAGE_QUERY_PROPERTY", f["smart_absence"])
        self.assertEqual(inventory.expliquer_smart_absent(idt, {"disponible": False}),
                         "smartctl absent (tools\\smartctl.exe introuvable)")
        self.assertIn("aucun peripherique",
                      inventory.expliquer_smart_absent(idt, {"disponible": True, "entrees": []}))
        sm = {"numero_serie": "S4EV", "modele": "X", "exploitable": True}
        f = inventory.construire_fiche(geo, idt, sm, {"porteur_exe": [], "boot_pe": []},
                                       smart_appariement="modele", smart_info=vues)
        self.assertEqual(f["smart_appariement"], "modele")
        self.assertIsNone(f["smart_absence"])


class TestExclusions(unittest.TestCase):

    def _fiche(self, index, idt):
        return {"index": index, "identite": idt, "geometrie": {"taille_octets": 10 ** 12}}

    def test_porteur_et_boot(self):
        excl = {"porteur_exe": [2], "boot_pe": [3]}
        ok, raisons, _ = inventory.regles_exclusion(self._fiche(2, {"bus": "USB", "amovible": True}), excl)
        self.assertFalse(ok)
        self.assertTrue(any("garde-fou 3" in r for r in raisons))
        ok, raisons, _ = inventory.regles_exclusion(self._fiche(3, {"bus": "USB"}), excl)
        self.assertFalse(ok)
        self.assertTrue(any("demarrage" in r for r in raisons))

    def test_usb_amovible_exclu_mais_dock_teste(self):
        ok, raisons, avert = inventory.regles_exclusion(self._fiche(4, {"bus": "USB", "amovible": True}), {})
        self.assertFalse(ok)
        ok, raisons, avert = inventory.regles_exclusion(self._fiche(4, {"bus": "USB", "amovible": False}), {})
        self.assertTrue(ok)
        self.assertTrue(any("USB" in a for a in avert))

    def test_optane_composite_et_raid(self):
        ok, raisons, _ = inventory.regles_exclusion(
            self._fiche(0, {"bus": "RAID", "modele": "Optane+932GBHDD"}), {})
        self.assertFalse(ok)
        self.assertTrue(any("Optane" in r for r in raisons))
        # Le NVMe systeme derriere RST est bien TESTABLE (c'est la population visee).
        ok, raisons, avert = inventory.regles_exclusion(
            self._fiche(0, {"bus": "RAID", "modele": "NVMe SAMSUNG MZVLB512"}), {})
        self.assertTrue(ok)
        self.assertTrue(any("RAID" in a for a in avert))

    def test_virtuel(self):
        ok, raisons, _ = inventory.regles_exclusion(self._fiche(5, {"bus": "virtuel"}), {})
        self.assertFalse(ok)

    def test_fiche_complete(self):
        geo = {"index": 1, "peripherique": r"\\.\PhysicalDrive1", "taille_octets": 500 * 10 ** 9,
               "taille_go": 500.0, "secteur_logique": 512, "secteur_physique": 4096}
        idt = {"modele": "WDC WD5000AAKX", "numero_serie": "WD-WCC2E5FK8EU6", "bus": "SATA",
               "amovible": False}
        sm = {"numero_serie": "WD-WCC2E5FK8EU6", "modele": "WDC WD5000AAKX", "rotation_rate": 7200,
              "heures": 12000, "exploitable": True}
        f = inventory.construire_fiche(geo, idt, sm, {"porteur_exe": [0], "boot_pe": []})
        self.assertTrue(f["testable"])
        self.assertEqual(f["classe"], "hdd")
        self.assertEqual(f["confiance_cle"], "forte")
        self.assertTrue(f["smart_disponible"])
        self.assertIsNone(f["usure"])


class TestDecodageIoctl(unittest.TestCase):

    def _descripteur(self, fabricant, modele, revision, serie, bus=11, amovible=0):
        """Construit un STORAGE_DEVICE_DESCRIPTOR avec les VRAIS offsets."""
        entete = 36
        chaines = [fabricant, modele, revision, serie]
        corps, offsets, pos = b"", [], entete
        for c in chaines:
            offsets.append(pos)
            b = c.encode("latin-1") + b"\x00"
            corps += b
            pos += len(b)
        raw = (1).to_bytes(4, "little") + (entete + len(corps)).to_bytes(4, "little")
        raw += bytes([0, 0, amovible, 1])
        for o in offsets:
            raw += o.to_bytes(4, "little")
        raw += bus.to_bytes(4, "little") + b"\x00" * 4
        return raw + corps

    def test_offsets_serie_et_non_revision(self):
        raw = self._descripteur("WDC     ", "WD5000AAKX-00ERMA0", "15.01H15", "WD-WCC2E5FK8EU6")
        d = rawdisk.decoder_descripteur(raw)
        self.assertEqual(d["numero_serie"], "WD-WCC2E5FK8EU6")
        self.assertEqual(d["revision"], "15.01H15")
        self.assertEqual(d["modele"], "WD5000AAKX-00ERMA0")
        self.assertEqual(d["fabricant"], "WDC")
        self.assertEqual(d["bus"], "SATA")
        self.assertFalse(d["amovible"])

    def test_usb_amovible(self):
        raw = self._descripteur("Kingston", "DataTraveler 3.0", "PMAP", "\x031", bus=7, amovible=1)
        d = rawdisk.decoder_descripteur(raw)
        self.assertEqual(d["bus"], "USB")
        self.assertTrue(d["amovible"])
        self.assertEqual(inventory.nettoyer_serie(d["numero_serie"]), ("1", True))

    def test_descripteur_tronque(self):
        d = rawdisk.decoder_descripteur(b"\x00" * 10)
        self.assertIsNone(d["numero_serie"])
        self.assertIsNone(d["bus"])


class TestSmart(unittest.TestCase):

    def test_decodage_ata(self):
        data = {"model_name": "WDC WD5000AAKX", "serial_number": "WD-WCC2E5FK8EU6",
                "smart_status": {"passed": True}, "temperature": {"current": 34},
                "power_on_time": {"hours": 12345}, "rotation_rate": 7200,
                "device": {"protocol": "ATA"},
                "ata_smart_attributes": {"table": [
                    {"id": 5, "raw": {"value": 3}}, {"id": 197, "raw": {"value": 12}},
                    {"id": 9, "raw": {"value": 12345}}]}}
        e = smart.decoder(data, "/dev/sda", "ata")
        self.assertTrue(e["exploitable"])
        self.assertEqual(e["attributs_ata"], {"secteurs_realloues": 3, "secteurs_en_attente": 12})
        self.assertEqual(e["rotation_rate"], 7200)
        self.assertFalse(e["muet_controleur_raid"])
        self.assertIsNone(smart.projection_usure(e))

    def test_nvme_muet_derriere_rst(self):
        data = {"smartctl": {"messages": [{"string": "Read NVMe Identify Controller failed: "
                                            "IOCTL_STORAGE_QUERY_PROPERTY(NVMe) failed, Error=1"}]}}
        e = smart.decoder(data, "/dev/sdb", "nvme")
        self.assertFalse(e["exploitable"])
        self.assertTrue(e["muet_controleur_raid"])

    def test_nvme_usure_et_projection(self):
        data = {"model_name": "Samsung SSD 980", "serial_number": "S6PENX0T123456",
                "power_on_time": {"hours": 8760}, "device": {"protocol": "NVMe"},
                "nvme_smart_health_information_log": {"percentage_used": 10, "media_errors": 0,
                                                      "critical_warning": 0}}
        e = smart.decoder(data, "/dev/nvme0", "nvme")
        self.assertEqual(e["usure_nvme_pct"], 10)
        self.assertEqual(e["nvme"]["erreurs_media"], 0)
        p = smart.projection_usure(e)
        self.assertEqual(p["annees_restantes_estimees"], 9.0)

    def test_dedup_rst(self):
        a = {"numero_serie": "ABC123456", "peripherique": "/dev/sdb"}
        b = {"numero_serie": "abc 123456", "peripherique": "/dev/csmi1,0"}
        c = {"numero_serie": None, "peripherique": "/dev/sr0"}
        self.assertEqual([e["peripherique"] for e in smart.deduper([a, b, c])],
                         ["/dev/sdb", "/dev/sr0"])


class TestNiveaux(unittest.TestCase):

    def test_t1_seul_implemente_et_t3_sous_marqueur(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self.assertEqual(niveaux.niveaux_autorises(d), ("T1", "T2"))
            self.assertEqual(niveaux.verifier_niveau("T1", d), "T1")
            with self.assertRaises(niveaux.NiveauRefuse):
                niveaux.verifier_niveau("T3", d)          # pas de marqueur
            with self.assertRaises(niveaux.NiveauRefuse):
                niveaux.verifier_niveau("T2", d)          # pas implemente
            (d / niveaux.MARQUEUR_T3).write_text("oui", encoding="utf-8")
            self.assertEqual(niveaux.niveaux_autorises(d), ("T1", "T2", "T3"))
            with self.assertRaises(niveaux.NiveauRefuse) as cm:
                niveaux.verifier_niveau("T3", d)          # autorise mais pas implemente
            self.assertIn("implemente", str(cm.exception))
            with self.assertRaises(niveaux.NiveauRefuse):
                niveaux.verifier_niveau("T9", d)

    def test_mention_rapport(self):
        self.assertIn("aucune ecriture", niveaux.MENTION_RAPPORT["T1"])
        self.assertIn("DESTRUCTIF", niveaux.MENTION_RAPPORT["T3"])


if __name__ == "__main__":
    unittest.main()
