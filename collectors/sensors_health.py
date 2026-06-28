"""
Ghisdiag - Synthese << sante capteurs >> reutilisable.

Centralise le verdict << pourquoi la temperature CPU ne remonte pas >> pour
qu'il soit affiche dans l'app (moniteur temps reel + rapport), au lieu de vivre
seulement dans le script diagnose_sensors.py qu'il faut penser a lancer.

Deux profondeurs :
  - cpu_status(probe=False) : verdict instantane base sur des tests bon marche
    (elevation, presence de PawnIO, presence du backend LHM). Aucun
    sous-processus -> appelable a chaque rafraichissement du moniteur.
  - cpu_status(probe=True)  : lance en plus une lecture LHM -Once pour
    distinguer les cas fins (CPU recent non supporte, mapping a adapter,
    backend qui se fige). Plus couteux -> reserve au rapport / diagnostic.

Aucune exception ne remonte : toute indisponibilite se traduit par un verdict
(NO_BACKEND / UNKNOWN), jamais par une erreur cote appelant.
"""

import json
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# --- Codes de verdict (stables : utilisables comme cle d'affichage / de tri) ---
OK          = "ok"            # temperature CPU lue, tout va bien
NOT_ADMIN   = "not_admin"     # console non elevee -> acces MSR bloque
NO_PAWNIO   = "no_pawnio"     # driver PawnIO absent -> pas de lecture MSR
NO_BACKEND  = "no_backend"    # DLL/script LibreHardwareMonitor absents
LHM_STALL   = "lhm_stall"     # LHM se fige (timeout) -> CPU trop recent ?
LHM_ERROR   = "lhm_error"     # LHM renvoie une erreur explicite
UNMAPPED    = "unmapped"      # capteurs CPU presents mais temperature non reconnue
UNSUPPORTED = "unsupported"   # aucun capteur CPU expose par la DLL
UNKNOWN     = "unknown"       # cause indeterminee (verdict sans probe)

# Libelle court (affichable tel quel) + indice d'action, indexes par code.
_LABELS = {
    OK:          ("Temperature CPU OK", None),
    NOT_ADMIN:   ("Console non elevee",
                  "Relancer Ghisdiag en administrateur."),
    NO_PAWNIO:   ("PawnIO absent",
                  "Installer le driver PawnIO (auto au demarrage si eleve)."),
    NO_BACKEND:  ("Backend LHM absent",
                  "LibreHardwareMonitorLib.dll introuvable dans tools."),
    LHM_STALL:   ("Capteurs figes (CPU recent ?)",
                  "Tester une DLL LHM plus recente (update_backend)."),
    LHM_ERROR:   ("Erreur LibreHardwareMonitor", None),
    UNMAPPED:    ("Capteurs CPU non reconnus",
                  "Mapping a adapter pour ce CPU (voir diagnose_sensors)."),
    UNSUPPORTED: ("CPU non supporte par la DLL",
                  "Tester une DLL LHM plus recente (update_backend)."),
    UNKNOWN:     ("Temperature CPU indisponible",
                  "Lancer diagnose_sensors pour la cause exacte."),
}


def label_for(code: str) -> str:
    """Libelle court d'un code de verdict."""
    return _LABELS.get(code, _LABELS[UNKNOWN])[0]


def _environment() -> dict:
    """Etat bon marche de l'environnement capteurs (aucun sous-processus)."""
    admin: Optional[bool] = None
    pawnio_ok = False
    try:
        from collectors import pawnio
        admin = pawnio.is_admin()
        pawnio_ok = pawnio.pawnio_installed()
    except Exception:
        logger.debug("sensors_health : module pawnio indisponible", exc_info=True)

    backend_ok = False
    version: Optional[str] = None
    override = False
    try:
        from collectors import sensors, lhm_backend
        backend_ok = sensors.lhm_available()
        info = lhm_backend.info()
        version = info.get("version")
        override = bool(info.get("override"))
    except Exception:
        logger.debug("sensors_health : backend LHM indisponible", exc_info=True)

    return {
        "admin":             admin,
        "pawnio_installed":  pawnio_ok,
        "backend_available": backend_ok,
        "backend_version":   version,
        "backend_override":  override,
    }


