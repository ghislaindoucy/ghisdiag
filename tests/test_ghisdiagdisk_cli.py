"""
Tests de la console GhisdiagDisk (ghisdiagdisk/cli.py) - sans materiel.

Deux defauts vus en atelier le 05/09 sont figes ici :

  - apres un Ctrl+C, le fil principal sortait de son attente et affichait
    << Aucune session produite >> alors que le balayage ecrivait encore sa
    zone. Cause : quand un KeyboardInterrupt interrompt `Thread.join()`,
    CPython marque l'objet Thread comme termine et `is_alive()` rend False
    pour toujours (verifie sur 3.12.10). `patienter` n'utilise plus que
    l'Event pose par le worker ;
  - `--reprendre <mauvais nom>` repondait << session illisible >> sans dire
    quoi taper. La commande liste desormais les sessions reprenables, et
    `--reprendre` sans valeur prend la plus recente.

Lancement :  py -m unittest tests.test_ghisdiagdisk_cli -v
"""

import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ghisdiagdisk import cli, scan  # noqa: E402

MIB = scan.MIB
GO = 10 ** 9


def fiche(cle="WD-TEST123456", taille=64 * GO):
    return {"index": 0, "cle_identite": cle, "confiance_cle": "forte", "modele": "FAUX HDD",
            "bus": "SATA", "type_support": "Disque mecanique (7200 tr/min)", "classe": "hdd",
            "smart": None, "avertissements": [],
            "geometrie": {"index": 0, "taille_octets": taille, "taille_go": round(taille / 1e9, 1),
                          "secteur_logique": 512, "secteur_physique": 4096}}


ENV_PE = {"environnement": "winpe", "winpe": True, "admin": True}


def session_ecrite(dossier: Path, cle="WD-TEST123456", statut="interrompu",
                   zones=3, demarre="2026-09-05T11:41:00", mode="complet"):
    """Une session plausible, ecrite comme le ferait un checkpoint."""
    f = fiche(cle)
    cfg = scan.ScanConfig(mode=mode, nb_segments=8, segment_octets=8 * MIB)
    s = scan.nouvelle_session(f, cfg, ENV_PE)
    s["demarre_a"] = demarre
    s["statut"] = statut
    if statut == "interrompu":
        s["arret"] = scan.ARRET_UTILISATEUR
    s["segments"] = [{"index": i, "offset": i * 8 * MIB, "longueur": 8 * MIB,
                      "offset_go": round(i * 8 * MIB / 1e9, 2), "octets_lus": 8 * MIB,
                      "nb_blocs": 8, "duree_ms": 80.0, "duree_erreurs_ms": 0.0,
                      "debit_mo_s": 100.0, "bloc_median_ms": 10.0, "bloc_p99_ms": 10.5,
                      "bloc_max_ms": 10.6, "bloc_moyen_ms": 10.0, "seuil_anomalie_ms": 30.0,
                      "nb_blocs_anormaux": 0, "nb_blocs_isoles": 0, "nb_blocs_mourants": 0,
                      "anomalies": [], "anomalies_isolees": [], "nb_blocs_illisibles": 0,
                      "nb_secteurs_illisibles": 0, "plages_illisibles": [],
                      "nb_plages_illisibles": 0, "complet": True, "interrompu": False}
                     for i in range(zones)]
    chemin = scan.chemin_session(dossier, s)
    scan.sauver_session(s, chemin)
    return chemin


class EventQuiInterrompt:
    """Event dont `wait` leve KeyboardInterrupt les N premieres fois - comme
    un Ctrl+C (ou plusieurs) pendant l'attente."""

    def __init__(self, interruptions=1, poses_apres=3):
        self.reste = interruptions
        self.poses_apres = poses_apres
        self.appels = 0
        self._pose = False

    def is_set(self):
        return self._pose

    def wait(self, timeout=None):
        self.appels += 1
        if self.reste > 0:
            self.reste -= 1
            raise KeyboardInterrupt
        if self.appels >= self.poses_apres:
            self._pose = True
        return self._pose


