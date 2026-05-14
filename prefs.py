"""
PlanetDiag - Gestion des préférences utilisateur.
"""
import json
import logging
import os
from pathlib import Path

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
}
_PREFS_VALIDATORS: dict[str, object] = {
    "output_dir": lambda v: len(v) < 4096,
}


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
                validator = _PREFS_VALIDATORS.get(key)
                if validator is None or validator(val):
                    out[key] = val
        return out
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict):
    try:
        tmp = PREFS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(prefs, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(PREFS_FILE)
    except OSError as e:
        logger.warning("Impossible de sauvegarder prefs : %s", e)