def _probe_once(timeout: float = 15.0) -> Optional[dict]:
    """Lecture LHM -Once en conservant les reponses ok=false (pour le message
    d'erreur). Retourne le dict brut, ou None si DLL/script absents.

    Contrairement a sensors.read_once(), on garde les echecs explicites : c'est
    justement le message d'erreur qui permet de classer la cause (figeage,
    mapping, CPU non supporte...).
    """
    try:
        from collectors.sensors import _ps_args, _NO_WINDOW, lhm_available
    except Exception:
        return None
    if not lhm_available():
        return None
    try:
        proc = subprocess.run(
            _ps_args(["-Once"]),
            capture_output=True, timeout=timeout, shell=False,
            creationflags=_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if not out:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            return {"ok": False, "error": err or "(aucune sortie)"}
        line = [l for l in out.splitlines() if l.strip()][-1]
        return json.loads(line)
    except subprocess.TimeoutExpired:
        # Marqueur explicite : le mot "Timeout" est utilise par la classification.
        return {"ok": False, "error": f"Timeout {timeout:.0f}s (backend fige ?)"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _classify_cheap(env: dict) -> str:
    """Cause la plus probable a partir du seul environnement (sans probe)."""
    if env["admin"] is False:
        return NOT_ADMIN
    if not env["pawnio_installed"]:
        return NO_PAWNIO
    return UNKNOWN


def _classify_probed(env: dict, error: Optional[str], debug) -> str:
    """Cause apres lecture LHM ratee. Les causes d'environnement priment (les
    plus actionnables), puis on lit l'erreur / les capteurs bruts."""
    if env["admin"] is False:
        return NOT_ADMIN
    if not env["pawnio_installed"]:
        return NO_PAWNIO
    if error:
        e = str(error)
        if "Timeout" in e or "timed out" in e or "fige" in e:
            return LHM_STALL
        return LHM_ERROR
    if debug:
        return UNMAPPED
    return UNSUPPORTED


def cpu_status(probe: bool = False) -> dict:
    """Verdict structure sur la disponibilite de la temperature CPU.

    Retourne un dict : code, ok, label, hint, cpu_temp, error, probed, plus
    l'etat d'environnement (admin, pawnio_installed, backend_available,
    backend_version, backend_override).
    """
    env = _environment()
    code = UNKNOWN
    cpu_temp = None
    error = None
    probed = False

    if not env["backend_available"]:
        code = NO_BACKEND
    elif probe:
        probed = True
        sample = _probe_once()
        if sample is None:
            code = NO_BACKEND
        elif sample.get("ok") and sample.get("cpu_ref") is not None:
            code = OK
            cpu_temp = sample.get("cpu_ref")
        else:
            error = sample.get("error") if not sample.get("ok") else None
            code = _classify_probed(env, error, sample.get("debug_sensors"))
    else:
        code = _classify_cheap(env)

    label, hint = _LABELS.get(code, _LABELS[UNKNOWN])
    result = {
        "code":     code,
        "ok":       code == OK,
        "label":    label,
        "hint":     hint,
        "cpu_temp": cpu_temp,
        "error":    error,
        "probed":   probed,
    }
    result.update(env)
    return result


def collect() -> dict:
    """Entree << collecteur >> pour le rapport : verdict CPU complet (avec
    probe) + couverture des sources maison (GPU NVML, disques smartctl).

    Toujours _status=ok : un echec de lecture est encode dans `code`, pas dans
    un statut d'erreur de collecteur."""
    status = cpu_status(probe=True)

    gpus = []
    try:
        from collectors import gpu
        gpus = gpu.read()
    except Exception:
        logger.debug("sensors_health.collect : GPU NVML indisponible", exc_info=True)

    disks = []
    try:
        from collectors import disk_temp
        disks = disk_temp.read_all()
    except Exception:
        logger.debug("sensors_health.collect : disques smartctl indisponibles", exc_info=True)

    status["gpus"] = gpus
    status["disks"] = disks
    status["_status"] = "ok"
    return status