class TestPatienter(unittest.TestCase):
    """Le fil principal doit attendre la fin du balayage, Ctrl+C ou pas."""

    def test_sans_interruption(self):
        fin, annulation = EventQuiInterrompt(interruptions=0, poses_apres=2), threading.Event()
        messages = []
        self.assertFalse(cli.patienter(fin, annulation, annoncer=lambda: messages.append(1), pas=0))
        self.assertFalse(annulation.is_set())
        self.assertEqual(messages, [])

    def test_un_ctrl_c_demande_l_arret_mais_continue_d_attendre(self):
        fin, annulation = EventQuiInterrompt(interruptions=1, poses_apres=4), threading.Event()
        messages = []
        self.assertTrue(cli.patienter(fin, annulation, annoncer=lambda: messages.append(1), pas=0))
        self.assertTrue(annulation.is_set())
        self.assertTrue(fin.is_set(), "on ne sort pas avant que le worker ait pose la fin")
        self.assertEqual(messages, [1], "le message d'arret n'est dit qu'une fois")
        self.assertGreater(fin.appels, 1, "l'attente s'est poursuivie apres le Ctrl+C")

    def test_ctrl_c_repetes(self):
        """Un technicien qui pilonne Ctrl+C ne doit pas perdre sa session."""
        fin, annulation = EventQuiInterrompt(interruptions=5, poses_apres=8), threading.Event()
        messages = []
        cli.patienter(fin, annulation, annoncer=lambda: messages.append(1), pas=0)
        self.assertTrue(fin.is_set())
        self.assertEqual(messages, [1])

    def test_interruption_pendant_le_message_ne_fait_pas_sortir(self):
        """Le Ctrl+C peut tomber pendant l'affichage : tout le corps de la
        boucle est dans le try, on reste en attente."""
        fin, annulation = EventQuiInterrompt(interruptions=1, poses_apres=6), threading.Event()
        etat = {"n": 0}

        def _annoncer():
            etat["n"] += 1
            raise KeyboardInterrupt          # Ctrl+C pile pendant le print
        cli.patienter(fin, annulation, annoncer=_annoncer, pas=0)
        self.assertTrue(fin.is_set())
        self.assertEqual(etat["n"], 1)


class TestExecuterBalayage(unittest.TestCase):
    """Le bout en bout console, avec un faux lecteur : la session revient
    toujours, et le fichier ecrit est nomme dans la sortie."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._rawdisk = cli.rawdisk

        class FauxLecteur:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def lire(self, off, n): return n
        cli.rawdisk = type("R", (), {"LecteurDisque": FauxLecteur})

    def tearDown(self):
        cli.rawdisk = self._rawdisk

    def test_balayage_complet_rend_la_session_et_son_fichier(self):
        cfg = scan.ScanConfig(mode="express", nb_segments=4, segment_octets=4 * MIB,
                              lectures_aleatoires=0)
        with redirect_stdout(io.StringIO()):
            s = cli.executer_balayage(fiche(), cfg, ENV_PE, self.tmp)
        self.assertIsNotNone(s)
        self.assertEqual(s["statut"], "termine")
        self.assertTrue(s["_fichier"].endswith(".json"))
        self.assertTrue(Path(s["_fichier"]).is_file())

    def test_vrai_ctrl_c_pendant_le_balayage(self):
        """Regression de l'atelier du 05/09 : un Ctrl+C reel (interrupt_main,
        comme la console) pendant une zone. La session doit revenir complete,
        avec son verdict et son fichier - la console disait
        << Aucune session produite >> pendant que le fichier s'ecrivait."""
        import _thread
        import time as _t
        compteur = {"blocs": 0}

        class LecteurQuiInterrompt:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def lire(self, off, n):
                compteur["blocs"] += 1
                if compteur["blocs"] == 10:        # au milieu de la 3e zone
                    _thread.interrupt_main()
                _t.sleep(0.004)
                return n
        cli.rawdisk = type("R", (), {"LecteurDisque": LecteurQuiInterrompt})
        cfg = scan.ScanConfig(mode="express", nb_segments=60, segment_octets=4 * MIB,
                              lectures_aleatoires=0)
        with redirect_stdout(io.StringIO()):
            s = cli.executer_balayage(fiche(), cfg, ENV_PE, self.tmp, pas=0.02)
        self.assertIsNotNone(s, "la session doit revenir malgre le Ctrl+C")
        self.assertEqual(s["statut"], "interrompu")
        self.assertEqual(s["arret"], scan.ARRET_UTILISATEUR)
        self.assertIsNotNone(s["verdict"])
        self.assertLess(len(s["segments"]), 60, "le balayage s'est bien arrete")
        self.assertGreaterEqual(len(s["segments"]), 1)
        self.assertTrue(Path(s["_fichier"]).is_file())
        relu = scan.charger_session(s["_fichier"])
        self.assertEqual(relu["statut"], "interrompu")
        self.assertEqual(len(relu["segments"]), len(s["segments"]))


