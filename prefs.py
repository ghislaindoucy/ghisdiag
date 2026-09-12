"""
Ghisdiag - Gestion des préférences utilisateur.
"""
import json
import logging
import os
import socket
import base64
import hashlib
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False

logger = logging.getLogger(__name__)

# ── Chiffrement des clés API : DPAPI de Windows ──────────────────────────────
#
# L'ancien schéma dérivait la clé Fernet du nom de machine + nom d'utilisateur
# (voir _legacy_fernet_decrypt). Ces deux valeurs figurent dans CHAQUE rapport
# JSON produit par Ghisdiag : quiconque récupérait un rapport et le prefs.json
# pouvait reconstruire la clé et déchiffrer les clés API. Le « chiffrement »
# n'en était pas un.
#
# DPAPI (CryptProtectData, portée utilisateur) lie le secret au compte Windows
# courant : le chiffré n'est déchiffrable que par le même utilisateur, sur la
# même machine, protégé par ses identifiants de session — et rien n'est
# dérivable d'informations publiques. C'est le mécanisme prévu par Windows pour
# exactement cet usage. On ajoute une entropie secondaire propre à l'app.
#
# Les clés déjà enregistrées à l'ancien format sont relues (migration) puis
# réécrites en DPAPI au premier save_prefs. Si le chiffrement échoue, la clé
# n'est PAS écrite en clair : elle n'est pas enregistrée du tout.

_DPAPI_PREFIX = "dpapi:"
_DPAPI_ENTROPY = b"ghisdiag-api-key-v1"

try:
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DATA_BLOB)]
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _HAS_DPAPI = True
except (ImportError, OSError, AttributeError):
    _HAS_DPAPI = False


def _dpapi(func, data: bytes) -> bytes:
    """Appelle CryptProtectData / CryptUnprotectData avec l'entropie de l'app.

    Les tampons source restent des variables locales le temps de l'appel : les
    laisser filer avant le retour de l'API corromprait la mémoire lue."""
    src = ctypes.create_string_buffer(data, len(data))
    ent = ctypes.create_string_buffer(_DPAPI_ENTROPY, len(_DPAPI_ENTROPY))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(src, ctypes.POINTER(ctypes.c_char)))
    blob_ent = _DATA_BLOB(len(_DPAPI_ENTROPY), ctypes.cast(ent, ctypes.POINTER(ctypes.c_char)))
    blob_out = _DATA_BLOB()
    if not func(ctypes.byref(blob_in), None, ctypes.byref(blob_ent),
                None, None, 0, ctypes.byref(blob_out)):
        raise OSError(f"DPAPI a échoué (code {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        _kernel32.LocalFree(blob_out.pbData)

def _log_dir() -> Path:
    """Dossier du journal et des preferences.

    Surchargeable par GHISDIAG_LOG_DIR. Sert d'abord aux TESTS : importer
    main.py installe un handler de journal, si bien qu'une simple execution de
    la suite ecrivait ses faux incidents (« Fake GPU 9000 », JSON invalides
    volontaires, seuils aberrants) dans le journal REEL de l'utilisateur — et
    poussait dehors, par rotation, les lignes de vrai diagnostic. On a perdu du
    temps a demeler les deux le 28/07/2026.
    """
    forced = os.environ.get("GHISDIAG_LOG_DIR", "").strip()
    if forced:
        try:
            d = Path(forced).expanduser()
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            pass    # chemin invalide : on retombe sur l'emplacement standard
    return Path(os.path.expanduser("~")) / "AppData" / "Local" / "Ghisdiag"


LOG_DIR = _log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)
PREFS_FILE = LOG_DIR / "prefs.json"

_PREFS_MAX_BYTES = 16 * 1024

# Types et validateurs attendus par clé.
# Pour ajouter une préférence : déclarer ici, pas dans _load_prefs.
# `ai_provider` = fournisseur IA actif ; une clé API par fournisseur (chiffrée).
# `mistral_api_key` est conservé tel quel pour la migration des anciennes prefs.
_PREFS_SCHEMA: dict[str, type] = {
    "output_dir":        str,
    "auto_open_browser": bool,
    "ai_provider":       str,
    "anthropic_api_key": str,
    "mistral_api_key":   str,
    "openai_api_key":    str,
    "gemini_api_key":    str,
    "grok_api_key":      str,
}
_PREFS_VALIDATORS: dict[str, object] = {
    "output_dir": lambda v: len(v) < 4096,
    "ai_provider": lambda v: len(v) < 32,
    "anthropic_api_key": lambda v: len(v) < 4096,
    "mistral_api_key": lambda v: len(v) < 4096,
    "openai_api_key": lambda v: len(v) < 4096,
    "gemini_api_key": lambda v: len(v) < 4096,
    "grok_api_key": lambda v: len(v) < 4096,
}

