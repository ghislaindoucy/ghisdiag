"""
Tests du moteur de balayage T1 de GhisdiagDisk (ghisdiagdisk/scan.py).

SANS materiel : le moteur tourne sur un faux disque qui simule la latence par
bloc, des secteurs illisibles et le profil ZBR d'un disque mecanique, avec une
horloge virtuelle. Verifie :

  - le plan : express/standard repartis avec debut a 0 et fin exacte, complet
    contigu, alignement secteur, petit disque balaye en entier ;
  - un disque sain en WinPE -> SAIN, profil ZBR reconnu, aucune anomalie ;
  - un bloc lent -> A SURVEILLER (offset releve), un bloc > 500 ms -> A REMPLACER ;
  - un secteur illisible -> A REMPLACER, localise par bissection au secteur
    physique, concluant meme sous Windows ;
  - hors WinPE, les latences ne concluent JAMAIS (non concluant) ;
  - arret de securite au-dela du nombre de blocs illisibles ;
  - annulation propre (statut interrompu, verdict partiel) ;
  - checkpoint apres chaque zone et REPRISE sur le meme disque seulement ;
  - le debit sous le plancher de la classe et un SMART deja degrade pesent
    dans le verdict ; l'echauffement n'est pas mesure.

Lancement :  py -m unittest discover -s tests -v
"""

import copy
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import scan  # noqa: E402
from ghisdiagdisk.scan import ScanConfig, ScanEngine, planifier  # noqa: E402

MIB = scan.MIB
GO = 10 ** 9


class Horloge:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def avancer_ms(self, ms):
        self.t += ms / 1000.0


class FauxDisque:
    """Disque simule : latence par bloc fonction de l'offset, secteurs morts."""

    def __init__(self, horloge, taille, secteur=512, ms_par_mib=None,
                 illisibles=(), lents=None, ms_reveil=0.0):
        self.h = horloge
        self.taille = taille
        self.secteur = secteur
        self.ms_par_mib = ms_par_mib or (lambda off: 8.0)
        self.illisibles = list(illisibles)          # (offset, longueur)
        self.lents = dict(lents or {})              # offset -> ms
        self.ms_reveil = ms_reveil                  # plateaux en veille
        self.lectures = []                          # (offset, taille)
        self._reveille = False

    def lire(self, offset, taille):
        assert offset % self.secteur == 0 and taille % self.secteur == 0, "non aligne"
        assert offset + taille <= self.taille, "lecture hors disque"
        self.lectures.append((offset, taille))
        if not self._reveille:
            self.h.avancer_ms(self.ms_reveil)
            self._reveille = True
        for a, n in self.illisibles:
            if offset < a + n and a < offset + taille:
                self.h.avancer_ms(200.0)
                raise OSError(23, "ReadFile")
        if offset in self.lents:
            self.h.avancer_ms(self.lents[offset])
        else:
            self.h.avancer_ms(self.ms_par_mib(offset) * taille / MIB)
        return taille


def fiche_test(taille=64 * GO, secteur=512, physique=4096, classe="hdd", smart=None,
               avert=None, cle="WD-TEST123456"):
    return {
        "index": 1, "cle_identite": cle, "confiance_cle": "forte",
        "modele": "FAUX HDD", "bus": "SATA", "type_support": "Disque mecanique (7200 tr/min)",
        "classe": classe, "smart": smart, "avertissements": avert or [],
        "geometrie": {"index": 1, "taille_octets": taille, "taille_go": round(taille / 1e9, 1),
                      "secteur_logique": secteur, "secteur_physique": physique},
    }


ENV_PE = {"environnement": "winpe", "winpe": True, "admin": True}
ENV_WIN = {"environnement": "windows", "winpe": False, "admin": True}


def _cfg(**kw):
    base = dict(mode="express", nb_segments=6, segment_octets=16 * MIB,
                lectures_aleatoires=20, graine_aleatoire=42)
    base.update(kw)
    return ScanConfig(**base)


def _zbr(off):
    """Debit qui chute des pistes exterieures vers les interieures : 8 ms/Mio
    au debut, 16 ms/Mio a la fin (ratio 0,5 comme les disques calibres)."""
    return 8.0 + 8.0 * off / (64 * GO)


