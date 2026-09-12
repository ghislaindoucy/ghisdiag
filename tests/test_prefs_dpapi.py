"""
Tests du chiffrement des clés API (prefs.py) — audit du 13/09/2026.

L'ancien schéma dérivait la clé de chiffrement du nom de machine + nom
d'utilisateur, deux valeurs présentes dans CHAQUE rapport JSON de Ghisdiag :
quiconque récupérait un rapport et prefs.json pouvait déchiffrer les clés API.
Remplacé par DPAPI (lié au compte Windows, non dérivable d'infos publiques).

Vérifie :
  - aller-retour DPAPI : la clé se relit, le clair n'est jamais dans le fichier ;
  - si le chiffrement échoue, la clé n'est PAS écrite en clair (elle est perdue,
    pas exposée) ;
  - migration transparente d'une clé à l'ancien format Fernet ;
  - une clé illisible (DPAPI d'un autre compte) est ignorée, jamais devinée.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER JOURNAL + PREFS AVANT D'IMPORTER prefs (le module fige prefs.json à l'import).
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import json
import unittest

import prefs as p
from prefs import PREFS_FILE, load_prefs, save_prefs


@unittest.skipUnless(p._HAS_DPAPI, "DPAPI indisponible (hors Windows)")
class DpapiTests(unittest.TestCase):

    def setUp(self):
        if PREFS_FILE.exists():
            PREFS_FILE.unlink()

    tearDown = setUp

    def _raw_text(self) -> str:
        return PREFS_FILE.read_text(encoding="utf-8")

    def test_aller_retour(self):
        save_prefs({"output_dir": r"C:\R", "anthropic_api_key": "sk-ant-SECRET-xyz"})
        self.assertNotIn("sk-ant-SECRET-xyz", self._raw_text())
        self.assertIn(p._DPAPI_PREFIX, self._raw_text())
        self.assertEqual(load_prefs().get("anthropic_api_key"), "sk-ant-SECRET-xyz")

    def test_clair_jamais_dans_le_fichier(self):
        # Même en simulant DPAPI indisponible, on n'écrit pas la clé en clair.
        orig = p._HAS_DPAPI
        p._HAS_DPAPI = False
        try:
            save_prefs({"output_dir": r"C:\R", "openai_api_key": "sk-oai-SECRET"})
        finally:
            p._HAS_DPAPI = orig
        raw = self._raw_text()
        self.assertNotIn("sk-oai-SECRET", raw)
        self.assertNotIn("openai_api_key", json.loads(raw))
        # La préférence non sensible, elle, est bien enregistrée.
        self.assertEqual(json.loads(raw)["output_dir"], r"C:\R")

    def test_valeur_illisible_ignoree(self):
        # Un blob DPAPI bidon (autre compte / corrompu) ne doit pas être deviné.
        import base64
        faux = p._DPAPI_PREFIX + base64.b64encode(b"pas un vrai blob dpapi").decode()
        PREFS_FILE.write_text(json.dumps({"grok_api_key": faux, "output_dir": r"C:\R"}),
                              encoding="utf-8")
        loaded = load_prefs()
        self.assertNotIn("grok_api_key", loaded)
        self.assertEqual(loaded["output_dir"], r"C:\R")

    @unittest.skipUnless(p._HAS_CRYPTO, "cryptography absent")
    def test_migration_fernet_vers_dpapi(self):
        from cryptography.fernet import Fernet
        legacy = Fernet(p._legacy_fernet_key()).encrypt(b"ms-LEGACY").decode()
        PREFS_FILE.write_text(json.dumps({"mistral_api_key": legacy, "output_dir": r"C:\R"}),
                              encoding="utf-8")
        loaded = load_prefs()
        self.assertEqual(loaded.get("mistral_api_key"), "ms-LEGACY")   # relu
        save_prefs(loaded)
        raw = self._raw_text()
        self.assertIn(p._DPAPI_PREFIX, raw)      # réécrit en DPAPI
        self.assertNotIn(legacy, raw)            # l'ancien format a disparu


class NoPlaintextContractTests(unittest.TestCase):
    """Contrat indépendant de DPAPI : _encrypt_string ne renvoie jamais de clair."""

    def test_encrypt_echec_renvoie_none(self):
        orig = p._HAS_DPAPI
        p._HAS_DPAPI = False
        try:
            self.assertIsNone(p._encrypt_string("une-cle"))
        finally:
            p._HAS_DPAPI = orig

    def test_encrypt_vide_renvoie_none(self):
        self.assertIsNone(p._encrypt_string(""))


if __name__ == "__main__":
    unittest.main()
