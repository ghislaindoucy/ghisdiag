"""
Rejeu des 15 rapports de la validation atelier du 04/09/2026 (GhisdiagDisk 0.1.0,
Hiren's BootCD PE, 8 disques reels) a travers la synthese et le verdict courants.

Les fixtures sont les sessions ecrites par l'exe d'essai, au schema 1, allegees
du plan de zones (inutile au verdict) et compressees. Chaque verdict attendu
ci-dessous a ete arrete A LA MAIN en lisant les mesures, PAS en recopiant la
sortie du code : c'est la table de verite de la calibration du 04/09.

Ce que ces rapports ont revele (et que le moteur du 03/09 ratait) :
  - ST500DM002 : 108 erreurs non corrigeables (SMART 187) ignorees ;
  - Lexar NQ100 : 5 zones sur 12 a 8-14x la mediane du disque sans un seul bloc
    << anormal >>, verdict express << a surveiller >> vs << a remplacer >> en complet ;
  - ST1000DM003 : 120 blocs lents ISOLES a periode fixe (58,5 s) comptes comme
    anomalies -> express sain, standard 20, complet 135 sur un disque sain.

Lancement :  py -m unittest tests.test_ghisdiagdisk_atelier_0409 -v
"""

import gzip
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import scan  # noqa: E402

DOSSIER = Path(__file__).parent / "fixtures" / "ghisdiagdisk_atelier_20260904"

# fichier -> (etat attendu, blocs anormaux retenus, blocs isoles, fragments de raisons)
ATTENDU = {
    # Samsung NVMe PM991 256 Go : sain dans les trois modes, 0 anomalie a 100 %.
    "ghisdiagdisk_0025_38D7_1145_F173_T1_20260904_105138": ("sain", 0, 0, []),
    "ghisdiagdisk_0025_38D7_1145_F173_T1_20260904_105204": ("sain", 0, 0, []),
    "ghisdiagdisk_0025_38D7_1145_F173_T1_20260904_105303": ("sain", 0, 0, []),
    # Crucial BX500 n1 : reference propre (max 11 ms sur 240 Go).
    "ghisdiagdisk_2240E6743207_T1_20260904_114807": ("sain", 0, 0, []),
    # Crucial BX500 n2 : 33 blocs de 25-54 ms groupes dans 2 zones (6,4-8,6 Go).
    "ghisdiagdisk_2305E6A6D126_T1_20260904_120406": ("a_surveiller", 33, 0, ["grappe"]),
    # WD Green 240 : 34 realloues, premiers 80 Go a 95-170 Mo/s (4-5x plus lents).
    "ghisdiagdisk_22194U800957_T1_20260904_142116": (
        "a_surveiller", 76, 97, ["realloue", "uniformement lente", "les masque"]),
    # Lexar NQ100 mourant, complet interrompu a 3,3 % : 7 blocs > 500 ms.
    "ghisdiagdisk_NM966820193470S30T_T1_20260904_160616": (
        "a_remplacer", 434, 0, ["mourir", "12.6 Mo/s", "verdict partiel"]),
    # Le meme en express : 5 zones sur 12 degradees -> meme verdict qu'en complet.
    "ghisdiagdisk_NM966820193470S30T_T1_20260904_161822": (
        "a_remplacer", 34, 0, ["uniformement lente", "les masque", "surface en train de lacher"]),
    # Samsung SATA sous Windows (03/09) : les latences ne concluent pas.
    "ghisdiagdisk_S3S7NX0M616075_T1_20260903_222836": ("non_concluant", 0, 0, ["WinPE"]),
    # WD10JPCX 5400 tr/min : express sain, complet interrompu a 1,7 % avec un
    # seul bloc a 33 ms -> tic isole, verdict partiel sans defaut.
    "ghisdiagdisk_WD-WX61A16LKLAX_T1_20260904_154423": ("sain", 0, 0, []),
    "ghisdiagdisk_WD-WX61A16LKLAX_T1_20260904_154525": ("non_concluant", 0, 1, ["verdict partiel"]),
    # ST1000DM003 (43 659 h, SMART vierge) : tic periodique isole, MAIS deux
    # vraies grappes (82,7 Go : 7 blocs jusqu'a 131 ms ; fin de disque : 377 ms).
    "ghisdiagdisk_Z1D3AEYY_T1_20260904_085215": ("sain", 0, 0, []),
    "ghisdiagdisk_Z1D3AEYY_T1_20260904_085355": ("a_surveiller", 8, 12, ["376.885"]),
    "ghisdiagdisk_Z1D3AEYY_T1_20260904_090259": ("a_surveiller", 10, 125, ["331.474"]),
    # ST500DM002 : 3 tics isoles, et 108 erreurs non corrigeables (attribut 187).
    "ghisdiagdisk_ZA435B94_T1_20260904_173408": ("a_surveiller", 0, 3, ["187", "108"]),
}