# --- Plan --------------------------------------------------------------------

class TestPlan(unittest.TestCase):

    def test_express_reparti_debut_et_fin_exacte(self):
        plan = planifier(64 * GO, 512, ScanConfig(mode="express"))
        self.assertEqual(len(plan), 12)
        self.assertEqual(plan[0].offset, 0)
        self.assertEqual(plan[-1].offset + plan[-1].longueur, 64 * GO)
        for s in plan:
            self.assertEqual(s.offset % 512, 0)
            self.assertEqual(s.longueur % 512, 0)
            self.assertEqual(s.longueur, 256 * MIB)
        offsets = [s.offset for s in plan]
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreater(offsets[1], 0)

    def test_taille_non_multiple_du_secteur_est_tronquee(self):
        plan = planifier(64 * GO + 100, 4096, ScanConfig(mode="express"))
        self.assertEqual(plan[-1].offset + plan[-1].longueur, (64 * GO + 100) // 4096 * 4096)

    def test_complet_contigu(self):
        plan = planifier(5 * scan.GIB + 3 * MIB, 512, ScanConfig(mode="complet"))
        self.assertEqual(plan[0].offset, 0)
        for a, b in zip(plan, plan[1:]):
            self.assertEqual(a.offset + a.longueur, b.offset)
        self.assertEqual(sum(s.longueur for s in plan), 5 * scan.GIB + 3 * MIB)
        self.assertEqual(plan[-1].longueur, 3 * MIB)

    def test_petit_disque_balaye_en_entier(self):
        plan = planifier(1 * scan.GIB, 512, ScanConfig(mode="express"))
        self.assertEqual(sum(s.longueur for s in plan), 1 * scan.GIB)

    def test_standard_48_zones(self):
        plan = planifier(1000 * GO, 4096, ScanConfig(mode="standard"))
        self.assertEqual(len(plan), 48)
        self.assertEqual(plan[-1].offset + plan[-1].longueur, 1000 * GO // 4096 * 4096)


# --- Moteur ------------------------------------------------------------------

class TestMoteurSain(unittest.TestCase):

    def setUp(self):
        self.h = Horloge()
        self.disque = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, ms_reveil=313.0)
        self.fiche = fiche_test()

    def test_disque_sain_en_pe(self):
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["statut"], "termine")
        self.assertEqual(s["verdict"]["etat"], "sain")
        self.assertTrue(s["verdict"]["concluant"])
        self.assertEqual(s["verdict"]["portee"], "echantillon")
        self.assertEqual(s["niveau"], "T1")
        self.assertIn("non destructif", s["mention_niveau"])
        self.assertEqual(len(s["segments"]), 6)
        self.assertEqual(s["synthese"]["nb_blocs_anormaux"], 0)
        self.assertEqual(s["synthese"]["nb_secteurs_illisibles"], 0)
        self.assertEqual(s["synthese"]["couverture_disque_pct"],
                         round(6 * 16 * MIB / (64 * GO) * 100, 2))

    def test_reveil_des_plateaux_non_mesure(self):
        """313 ms sur le premier bloc = demarrage du moteur, PAS un defaut."""
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["segments"][0]["nb_blocs_anormaux"], 0)
        self.assertLess(s["segments"][0]["bloc_max_ms"], 20.0)
        # L'echauffement a lu AU-DELA de la fenetre, pas dedans.
        premiere = self.disque.lectures[0]
        self.assertEqual(premiere[0], 16 * MIB)

    def test_echauffement_derniere_zone_avant_la_fenetre(self):
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        derniere = s["plan"]["segments"][-1]
        lectures_zone = [o for o, _ in self.disque.lectures
                         if derniere["offset"] - scan.ECART_ECHAUFFEMENT <= o < derniere["offset"]]
        self.assertTrue(lectures_zone, "l'echauffement de la derniere zone doit se faire avant elle")

    def test_profil_zbr_reconnu(self):
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        p = s["synthese"]["profil_zbr"]
        self.assertTrue(p["signature_mecanique"])
        self.assertTrue(p["monotone_decroissant"])
        self.assertAlmostEqual(p["ratio_fin_debut"], 0.5, delta=0.05)
        self.assertTrue(any("mecanique" in n for n in s["verdict"]["notes"]))
        self.assertAlmostEqual(s["segments"][0]["debit_mo_s"], MIB / 1e6 / 0.008, delta=1.0)

    def test_lecture_aleatoire(self):
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        la = s["lecture_aleatoire"]
        self.assertEqual(la["nb_lectures"], 20)
        self.assertEqual(la["taille_lecture"], 4096)
        self.assertEqual(la["erreurs"], 0)
        self.assertIsNotNone(la["p50_ms"])
        self.assertEqual(la["graine"], 42)

    def test_mode_complet_couvre_tout(self):
        h = Horloge()
        d = FauxDisque(h, 3 * scan.GIB + 5 * MIB, ms_par_mib=lambda o: 0.5)
        f = fiche_test(taille=3 * scan.GIB + 5 * MIB, classe="ssd")
        s = ScanEngine(d, f, ScanConfig(mode="complet", lectures_aleatoires=0), ENV_PE, clock=h).run()
        self.assertEqual(s["synthese"]["couverture_disque_pct"], 100.0)
        self.assertEqual(s["verdict"]["portee"], "surface complete")
        self.assertEqual(s["verdict"]["etat"], "sain")
        # Un seul echauffement en mode complet : la premiere lecture tombe
        # au-dela de la premiere zone (donc dans la 2e, tant pis : elle n'est
        # pas mesuree), puis tout est contigu depuis 0.
        self.assertEqual(d.lectures[0], (scan.GIB, MIB))
        self.assertEqual(d.lectures[1][0], 0)
        nb_blocs = sum(z["nb_blocs"] for z in s["segments"])
        self.assertEqual(len(d.lectures), 1 + nb_blocs)

    def test_hors_pe_sain_devient_non_concluant(self):
        s = ScanEngine(self.disque, self.fiche, _cfg(), ENV_WIN, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "non_concluant")
        self.assertFalse(s["environnement"]["conclusion_latence_autorisee"])
        self.assertTrue(any("WinPE" in r for r in s["verdict"]["raisons"]))




