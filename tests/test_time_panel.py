"""
Tests de la saisie manuelle date/heure du panneau « Heure & veille » (main.py).

C'est le chemin de l'atelier : machine fraîchement réinstallée, pas encore de
réseau, donc pas de synchronisation NTP possible — l'horloge se règle à la main.
Une saisie mal validée ici met la machine à une date arbitraire, ce qui casse
ensuite winget, l'activation et toute connexion HTTPS.

Vérifie :
  - les deux formes tolérées (avec et sans les secondes, que personne ne tape) ;
  - le format rendu, qui doit être exactement celui qu'attend
    collectors/time_manager.ps1 (ParseExact "yyyy-MM-dd HH:mm:ss") ;
  - les refus : champ vide, date impossible, année hors plage.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main : son import installe un handler sur
# le journal REEL de l'utilisateur (voir tests/test_bench_gpu_detect.py).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import unittest
from datetime import datetime

import main

parse = main.GhisdiagApp._parse_manual_datetime

# Format attendu par le collecteur PowerShell, cote a cote avec le test pour que
# toute divergence saute aux yeux.
PS_FORMAT = "%Y-%m-%d %H:%M:%S"


class ParseManualDatetimeTest(unittest.TestCase):

    def test_saisie_complete(self):
        value, err = parse("05/08/2026", "14:32:10")
        self.assertEqual(err, "")
        self.assertEqual(value, "2026-08-05 14:32:10")

    def test_secondes_facultatives(self):
        value, err = parse("05/08/2026", "14:32")
        self.assertEqual(err, "")
        self.assertEqual(value, "2026-08-05 14:32:00")

    def test_espaces_autour_de_la_saisie(self):
        value, err = parse("  05/08/2026 ", " 14:32 ")
        self.assertEqual(err, "")
        self.assertEqual(value, "2026-08-05 14:32:00")

    def test_format_relisible_par_le_collecteur(self):
        value, _ = parse("29/02/2028", "23:59:59")
        # Meme format que le ParseExact de time_manager.ps1 : s'il change d'un
        # cote, ce test tombe.
        self.assertEqual(datetime.strptime(value, PS_FORMAT),
                         datetime(2028, 2, 29, 23, 59, 59))

    def test_refuse_champs_vides(self):
        for date_str, hour_str in (("", "10:00"), ("05/08/2026", ""), ("", "")):
            value, err = parse(date_str, hour_str)
            self.assertEqual(value, "")
            self.assertIn("date", err.lower())

    def test_refuse_date_impossible(self):
        for date_str in ("32/13/2026", "05-08-2026", "2026/08/05", "29/02/2027"):
            value, err = parse(date_str, "10:00")
            self.assertEqual(value, "", f"{date_str} aurait du etre refuse")
            self.assertTrue(err)

    def test_refuse_heure_impossible(self):
        for hour_str in ("25:00", "10h30", "10:61:00"):
            value, err = parse("05/08/2026", hour_str)
            self.assertEqual(value, "", f"{hour_str} aurait du etre refuse")
            self.assertTrue(err)

    def test_refuse_annee_hors_plage(self):
        for date_str, annee in (("05/08/1999", "1999"), ("05/08/2101", "2101")):
            value, err = parse(date_str, "10:00")
            self.assertEqual(value, "")
            self.assertIn(annee, err)


class KeepaliveReasonsTest(unittest.TestCase):
    """Les deux demandeurs de blocage doivent porter des raisons distinctes :
    sinon la fin du bench retirerait le blocage posé à la main par le
    technicien (et inversement)."""

    def test_raisons_distinctes(self):
        self.assertNotEqual(main.GhisdiagApp._KEEPALIVE_UI,
                            main.GhisdiagApp._KEEPALIVE_BENCH)


if __name__ == "__main__":
    unittest.main()
