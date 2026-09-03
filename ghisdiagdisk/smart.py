r"""
GhisdiagDisk - lecture SMART via smartctl.exe (embarque dans tools\).

Lecons des campagnes, appliquees ici :
  - `--scan-open` rend le TYPE du peripherique (nvme/ata/scsi/sat) et il faut
    le repasser en `-d`, sinon smartctl rend un JSON vide sur certains NVMe
    (campagne du 01/09 : 2 machines sur 4 muettes pour cette seule raison) ;
  - les MESSAGES de smartctl expliquent pourquoi un disque reste muet : un
    JSON tout en null est sinon indistinguable d'un disque sans SMART. Le cas
    type est le controleur Intel RST en mode RAID (`IOCTL_STORAGE_QUERY_PROPERTY
    (NVMe) failed, Error=1`) : c'est Windows qui refuse, pas smartctl ;
  - derriere un controleur RST, smartctl voit DEUX FOIS le meme disque
    (/dev/sdb et /dev/csmi1,0) : deduplication par numero de serie ;
  - `rotation_rate` est un champ ATA, TOUJOURS absent en NVMe.

Aucune exception ne remonte : indisponibilite => champs None / liste vide.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from . import rawdisk

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Attributs ATA qui parlent d'un disque qui meurt. Les VALEURS BRUTES sont les
# seules comparables d'un passage a l'autre (delta historique, phase 3).
ATTRIBUTS_ATA = {
    5:   "secteurs_realloues",
    187: "erreurs_non_corrigeables_rapportees",
    196: "evenements_reallocation",
    197: "secteurs_en_attente",
    198: "secteurs_non_corrigeables_hors_ligne",
    199: "erreurs_crc_udma",
}


def chemin_smartctl() -> Optional[str]:
    candidats = [rawdisk.dossier_bundle() / "tools" / "smartctl.exe",
                 rawdisk.dossier_exe() / "tools" / "smartctl.exe",
                 rawdisk.dossier_exe() / "smartctl.exe"]
    for p in candidats:
        if p.is_file():
            return str(p)
    from shutil import which
    return which("smartctl")


def disponible() -> bool:
    return chemin_smartctl() is not None


def _run_json(args: list, timeout: float) -> Optional[dict]:
    exe = chemin_smartctl()
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, *args, "--json"], capture_output=True,
                              timeout=timeout, shell=False, creationflags=_NO_WINDOW)
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        if not out:
            return None
        data = json.loads(out)
        data["_code_sortie"] = proc.returncode
        return data
    except Exception:
        return None


def scanner() -> list:
    """Peripheriques vus par smartctl : [{nom, type}] - le type est conserve."""
    data = _run_json(["--scan-open"], timeout=60.0)
    out = []
    for d in (data or {}).get("devices") or []:
        if d.get("name"):
            out.append({"nom": d.get("name"), "type": d.get("type")})
    return out


def decoder(data: dict, nom: Optional[str] = None,
            typ: Optional[str] = None) -> dict:
    """Extraction pure des champs utiles d'un JSON `smartctl -a` (testable)."""
    data = data or {}
    msgs = [m.get("string") for m
            in ((data.get("smartctl") or {}).get("messages") or []) if m.get("string")]
    nvme = data.get("nvme_smart_health_information_log") or {}
    ata_attrs = {}
    for a in ((data.get("ata_smart_attributes") or {}).get("table") or []):
        nom_attr = ATTRIBUTS_ATA.get(a.get("id"))
        if nom_attr:
            raw = (a.get("raw") or {}).get("value")
            ata_attrs[nom_attr] = raw
    entree = {
        "peripherique":   nom,
        "type_smartctl":  typ,
        "protocole":      (data.get("device") or {}).get("protocol"),
        "modele":         data.get("model_name") or data.get("model_family"),
        "famille":        data.get("model_family"),
        "numero_serie":   data.get("serial_number"),
        "firmware":       data.get("firmware_version"),
        "smart_actif":    (data.get("smart_status") or {}).get("passed"),
        "temperature":    (data.get("temperature") or {}).get("current"),
        "heures":         (data.get("power_on_time") or {}).get("hours"),
        "cycles_demarrage": data.get("power_cycle_count"),
        "rotation_rate":  data.get("rotation_rate"),
        "format":         (data.get("form_factor") or {}).get("name"),
        "usure_nvme_pct": nvme.get("percentage_used"),
        "nvme": ({
            "avertissement_critique": nvme.get("critical_warning"),
            "erreurs_media":          nvme.get("media_errors"),
            "unites_lues":            nvme.get("data_units_read"),
            "unites_ecrites":         nvme.get("data_units_written"),
            "reserve_disponible_pct": nvme.get("available_spare"),
        } if nvme else None),
        "attributs_ata":  ata_attrs or None,
        "messages":       msgs or None,
        "code_sortie":    data.get("_code_sortie"),
    }
    entree["exploitable"] = bool(entree["modele"] or entree["numero_serie"])
    entree["muet_controleur_raid"] = any(
        "IOCTL_STORAGE_QUERY_PROPERTY" in m for m in msgs)
    return entree


def lire(nom: str, typ: Optional[str]) -> dict:
    args = ["-a"]
    if typ:
        args += ["-d", typ]
    data = _run_json(args + [nom], timeout=60.0)
    return decoder(data, nom, typ)


def projection_usure(entree: dict) -> Optional[dict]:
    """NVMe : usure declaree + heures de fonctionnement -> annees restantes.

    Quasi gratuit et c'est ce qui parle le plus au client. Lineaire, donc une
    PROJECTION, pas une promesse : le rapport doit le dire.
    """
    pct = (entree or {}).get("usure_nvme_pct")
    heures = (entree or {}).get("heures")
    if pct is None or not heures or pct <= 0:
        return None
    restant_h = heures * (100.0 - pct) / pct
    return {"usure_pct": pct, "heures": heures,
            "annees_restantes_estimees": round(restant_h / 8760.0, 1),
            "hypothese": "usage constant, projection lineaire"}


def deduper(entrees: list) -> list:
    """Un disque, une entree : derriere RST le meme disque apparait deux fois
    (sdX et csmiN,M). On garde la premiere exploitable par numero de serie."""
    vus, out = set(), []
    for e in entrees:
        cle = "".join(str(e.get("numero_serie") or "").split()).upper()
        if cle and cle in vus:
            continue
        if cle:
            vus.add(cle)
        out.append(e)
    return out


def inventaire() -> dict:
    """Toutes les entrees SMART de la machine, dedupliquees."""
    exe = chemin_smartctl()
    if not exe:
        return {"disponible": False, "entrees": []}
    entrees = [lire(d["nom"], d.get("type")) for d in scanner()[:MAX_PERIPHERIQUES]]
    return {"disponible": True, "chemin": exe, "entrees": deduper(entrees)}


MAX_PERIPHERIQUES = 12