class TestMoteurDefauts(unittest.TestCase):

    def setUp(self):
        self.h = Horloge()
        self.fiche = fiche_test()

    def test_bloc_lent_a_surveiller(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        s0 = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        cible = s0["plan"]["segments"][2]["offset"] + 5 * MIB
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, lents={cible: 100.0})
        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "a_surveiller")
        self.assertEqual(s["synthese"]["nb_blocs_anormaux"], 1)
        self.assertEqual(s["segments"][2]["anomalies"][0]["offset"], cible)
        self.assertEqual(s["synthese"]["zones_avec_anomalies"], [2])

    def test_bloc_mourant_a_remplacer(self):
        d0 = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        s0 = ScanEngine(d0, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        cible = s0["plan"]["segments"][4]["offset"] + 1 * MIB
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, lents={cible: 800.0})
        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "a_remplacer")
        self.assertEqual(s["synthese"]["nb_blocs_mourants"], 1)
        self.assertTrue(any("mourir" in r for r in s["verdict"]["raisons"]))

    def test_bloc_lent_hors_pe_non_concluant(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, lents={5 * MIB: 100.0})
        s = ScanEngine(d, self.fiche, _cfg(), ENV_WIN, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "non_concluant")
        self.assertEqual(s["synthese"]["nb_blocs_anormaux"], 1)   # mesure quand meme
        self.assertTrue(any("WinPE" in r for r in s["verdict"]["raisons"]))

    def test_plancher_ssd_ignore_le_bruit(self):
        """Sur un SSD (mediane 0,4 ms), 3x mediane serait du bruit : un bloc a
        5 ms n'est pas une anomalie, un bloc a 60 ms si."""
        f = fiche_test(classe="nvme")
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=lambda o: 0.4, lents={3 * MIB: 5.0})
        s = ScanEngine(d, f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["synthese"]["nb_blocs_anormaux"], 0)
        self.assertEqual(s["verdict"]["etat"], "sain")
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=lambda o: 0.4, lents={3 * MIB: 60.0})
        s = ScanEngine(d, f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["synthese"]["nb_blocs_anormaux"], 1)

    def test_secteur_illisible_localise_et_concluant_partout(self):
        # Defaut place dans la premiere zone : un seul secteur physique de
        # 4 Kio doit ressortir, localise par bissection.
        off_mort = 7 * MIB + 3 * 4096
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, illisibles=[(off_mort, 512)])
        for env in (ENV_PE, ENV_WIN):
            d.lectures.clear()
            s = ScanEngine(d, self.fiche, _cfg(), env, clock=self.h).run()
            self.assertEqual(s["verdict"]["etat"], "a_remplacer", env)
            self.assertTrue(s["verdict"]["concluant"])
            z = s["segments"][0]
            self.assertEqual(z["nb_blocs_illisibles"], 1)
            self.assertEqual(z["nb_plages_illisibles"], 1)
            p = z["plages_illisibles"][0]
            self.assertEqual(p["offset"], off_mort)
            self.assertEqual(p["octets"], 4096)          # secteur physique
            self.assertEqual(p["secteurs"], 8)           # en secteurs logiques
            self.assertEqual(p["lba"], off_mort // 512)
            self.assertTrue(p["localise"])
            self.assertEqual(z["octets_lus"], 16 * MIB - 4096)
            self.assertEqual(s["synthese"]["nb_secteurs_illisibles"], 8)

    def test_arret_de_securite(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr, illisibles=[(0, 16 * MIB)])
        s = ScanEngine(d, self.fiche, _cfg(max_blocs_illisibles=3), ENV_PE, clock=self.h).run()
        self.assertEqual(s["statut"], "arrete_securite")
        self.assertEqual(s["verdict"]["etat"], "a_remplacer")
        self.assertTrue(any("Imager" in r for r in s["verdict"]["raisons"]))
        self.assertEqual(len(s["segments"]), 1)
        self.assertEqual(s["segments"][0]["nb_blocs_illisibles"], 3)
        self.assertIsNone(s["lecture_aleatoire"])
        # Bissection plafonnee : on ne martele pas un disque mort.
        self.assertLess(len(d.lectures), 3 * (scan.MAX_SOUS_LECTURES_BLOC + 64))

    def test_debit_sous_plancher_classe(self):
        f = fiche_test(classe="ssd")
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=lambda o: 20.0)   # ~52 Mo/s
        s = ScanEngine(d, f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "a_surveiller")
        self.assertTrue(any("plancher" in r for r in s["verdict"]["raisons"]))

    def test_debit_non_compare_derriere_usb(self):
        f = fiche_test(classe="ssd", avert=["disque derriere un pont USB : ..."])
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=lambda o: 20.0)
        s = ScanEngine(d, f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "sain")
        self.assertTrue(any("USB" in n for n in s["verdict"]["notes"]))

    def test_smart_degrade_pese(self):
        smart = {"smart_actif": True, "attributs_ata": {"secteurs_en_attente": 8}}
        f = fiche_test(smart=smart)
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        s = ScanEngine(d, f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "a_surveiller")
        self.assertTrue(any("attente" in r for r in s["verdict"]["raisons"]))
        f = fiche_test(smart={"smart_actif": False})
        s = ScanEngine(FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr), f, _cfg(), ENV_PE, clock=self.h).run()
        self.assertEqual(s["verdict"]["etat"], "a_remplacer")


