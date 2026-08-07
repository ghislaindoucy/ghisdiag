"""
Tests de l'éjection des clés API (prefs.py).

Le cas réel : Ghisdiag reste installé sur le poste d'un client, mais la clé API
du technicien ne doit pas y rester active. Une clé « éjectée » doit disparaître
du disque — pas être remplacée par une chaîne vide chiffrée, qui laisserait
croire à un reste exploitable et repousserait une valeur vide dans les prefs.

Vérifie :
  - qu'une clé vide n'est jamais écrite dans prefs.json ;
  - que clear_api_keys retire bien l'entrée du fichier et compte ce qu'elle a
    retiré (une clé absente ne compte pas) ;
  - que les autres préférences (dossier de sortie, fournisseur actif, autres
    clés) survivent à l'éjection ;
  - que la clé éjectée n'est plus relue au chargement suivant.

Lancement :  py -m unittest discover -s tests -v
"""

# ISOLER LE JOURNAL ET LES PREFS AVANT D'IMPORTER prefs : le module fige son
# dossier (donc prefs.json) au moment de l'import.
import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import json
import unittest

import prefs as prefs_mod
from prefs import PREFS_FILE, clear_api_keys, load_prefs, save_prefs


class ApiKeyEjectTests(unittest.TestCase):

    def setUp(self):
        # Chaque test part d'un fichier de préférences vierge.
        if PREFS_FILE.exists():
            PREFS_FILE.unlink()

    tearDown = setUp

    def _raw(self) -> dict:
        """Contenu brut de prefs.json (valeurs encore chiffrées)."""
        return json.loads(PREFS_FILE.read_text(encoding="utf-8"))

    def test_cle_vide_jamais_ecrite(self):
        save_prefs({"output_dir": r"C:\Rapports", "anthropic_api_key": ""})
        raw = self._raw()
        self.assertNotIn("anthropic_api_key", raw)
        self.assertEqual(raw["output_dir"], r"C:\Rapports")

    def test_ejection_retire_la_cle_du_fichier(self):
        save_prefs({"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-secret"})
        # Pré-condition : la clé est bien là (et chiffrée, pas en clair).
        raw = self._raw()
        self.assertIn("anthropic_api_key", raw)
        self.assertNotIn("sk-ant-secret", PREFS_FILE.read_text(encoding="utf-8"))

        removed = clear_api_keys(["anthropic_api_key"])

        self.assertEqual(removed, 1)
        self.assertNotIn("anthropic_api_key", self._raw())
        self.assertNotIn("anthropic_api_key", load_prefs())

    def test_ejection_preserve_les_autres_prefs(self):
        save_prefs({
            "output_dir":        r"C:\Rapports",
            "auto_open_browser": False,
            "ai_provider":       "anthropic",
            "anthropic_api_key": "sk-ant-secret",
            "mistral_api_key":   "ms-secret",
        })

        clear_api_keys(["anthropic_api_key"])

        after = load_prefs()
        self.assertEqual(after["output_dir"], r"C:\Rapports")
        self.assertIs(after["auto_open_browser"], False)
        self.assertEqual(after["ai_provider"], "anthropic")
        self.assertEqual(after["mistral_api_key"], "ms-secret")
        self.assertNotIn("anthropic_api_key", after)

    def test_ejection_globale_de_toutes_les_cles(self):
        save_prefs({
            "output_dir":        r"C:\Rapports",
            "anthropic_api_key": "sk-ant-secret",
            "mistral_api_key":   "ms-secret",
            "openai_api_key":    "sk-oai-secret",
        })

        removed = clear_api_keys(
            ["anthropic_api_key", "mistral_api_key", "openai_api_key", "gemini_api_key"]
        )

        # gemini n'était pas renseignée : elle ne compte pas comme éjectée.
        self.assertEqual(removed, 3)
        after = load_prefs()
        self.assertEqual(after["output_dir"], r"C:\Rapports")
        for name in prefs_mod._ENCRYPTED_KEYS:
            self.assertNotIn(name, after)

    def test_ejection_sans_fichier_ne_leve_pas(self):
        # Poste où l'IA n'a jamais été configurée : l'appel doit rester inoffensif.
        self.assertEqual(clear_api_keys(["anthropic_api_key"]), 0)

    def test_seules_les_cles_sensibles_sont_ejectables(self):
        # Garde-fou : clear_api_keys ne doit pas servir à effacer n'importe quelle
        # préférence par erreur de nom.
        save_prefs({"output_dir": r"C:\Rapports"})
        self.assertEqual(clear_api_keys(["output_dir"]), 0)
        self.assertEqual(load_prefs()["output_dir"], r"C:\Rapports")


if __name__ == "__main__":
    unittest.main()
