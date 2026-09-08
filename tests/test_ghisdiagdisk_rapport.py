"""
Tests du rapport client HTML de GhisdiagDisk (ghisdiagdisk/rapport.py) et de
la commande --rapport (ghisdiagdisk/cli.py) - phase 2, spec du 08/09/2026.

Les sept invariants de la spec (section 8) sont rejoues sur les 18 sessions
d'atelier reelles figees en fixtures (04, 05 et 08/09) : chaque HTML est
ECRIT puis RELU, jamais valide sur un code retour.

  1. aucune reference externe (http, src=, <script) ;
  2. le mot du verdict et sa phrase de portee sont presents et coherents ;
  3. << surface complete >> n'apparait jamais sur la session du 08/09 (157 Mio
     jamais lus) ;
  4. le WD Green fait apparaitre ses 34 secteurs realloues dans le bloc SMART ;
  5. le NVMe sans SMART fait apparaitre `smart_absence` ;
  6. un disque derriere un pont USB affiche la mention de non-comparaison ;
  7. un nom de client contenant << < >> ne casse pas la page.

Aucune fixture n'a de disque en dock USB : l'invariant 6 part d'une session
reelle dans laquelle l'avertissement USB de `inventory.regles_exclusion` est
injecte.

Lancement :  py -m unittest tests.test_ghisdiagdisk_rapport -v
"""

import gzip
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import cli, inventory, rapport, scan  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
DOSSIERS = ("ghisdiagdisk_atelier_20260904", "ghisdiagdisk_atelier_20260905",
            "ghisdiagdisk_atelier_20260908")

WD_GREEN = "ghisdiagdisk_22194U800957_T1_20260904_142116"
NVME_SANS_SMART = "ghisdiagdisk_0025_38D7_1145_F173_T1_20260904_105303"
REPRISE_0809 = "ghisdiagdisk_0025_38D7_1145_F173_T1_20260908_105937"
SOUS_WINDOWS = "ghisdiagdisk_S3S7NX0M616075_T1_20260903_222836"
BX500_SAIN = "ghisdiagdisk_2240E6743207_T1_20260904_114807"
LEXAR_TRONQUE = "ghisdiagdisk_NM966820193470S30T_T1_20260904_160616"
SEAGATE_TICS = "ghisdiagdisk_Z1D3AEYY_T1_20260904_090259"

TITRES = {"sain": "Aucun défaut détecté",
          "a_surveiller": "Signes de faiblesse",
          "a_remplacer": "Disque défaillant",
          "non_concluant": "Diagnostic non concluant"}


def toutes_les_fixtures() -> dict:
    out = {}
    for d in DOSSIERS:
        for f in sorted((FIXTURES / d).glob("*.json.gz")):
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                out[f.name[:-len(".json.gz")]] = json.load(fh)
    return out


def charger(nom: str) -> dict:
    return toutes_les_fixtures()[nom]


def verdict_attendu(session: dict) -> dict:
    """Le verdict tel que les regles COURANTES le calculent, independamment du
    generateur (qui est cense faire la meme chose)."""
    s = scan.migrer_session(json.loads(json.dumps(session)))
    s["synthese"] = scan.synthese(s)
    return scan.calculer_verdict(s)


def ecrire_et_relire(session: dict, dossier: Path, nom: str, identite=None) -> str:
    """Passe par le disque, comme le fera le technicien."""
    chemin = dossier / f"{nom}.json"
    chemin.write_text(json.dumps(session), encoding="utf-8")
    cible = rapport.ecrire_rapport(session, chemin, identite)
    assert cible == chemin.with_suffix(".html"), cible
    return cible.read_text(encoding="utf-8")