class TestReprise(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def _capturer(self, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            res = cli.resoudre_reprise(*a, **kw)
        return res, buf.getvalue()

    def test_fichier_nomme(self):
        chemin = session_ecrite(self.tmp)
        (s, f), _ = self._capturer(str(chemin), self.tmp)
        self.assertEqual(s["statut"], "interrompu")
        self.assertEqual(Path(f).name, chemin.name)

    def test_auto_prend_la_plus_recente(self):
        session_ecrite(self.tmp, demarre="2026-09-05T09:00:00", zones=1)
        recente = session_ecrite(self.tmp, demarre="2026-09-05T11:41:00", zones=5)
        (s, f), _ = self._capturer("auto", self.tmp)
        self.assertEqual(Path(f).name, recente.name)
        self.assertEqual(len(s["segments"]), 5)

    def test_auto_filtre_sur_le_disque_choisi(self):
        session_ecrite(self.tmp, cle="AUTRE-DISQUE", demarre="2026-09-05T12:00:00")
        voulue = session_ecrite(self.tmp, cle="WD-TEST123456", demarre="2026-09-05T11:00:00")
        (s, f), _ = self._capturer("auto", self.tmp, "WD-TEST123456")
        self.assertEqual(Path(f).name, voulue.name)

    def test_session_terminee_non_reprenable(self):
        session_ecrite(self.tmp, statut="termine")
        (s, f), sortie = self._capturer("auto", self.tmp)
        self.assertIsNone(s)
        self.assertIn("Aucune session reprenable", sortie)

    def test_arret_de_securite_non_reprenable(self):
        session_ecrite(self.tmp, statut="arrete_securite")
        self.assertEqual(cli.sessions_reprenables(self.tmp), [])

    def test_mauvais_nom_liste_ce_qui_existe(self):
        """`--reprendre reprendre` du 05/09 : dire quoi taper, pas seulement
        que c'est illisible."""
        chemin = session_ecrite(self.tmp)
        (s, f), sortie = self._capturer("reprendre", self.tmp)
        self.assertIsNone(s)
        self.assertIn("introuvable", sortie)
        self.assertIn(chemin.name, sortie)
        self.assertIn("--disque N --reprendre", sortie)

    def test_dossier_sans_session(self):
        (s, f), sortie = self._capturer("auto", self.tmp)
        self.assertIsNone(s)
        self.assertIn("Aucune session reprenable", sortie)

    def test_fichier_qui_n_est_pas_une_session(self):
        p = self.tmp / "ghisdiagdisk_bidon.json"
        p.write_text("{ pas du json", encoding="utf-8")
        (s, f), sortie = self._capturer(str(p), self.tmp)
        self.assertIsNone(s)
        self.assertIn("illisible", sortie)

    def test_session_du_0409_schema_1_est_reprenable(self):
        """Les rapports de la premiere campagne se reprennent aussi."""
        chemin = session_ecrite(self.tmp)
        d = json.loads(chemin.read_text(encoding="utf-8"))
        d["schema"] = 1
        for seg in d["segments"]:
            seg.pop("nb_blocs_isoles", None), seg.pop("anomalies_isolees", None)
        chemin.write_text(json.dumps(d), encoding="utf-8")
        (s, f), _ = self._capturer("auto", self.tmp)
        self.assertIsNotNone(s)
        self.assertEqual(s["schema"], scan.SCHEMA_VERSION)
        scan.reprendre_session(s, fiche())          # accepte apres migration


if __name__ == "__main__":
    unittest.main()
