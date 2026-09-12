"""
Tests de non-fuite de la clé API (ai_analyzer.py) — audit du 13/09/2026.

La clé Gemini partait dans l'URL (?key=...), et le message d'erreur de connexion
recopiait l'URL : la clé se retrouvait dans le journal et à l'écran. Corrigé :
clé en en-tête x-goog-api-key, plus jamais dans l'URL ; et filet de sécurité
_redact() qui retire la clé de tout message.

Lancement :  py -m unittest discover -s tests -v
"""

import os
import tempfile

os.environ.setdefault("GHISDIAG_LOG_DIR",
                      os.path.join(tempfile.gettempdir(), "ghisdiag_tests"))

import unittest

import ai_analyzer as a


class GeminiUrlTests(unittest.TestCase):

    def test_url_gemini_sans_cle(self):
        self.assertNotIn("key=", a.PROVIDERS["gemini"]["url"])
        self.assertNotIn("{key}", a.PROVIDERS["gemini"]["url"])


class RedactTests(unittest.TestCase):

    def test_cle_retiree(self):
        key = "AIzaSyLONGENOUGH1234567890"
        msg = a._redact(f"echec sur https://x/y?key={key}&z=1", key)
        self.assertNotIn(key, msg)
        self.assertIn("***", msg)

    def test_cle_courte_ignoree(self):
        # Sous 8 caractères : trop court pour être une vraie clé, on ne massacre
        # pas le message avec des faux positifs.
        self.assertEqual(a._redact("erreur abc", "abc"), "erreur abc")

    def test_message_sans_cle_inchange(self):
        self.assertEqual(a._redact("connexion refusee", "AIzaSyLONG1234567890"),
                         "connexion refusee")


class RealCallNoLeakTests(unittest.TestCase):
    """Appel réel avec une fausse clé : la clé ne doit apparaître nulle part."""

    FAKE = "AIzaSyFAKEKEYFORTEST123456789"

    def test_gemini_test_api_key_ne_fuit_pas(self):
        kind, msg = a.test_api_key("gemini", self.FAKE)
        # Fausse clé -> invalide/erreur, mais surtout : jamais la clé en clair.
        self.assertIn(kind, ("invalid", "error"))
        self.assertNotIn(self.FAKE, msg)


if __name__ == "__main__":
    unittest.main()
