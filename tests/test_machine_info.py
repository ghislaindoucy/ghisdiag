"""
Tests de la fiche machine (onglet Setup / MAJ → Machine) :
collectors/machine_info.ps1 + machine_info.py + rendu dans main.py.

La règle qui guide ces tests : une valeur NON LUE ne s'affiche jamais comme une
valeur. Les cas viennent du premier relevé réel (ThinkStation P330, 13/09/2026),
lancé sans droits admin :
  - Win32_Tpm refusé → la fiche disait « TPM absent » sur une machine qui a un
    TPM 2.0 ;
  - LastLogon du compte Microsoft figé en 2021 pour une session ouverte le jour
    même ;
  - VirtualBox, OpenVPN, Bluetooth déclarés « cartes physiques » par Windows ;
  - une IP seule sérialisée en chaîne, une liste vide en « {} ».

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main (voir tests/test_bench_gpu_detect.py).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import copy
import gc
import unittest
from pathlib import Path

import machine_info as mi

SCRIPT = Path(__file__).resolve().parent.parent / "collectors" / "machine_info.ps1"

# Relevé réel anonymisé (série, MAC, adresse du compte).
FIXTURE = {
    "collected_at": "2026-09-13 00:10:00",
    "elevated": False,
    "machine": {"name": "PC-ATELIER", "manufacturer": "LENOVO", "model": "30C50053FR",
                "product_version": "ThinkStation P330", "serial": "XXXX0000",
                "chassis_types": 3, "part_of_domain": False, "domain": None,
                "workgroup": "WORKGROUP", "azure_ad_joined": False,
                "bios_version": "M1VKT77A", "bios_date": "2024-04-10 02:00:00"},
    "windows": {"caption": "Microsoft Windows 11 Professionnel", "display_version": "25H2",
                "build": "26200", "ubr": 9445, "architecture": "64 bits",
                "install_date": "2024-11-24 11:56:02", "last_boot": "2026-09-12 18:56:09",
                "uptime_hours": 5.1, "license_status": 1, "license_channel": "Retail",
                "oem_key_in_firmware": True, "reboot_pending": False},
    "cpu": {"name": "Intel(R) Core(TM) i7-8700 CPU @ 3.20GHz", "cores": 6, "threads": 12,
            "load_percent": 35},
    "memory": {"total_gb": 15.8, "used_gb": 11, "used_percent": 69, "slots_total": 4,
               "modules": [
                   {"slot": "ChannelA-DIMM1", "capacity_gb": 8, "smbios_type": 26, "speed_mhz": 2666},
                   {"slot": "ChannelB-DIMM1", "capacity_gb": 8, "smbios_type": 26, "speed_mhz": 2666}]},
    "disks": [
        {"number": 0, "model": "CT1000P3PSSD8", "media_type": 4, "bus_type": 17, "size_gb": 932, "health": 0},
        {"number": 1, "model": "SAMSUNG MZ7LN256HAJQ", "media_type": 4, "bus_type": 11, "size_gb": 238, "health": 0},
        {"number": 2, "model": "Generic Flash Disk", "media_type": 0, "bus_type": 7, "size_gb": 4, "health": 0}],
    "volumes": [
        {"letter": "C:", "label": "Windows", "filesystem": "NTFS", "size_gb": 930, "free_gb": 480.2,
         "used_percent": 48, "disk_number": 0, "bitlocker": None},
        {"letter": "H:", "label": "CLAUDE", "filesystem": "FAT", "size_gb": 3.7, "free_gb": 3.5,
         "used_percent": 7, "disk_number": 2, "bitlocker": None},
        {"letter": "G:", "label": "Google Drive", "filesystem": "FAT32", "size_gb": 930, "free_gb": 456,
         "used_percent": 51, "disk_number": None, "bitlocker": None}],
    "accounts": [
        {"name": "Administrateur", "enabled": True, "is_admin": True, "builtin": True,
         "principal_source": "Local", "identity": None, "last_logon": "2025-05-24 21:50:55",
         "profile_last_use": None},
        {"name": "Ghislain", "full_name": "Ghislain Doucy", "enabled": True, "is_admin": True,
         "builtin": False, "principal_source": "MicrosoftAccount", "identity": "exemple@hotmail.com",
         "last_logon": "2021-12-31 16:51:21", "profile_last_use": "2026-09-13 00:05:13"},
        {"name": "Invité", "enabled": False, "is_admin": False, "builtin": True,
         "principal_source": "Local", "identity": None, "last_logon": None, "profile_last_use": None},
        {"name": "Lucifer", "enabled": True, "is_admin": False, "builtin": False,
         "principal_source": "Local", "identity": None, "last_logon": None, "profile_last_use": None}],
    "other_profiles": [],
    "security": {"firmware_type": "UEFI", "secure_boot": True, "tpm_present": True,
                 "tpm_enabled": None, "tpm_version": "2.0", "bitlocker_readable": False,
                 "antivirus": [{"name": "Windows Defender", "realtime": False},
                               {"name": "Surfshark", "realtime": True}]},
    "battery": {"present": False},
    "gpu": [{"name": "NVIDIA Quadro P2000", "driver_version": "32.0.15.7342",
             "driver_date": "2025-06-12 02:00:00"}],
    "network": [
        {"name": "Ethernet", "description": "Intel(R) Ethernet Connection (7) I219-LM",
         "connected": True, "mac": "00:00:00:00:00:01", "speed_mbps": 1000, "ipv4": "192.168.1.142"},
        {"name": "Ethernet 2", "description": "VirtualBox Host-Only Ethernet Adapter",
         "connected": True, "mac": "00:00:00:00:00:02", "speed_mbps": 1000, "ipv4": "192.168.56.1"},
        {"name": "Wi-Fi 3", "description": "D-Link DWA-131 Wireless N Nano USB Adapter",
         "connected": False, "mac": "00:00:00:00:00:03", "speed_mbps": None, "ipv4": {}}],
    "device_errors": [],
}


def data(**changes):
    d = copy.deepcopy(FIXTURE)
    for path, value in changes.items():
        section, key = path.split("__")
        d[section][key] = value
    return d


class FormatTests(unittest.TestCase):

    def test_as_list_et_str_list(self):
        self.assertEqual(mi.as_list(3), [3])
        self.assertEqual(mi.as_list(None), [])
        self.assertEqual(mi.str_list("192.168.1.2"), ["192.168.1.2"])
        self.assertEqual(mi.str_list({}), [])  # tableau vide sérialisé par PS 5.1

    def test_tailles(self):
        self.assertEqual(mi.fmt_size_gb(8), "8 Go")
        self.assertEqual(mi.fmt_size_gb(3.7), "3,7 Go")
        self.assertEqual(mi.fmt_size_gb(930), "930 Go")
        self.assertEqual(mi.fmt_size_gb(1863), "1,8 To")
        self.assertEqual(mi.fmt_size_gb(None), "?")

    def test_dates_et_uptime(self):
        self.assertEqual(mi.fmt_date("2026-09-12 18:56:09", True), "12/09/2026 18:56")
        self.assertEqual(mi.fmt_date(None), mi.NON_LU)
        self.assertEqual(mi.fmt_uptime(5.1), "5 h")
        self.assertEqual(mi.fmt_uptime(200), "8 j 8 h")


class IdentityTests(unittest.TestCase):

    def test_chassis(self):
        self.assertEqual(mi.chassis_label(3), "Fixe")
        self.assertEqual(mi.chassis_label([10]), "Portable")
        self.assertEqual(mi.chassis_label([13]), "Tout-en-un")
        self.assertIsNone(mi.chassis_label([2]))
        self.assertEqual(mi.chassis_label([2], has_battery=True), "Portable")

    def test_modele_lenovo_nom_commercial(self):
        self.assertEqual(mi.model_label(FIXTURE["machine"]), "LENOVO ThinkStation P330 (30C50053FR)")

    def test_modele_version_generique_ignoree(self):
        m = {"manufacturer": "ASUS", "model": "X515EA", "product_version": "System Version"}
        self.assertEqual(mi.model_label(m), "ASUS X515EA")

    def test_windows_et_activation(self):
        self.assertEqual(mi.windows_label(FIXTURE["windows"]),
                         "Windows 11 Professionnel 25H2 (build 26200.9445)")
        self.assertIn("Activé", mi.license_label(FIXTURE["windows"]))
        self.assertIn("clé OEM", mi.license_label(FIXTURE["windows"]))
        self.assertEqual(mi.license_label({}), mi.NON_LU)


class HardwareTests(unittest.TestCase):

    def test_barrettes(self):
        self.assertEqual(mi.memory_modules_label(FIXTURE["memory"]),
                         "2 × 8 Go DDR4 2666 MHz · 2/4 emplacements")

    def test_disques(self):
        d0, d1, d2 = FIXTURE["disks"]
        self.assertIn("SSD NVMe", mi.disk_label(d0))
        self.assertIn("SSD SATA", mi.disk_label(d1))
        self.assertIn("USB", mi.disk_label(d2))
        self.assertEqual(mi.disk_health(d0), ("Sain", "ok"))
        self.assertEqual(mi.disk_health({"health": 2})[1], "crit")
        self.assertEqual(mi.disk_health({})[0], mi.NON_LU)

    def test_volumes_ranges_sous_leur_disque(self):
        groups, orphans = mi.volumes_by_disk(FIXTURE)
        self.assertEqual([v["letter"] for v in groups[0][1]], ["C:"])
        self.assertEqual(groups[1][1], [])
        self.assertEqual([v["letter"] for v in orphans], ["G:"])

    def test_cle_usb_pas_jugee_sur_son_espace_libre(self):
        self.assertEqual(mi.volume_level(FIXTURE["volumes"][1]), "ok")

    def test_volume_plein(self):
        v = {"letter": "C:", "size_gb": 476, "free_gb": 3, "used_percent": 99}
        self.assertEqual(mi.volume_level(v), "crit")
        v = {"letter": "C:", "size_gb": 476, "free_gb": 12, "used_percent": 80}
        self.assertEqual(mi.volume_level(v), "warn")

    def test_batterie(self):
        self.assertEqual(mi.battery_wear({"design_mwh": 50000, "full_charge_mwh": 30000}), 40)
        self.assertEqual(mi.battery_wear({"design_mwh": 50000, "full_charge_mwh": 52000}), 0)
        self.assertIsNone(mi.battery_wear({"design_mwh": 0, "full_charge_mwh": 30000}))
        self.assertIsNone(mi.battery_wear({"design_mwh": 50000, "full_charge_mwh": 90000}))

    def test_cartes_virtuelles_ecartees(self):
        noms = [n["name"] for n in mi.physical_networks(FIXTURE)]
        self.assertEqual(noms, ["Ethernet", "Wi-Fi 3"])


class NonLuTests(unittest.TestCase):
    """Une valeur non lue ne devient jamais une valeur."""

    def test_tpm_non_lu_n_est_pas_absent(self):
        label, level = mi.tpm_label({"tpm_present": None})
        self.assertEqual(label, mi.NON_LU)
        self.assertNotIn("absent", label)
        self.assertIn("absent", mi.tpm_label({"tpm_present": False})[0])
        self.assertEqual(mi.tpm_label(FIXTURE["security"]), ("présent (version 2.0)", "ok"))

    def test_bitlocker_non_lu_n_est_pas_desactive(self):
        v = {"bitlocker": None}
        self.assertIn(mi.NON_LU, mi.bitlocker_label(v, readable=False))
        self.assertIsNone(mi.bitlocker_label(v, readable=True))
        self.assertIsNone(mi.bitlocker_label({"bitlocker": 0}, readable=True))
        self.assertEqual(mi.bitlocker_label({"bitlocker": 1}, readable=True), "BitLocker actif")

    def test_secure_boot(self):
        self.assertEqual(mi.secure_boot_label(FIXTURE["security"]), ("activé", "ok"))
        self.assertEqual(mi.secure_boot_label({"firmware_type": "UEFI"})[0], mi.NON_LU)
        self.assertIn("Legacy", mi.secure_boot_label({"firmware_type": "Legacy"})[0])

    def test_antivirus(self):
        self.assertEqual(mi.antivirus_label(FIXTURE["security"])[1], "ok")
        self.assertEqual(mi.antivirus_label({})[0], mi.NON_LU)
        self.assertEqual(mi.antivirus_label({"antivirus": {"name": "X", "realtime": False}})[1], "crit")


class AccountTests(unittest.TestCase):

    def test_compte_microsoft(self):
        ms = FIXTURE["accounts"][1]
        self.assertEqual(mi.account_kind(ms), "Compte Microsoft (exemple@hotmail.com)")
        self.assertEqual(mi.account_kind({**ms, "identity": None}), "Compte Microsoft")
        self.assertEqual(mi.account_kind(FIXTURE["accounts"][0]), "Local")

    def test_derniere_activite_la_plus_recente(self):
        # LastLogon figé en 2021, profil utilisé le jour même.
        self.assertEqual(mi.last_activity(FIXTURE["accounts"][1]), "2026-09-13 00:05:13")
        self.assertIsNone(mi.last_activity(FIXTURE["accounts"][3]))

    def test_integres_desactives_masques(self):
        shown, hidden = mi.visible_accounts(FIXTURE["accounts"])
        self.assertEqual(hidden, 1)
        self.assertEqual([a["name"] for a in shown], ["Administrateur", "Ghislain", "Lucifer"])


class AttentionTests(unittest.TestCase):

    def textes(self, d):
        return " | ".join(t for _, t in mi.attention_points(d))

    def test_machine_saine(self):
        pts = mi.attention_points(FIXTURE)
        self.assertEqual([lvl for lvl, _ in pts], ["info"])  # Administrateur intégré actif

    def test_windows_non_active_en_tete(self):
        pts = mi.attention_points(data(windows__license_status=0))
        self.assertEqual(pts[0][0], "crit")
        self.assertIn("Windows", pts[0][1])

    def test_bitlocker_actif_signale(self):
        d = copy.deepcopy(FIXTURE)
        d["volumes"][0]["bitlocker"] = 1
        self.assertIn("clé de récupération", self.textes(d))

    def test_redemarrage_et_uptime(self):
        self.assertIn("Redémarrage en attente", self.textes(data(windows__reboot_pending=True)))
        self.assertIn("Pas redémarré", self.textes(data(windows__uptime_hours=24 * 10)))

    def test_pilotes_et_graphique(self):
        d = copy.deepcopy(FIXTURE)
        d["device_errors"] = {"name": "Contrôleur SM Bus", "code": 28, "class": ""}
        d["gpu"] = [{"name": "Carte graphique de base Microsoft"}]
        txt = self.textes(d)
        self.assertIn("1 périphérique(s) en erreur", txt)
        self.assertIn("Pilote graphique manquant", txt)

    def test_antivirus_illisible_pas_signale(self):
        self.assertNotIn("Antivirus", self.textes(data(security__antivirus=[])))


class SummaryTests(unittest.TestCase):

    def test_fiche_texte(self):
        txt = mi.summary_text(FIXTURE)
        for attendu in ("LENOVO ThinkStation P330", "XXXX0000", "Windows 11 Professionnel 25H2",
                        "2 × 8 Go DDR4", "SSD NVMe", "Compte Microsoft (exemple@hotmail.com)",
                        "dernière activité : 13/09/2026", "Lucifer — Local — standard, actif — dernière activité : jamais",
                        "192.168.1.142", "TPM           : présent (version 2.0)"):
            self.assertIn(attendu, txt)
        self.assertNotIn("None", txt)
        self.assertNotIn("192.168.56.1", txt)  # VirtualBox
        self.assertNotIn("{}", txt)

    def test_fiche_sur_donnees_vides(self):
        # Collecteur en échec partiel : la fiche reste lisible, sans exception.
        txt = mi.summary_text({})
        self.assertIn("FICHE MACHINE", txt)
        self.assertNotIn("None", txt)


class CollectorContractTests(unittest.TestCase):

    def test_ascii_strict(self):
        SCRIPT.read_bytes().decode("ascii")

    def test_lecture_seule(self):
        src = SCRIPT.read_text(encoding="ascii")
        for verbe in ("Set-", "New-Item", "Remove-", "Invoke-CimMethod", "Enable-", "Disable-"):
            self.assertNotIn(verbe, src)

    def test_releve_reel(self):
        # Exécution réelle (lecture seule) : clés et types attendus par l'UI.
        from orchestrator import run_ps_action
        d = run_ps_action("collectors/machine_info.ps1", [], timeout=180)
        for key in ("machine", "windows", "cpu", "memory", "disks", "volumes", "accounts",
                    "security", "battery", "gpu", "network", "device_errors", "collector_timings"):
            self.assertIn(key, d)
        for n in mi.as_list(d["network"]):
            self.assertIsInstance(n.get("ipv4"), list)
        if not d.get("elevated"):
            # Sans droits : TPM et BitLocker peuvent être illisibles, jamais « faux ».
            self.assertFalse(d["security"].get("bitlocker_readable"))
        mi.summary_text(d)


class RenderSmokeTests(unittest.TestCase):

    def tearDown(self):
        # Les widgets Tk forment des cycles (master/children, resync) : sans
        # collecte ICI, dans le thread principal, le ramasse-miettes libère
        # l'interpréteur Tcl plus tard depuis le thread d'un autre test, et le
        # processus meurt sur « Tcl_AsyncDelete: async handler deleted by the
        # wrong thread » (constaté sur la suite complète).
        gc.collect()

    def test_rendu_tk(self):
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as exc:  # pas d'affichage disponible
            self.skipTest(f"Tk indisponible : {exc}")
        try:
            root.withdraw()
            import main
            body = tk.Frame(root)
            main.GhisdiagApp._render_machine_sheet(body, FIXTURE)
            self.assertGreater(len(body.winfo_children()), 5)
            # Re-rendu (bouton Actualiser) : le contenu est remplacé, pas empilé.
            n = len(body.winfo_children())
            main.GhisdiagApp._render_machine_sheet(body, FIXTURE)
            self.assertEqual(len(body.winfo_children()), n)
            main.GhisdiagApp._render_machine_sheet(body, {})
        finally:
            root.destroy()

    def test_barre_de_defilement_apres_releve(self):
        # Défaut signalé en atelier : la fiche arrive après le relevé, et la barre
        # de défilement n'apparaissait qu'en redimensionnant la fenêtre.
        try:
            import tkinter as tk
            root = tk.Tk()
        except Exception as exc:
            self.skipTest(f"Tk indisponible : {exc}")
        try:
            import types
            import main
            root.geometry("900x500")
            parent = tk.Frame(root)
            parent.pack(fill="both", expand=True)
            ns = types.SimpleNamespace(_scroll_zones={})
            inner = main.GhisdiagApp._scrollable(ns, parent)
            body = tk.Frame(inner)
            body.pack(fill="x")
            tk.Label(body, text="Relevé en cours").pack()
            root.update()
            main.GhisdiagApp._render_machine_sheet(body, FIXTURE)
            inner.resync()
            root.update()
            sb = [w for w in parent.winfo_children() if w.winfo_class() == "TScrollbar"][0]
            self.assertGreater(inner.winfo_reqheight(), 500)
            self.assertTrue(sb.winfo_ismapped(), "la barre doit apparaître dès la fin du relevé")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
