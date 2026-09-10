"""
Rejeu des sessions d'atelier des 09 et 10/09/2026 : la phase 2 validee sur la
cle (7 rapports HTML ecrits par l'exe gele), deux disques en dock USB contre
les memes en SATA, et une confrontation en deux passages avec l'outil
commercial sur un MX500 de 11 000 h.

Ce que ces sept sessions ont montre (detail dans ROADMAP.md) :
  - un dock USB 3.0 ne change RIEN a la mesure d'un disque mecanique (ecart
    de mediane par zone : 0,003 ms en moyenne), il fait perdre l'identite et
    le SMART - alors que smartctl voit le disque a travers le pont ;
  - le WD5000AAKX de reference sort << a surveiller >> en SATA a cause de
    10 blocs a 143 ms parfaitement periodiques (espaces de 196-198 Mio, duree
    constante) que la regle << 4 blocs par zone = grappe >> retient. Meme
    disque via USB 8 h plus tot : rien. Faux positif probable, a trancher par
    un critere de regularite ;
  - MX500 2143E5DC7BC9 : une bande lente de 4 Go a 08:57 (48 Mo/s, 103 blocs
    a 80-110 ms), DISPARUE a 14:02 (rafraichie par le firmware entre les deux,
    l'outil concurrent passe entre-temps n'a rien vu), MAIS 12 blocs lents
    aux memes offsets exacts dans les deux passages : des pages faibles liees
    a la position, que le filtre du tic (calibre sur les HDD) range parmi les
    isoles. L'outil concurrent a rendu << BON >> les deux fois.

Lancement :  py -m unittest tests.test_ghisdiagdisk_atelier_0910 -v
"""

import gzip
import json
import statistics
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import scan  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
D0909 = FIXTURES / "ghisdiagdisk_atelier_20260909"
D0910 = FIXTURES / "ghisdiagdisk_atelier_20260910"

NVME = "ghisdiagdisk_0025_38D7_1145_F173_T1_20260909_082929"
WD_USB = "ghisdiagdisk_USB_3_0_Device-500_1Go-SANS-SERIE_T1_20260909_090555"
BX_USB = "ghisdiagdisk_USB_3_0_Device-240_1Go-SANS-SERIE_T1_20260909_120429"
WD_SATA = "ghisdiagdisk_WD-WCC2E5FK8EU6_T1_20260909_170106"
MX_SAIN = "ghisdiagdisk_21132E011D35_T1_20260910_083828"
MX_PASSE1 = "ghisdiagdisk_2143E5DC7BC9_T1_20260910_085717"
MX_PASSE2 = "ghisdiagdisk_2143E5DC7BC9_T1_20260910_140251"

# fichier -> (dossier, etat attendu, fragments de raisons/notes)
ATTENDU = {
    NVME:      (D0909, "sain", []),
    WD_USB:    (D0909, "sain", ["pont USB", "mecanique"]),
    BX_USB:    (D0909, "sain", ["pont USB"]),
    WD_SATA:   (D0909, "a_surveiller", ["10 bloc(s)", "143.97"]),
    MX_SAIN:   (D0910, "sain", []),
    MX_PASSE1: (D0910, "a_surveiller", ["115 bloc(s)", "4 zone(s) uniformement lente(s)",
                                        "4 zone(s) sous le plancher"]),
    MX_PASSE2: (D0910, "a_surveiller", ["14 bloc(s)", "93.146"]),
}

MIB = 2 ** 20


