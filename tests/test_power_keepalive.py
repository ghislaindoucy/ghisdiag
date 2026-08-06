"""
Tests du blocage de la mise en veille (power_keepalive.py).

L'appel systeme SetThreadExecutionState est remplace par un enregistreur : on
verifie les drapeaux DEMANDES a Windows, sans toucher a l'etat energetique de
la machine qui execute la suite.

Points couverts :
  - les drapeaux poses (ES_CONTINUOUS + ES_SYSTEM_REQUIRED, et l'ecran en plus
    seulement si on l'a demande) ;
  - le comptage par raison : le bench et l'interrupteur de l'onglet Setup
    peuvent bloquer en meme temps, et la veille n'est rendue qu'a la derniere
    raison levee (c'est le scenario qui ruinerait un bench de 17 min) ;
  - un refus de Windows est rendu tel quel : acquire() ne doit pas affirmer un
    blocage qui n'a pas eu lieu ;
  - shutdown() relache l'etat.

Lancement :  py -m unittest discover -s tests -v
"""

import threading
import unittest

import power_keepalive as pk


class _Recorder:
    """Faux SetThreadExecutionState : memorise les appels, refuse sur demande."""

    def __init__(self, result=True):
        self.calls  = []
        self.result = result
        self.seen   = threading.Event()

    def __call__(self, flags):
        self.calls.append(flags)
        self.seen.set()
        return self.result

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


class PowerKeepaliveTest(unittest.TestCase):

    def setUp(self):
        self.real = pk._set_execution_state
        self.rec  = _Recorder()
        pk._set_execution_state = self.rec

    def tearDown(self):
        pk.shutdown()
        pk._set_execution_state = self.real

    # -- drapeaux ----------------------------------------------------------

    def test_acquire_pose_continuous_et_system_required(self):
        self.assertTrue(pk.acquire("test"))
        self.assertTrue(pk.is_active())
        self.assertEqual(self.rec.last,
                         pk.ES_CONTINUOUS | pk.ES_SYSTEM_REQUIRED)

    def test_ecran_allume_seulement_si_demande(self):
        pk.acquire("bench")
        self.assertFalse(self.rec.last & pk.ES_DISPLAY_REQUIRED)

        pk.acquire("technicien", keep_display=True)
        self.assertTrue(self.rec.last & pk.ES_DISPLAY_REQUIRED)

        # La raison sans ecran subsiste : on retombe sur le blocage veille seul.
        pk.release("technicien")
        self.assertTrue(pk.is_active())
        self.assertFalse(self.rec.last & pk.ES_DISPLAY_REQUIRED)

    # -- comptage par raison -----------------------------------------------

    def test_veille_rendue_seulement_a_la_derniere_raison(self):
        pk.acquire("bench")
        pk.acquire("interrupteur")
        self.assertEqual(pk.reasons(), {"bench", "interrupteur"})

        self.assertTrue(pk.release("interrupteur"))
        self.assertTrue(pk.is_active(),
                        "le bench bloque encore : la veille ne doit pas revenir")
        self.assertTrue(self.rec.last & pk.ES_SYSTEM_REQUIRED)

        self.assertFalse(pk.release("bench"))
        self.assertFalse(pk.is_active())
        self.assertEqual(self.rec.last, pk.ES_CONTINUOUS)

    def test_release_d_une_raison_inconnue_est_sans_effet(self):
        pk.acquire("bench")
        self.assertTrue(pk.release("jamais posee"))
        self.assertTrue(pk.is_active())
        self.assertEqual(pk.reasons(), {"bench"})

    def test_acquire_deux_fois_la_meme_raison_ne_compte_qu_une_fois(self):
        pk.acquire("bench")
        pk.acquire("bench")
        pk.release("bench")
        self.assertFalse(pk.is_active())
        self.assertEqual(pk.reasons(), set())

    # -- refus de Windows --------------------------------------------------

    def test_refus_de_windows_rendu_tel_quel(self):
        self.rec.result = False
        self.assertFalse(pk.acquire("test"),
                         "acquire ne doit pas affirmer un blocage refuse")
        self.assertFalse(pk.is_active())

    # -- arret -------------------------------------------------------------

    def test_shutdown_relache_l_etat(self):
        pk.acquire("bench")
        pk.shutdown()
        self.assertFalse(pk.is_active())
        self.assertEqual(self.rec.last, pk.ES_CONTINUOUS)
        self.assertEqual(pk.reasons(), set())

    def test_reutilisable_apres_shutdown(self):
        pk.acquire("bench")
        pk.shutdown()
        self.assertTrue(pk.acquire("bench"))
        self.assertTrue(pk.is_active())


if __name__ == "__main__":
    unittest.main()