class TestSessionEtReprise(unittest.TestCase):

    def setUp(self):
        self.h = Horloge()
        self.fiche = fiche_test()

    def test_annulation_propre(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        annul = threading.Event()

        def _seg(session, res):
            if len(session["segments"]) == 2:
                annul.set()

        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h,
                       on_segment=_seg, annulation=annul).run()
        self.assertEqual(s["statut"], "interrompu")
        self.assertEqual(len(s["segments"]), 2)
        self.assertEqual(s["verdict"]["etat"], "non_concluant")
        self.assertTrue(any("interrompu" in r for r in s["verdict"]["raisons"]))
        self.assertIsNone(s["lecture_aleatoire"])

    def test_annulation_en_pleine_zone(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        annul = threading.Event()
        compteur = {"n": 0}
        original = d.lire

        def _lire(off, n):
            compteur["n"] += 1
            if compteur["n"] == 6:
                annul.set()
            return original(off, n)
        d.lire = _lire
        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h, annulation=annul).run()
        self.assertEqual(s["statut"], "interrompu")
        self.assertEqual(len(s["segments"]), 1)
        self.assertTrue(s["segments"][0]["interrompu"])
        self.assertFalse(s["segments"][0]["complet"])

    def test_checkpoint_puis_reprise(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        points, annul = [], threading.Event()

        def _ckpt(session):
            points.append(copy.deepcopy(session))
            if len(session["segments"]) == 2:
                annul.set()

        s1 = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h,
                        checkpoint=_ckpt, annulation=annul).run()
        self.assertEqual(s1["statut"], "interrompu")
        # 2 zones + l'ecriture finale.
        self.assertEqual(len(points), 3)
        sauve = points[1]
        self.assertEqual(sauve["statut"], "en_cours")
        self.assertEqual(len(sauve["segments"]), 2)

        # Reprise : seules les 4 zones restantes sont lues.
        d2 = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        repris = scan.reprendre_session(sauve, self.fiche)
        self.assertEqual(len(repris["reprises"]), 1)
        s2 = ScanEngine(d2, self.fiche, _cfg(), ENV_PE, session=repris, clock=self.h).run()
        self.assertEqual(s2["statut"], "termine")
        self.assertEqual(sorted(z["index"] for z in s2["segments"]), [0, 1, 2, 3, 4, 5])
        self.assertEqual(s2["verdict"]["etat"], "sain")
        offsets_relus = {o for o, _ in d2.lectures}
        self.assertNotIn(0, offsets_relus, "la zone 0 ne doit pas etre relue")
        self.assertEqual(s2["demarre_a"], sauve["demarre_a"])

    def test_reprise_refusee_sur_autre_disque(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        autre = fiche_test(cle="AUTRE-SERIE-999")
        with self.assertRaises(ValueError):
            scan.reprendre_session(s, autre)
        meme_cle_autre_taille = fiche_test(taille=32 * GO)
        with self.assertRaises(ValueError):
            scan.reprendre_session(s, meme_cle_autre_taille)

    def test_persistance_atomique_et_nom_de_fichier(self):
        d = FauxDisque(self.h, 64 * GO, ms_par_mib=_zbr)
        s = ScanEngine(d, self.fiche, _cfg(), ENV_PE, clock=self.h).run()
        with tempfile.TemporaryDirectory() as tmp:
            chemin = scan.chemin_session(Path(tmp), s)
            self.assertTrue(chemin.name.startswith("ghisdiagdisk_WD-TEST123456_T1_"))
            scan.sauver_session(s, chemin)
            self.assertFalse(chemin.with_suffix(".json.tmp").exists())
            relu = scan.charger_session(chemin)
            self.assertEqual(relu["verdict"]["etat"], "sain")
            self.assertEqual(relu["schema"], scan.SCHEMA_VERSION)
            # Serialisable sans `default=str` : aucune valeur exotique.
            json.dumps(s)

    def test_cle_exotique_assainie_dans_le_nom(self):
        f = fiche_test(cle="ST380815AS-80.0Go-SANS-SERIE")
        s = scan.nouvelle_session(f, _cfg(), ENV_PE)
        with tempfile.TemporaryDirectory() as tmp:
            chemin = scan.chemin_session(Path(tmp), s)
            self.assertNotIn(".0Go", chemin.stem.replace(chemin.suffix, ""))
            scan.sauver_session(s, chemin)
            self.assertTrue(chemin.exists())


class TestConfig(unittest.TestCase):

    def test_normalisation(self):
        c = ScanConfig(mode="nimporte", niveau="T9", bloc_octets=10,
                       max_blocs_illisibles=0, lectures_aleatoires=-5).normalized()
        self.assertEqual(c.mode, "express")
        self.assertEqual(c.niveau, "T1")
        self.assertEqual(c.bloc_octets, scan.SOUS_BLOC_MIN)
        self.assertEqual(c.max_blocs_illisibles, 1)
        self.assertEqual(c.lectures_aleatoires, 0)
        self.assertEqual(c.nb_segments, 12)
        self.assertEqual(c.segment_octets, 256 * MIB)
        self.assertIsNone(ScanConfig(mode="complet").normalized().nb_segments)


if __name__ == "__main__":
    unittest.main()
