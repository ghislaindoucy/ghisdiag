"""
Tests de sécurité : passage d'arguments aux scripts PowerShell (orchestrator.py).

Contexte (audit du 13/09/2026). L'ancienne construction de la ligne de commande
`& 'script.ps1' -Name 'valeur'` avait deux trous, démontrés :
  - une valeur commençant par « - » était insérée sans guillemets ;
  - l'échappement ne doublait que l'apostrophe ASCII, pas « ’ » / « ‘ » que
    PowerShell traite AUSSI comme des guillemets.
Un SSID, un nom d'imprimante ou un chemin bien choisi exécutait alors du code
arbitraire dans le PowerShell élevé. Le correctif fait passer les arguments en
JSON sur l'entrée standard, splattés côté PowerShell : une valeur reste une
donnée, jamais du code.

Ces tests exécutent RÉELLEMENT PowerShell (lecture seule) et vérifient qu'aucune
charge d'injection ne crée de fichier témoin.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL AVANT D'IMPORTER main/orchestrator (voir test_bench_gpu_detect).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import json
import unittest
from pathlib import Path

import orchestrator as o

BASE = o.get_base_path()


def _script(rel):
    return (BASE / rel).resolve()


class ParamBlockTests(unittest.TestCase):
    """Le bloc param() est lu correctement, y compris avec ValidateSet/Parameter
    (qui contiennent des parenthèses et cassaient une extraction naïve)."""

    def test_spooler_params_malgre_validateset(self):
        params = o._script_params(_script("collectors/spooler_fix.ps1"))
        self.assertEqual(set(params), {"action", "printername", "jobid"})
        self.assertFalse(any(params.values()))  # aucun switch

    def test_switch_detecte(self):
        self.assertTrue(o._script_params(_script("collectors/clear_logs.ps1"))["includesecurity"])
        self.assertTrue(o._script_params(_script("collectors/user_manager.ps1"))["noexpiry"])
        self.assertTrue(o._script_params(_script("collectors/wifi_manager.ps1"))["includekeys"])

    def test_param_block_parentheses_equilibrees(self):
        text = 'param(\n  [ValidateSet("a","b")]\n  [string]$Action,\n  [switch]$Flag\n)'
        self.assertIn("$Action", o._extract_param_block(text))
        self.assertIn("$Flag", o._extract_param_block(text))

    def test_sans_param_block(self):
        self.assertEqual(o._extract_param_block("# aucun bloc\nWrite-Output 1"), "")


class BuildArgsTests(unittest.TestCase):

    def setUp(self):
        self.spooler = _script("collectors/spooler_fix.ps1")
        self.user = _script("collectors/user_manager.ps1")

    def test_paires_nom_valeur(self):
        self.assertEqual(
            o._build_ps_args(self.spooler, ["-Action", "list", "-PrinterName", "HP"]),
            {"Action": "list", "PrinterName": "HP"})

    def test_valeur_commencant_par_tiret_preservee(self):
        # Bug corrigé au passage : un mot de passe « -abc » fonctionne enfin.
        args = o._build_ps_args(self.user, ["-Password", "-abc"])
        self.assertEqual(args, {"Password": "-abc"})

    def test_switch_sans_valeur(self):
        args = o._build_ps_args(self.user,
                                ["-Action", "set-password-policy", "-Username", "x", "-NoExpiry"])
        self.assertEqual(args["NoExpiry"], True)

    def test_parametre_inconnu_rejete(self):
        with self.assertRaises(ValueError):
            o._build_ps_args(self.spooler, ["-Action", "list", "-Evil", "x"])

    def test_valeur_orpheline_rejetee(self):
        with self.assertRaises(ValueError):
            o._build_ps_args(self.spooler, ["-PrinterName"])

    def test_token_sans_tiret_rejete(self):
        with self.assertRaises(ValueError):
            o._build_ps_args(self.spooler, ["Action", "list"])

    def test_payload_json_ascii_strict(self):
        payload = o._ps_payload(self.spooler, {"PrinterName": "été ’ 日本"})
        payload.decode("ascii")  # ne lève pas : ensure_ascii
        obj = json.loads(payload)
        self.assertEqual(obj["args"]["PrinterName"], "été ’ 日本")


class InjectionExecutionTests(unittest.TestCase):
    """Exécution RÉELLE : aucune charge d'injection ne doit créer de fichier.

    On cible print-test avec un nom d'imprimante hostile : l'imprimante n'existe
    pas, l'action échoue proprement, et surtout rien ne s'exécute."""

    PAYLOADS = [
        "-x; Set-Content $env:TEMP\\{mark} pwn",
        "a’; Set-Content $env:TEMP\\{mark} pwn; ’",
        "$(Set-Content $env:TEMP\\{mark} pwn)",
        "'; Set-Content $env:TEMP\\{mark} pwn #",
    ]

    def test_aucune_injection_ne_cree_de_fichier(self):
        tmp = Path(tempfile.gettempdir())
        for i, tpl in enumerate(self.PAYLOADS):
            mark = tmp / f"ghisdiag_inj_test_{i}.txt"
            mark.unlink(missing_ok=True)
            payload = tpl.format(mark=mark.name)
            try:
                o.run_ps_action("collectors/spooler_fix.ps1",
                                ["-Action", "print-test", "-PrinterName", payload], timeout=30)
            finally:
                created = mark.exists()
                mark.unlink(missing_ok=True)
            self.assertFalse(created, f"charge exécutée : {payload!r}")

    def test_valeur_unicode_traverse_intacte(self):
        # Une valeur légitime pleine d'accents et de non-ASCII doit passer.
        d = o.run_ps_action("collectors/spooler_fix.ps1",
                            ["-Action", "print-test", "-PrinterName", "Imprimante été 日本 ✓"],
                            timeout=30)
        # Imprimante inexistante -> échec, mais l'appel aboutit et renvoie du JSON.
        self.assertIn("success", d)


class ReadOnlyCallsTests(unittest.TestCase):
    """Les appels légitimes existants continuent de fonctionner."""

    def test_smart_sans_args(self):
        d = o.run_ps_action("collectors/smart.ps1", [], timeout=30)
        self.assertIn("disks", d)

    def test_spooler_printers(self):
        d = o.run_ps_action("collectors/spooler_fix.ps1", ["-Action", "printers"], timeout=30)
        self.assertTrue(d.get("success"))

    def test_stream_stdin(self):
        lines = []
        rc = o.run_ps_stream("collectors/winget_manager.ps1", ["-Action", "check"],
                             lines.append, timeout=60)
        self.assertEqual(rc, 0)
        self.assertTrue(lines)

    def test_chemin_hors_base_rejete(self):
        with self.assertRaises(RuntimeError):
            o.run_ps_action("../evil.ps1", [], timeout=10)


if __name__ == "__main__":
    unittest.main()