# Clés sensibles qui doivent être chiffrées (une par fournisseur)
_ENCRYPTED_KEYS = {
    "anthropic_api_key",
    "mistral_api_key",
    "openai_api_key",
    "gemini_api_key",
    "grok_api_key",
}


def _encrypt_string(plaintext: str) -> Optional[str]:
    """Chiffre une clé API avec DPAPI. Retourne None si le chiffrement échoue :
    on ne stocke JAMAIS une clé en clair, mieux vaut ne pas la garder."""
    if not plaintext:
        return None
    if _HAS_DPAPI:
        try:
            blob = _dpapi(_crypt32.CryptProtectData, plaintext.encode("utf-8"))
            return _DPAPI_PREFIX + base64.b64encode(blob).decode("ascii")
        except OSError as e:
            logger.error("Chiffrement DPAPI impossible : %s", e)
    logger.error("Clé API non chiffrable : elle ne sera pas enregistrée")
    return None


def _decrypt_string(ciphertext: str) -> Optional[str]:
    """Déchiffre une clé API. None = illisible (à ignorer, jamais deviner)."""
    if ciphertext.startswith(_DPAPI_PREFIX):
        if not _HAS_DPAPI:
            return None
        try:
            blob = base64.b64decode(ciphertext[len(_DPAPI_PREFIX):])
            return _dpapi(_crypt32.CryptUnprotectData, blob).decode("utf-8")
        except (OSError, ValueError) as e:
            logger.warning("Déchiffrement DPAPI impossible : %s", e)
            return None
    # Format hérité (Fernet dérivé du nom machine+utilisateur) : relu pour migrer,
    # réécrit en DPAPI au prochain save_prefs.
    return _legacy_fernet_decrypt(ciphertext)


def _legacy_fernet_key() -> bytes:
    """Ancienne clé Fernet dérivée de la machine + username (schéma déprécié)."""
    try:
        machine_name = socket.gethostname()
    except Exception:
        machine_name = "unknown"
    username = os.environ.get("USERNAME", "unknown")
    seed = f"{machine_name}:{username}:ghisdiag".encode("utf-8")
    return base64.urlsafe_b64encode(hashlib.sha256(seed).digest())


def _legacy_fernet_decrypt(ciphertext: str) -> Optional[str]:
    """Déchiffre une clé à l'ancien format, uniquement pour la migration."""
    if not _HAS_CRYPTO:
        return None
    try:
        return Fernet(_legacy_fernet_key()).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # Chiffrée sur une autre machine, ou déjà en clair (très ancienne version).
        logger.warning("Clé héritée non déchiffrable, ignorée")
        return None
    except Exception as e:
        logger.warning("Erreur déchiffrement hérité : %s", e)
        return None


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
                # Déchiffrer les clés sensibles ; None = illisible, on l'ignore
                # (on ne charge jamais une valeur qu'on n'a pas su déchiffrer).
                if key in _ENCRYPTED_KEYS and isinstance(val, str):
                    val = _decrypt_string(val)
                    if val is None:
                        continue

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
                # Clé vide (jamais saisie ou éjectée), ou non chiffrable : on
                # n'écrit RIEN. Le fichier ne garde aucune trace d'un fournisseur
                # dont la clé a été retirée, ni jamais de clé en clair.
                enc = _encrypt_string(val)
                if enc:
                    prefs_to_save[key] = enc
            else:
                prefs_to_save[key] = val

        tmp = PREFS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs_to_save, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PREFS_FILE)
    except OSError as e:
        logger.warning("Impossible de sauvegarder prefs : %s", e)


def clear_api_keys(key_prefs) -> int:
    """Éjecte des clés API : les retire définitivement de prefs.json.

    Sert quand on laisse Ghisdiag installé sur un poste tiers : la clé ne doit
    plus être présente sur le disque, ni utilisable, une fois l'intervention
    terminée. Retourne le nombre de clés réellement retirées.
    """
    prefs = load_prefs()
    removed = 0
    for name in key_prefs:
        if name in _ENCRYPTED_KEYS and prefs.pop(name, ""):
            removed += 1
    save_prefs(prefs)
    return removed
