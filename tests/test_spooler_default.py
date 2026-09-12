"""
Tests de l'imprimante par défaut et du raccourci « Périphériques et imprimantes »
(collectors/spooler_fix.ps1 + main.py, onglet Dépannage).

Vérifie :
  - que la branche « set-default » coupe la gestion automatique de Windows AVANT
    de définir l'imprimante (sinon Windows réattribue le rôle à la dernière
    imprimante utilisée et le choix est perdu) ;
  - que le succès se juge sur une relecture, pas sur le code retour WMI ;
  - que les garde-fous (nom invalide, imprimante introuvable) répondent sans rien
    modifier — exécutés pour de vrai, ils n'atteignent jamais le registre ;
  - le libellé affiché et le raccourci shell.

Le chemin nominal (changer réellement l'imprimante par défaut) modifie un réglage
de l'utilisateur : il se valide à la main, en atelier, via l'exe.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main (voir tests/test_bench_gpu_detect.py).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import unittest
from pathlib import Path

import main
from orchestrator import run_ps_action

SCRIPT = Path(__file__).resolve().parent.parent / "collectors" / "spooler_fix.ps1"
SOURCE = SCRIPT.read_text(encoding="utf-8", errors="replace")


def _set_default_branch() -> str:
    start = SOURCE.index('if ($Action -eq "set-default")')
    return SOURCE[start:]


class SetDefaultScriptContractTests(unittest.TestCase):

    def test_script_ascii_strict(self):
        # Règle PS du projet, rappelée dans l'en-tête des collecteurs.
        SCRIPT.read_bytes().decode("ascii")

    def test_action_declaree(self):
        self.assertIn('"set-default"', SOURCE[:SOURCE.index("$ErrorActionPreference")])

    def test_gestion_automatique_coupee_avant_definition(self):
        branch = _set_default_branch()
        self.assertIn("LegacyDefaultPrinterMode", branch)
        self.assertLess(branch.index("New-ItemProperty"), branch.index("SetDefaultPrinter"))

    def test_succes_juge_sur_relecture(self):
        branch = _set_default_branch()
        self.assertLess(branch.index("SetDefaultPrinter"), branch.index("Get-DefaultPrinterName"))
        self.assertIn("$ok      = ($current -eq $PrinterName)", branch)

    def test_garde_fous(self):
        branch = _set_default_branch()
        self.assertIn("Test-SafeName -Name $PrinterName", branch)
        # L'imprimante est cherchée avant toute écriture dans le registre.
        self.assertLess(branch.index("Imprimante introuvable"), branch.index("New-ItemProperty"))


class SetDefaultScriptRunTests(unittest.TestCase):
    """Chemins de refus exécutés réellement : aucun ne modifie la machine."""

    def test_nom_invalide_refuse(self):
        data = run_ps_action("collectors/spooler_fix.ps1",
                             ["-Action", "set-default", "-PrinterName", "a;b"])
        self.assertFalse(data.get("success"))
        self.assertIn("invalide", data.get("error", ""))

    def test_imprimante_introuvable(self):
        name = "Ghisdiag_imprimante_inexistante_42"
        data = run_ps_action("collectors/spooler_fix.ps1",
                             ["-Action", "set-default", "-PrinterName", name],
                             timeout=90)
        self.assertFalse(data.get("success"))
        self.assertIn("introuvable", data.get("error", ""))


class SetDefaultUiTests(unittest.TestCase):

    feedback = staticmethod(main.GhisdiagApp._set_default_feedback)
    label = staticmethod(main.GhisdiagApp._spooler_printer_label)

    def test_succes_simple(self):
        txt = self.feedback({"success": True, "name": "HP"})
        self.assertTrue(txt.startswith("✓"))
        self.assertIn("HP", txt)
        self.assertNotIn("⚠", txt)
        self.assertNotIn("automatique", txt)

    def test_succes_mode_auto_coupe_et_avertissement(self):
        txt = self.feedback({"success": True, "name": "HP", "auto_mode_disabled": True,
                             "warning": "autre compte"})
        self.assertIn("gestion automatique par Windows désactivée", txt)
        self.assertIn("⚠ autre compte", txt)

    def test_echec(self):
        txt = self.feedback({"success": False, "error": "Windows n'a pas retenu le choix"})
        self.assertTrue(txt.startswith("✗"))
        self.assertIn("pas retenu", txt)

    def test_libelle_etoile_et_travaux(self):
        self.assertEqual(self.label({"name": "HP", "status": "Normal", "is_default": True,
                                     "job_count": 2}),
                         "  ●  HP  ★  (2 travaux)")
        self.assertEqual(self.label({"name": "PDF", "status": "Offline"}), "  ○  PDF")

    def test_raccourci_peripheriques_et_imprimantes(self):
        self.assertEqual(main.GhisdiagApp.PRINTERS_FOLDER,
                         "shell:::{A8A91A66-3A7D-4424-8D24-04E180695C7A}")


if __name__ == "__main__":
    unittest.main()
