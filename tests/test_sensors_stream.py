"""
Un figeage du flux de capteurs ne doit plus coûter le bench entier.

Cas réel (atelier, 27/07/2026) : « flux interrompu (8s sans donnee, backend
fige ?) » sur deux machines, sur celle de Ghislain **exactement en fin de
bench**. Le chien de garde tuait le backend et l'affaire s'arrêtait là : dix
minutes de test déjà écoulées, perdues, alors que le flux serait reparti.

Le backend est désormais relancé (`max_restarts`), l'incident remonte via
`on_gap`, et `on_stall` — l'arrêt définitif — ne se déclenche plus qu'une fois
les relances épuisées.

`max_gap_sec` est le signal avant-coureur : le plus long silence observé entre
deux lignes, même quand il reste sous le seuil du chien de garde.

Lancement :  py -m unittest discover -s tests -v
"""

import json
import time
import unittest

from collectors.sensors import SensorStream


class _FluxSansProcess(SensorStream):
    """SensorStream dont le backend est simulé : `_spawn` ne lance rien."""

    def __init__(self, *args, spawn_ok=True, **kw):
        super().__init__(*args, **kw)
        self.spawns = 0
        self._spawn_ok = spawn_ok

    def _spawn(self) -> bool:
        self.spawns += 1
        if not self._spawn_ok:
            return False
        self._running = True
        self._last_line_ts = None
        self._start_ts = time.monotonic()
        return True

    def _terminate_proc(self) -> None:
        pass


class TestRelanceApresFigeage(unittest.TestCase):

    def setUp(self):
        self.gaps = []
        self.stalls = []

    def _flux(self, max_restarts=2, spawn_ok=True):
        return _FluxSansProcess(2000, max_restarts=max_restarts,
                                spawn_ok=spawn_ok,
                                on_gap=self.gaps.append,
                                on_stall=self.stalls.append)

    def test_le_premier_figeage_relance_au_lieu_de_tuer(self):
        s = self._flux()
        self.assertTrue(s._trigger_stall("fige 1"))
        self.assertFalse(s.stalled)          # le flux vit encore
        self.assertEqual(s.spawns, 1)        # relancé une fois
        self.assertEqual(self.stalls, [])    # personne n'a été prévenu d'un arrêt
        self.assertEqual(len(self.gaps), 1)
        self.assertTrue(self.gaps[0]["recovered"])
        self.assertEqual(self.gaps[0]["reason"], "fige 1")

    def test_arret_definitif_quand_les_relances_sont_epuisees(self):
        s = self._flux(max_restarts=2)
        self.assertTrue(s._trigger_stall("fige 1"))
        self.assertTrue(s._trigger_stall("fige 2"))
        self.assertFalse(s._trigger_stall("fige 3"))   # la 3e est fatale
        self.assertTrue(s.stalled)
        self.assertEqual(s.stall_reason, "fige 3")
        self.assertEqual(self.stalls, ["fige 3"])
        self.assertEqual([g["recovered"] for g in s.gaps], [True, True, False])

    def test_sans_relance_le_comportement_historique_est_conserve(self):
        s = self._flux(max_restarts=0)
        self.assertFalse(s._trigger_stall("fige"))
        self.assertTrue(s.stalled)
        self.assertEqual(s.spawns, 0)
        self.assertEqual(self.stalls, ["fige"])

    def test_relance_impossible_egale_arret_definitif(self):
        # Le process ne repart pas (PowerShell absent, machine saturée) : on ne
        # fait pas semblant d'avoir récupéré.
        s = self._flux(max_restarts=3, spawn_ok=False)
        self.assertFalse(s._trigger_stall("fige"))
        self.assertTrue(s.stalled)
        self.assertEqual(self.stalls, ["fige"])
        self.assertFalse(s.gaps[0]["recovered"])

    def test_un_figeage_deja_definitif_ne_se_rejoue_pas(self):
        s = self._flux(max_restarts=0)
        s._trigger_stall("fige")
        self.assertFalse(s._trigger_stall("fige encore"))
        self.assertEqual(self.stalls, ["fige"])       # une seule notification
        self.assertEqual(len(s.gaps), 1)


class _FluxLent:
    """stdout factice : insère un silence avant la deuxième ligne."""

    def __init__(self, lignes, silence_sec):
        self._lignes = lignes
        self._silence = silence_sec

    def __iter__(self):
        for i, l in enumerate(self._lignes):
            if i:
                time.sleep(self._silence)
            yield l.encode("utf-8") + b"\n"


class _FauxProc:
    def __init__(self, stdout):
        self.stdout = stdout


class TestPlusLongSilence(unittest.TestCase):
    """`max_gap_sec` : voir venir le figeage avant qu'il ne coupe."""

    BON = json.dumps({"ok": True, "cpu_ref": 55.0})

    def _lire(self, silence_sec):
        s = SensorStream(2000)
        s._proc = _FauxProc(_FluxLent([self.BON, self.BON], silence_sec))
        s._running = True
        s._reader(s._proc)
        return s

    def test_le_silence_le_plus_long_est_retenu(self):
        s = self._lire(0.4)
        self.assertGreaterEqual(s.max_gap_sec, 0.3)

    def test_flux_regulier_ne_signale_rien(self):
        s = self._lire(0.0)
        self.assertLess(s.max_gap_sec, 0.2)


if __name__ == "__main__":
    unittest.main()