class TestInvariantsSurLesFixtures(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dossier = Path(cls.tmp.name)
        cls.sessions = toutes_les_fixtures()
        cls.html = {nom: ecrire_et_relire(s, cls.dossier, nom)
                    for nom, s in cls.sessions.items()}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_les_18_fixtures_sont_rendues(self):
        self.assertEqual(len(self.html), 18)
        for nom, h in self.html.items():
            with self.subTest(nom):
                self.assertTrue(h.startswith("<!DOCTYPE html>"))
                self.assertIn('<meta charset="utf-8">', h)
                self.assertIn("</html>", h)

    def test_1_aucune_reference_externe(self):
        for nom, h in self.html.items():
            with self.subTest(nom):
                for interdit in ("http", "src=", "<script", "href="):
                    self.assertNotIn(interdit, h)

    def test_2_mot_du_verdict_et_phrase_de_portee(self):
        for nom, s in self.sessions.items():
            with self.subTest(nom):
                h = self.html[nom]
                v = verdict_attendu(s)
                etat = v["etat"]
                self.assertIn(TITRES[etat], h)
                for autre, titre in TITRES.items():
                    if autre != etat:
                        self.assertNotIn(titre, h, f"deux titres de verdict dans {nom}")
                if etat == "sain":
                    couv = f"{v['couverture_disque_pct']:.2f}".replace(".", ",")
                    self.assertIn(f"{couv} % du disque, mode {s['mode']}", h)
                elif etat == "a_surveiller":
                    self.assertIn("voir le détail ci-dessous", h)
                elif etat == "a_remplacer":
                    self.assertIn("ne pas continuer à l’utiliser", h)
                else:
                    for raison in v["raisons"]:
                        self.assertIn(rapport._esc(raison), h)
                # Les raisons du verdict sont toutes sur le papier.
                for raison in v["raisons"]:
                    self.assertIn(rapport._esc(raison), h)

    def test_3_jamais_surface_complete_sur_la_reprise_du_0809(self):
        h = self.html[REPRISE_0809]
        self.assertNotIn("surface complète", h)
        self.assertNotIn("surface complete", h)
        self.assertIn("99,94 % du disque, mode complet", h)
        self.assertIn("1 zone(s) incomplète(s)", h)

    def test_3bis_surface_complete_seulement_si_toutes_les_zones_sont_entieres(self):
        for nom, s in self.sessions.items():
            with self.subTest(nom):
                entieres = all(z.get("complet") for z in s["segments"])
                attendu = s["mode"] == "complet" and s["statut"] == "termine" and entieres
                self.assertEqual("surface complète" in self.html[nom], attendu)

    def test_4_le_wd_green_montre_ses_34_secteurs_realloues(self):
        h = self.html[WD_GREEN]
        smart = h[h.index("SMART — compteurs bruts"):h.index("Les zones à problème")]
        cellule = re.search(r'<div class="smart-cell smart-crit">.*?Secteurs réalloués.*?>34<', smart)
        self.assertIsNotNone(cellule, smart[:600])
        self.assertIn("SMART : 34 secteur(s) realloue(s)", h)      # raison du verdict, verbatim
        self.assertIn("PASSED", smart)                              # le drapeau est dit...
        self.assertIn("ne suffit pas", smart)                       # ... et relativise

    def test_5_le_nvme_sans_smart_dit_pourquoi(self):
        h = self.html[REPRISE_0809]
        absence = self.sessions[REPRISE_0809]["disque"]["smart_absence"]
        self.assertIn("SMART indisponible", h)
        self.assertIn(rapport._esc(absence), h)
        self.assertIn("IOCTL_STORAGE_QUERY_PROPERTY", h)
        self.assertIn("4 entree(s) smartctl", h)
        self.assertIn("source : IOCTL, confiance moyenne", h)
        # Le meme disque le 04/09, AVANT le correctif qui ecrit smart_absence :
        # le rapport ne peut pas inventer la raison, il dit qu'elle manque.
        self.assertNotIn("smart_absence", self.sessions[NVME_SANS_SMART]["disque"])
        self.assertIn("SMART indisponible", self.html[NVME_SANS_SMART])
        self.assertIn("raison non enregistrée", self.html[NVME_SANS_SMART])

    def test_6_pont_usb_mention_de_non_comparaison(self):
        s = json.loads(json.dumps(self.sessions[BX500_SAIN]))
        s["disque"]["bus"] = "USB"
        s["disque"]["identite"]["bus"] = "USB"
        s["disque"]["identite"]["amovible"] = False
        fiche = {"index": 3, "identite": s["disque"]["identite"],
                 "geometrie": s["disque"]["geometrie"]}
        testable, raisons, avert = inventory.regles_exclusion(fiche, {})
        self.assertTrue(testable, raisons)
        s["disque"]["avertissements"] = avert
        h = ecrire_et_relire(s, self.dossier, "usb")
        self.assertIn("pont USB", h)
        self.assertIn("non comparé", h)
        self.assertNotIn("plancher ssd", h)
        self.assertNotIn('class="plancher"', h)
        self.assertIn("disque derriere un pont USB", h)             # l'avertissement de la fiche

    def test_7_les_identites_sont_echappees(self):
        s = self.sessions[BX500_SAIN]
        identite = {"client": "<b>Dupont</b> & fils <script>alert(1)</script>",
                    "technicien": "O'Neil <i>", "reference": '"DOS-42"'}
        h = ecrire_et_relire(s, self.dossier, "echappement", identite)
        self.assertIn("&lt;b&gt;Dupont&lt;/b&gt; &amp; fils", h)
        self.assertNotIn("<b>Dupont", h)
        self.assertNotIn("<script", h)
        self.assertIn("O&#x27;Neil &lt;i&gt;", h)
        self.assertIn("&quot;DOS-42&quot;", h)
        self.assertIn("</html>", h)

    # -- au-dela des sept invariants : les refus de la section 5 ---------------

    def test_hors_winpe_ligne_visible(self):
        h = self.html[SOUS_WINDOWS]
        self.assertIn("Mesure hors WinPE", h)
        self.assertIn(TITRES["non_concluant"], h)
        self.assertIn("rejouer le balayage depuis la clé WinPE", h)

    def test_les_blocs_isoles_sont_nommes(self):
        h = self.html[SEAGATE_TICS]
        self.assertIn("125 bloc(s) lent(s) isole(s)", h)
        self.assertIn("tic periodique", h)

    def test_la_consigne_suit_le_verdict(self):
        attendu = {"sain": "peut être remis en service",
                   "a_surveiller": "Sauvegarder les données sans attendre",
                   "a_remplacer": "Imager d’abord, tester ensuite",
                   "non_concluant": "Diagnostic à compléter"}
        for nom, s in self.sessions.items():
            with self.subTest(nom):
                self.assertIn(attendu[verdict_attendu(s)["etat"]], self.html[nom])

    def test_le_nom_du_client_ne_va_pas_dans_le_nom_de_fichier(self):
        self.assertEqual(rapport.chemin_rapport(Path("x/ghisdiagdisk_ABC_T1_20260908_105937.json")).name,
                         "ghisdiagdisk_ABC_T1_20260908_105937.html")

    def test_le_bloc_zones_n_apparait_que_s_il_y_a_matiere(self):
        for nom, s in self.sessions.items():
            with self.subTest(nom):
                syn = scan.synthese(scan.migrer_session(json.loads(json.dumps(s))))
                matiere = bool(syn["zones_degradees"] or syn["zones_sous_plancher"]
                               or syn["zones_avec_anomalies"])
                self.assertEqual("Les zones à problème" in self.html[nom], matiere)


class TestHistogramme(unittest.TestCase):
    """Choix A du 08/09 : l'histogramme ne dit que ce que la session sait."""

    def test_les_blocs_sont_tous_comptes_une_fois(self):
        for nom, s in toutes_les_fixtures().items():
            with self.subTest(nom):
                s = scan.migrer_session(s)
                h = rapport.histogramme_latences(s)
                self.assertEqual(h["total"], sum(z["nb_blocs"] for z in s["segments"]))
                self.assertEqual(h["sous_seuil"] + sum(n for _, n in h["bornes"]) + h["non_conserves"],
                                 h["total"])
                self.assertEqual([lib for lib, _ in h["bornes"]],
                                 ["25 à 50 ms", "50 à 150 ms", "150 à 500 ms", "plus de 500 ms"])

    def test_wd_green(self):
        h = rapport.histogramme_latences(scan.migrer_session(charger(WD_GREEN)))
        self.assertEqual(h["non_conserves"], 0)
        self.assertEqual(h["isoles"], 97)
        self.assertEqual(sum(n for _, n in h["bornes"]), 76 + 97)
        self.assertEqual(dict(h["bornes"])["plus de 500 ms"], 0)

    def test_les_zones_tronquees_sont_comptees_a_part(self):
        s = scan.migrer_session(charger(LEXAR_TRONQUE))
        h = rapport.histogramme_latences(s)
        self.assertGreater(h["non_conserves"], 0)
        # Les 7 blocs > 500 ms ne sont pas dans les 50 anomalies conservees
        # (premieres par position) : c'est nb_blocs_mourants qui les compte.
        self.assertEqual(s["synthese"]["nb_blocs_mourants"], 7)
        self.assertEqual(dict(h["bornes"])["plus de 500 ms"], 7)
        self.assertEqual(h["sous_seuil"] + sum(n for _, n in h["bornes"]) + h["non_conserves"], h["total"])
        html = rapport.generer_html(s)
        self.assertIn("temps n’a pas été conservé", html)
        self.assertIn("les bornes 5 et 10 ms ne sont pas calculables", html)


class TestPreparationEtRefus(unittest.TestCase):

    def test_le_verdict_est_recalcule_sans_toucher_l_original(self):
        s = charger(REPRISE_0809)
        self.assertEqual(s["verdict"]["portee"], "surface complete")     # ecrit par l'exe d'alors
        p = rapport.preparer(s)
        self.assertEqual(p["verdict"]["portee"], "echantillon")
        self.assertEqual(s["verdict"]["portee"], "surface complete")     # l'original n'a pas bouge

    def test_refus(self):
        with self.assertRaises(rapport.RapportRefuse):
            rapport.preparer({"outil": "autre chose"})
        s = charger(BX500_SAIN)
        s["segments"] = []
        with self.assertRaises(rapport.RapportRefuse):
            rapport.preparer(s)

    def test_projection_nvme_etiquetee(self):
        s = charger(BX500_SAIN)
        s["disque"]["smart"]["usure_nvme_pct"] = 12
        s["disque"]["smart"]["nvme"] = {"erreurs_media": 0, "avertissement_critique": 0,
                                        "reserve_disponible_pct": 100}
        s["disque"]["usure"] = {"usure_pct": 12, "heures": 8760,
                                "annees_restantes_estimees": 7.3,
                                "hypothese": "usage constant, projection lineaire"}
        h = rapport.generer_html(s)
        self.assertIn("7,3 an(s)", h)
        self.assertIn("projection linéaire, usage constant", h)

    def test_bloc_dossier(self):
        self.assertIsNone(rapport.bloc_dossier())
        self.assertIsNone(rapport.bloc_dossier(None, "", None))
        b = rapport.bloc_dossier(client="Dupont")
        self.assertEqual(sorted(b), ["client", "reference", "saisi_a", "technicien"])
        self.assertEqual(b["client"], "Dupont")
        self.assertIsNone(b["technicien"])

    def test_identite_de_la_session_reprise_si_rien_n_est_donne(self):
        s = charger(BX500_SAIN)
        s["dossier"] = rapport.bloc_dossier(client="Martin", technicien="GD")
        h = rapport.generer_html(s)
        self.assertIn("Martin", h)
        h2 = rapport.generer_html(s, {"client": "Durand"})
        self.assertIn("Durand", h2)
        self.assertNotIn("Martin", h2)


class TestCommandeRapport(unittest.TestCase):
    """--rapport : n'ouvre aucun disque, ne modifie jamais le JSON."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dossier = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ecrire(self, nom, demarre=None) -> Path:
        s = charger(nom)
        if demarre:
            s["demarre_a"] = demarre
        p = self.dossier / f"{nom}.json"
        p.write_text(json.dumps(s), encoding="utf-8")
        return p

    def _main(self, argv) -> tuple:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(argv)
        return rc, buf.getvalue()

    def test_fichier_nomme_avec_identite(self):
        p = self._ecrire(WD_GREEN)
        avant = p.read_bytes()
        rc, out = self._main(["--rapport", str(p), "--sortie", str(self.dossier),
                              "--client", "Dupont", "--technicien", "GD", "--reference", "D-1"])
        self.assertEqual(rc, 0, out)
        self.assertIn("Rapport ecrit", out)
        html = p.with_suffix(".html").read_text(encoding="utf-8")
        self.assertIn("Dupont", html)
        self.assertIn("D-1", html)
        self.assertEqual(p.read_bytes(), avant, "le JSON ne doit jamais etre modifie par --rapport")
        self.assertNotIn("Dupont", p.read_text(encoding="utf-8"))

    def test_auto_prend_la_plus_recente(self):
        self._ecrire(BX500_SAIN, "2026-09-04T11:48:07")
        p2 = self._ecrire(WD_GREEN, "2026-09-04T14:21:16")
        rc, out = self._main(["--rapport", "--sortie", str(self.dossier)])
        self.assertEqual(rc, 0, out)
        self.assertTrue(p2.with_suffix(".html").exists())
        self.assertFalse((self.dossier / f"{BX500_SAIN}.html").exists())
        self.assertIn("sans identite client", out)

    def test_mauvais_nom_liste_ce_qui_existe(self):
        self._ecrire(BX500_SAIN)
        rc, out = self._main(["--rapport", str(self.dossier / "nexiste_pas.json"),
                              "--sortie", str(self.dossier)])
        self.assertEqual(rc, 1)
        self.assertIn("introuvable", out)
        self.assertIn(f"{BX500_SAIN}.json", out)
        self.assertIn("--rapport rapports_disque\\", out)

    def test_dossier_vide(self):
        rc, out = self._main(["--rapport", "--sortie", str(self.dossier)])
        self.assertEqual(rc, 1)
        self.assertIn("Aucune session", out)

    def test_fichier_qui_n_est_pas_une_session(self):
        p = self.dossier / "ghisdiagdisk_bidon.json"
        p.write_text("pas du json", encoding="utf-8")
        rc, out = self._main(["--rapport", str(p), "--sortie", str(self.dossier)])
        self.assertEqual(rc, 1)
        self.assertIn("illisible", out)

    def test_refus_session_sans_zone(self):
        s = charger(BX500_SAIN)
        s["segments"] = []
        p = self.dossier / "ghisdiagdisk_vide.json"
        p.write_text(json.dumps(s), encoding="utf-8")
        rc, out = self._main(["--rapport", str(p), "--sortie", str(self.dossier)])
        self.assertEqual(rc, 2)
        self.assertIn("[REFUS]", out)
        self.assertFalse(p.with_suffix(".html").exists())

    def test_apres_balayage_sans_identite_le_json_reste_anonyme(self):
        p = self._ecrire(BX500_SAIN)
        s = scan.charger_session(p)
        s["_fichier"] = str(p)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.ecrire_rapport_apres_balayage(s, {"client": None, "technicien": None, "reference": None})
        self.assertTrue(p.with_suffix(".html").exists())
        self.assertNotIn("dossier", json.loads(p.read_text(encoding="utf-8")))
        self.assertIn("--rapport --client", buf.getvalue())

    def test_apres_balayage_avec_identite_le_bloc_dossier_est_ecrit(self):
        p = self._ecrire(BX500_SAIN)
        s = scan.charger_session(p)
        s["_fichier"] = str(p)
        with redirect_stdout(io.StringIO()):
            cli.ecrire_rapport_apres_balayage(s, {"client": "Dupont", "technicien": "GD",
                                                  "reference": None})
        relu = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual(relu["dossier"]["client"], "Dupont")
        self.assertIn("saisi_a", relu["dossier"])
        self.assertNotIn("_fichier", relu)
        self.assertIn("Dupont", p.with_suffix(".html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