def charger(nom: str) -> dict:
    dossier = ATTENDU[nom][0]
    with gzip.open(dossier / f"{nom}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


def conclure(nom: str) -> dict:
    s = scan.migrer_session(charger(nom))
    s["synthese"] = scan.synthese(s)
    s["verdict"] = scan.calculer_verdict(s)
    return s


def blocs_lents(s: dict) -> dict:
    """offset -> (zone, ms) des blocs lents conserves, retenus ou isoles."""
    out = {}
    for z in s["segments"]:
        for x in z["anomalies"] + z["anomalies_isolees"]:
            out[x["offset"]] = (z["index"], x["ms"])
    return out


class TestRejeu0910(unittest.TestCase):

    def test_les_7_fixtures_sont_la(self):
        presentes = sorted(p.name[:-len(".json.gz")]
                           for d in (D0909, D0910) for p in d.glob("*.json.gz"))
        self.assertEqual(presentes, sorted(ATTENDU))

    def test_verdicts(self):
        for nom, (_, etat, fragments) in ATTENDU.items():
            with self.subTest(nom):
                s = conclure(nom)
                self.assertEqual(s["schema"], scan.SCHEMA_VERSION)
                self.assertEqual(s["statut"], "termine")
                self.assertEqual(s["verdict"]["etat"], etat, s["verdict"]["raisons"])
                self.assertEqual(s["verdict"]["portee"], "surface complete")
                texte = " | ".join(s["verdict"]["raisons"] + s["verdict"]["notes"])
                for frag in fragments:
                    self.assertIn(frag, texte)


class TestDockUSBContreSATA(unittest.TestCase):
    """Le meme WD5000AAKX, en dock USB 3.0 le matin et en SATA l'apres-midi."""

    def setUp(self):
        self.usb = conclure(WD_USB)
        self.sata = conclure(WD_SATA)

    def test_la_mesure_est_la_meme(self):
        a, b = self.usb["segments"], self.sata["segments"]
        self.assertEqual(len(a), len(b), "meme plan de 466 zones")
        ecarts = [abs(x["bloc_median_ms"] - y["bloc_median_ms"]) for x, y in zip(a, b)]
        self.assertLess(statistics.mean(ecarts), 0.05)
        self.assertLess(max(ecarts), 0.5)
        self.assertLess(abs(self.usb["synthese"]["debit_median_mo_s"]
                            - self.sata["synthese"]["debit_median_mo_s"]), 1.0)
        for s in (self.usb, self.sata):
            self.assertTrue(s["synthese"]["profil_zbr"]["signature_mecanique"])
            self.assertEqual(s["synthese"]["profil_zbr"]["ratio_fin_debut"], 0.5)

    def test_le_pont_usb_fait_perdre_l_identite_pas_smartctl(self):
        d = self.usb["disque"]
        self.assertEqual(d["bus"], "USB")
        self.assertEqual(d["confiance_cle"], "faible")
        self.assertIn("SANS-SERIE", d["cle_identite"])
        self.assertEqual(d["identite"]["numero_serie"], "0" * 20)
        self.assertFalse(d["smart_disponible"])
        # smartctl a bien vu le disque a travers le pont, avec sa vraie serie :
        # seul l'appariement (serie IOCTL nulle, modele generique) a echoue.
        self.assertIn("WD-WCC2E5FK8EU6", d["smart_absence"])
        self.assertIn("WDC WD5000AAKX", d["smart_absence"])
        self.assertEqual(self.sata["disque"]["cle_identite"], "WD-WCC2E5FK8EU6")
        self.assertTrue(self.sata["disque"]["smart_disponible"])

    def test_la_classe_n_est_pas_comparee_derriere_le_pont(self):
        self.assertEqual(self.usb["disque"]["classe"], "inconnue")
        self.assertEqual(self.usb["synthese"]["zones_sous_plancher"], [])
        self.assertIn("debit non compare a la classe (pont USB)", self.usb["verdict"]["notes"])

    def test_bx500_en_dock_plafonne_par_le_lien(self):
        """443 Mo/s en USB contre 519 en SATA le 04/09 : sain quand meme."""
        s = conclure(BX_USB)
        self.assertEqual(s["verdict"]["etat"], "sain")
        self.assertLess(s["synthese"]["debit_median_mo_s"], 460)
        self.assertGreater(s["synthese"]["debit_median_mo_s"], 400)
        self.assertIn("CT240BX500SSD1 / 2240E6743207", s["disque"]["smart_absence"])


class TestFauxPositifPeriodique(unittest.TestCase):
    """WD5000AAKX en SATA : 10 blocs a ~143 ms, 5 par zone dans deux zones
    contigues, espaces de 196-198 Mio, duree quasi constante. Un evenement
    periodique du firmware, pas un defaut de surface - la regle << 4 blocs
    dans la zone = grappe >> les retient pourtant. Ce test grave l'etat
    actuel de la regle ; il devra changer quand un critere de regularite
    sera decide."""

    def test_le_motif_est_periodique(self):
        s = conclure(WD_SATA)
        zones = [z for z in s["segments"] if z["nb_blocs_anormaux"]]
        self.assertEqual([z["index"] for z in zones], [236, 237])
        for z in zones:
            self.assertEqual(z["nb_blocs_anormaux"], 5)
            offs = sorted(a["offset"] for a in z["anomalies"])
            ecarts = [(offs[i + 1] - offs[i]) // MIB for i in range(len(offs) - 1)]
            self.assertTrue(all(190 <= e <= 205 for e in ecarts), ecarts)
            durees = [a["ms"] for a in z["anomalies"]]
            self.assertTrue(all(130 <= d <= 145 for d in durees), durees)
        self.assertEqual(s["verdict"]["etat"], "a_surveiller")   # etat actuel de la regle

    def test_rien_au_meme_endroit_via_usb_8h_plus_tot(self):
        usb = conclure(WD_USB)
        for i in (236, 237):
            self.assertLess(usb["segments"][i]["bloc_max_ms"], 20)


class TestMX500DeuxPassages(unittest.TestCase):
    """Le disque 2 de Coury : deux passages GhisdiagDisk a 5 h d'intervalle,
    l'outil concurrent entre les deux (et une seconde fois apres)."""

    def setUp(self):
        self.p1 = conclure(MX_PASSE1)
        self.p2 = conclure(MX_PASSE2)

    def test_la_bande_lente_des_4_premiers_go_a_disparu(self):
        syn1, syn2 = self.p1["synthese"], self.p2["synthese"]
        self.assertEqual(len(syn1["zones_sous_plancher"]), 4)
        self.assertEqual([z["index"] for z in syn1["zones_degradees"]], [0, 1, 2, 3])
        self.assertEqual(self.p1["segments"][0]["nb_blocs_anormaux"], 103)
        self.assertLess(self.p1["segments"][0]["debit_mo_s"], 50)
        self.assertEqual(syn2["zones_sous_plancher"], [])
        self.assertEqual(syn2["zones_degradees"], [])
        for i in range(4):
            self.assertGreater(self.p2["segments"][i]["debit_mo_s"], 200)
            self.assertEqual(self.p2["segments"][i]["nb_blocs_anormaux"], 0)
            self.assertLess(self.p2["segments"][i]["bloc_max_ms"], 10)

    def test_12_blocs_lents_aux_memes_offsets(self):
        """Sur 238 476 blocs, 97 puis 53 lents conserves : 12 offsets EXACTS en
        commun. Le hasard en donnerait 0,02. Ce sont des pages qui exigent
        des relectures a chaque passage, et que le firmware n'a pas
        rafraichies - contrairement a la bande des 4 premiers Go."""
        la, lb = blocs_lents(self.p1), blocs_lents(self.p2)
        communs = sorted(set(la) & set(lb))
        self.assertEqual(len(communs), 12)
        self.assertEqual(sorted({la[o][0] for o in communs}),
                         [98, 135, 186, 212, 214, 217, 219, 221, 223, 227, 229, 231])
        for o in communs:
            self.assertGreater(la[o][1], 40)
            self.assertGreater(lb[o][1], 40)
            self.assertLess(la[o][1], scan.SEUIL_ANOMALIE_ISOLEE_MS)
            self.assertLess(lb[o][1], scan.SEUIL_ANOMALIE_ISOLEE_MS)

    def test_le_filtre_du_tic_les_range_parmi_les_isoles(self):
        """Un par zone et sous 150 ms : pour le moteur ce sont des << tics de
        firmware sain >>. Le filtre a ete calibre sur des disques mecaniques
        (Seagate, un bloc toutes les 58 s) ; sur un SSD, des blocs lents
        lies a la POSITION ne sont pas un tic. Etat actuel, a revoir avec le
        delta entre passages (phase 3)."""
        la, lb = blocs_lents(self.p1), blocs_lents(self.p2)
        communs = set(la) & set(lb)
        for s in (self.p1, self.p2):
            isoles = {x["offset"] for z in s["segments"] for x in z["anomalies_isolees"]}
            self.assertTrue(communs <= isoles)
            self.assertIn("tic periodique", " ".join(s["verdict"]["notes"]))

    def test_le_mx500_sain_n_a_aucun_bloc_lent(self):
        """Meme modele, 1 465 h : max 9,9 ms sur tout le disque, zero isole.
        C'est le contraste qui donne son sens aux 35 puis 39 isoles du 2143."""
        s = conclure(MX_SAIN)
        self.assertEqual(s["verdict"]["etat"], "sain")
        self.assertLess(s["synthese"]["bloc_max_ms"], 10)
        self.assertEqual(s["synthese"]["nb_blocs_isoles"], 0)
        self.assertEqual(self.p1["synthese"]["nb_blocs_isoles"], 35)
        self.assertEqual(self.p2["synthese"]["nb_blocs_isoles"], 39)

    def test_smart_vierge_les_deux_fois(self):
        for s in (self.p1, self.p2):
            attrs = s["disque"]["smart"]["attributs_ata"]
            self.assertTrue(all(v == 0 for v in attrs.values()), attrs)
        self.assertEqual(self.p2["disque"]["smart"]["heures"] - self.p1["disque"]["smart"]["heures"], 3)


if __name__ == "__main__":
    unittest.main()
