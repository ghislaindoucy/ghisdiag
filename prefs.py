"""
PlanetDiag - Gestion des préférences utilisateur.
"""
import json
import logging
import os
import socket
import base64
import hashlib
from pathlib import Path

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

logger = logging.getLogger(__name__)

LOG_DIR    = Path(os.path.expanduser("~")) / "AppData" / "Local" / "PlanetDiag"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PREFS_FILE = LOG_DIR / "prefs.json"

_PREFS_MAX_BYTES = 16 * 1024

# Types et validateurs attendus par clé.
# Pour ajouter une préférence : déclarer ici, pas dans _load_prefs.
_PREFS_SCHEMA: dict[str, type] = {
    "output_dir":        str,
    "auto_open_browser": bool,
    "mistral_api_key":   str,
}
_PREFS_VALIDATORS: dict[str, object] = {
    "output_dir": lambda v: len(v) < 4096,
    "mistral_api_key": lambda v: len(v) < 4096,
}

# Clés sensibles qui doivent être chiffrées
_ENCRYPTED_KEYS = {"mistral_api_key"}


def _get_encryption_key() -> bytes:
    """Génère une clé Fernet dérivée de la machine + username."""
    try:
        machine_name = socket.gethostname()
    except Exception:
        machine_name = "unknown"

    username = os.environ.get("USERNAME", "unknown")
    seed = f"{machine_name}:{username}:planetdiag".encode("utf-8")

    # Hash du seed pour obtenir une clé 32 bytes (256 bits)
    key_hash = hashlib.sha256(seed).digest()
    # Encoder en base64 pour Fernet
    fernet_key = base64.urlsafe_b64encode(key_hash)
    return fernet_key


def _encrypt_string(plaintext: str) -> str:
    """Chiffre une chaîne. Retourne la chaîne en clair si crypto non disponible."""
    if not _HAS_CRYPTO:
        logger.warning("cryptography non disponible, clé non chiffrée")
        return plaintext

    try:
        key = _get_encryption_key()
        f = Fernet(key)
        encrypted = f.encrypt(plaintext.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        logger.warning(f"Erreur chiffrement: {e}, stockage en clair")
        return plaintext


def _decrypt_string(ciphertext: str) -> str:
    """Déchiffre une chaîne. Retourne la chaîne en clair si crypto non disponible ou erreur."""
    if not _HAS_CRYPTO:
        return ciphertext

    try:
        key = _get_encryption_key()
        f = Fernet(key)
        decrypted = f.decrypt(ciphertext.encode("utf-8"))
        return decrypted.decode("utf-8")
    except InvalidToken:
        # Valeur non déchiffrable : soit en clair (ancienne version / crypto absente
        # à la sauvegarde), soit chiffrée sur une autre machine. On la rend telle quelle.
        logger.warning("Clé non déchiffrable (texte clair ou autre machine), valeur ignorée")
        return ciphertext
    except Exception as e:
        logger.warning(f"Erreur déchiffrement: {e}")
        return ciphertext


def load_prefs() -> dict:
    try:
        if PREFS_FILE.stat().st_size > _PREFS_MAX_BYTES:
            logger.warning("prefs.json dépasse %d octets, ignoré", _PREFS_MAX_BYTES)
            return {}
        raw = json.loads(PREFS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        out = {}
        for key, expected_type in _PREFS_SCHEMA.items():
            val = raw.get(key)
            if isinstance(val, expected_type):
                # Déchiffrer les clés sensibles
                if key in _ENCRYPTED_KEYS and isinstance(val, str):
                    val = _decrypt_string(val)

                validator = _PREFS_VALIDATORS.get(key)
                if validator is None or validator(val):
                    out[key] = val
        return out
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict):
    try:
        # Préparer une copie avec les clés sensibles chiffrées
        prefs_to_save = {}
        for key, val in prefs.items():
            if key in _ENCRYPTED_KEYS and isinstance(val, str):
                prefs_to_save[key] = _encrypt_string(val)
            else:
                prefs_to_save[key] = val

        tmp = PREFS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs_to_save, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PREFS_FILE)
    except OSError as e:
        logger.warning("Impossible de sauvegarder prefs : %s", e)
