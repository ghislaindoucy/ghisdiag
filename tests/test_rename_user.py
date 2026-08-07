"""
Tests du renommage de compte local (collectors/user_manager.ps1 + main.py).

Le défaut constaté en atelier le 2026-08-07 : après un renommage, Ghisdiag
affichait le nouveau nom, mais Windows continuait d'afficher l'ancien à l'écran
de connexion et dans le menu Démarrer — même après redémarrage. Cause :
`Rename-LocalUser` ne change que le nom de compte (SAM) ; le nom AFFICHÉ est un
autre champ, `FullName`, qui n'était jamais mis à jour.

Vérifie :
  - que la branche « rename-user » aligne bien le nom complet sur le nouveau nom
    (garde-fou de régression : c'est exactement la ligne qui manquait) ;
  - que l'échec de cette seule étape reste un succès assorti d'un avertissement,
    puisque le compte, lui, est bel et bien renommé ;
  - que le message affiché porte l'avertissement quand il est présent.

Le chemin nominal (renommer un vrai compte) exige des droits administrateur et
modifie la base des comptes : il se valide à la main, en atelier, via l'exe.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main (voir tests/test_bench_gpu_detect.py).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import re
import unittest
from pathlib import Path

import main

SCRIPT = Path(__file__).resolve().parent.parent / "collectors" / "user_manager.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8", errors="replace")


def _rename_branch() -> str:
    """Corps de la branche « rename-user » du switch PowerShell."""
    start = SOURCE.index('"rename-user"')
    end = SOURCE.index('"set-password-policy"')
    return SOURCE[start:end]


class RenameScriptContractTests(unittest.TestCase):

    def test_le_nom_complet_est_aligne_sur_le_nouveau_nom(self):
        # Sans ce Set-LocalUser -FullName, l'écran de connexion garde l'ancien nom.
        branch = _rename_branch()
        self.assertRegex(
            branch,
            r"Set-LocalUser\s+-Name\s+\$NewName\s+-FullName\s+\$NewName",
            "le renommage doit aussi mettre à jour le nom AFFICHÉ par Windows",
        )

    def test_le_nom_complet_est_change_apres_le_nom_de_compte(self):
        # Set-LocalUser doit cibler le NOUVEAU nom : l'ancien n'existe plus.
        branch = _rename_branch()
        self.assertLess(
            branch.index("Rename-LocalUser"), branch.index("Set-LocalUser"),
            "Set-LocalUser doit suivre Rename-LocalUser, pas le précéder",
        )

    def test_echec_du_nom_affiche_reste_un_succes_avec_avertissement(self):
        # Le compte EST renommé : basculer en success=false ferait croire l'inverse.
        branch = _rename_branch()
        self.assertIn("$out.warning = $warning", branch)
        self.assertRegex(branch, r"success\s*=\s*\$true")

    def test_les_garde_fous_sont_intacts(self):
        branch = _rename_branch()
        for garde in ("Test-SafeUsername $Username", "Test-SafeUsername $NewName",
                      "est introuvable", "existe deja"):
            self.assertIn(garde, branch)


class RenameFeedbackTests(unittest.TestCase):

    feedback = staticmethod(main.GhisdiagApp._rename_feedback)

    def test_succes_simple(self):
        txt = self.feedback({"success": True, "message": "Compte 'a' renomme en 'b'."})
        self.assertTrue(txt.startswith("✓"))
        self.assertNotIn("⚠", txt)

    def test_avertissement_affiche(self):
        txt = self.feedback({
            "success": True,
            "message": "Compte 'a' renomme en 'b'.",
            "warning": "nom affiche non mis a jour",
        })
        self.assertIn("✓", txt)
        self.assertIn("⚠", txt)
        self.assertIn("nom affiche non mis a jour", txt)

    def test_message_absent_reste_lisible(self):
        self.assertEqual(self.feedback({"success": True}), "✓ Compte renommé.")


if __name__ == "__main__":
    unittest.main()
