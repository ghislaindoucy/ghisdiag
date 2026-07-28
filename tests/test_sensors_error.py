"""
Le backend capteurs explique ses refus — encore faut-il ne pas jeter le message.

sensors.ps1 emet {"ok": false, "error": "..."} quand il ne peut pas ouvrir le
materiel (DLL absente, Computer.Open() en echec, dependance manquante). Le
lecteur de flux ecartait ces lignes en silence : l'utilisateur recevait
« les capteurs ne repondent pas » et le journal ne gardait aucune trace de la
cause, pourtant passee sous nos yeux.

Cas reel : machine de dev, 28/07/2026 19h20 — bench refuse, log vide de toute
explication.

Lancement :  py -m unittest discover -s tests -v
"""

import json
import unittest

from collectors.sensors import SensorStream


class _FauxFlux:
    """Sert de stdout : une liste de lignes deja encodees."""

    def __init__(self, lignes):
        self._lignes = [l.encode("utf-8") + b"\n" for l in lignes]

    def __iter__(self):
        return iter(self._lignes)


class _FauxProc:
    def __init__(self, lignes):
        self.stdout = _FauxFlux(lignes)


def _lire(stream, lignes):
    """Fait tourner le lecteur sur des lignes fabriquees, sans PowerShell."""
    stream._proc = _FauxProc(lignes)
    stream._running = True
    stream._reader()
    return stream


class TestBackendError(unittest.TestCase):

    ERREUR = json.dumps({"ok": False,
                         "error": "LibreHardwareMonitorLib.dll introuvable : X:\\tools"})
    ERREUR2 = json.dumps({"ok": False, "error": "Echec Computer.Open() : acces refuse"})
    BON = json.dumps({"ok": True, "cpu_ref": 55.0, "cpu_load": 30.0})

    def test_error_is_kept_not_swallowed(self):
        s = _lire(SensorStream(2000), [self.ERREUR])
        self.assertIn("introuvable", s.backend_error)
        self.assertIsNone(s.latest())

    def test_first_error_wins(self):
        """Le script repete son erreur a chaque tick : on garde la premiere."""
        s = _lire(SensorStream(2000), [self.ERREUR, self.ERREUR2, self.ERREUR])
        self.assertIn("introuvable", s.backend_error)
        self.assertNotIn("Computer.Open", s.backend_error)

    def test_no_error_when_backend_is_fine(self):
        s = _lire(SensorStream(2000), [self.BON, self.BON])
        self.assertEqual(s.backend_error, "")
        self.assertIsNotNone(s.latest())

    def test_garbage_lines_do_not_invent_an_error(self):
        s = _lire(SensorStream(2000), ["pas du json", "", "{}", self.BON])
        self.assertEqual(s.backend_error, "")
        self.assertIsNotNone(s.latest())

    def test_ok_false_without_message_stays_silent(self):
        s = _lire(SensorStream(2000), [json.dumps({"ok": False})])
        self.assertEqual(s.backend_error, "")

    def test_start_clears_a_previous_error(self):
        s = _lire(SensorStream(2000), [self.ERREUR])
        self.assertNotEqual(s.backend_error, "")
        s._backend_error = ""      # ce que fait start() avant de relancer
        self.assertEqual(s.backend_error, "")


if __name__ == "__main__":
    unittest.main()