def charger(nom: str) -> dict:
    with gzip.open(DOSSIER / f"{nom}.json.gz", "rt", encoding="utf-8") as f:
        return json.load(f)


class TestRejeuAtelier0409(unittest.TestCase):

    def test_les_15_fixtures_sont_la(self):
        presentes = sorted(p.name[:-len(".json.gz")] for p in DOSSIER.glob("*.json.gz"))
        self.assertEqual(presentes, sorted(ATTENDU))

    def test_verdicts(self):
        for nom, (etat, anormaux, isoles, fragments) in ATTENDU.items():
            with self.subTest(nom):
                brut = charger(nom)
                self.assertEqual(brut["schema"], 1, "fixture = session d'origine, schema 1")
                s = scan.migrer_session(json.loads(json.dumps(brut)))
                self.assertEqual(s["schema"], scan.SCHEMA_VERSION)
                v, syn = s["verdict"], s["synthese"]
                self.assertEqual(v["etat"], etat, v["raisons"])
                self.assertEqual(syn["nb_blocs_anormaux"], anormaux)
                self.assertEqual(syn["nb_blocs_isoles"], isoles)
                texte = " | ".join(v["raisons"] + v["notes"])
                for frag in fragments:
                    self.assertIn(frag, texte)
                self.assertEqual(v["concluant"], etat != "non_concluant")

    def test_le_tic_periodique_ne_change_plus_le_verdict_avec_la_couverture(self):
        """Meme disque sain, trois couvertures : les tics isoles montent
        (0, 12, 125), le verdict ne se degrade qu'avec de vraies grappes."""
        etats = []
        for nom in ("ghisdiagdisk_Z1D3AEYY_T1_20260904_085215",
                    "ghisdiagdisk_Z1D3AEYY_T1_20260904_085355",
                    "ghisdiagdisk_Z1D3AEYY_T1_20260904_090259"):
            s = scan.migrer_session(charger(nom))
            etats.append((s["synthese"]["nb_blocs_isoles"], s["synthese"]["zones_avec_anomalies"]))
        self.assertEqual([e[0] for e in etats], [0, 12, 125])
        self.assertEqual(etats[1][1], [47])                       # fin de disque
        self.assertIn(77, etats[2][1])                            # 82,7 Go
        self.assertIn(253, etats[2][1])                           # 331 ms isole mais > 150

    def test_lexar_express_et_complet_concordent(self):
        express = scan.migrer_session(charger("ghisdiagdisk_NM966820193470S30T_T1_20260904_161822"))
        complet = scan.migrer_session(charger("ghisdiagdisk_NM966820193470S30T_T1_20260904_160616"))
        self.assertEqual(express["verdict"]["etat"], complet["verdict"]["etat"])
        zones = [z["index"] for z in express["synthese"]["zones_degradees"]]
        self.assertEqual(zones, [1, 2, 3, 8, 11])
        self.assertGreaterEqual(min(z["ratio"] for z in express["synthese"]["zones_degradees"]), 8.0)

    def test_marges_de_calibration(self):
        """Les disques sains restent loin du seuil de zone degradee (4x) : le
        pire ratio sain observe est le NVMe (zones pleines vs vides)."""
        pire_sain = 0.0
        for nom in ("ghisdiagdisk_0025_38D7_1145_F173_T1_20260904_105303",
                    "ghisdiagdisk_2240E6743207_T1_20260904_114807",
                    "ghisdiagdisk_Z1D3AEYY_T1_20260904_090259",
                    "ghisdiagdisk_WD-WX61A16LKLAX_T1_20260904_154423"):
            s = scan.migrer_session(charger(nom))
            ref = s["synthese"]["reference_zones_ms"]
            pire_sain = max(pire_sain, max(z["bloc_median_ms"] for z in s["segments"]
                                           if z["nb_blocs"] >= scan.MIN_BLOCS_ZONE_STATS) / ref)
            self.assertEqual(s["synthese"]["zones_degradees"], [])
        self.assertLess(pire_sain, 3.0)
        self.assertGreaterEqual(scan.RATIO_ZONE_DEGRADEE, 4.0)


if __name__ == "__main__":
    unittest.main()
