"""
Ghisdiag — Fiche machine (onglet Setup / MAJ, sous-onglet « Machine »).

Traduit la sortie brute de collectors/machine_info.ps1 en ce qu'affiche l'UI :
libellés, niveaux d'usage, points d'attention, texte à copier. Aucun Tk ici :
tout est testable sans fenêtre.

Règle : une valeur NON LUE n'est jamais affichée comme une valeur. Un TPM
illisible faute de droits n'est pas un TPM « absent », BitLocker illisible n'est
pas BitLocker « désactivé », et un compte Microsoft dont Windows n'a pas
l'adresse en cache reste un compte Microsoft.
"""

from datetime import datetime
from typing import Optional

NON_LU = "non lu"

# Seuils d'usage (%). Un volume de moins de 64 Go (clé USB) n'est jugé que sur
# son pourcentage : 3 Go libres sur une clé de 4 Go n'est pas une alerte.
RAM_WARN, RAM_CRIT = 85, 95
VOL_WARN, VOL_CRIT = 85, 95
VOL_FREE_WARN_GB, VOL_FREE_CRIT_GB = 15, 5
VOL_FREE_MIN_SIZE_GB = 64
UPTIME_WARN_H = 7 * 24
BATTERY_WEAR_WARN = 40

# Types de châssis SMBIOS (DMTF DSP0134, 7.4.1).
_CHASSIS_LAPTOP = {8, 9, 10, 11, 14, 30, 31, 32}
_CHASSIS_AIO = {13}
_CHASSIS_DESKTOP = {3, 4, 5, 6, 7, 15, 16, 24, 34, 35, 36}
_CHASSIS_SERVER = {17, 23, 28}

# SMBIOSMemoryType (DSP0134, 7.18.2).
_MEMORY_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 27: "LPDDR",
                 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5"}

# SoftwareLicensingProduct.LicenseStatus.
_LICENSE = {0: "Non activé", 1: "Activé", 2: "Période de grâce initiale",
            3: "Période de grâce (changement matériel)",
            4: "Période de grâce (non authentique)", 5: "Non activé (notification)",
            6: "Période de grâce étendue"}

# MSFT_PhysicalDisk.
_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
_BUS = {1: "SCSI", 2: "ATAPI", 3: "ATA", 6: "Fibre Channel", 7: "USB", 8: "RAID",
        9: "iSCSI", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 15: "Virtuel",
        16: "Espaces de stockage", 17: "NVMe"}
_HEALTH = {0: "Sain", 1: "Avertissement", 2: "Défaillant", 5: "Inconnu"}

# Pilote graphique générique de Windows = vrai pilote absent.
_BASIC_DISPLAY = ("microsoft basic display", "carte graphique de base microsoft")


# --- Utilitaires --------------------------------------------------------------

def as_list(v) -> list:
    """ConvertTo-Json (PS 5.1) déroule un tableau à un seul élément en scalaire."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def str_list(v) -> list:
    """Liste de chaînes non vides. ConvertTo-Json rend parfois un tableau vide
    sous la forme « {} » : il ne doit jamais s'afficher."""
    return [x for x in as_list(v) if isinstance(x, str) and x]


def _num(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt_size_gb(gb) -> str:
    g = _num(gb)
    if g is None:
        return "?"
    if g >= 1000:
        return f"{g / 1024:.1f} To".replace(".", ",")
    if g < 10 and not g.is_integer():
        return f"{g:.1f} Go".replace(".", ",")
    return f"{g:.0f} Go"


def fmt_date(s, with_time: bool = False) -> str:
    if not s:
        return NON_LU
    try:
        d = datetime.strptime(str(s), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(s)
    return d.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")


def fmt_uptime(hours) -> str:
    h = _num(hours)
    if h is None:
        return NON_LU
    if h < 1:
        return "moins d'une heure"
    if h < 24:
        return f"{h:.0f} h"
    days, rest = divmod(int(h), 24)
    return f"{days} j {rest} h"


def usage_level(pct, warn: float, crit: float) -> Optional[str]:
    p = _num(pct)
    if p is None:
        return None
    if p >= crit:
        return "crit"
    if p >= warn:
        return "warn"
    return "ok"


# --- Identité / Windows -------------------------------------------------------

def chassis_label(types, has_battery: bool = False) -> Optional[str]:
    t = {int(x) for x in as_list(types) if _num(x) is not None}
    if t & _CHASSIS_LAPTOP:
        return "Portable"
    if t & _CHASSIS_AIO:
        return "Tout-en-un"
    if t & _CHASSIS_SERVER:
        return "Serveur"
    if t & _CHASSIS_DESKTOP:
        return "Fixe"
    # Châssis non renseigné (fréquent sur les machines assemblées) : une
    # batterie suffit à trancher.
    return "Portable" if has_battery else None


def model_label(machine: dict) -> str:
    """Fabricant + nom commercial. Lenovo range le nom lisible dans
    product_version (Model = « 30C50053FR », Version = « ThinkStation P330 »)."""
    manuf = (machine.get("manufacturer") or "").strip()
    model = (machine.get("model") or "").strip()
    version = (machine.get("product_version") or "").strip()
    generic = {"", "none", "system version", "to be filled by o.e.m.", "default string"}
    if version.lower() not in generic and version.lower() != model.lower():
        label = f"{version} ({model})" if model else version
    else:
        label = model
    return f"{manuf} {label}".strip() or NON_LU


def join_label(machine: dict) -> str:
    if machine.get("part_of_domain"):
        return f"Domaine {machine.get('domain') or '?'}"
    parts = [f"Groupe de travail {machine.get('workgroup') or '?'}"]
    if machine.get("azure_ad_joined"):
        parts.append("joint à Entra ID")
    return " · ".join(parts)


def windows_label(win: dict) -> str:
    caption = (win.get("caption") or "Windows").replace("Microsoft ", "")
    ver = win.get("display_version")
    build = win.get("build")
    ubr = win.get("ubr")
    out = caption
    if ver:
        out += f" {ver}"
    if build:
        out += f" (build {build}{'.' + str(ubr) if ubr not in (None, '') else ''})"
    return out


def license_label(win: dict) -> str:
    status = win.get("license_status")
    if status is None:
        return NON_LU
    label = _LICENSE.get(int(status), f"Statut {status}")
    if win.get("license_channel"):
        label += f" · canal {win['license_channel']}"
    if win.get("oem_key_in_firmware"):
        label += " · clé OEM dans le BIOS"
    return label


# --- Processeur / mémoire -----------------------------------------------------

def memory_type_label(code) -> Optional[str]:
    n = _num(code)
    return _MEMORY_TYPES.get(int(n)) if n is not None else None


def memory_modules_label(mem: dict) -> str:
    """« 2 × 8 Go DDR4 2666 MHz · 2/4 emplacements »."""
    mods = [m for m in as_list(mem.get("modules")) if isinstance(m, dict)]
    if not mods:
        return NON_LU
    groups: dict = {}
    for m in mods:
        key = (m.get("capacity_gb"), memory_type_label(m.get("smbios_type")), m.get("speed_mhz"))
        groups[key] = groups.get(key, 0) + 1
    parts = []
    for (cap, typ, speed), n in groups.items():
        s = f"{n} × {fmt_size_gb(cap)}"
        if typ:
            s += f" {typ}"
        if speed:
            s += f" {speed} MHz"
        parts.append(s)
    out = " + ".join(parts)
    total = mem.get("slots_total")
    if total:
        out += f" · {len(mods)}/{total} emplacements"
    return out


# --- Stockage -----------------------------------------------------------------

def disk_label(d: dict) -> str:
    bus = _BUS.get(int(_num(d.get("bus_type")) or -1))
    media = _MEDIA.get(int(_num(d.get("media_type")) or -1))
    if bus == "NVMe":
        kind = "SSD NVMe"
    elif bus == "USB":
        kind = "USB"
    elif media:
        kind = f"{media} {bus}" if bus else media
    else:
        kind = bus or "type inconnu"
    return f"Disque {d.get('number', '?')} — {d.get('model') or '?'} · {kind} · {fmt_size_gb(d.get('size_gb'))}"


def disk_health(d: dict) -> tuple[str, str]:
    """(libellé, niveau) de l'état rapporté par Windows (pas un test SMART)."""
    code = _num(d.get("health"))
    if code is None:
        return NON_LU, "dim"
    label = _HEALTH.get(int(code), "Inconnu")
    level = {0: "ok", 1: "warn", 2: "crit"}.get(int(code), "dim")
    return label, level


def volume_level(v: dict) -> Optional[str]:
    level = usage_level(v.get("used_percent"), VOL_WARN, VOL_CRIT)
    size, free = _num(v.get("size_gb")), _num(v.get("free_gb"))
    if level is None or size is None or free is None or size < VOL_FREE_MIN_SIZE_GB:
        return level
    if free < VOL_FREE_CRIT_GB:
        return "crit"
    if free < VOL_FREE_WARN_GB and level == "ok":
        return "warn"
    return level


def bitlocker_label(v: dict, readable: bool) -> Optional[str]:
    status = v.get("bitlocker")
    if status is None:
        return None if readable else f"BitLocker {NON_LU}"
    return {0: None, 1: "BitLocker actif", 2: "BitLocker : verrouillé / inconnu"}.get(int(status))


def volume_label(v: dict) -> str:
    name = v.get("letter") or "?"
    if v.get("label"):
        name += f" {v['label']}"
    return (f"{name} · {v.get('filesystem') or '?'} · {fmt_size_gb(v.get('free_gb'))} libres "
            f"sur {fmt_size_gb(v.get('size_gb'))}")


def volumes_by_disk(data: dict) -> tuple[list, list]:
    """[(disque, [volumes])] dans l'ordre des disques, puis les volumes sans
    disque physique (lecteurs virtuels : Google Drive, VeraCrypt…)."""
    vols = [v for v in as_list(data.get("volumes")) if isinstance(v, dict)]
    out, used = [], set()
    for d in as_list(data.get("disks")):
        if not isinstance(d, dict):
            continue
        mine = [v for v in vols if v.get("disk_number") == d.get("number")]
        used.update(id(v) for v in mine)
        out.append((d, sorted(mine, key=lambda v: v.get("letter") or "")))
    orphans = sorted((v for v in vols if id(v) not in used), key=lambda v: v.get("letter") or "")
    return out, orphans


# --- Comptes ------------------------------------------------------------------

def account_kind(a: dict) -> str:
    src = a.get("principal_source") or ""
    ident = a.get("identity")
    if src == "MicrosoftAccount":
        return f"Compte Microsoft ({ident})" if ident else "Compte Microsoft"
    if src == "AzureAD":
        return f"Entra ID ({ident})" if ident else "Entra ID"
    return "Local"


def last_activity(a: dict) -> Optional[str]:
    """La plus récente de LastLogon et de l'utilisation du profil. LastLogon
    seul reste figé pour une session ouverte par compte Microsoft."""
    dates = [d for d in (a.get("last_logon"), a.get("profile_last_use")) if d]
    return max(dates) if dates else None


def visible_accounts(accounts) -> tuple[list, int]:
    """Masque les comptes intégrés DÉSACTIVÉS (Invité, DefaultAccount…), qui
    n'apportent rien. Un compte intégré ACTIF reste affiché : c'est une info."""
    shown, hidden = [], 0
    for a in as_list(accounts):
        if not isinstance(a, dict):
            continue
        if a.get("builtin") and not a.get("enabled"):
            hidden += 1
            continue
        shown.append(a)
    shown.sort(key=lambda a: (not a.get("enabled"), (a.get("name") or "").lower()))
    return shown, hidden


def profile_kind(p: dict) -> str:
    base = "Entra ID" if p.get("kind") == "entra" else "Domaine"
    return f"{base} ({p['identity']})" if p.get("identity") else base


# --- Sécurité / batterie / graphique -----------------------------------------

def tpm_label(sec: dict) -> tuple[str, str]:
    present = sec.get("tpm_present")
    if present is None:
        return NON_LU, "dim"
    if not present:
        return "absent ou désactivé dans le BIOS", "warn"
    v = sec.get("tpm_version")
    label = f"présent (version {v})" if v else "présent"
    if sec.get("tpm_enabled") is False:
        return label + ", désactivé", "warn"
    return label, "ok"


def secure_boot_label(sec: dict) -> tuple[str, str]:
    fw = (sec.get("firmware_type") or "").upper()
    sb = sec.get("secure_boot")
    if fw.startswith("LEGACY") or fw == "BIOS":
        return "sans objet (BIOS Legacy)", "warn"
    if sb is None:
        return NON_LU, "dim"
    return ("activé", "ok") if sb else ("désactivé", "warn")


def antivirus_label(sec: dict) -> tuple[str, str]:
    avs = [a for a in as_list(sec.get("antivirus")) if isinstance(a, dict)]
    if not avs:
        return NON_LU, "dim"
    active = [a.get("name") for a in avs if a.get("realtime")]
    if active:
        return ", ".join(active) + " (temps réel)", "ok"
    return "aucun en temps réel (" + ", ".join(a.get("name") or "?" for a in avs) + ")", "crit"


def battery_wear(bat: dict) -> Optional[int]:
    """Usure en % (capacité perdue). None si les capacités sont absentes ou
    incohérentes : certains firmwares rapportent 0, ou une pleine charge très
    au-dessus de la capacité d'origine."""
    design, full = _num(bat.get("design_mwh")), _num(bat.get("full_charge_mwh"))
    if not design or not full or design <= 0 or full <= 0:
        return None
    ratio = full / design
    if ratio > 1.2:
        return None
    return max(0, round((1 - ratio) * 100))


def is_basic_display(gpu: dict) -> bool:
    name = (gpu.get("name") or "").lower()
    return any(b in name for b in _BASIC_DISPLAY)


# --- Réseau -------------------------------------------------------------------

# Win32_NetworkAdapter.PhysicalAdapter se déclare vrai pour des cartes qui ne le
# sont pas (constaté : VirtualBox Host-Only, OpenVPN, PAN Bluetooth). Elles
# noient la vraie carte et affichent des IP sans rapport avec le réseau local.
_VIRTUAL_ADAPTER = ("virtualbox", "vmware", "hyper-v", "virtual", "vpn", "tap-",
                    "wireguard", "wintun", "zerotier", "tailscale", "bluetooth",
                    "loopback", "npcap")


def is_virtual_adapter(n: dict) -> bool:
    text = f"{n.get('description') or ''} {n.get('name') or ''}".lower()
    return any(k in text for k in _VIRTUAL_ADAPTER)


def physical_networks(data: dict) -> list:
    """Cartes réseau réelles, connectées d'abord."""
    nets = [n for n in as_list(data.get("network"))
            if isinstance(n, dict) and not is_virtual_adapter(n)]
    return sorted(nets, key=lambda n: not n.get("connected"))


# --- Points d'attention -------------------------------------------------------

def attention_points(data: dict) -> list[tuple[str, str]]:
    """[(niveau, texte)] — ce qu'un technicien doit voir avant d'intervenir.
    Triés : critiques d'abord."""
    pts: list[tuple[str, str]] = []
    win = data.get("windows") or {}
    sec = data.get("security") or {}
    mem = data.get("memory") or {}

    status = win.get("license_status")
    if status is not None and int(status) != 1:
        pts.append(("crit", f"Windows : {_LICENSE.get(int(status), 'non activé').lower()}"))

    for d in as_list(data.get("disks")):
        if isinstance(d, dict):
            label, level = disk_health(d)
            if level in ("warn", "crit"):
                pts.append((level, f"Disque {d.get('number')} ({d.get('model')}) : état « {label} » selon Windows"))

    for v in as_list(data.get("volumes")):
        if not isinstance(v, dict):
            continue
        level = volume_level(v)
        if level in ("warn", "crit"):
            pts.append((level, f"{v.get('letter')} presque plein : {fmt_size_gb(v.get('free_gb'))} libres "
                               f"({100 - int(_num(v.get('used_percent')) or 0)} %)"))
        if v.get("bitlocker") == 1:
            pts.append(("warn", f"BitLocker actif sur {v.get('letter')} : récupérer la clé de récupération "
                                "avant toute intervention sur le BIOS, le TPM ou le disque"))

    if usage_level(mem.get("used_percent"), RAM_WARN, RAM_CRIT) in ("warn", "crit"):
        pts.append(("warn", f"Mémoire utilisée à {mem.get('used_percent')} %"))

    av_label, av_level = antivirus_label(sec)
    if av_level == "crit":
        pts.append(("crit", f"Antivirus : {av_label}"))

    if win.get("reboot_pending"):
        pts.append(("warn", "Redémarrage en attente (mises à jour installées)"))
    up = _num(win.get("uptime_hours"))
    if up is not None and up >= UPTIME_WARN_H:
        pts.append(("warn", f"Pas redémarré depuis {fmt_uptime(up)} : redémarrer avant de diagnostiquer"))

    errs = [e for e in as_list(data.get("device_errors")) if isinstance(e, dict)]
    if errs:
        names = ", ".join((e.get("name") or "?") for e in errs[:3])
        more = f" (+{len(errs) - 3})" if len(errs) > 3 else ""
        pts.append(("warn", f"{len(errs)} périphérique(s) en erreur : {names}{more}"))

    for g in as_list(data.get("gpu")):
        if isinstance(g, dict) and is_basic_display(g):
            pts.append(("warn", "Pilote graphique manquant (carte graphique de base Microsoft)"))
            break

    bat = data.get("battery") or {}
    wear = battery_wear(bat) if bat.get("present") else None
    if wear is not None and wear >= BATTERY_WEAR_WARN:
        pts.append(("warn", f"Batterie usée à {wear} %"))

    for a in as_list(data.get("accounts")):
        if isinstance(a, dict) and a.get("builtin") and a.get("enabled") and a.get("is_admin"):
            pts.append(("info", f"Compte Administrateur intégré activé ({a.get('name')})"))

    order = {"crit": 0, "warn": 1, "info": 2}
    return sorted(pts, key=lambda p: order.get(p[0], 3))


# --- Texte à copier -----------------------------------------------------------

def summary_text(data: dict) -> str:
    """Fiche en texte brut : à coller dans un ticket ou une fiche d'intervention."""
    m = data.get("machine") or {}
    win = data.get("windows") or {}
    cpu = data.get("cpu") or {}
    mem = data.get("memory") or {}
    sec = data.get("security") or {}
    bat = data.get("battery") or {}
    L = []

    L.append(f"FICHE MACHINE — {m.get('name') or '?'} — relevé du {fmt_date(data.get('collected_at'), True)}")
    L.append("")
    L.append(f"Modèle        : {model_label(m)}")
    ch = chassis_label(m.get("chassis_types"), bool(bat.get("present")))
    if ch:
        L.append(f"Type          : {ch}")
    L.append(f"N° de série   : {m.get('serial') or NON_LU}")
    L.append(f"Réseau        : {join_label(m)}")
    L.append(f"BIOS          : {m.get('bios_version') or NON_LU} du {fmt_date(m.get('bios_date'))}")
    L.append(f"Windows       : {windows_label(win)} {win.get('architecture') or ''}".rstrip())
    L.append(f"Activation    : {license_label(win)}")
    L.append(f"Installé le   : {fmt_date(win.get('install_date'))}")
    L.append(f"Démarré depuis: {fmt_uptime(win.get('uptime_hours'))}")
    L.append("")
    L.append(f"Processeur    : {cpu.get('name') or NON_LU} — {cpu.get('cores') or '?'} cœurs / "
             f"{cpu.get('threads') or '?'} threads")
    L.append(f"Mémoire       : {fmt_size_gb(mem.get('total_gb'))} ({memory_modules_label(mem)}) — "
             f"utilisée à {mem.get('used_percent', '?')} %")
    for g in as_list(data.get("gpu")):
        if isinstance(g, dict):
            L.append(f"Graphique     : {g.get('name')} (pilote {g.get('driver_version') or '?'})")
    L.append("")
    L.append("Stockage :")
    groups, orphans = volumes_by_disk(data)
    readable = bool(sec.get("bitlocker_readable"))
    for d, vols in groups:
        L.append(f"  {disk_label(d)} — état : {disk_health(d)[0]}")
        for v in vols:
            bl = bitlocker_label(v, readable)
            L.append(f"    {volume_label(v)} — {v.get('used_percent', '?')} % utilisé" + (f" — {bl}" if bl else ""))
    for v in orphans:
        L.append(f"  {volume_label(v)} — {v.get('used_percent', '?')} % utilisé (hors disque physique)")
    L.append("")
    L.append("Comptes :")
    shown, hidden = visible_accounts(data.get("accounts"))
    for a in shown:
        flags = ["admin" if a.get("is_admin") else "standard",
                 "actif" if a.get("enabled") else "désactivé"]
        last = last_activity(a)
        L.append(f"  {a.get('name')} — {account_kind(a)} — {', '.join(flags)} — "
                 f"dernière activité : {fmt_date(last) if last else 'jamais'}")
    for p in as_list(data.get("other_profiles")):
        if isinstance(p, dict):
            L.append(f"  {p.get('profile_path')} — {profile_kind(p)} — "
                     f"dernière utilisation : {fmt_date(p.get('last_use'))}")
    if hidden:
        L.append(f"  ({hidden} compte(s) intégré(s) désactivé(s) non listé(s))")
    L.append("")
    L.append(f"Antivirus     : {antivirus_label(sec)[0]}")
    L.append(f"TPM           : {tpm_label(sec)[0]}")
    L.append(f"Secure Boot   : {secure_boot_label(sec)[0]} ({sec.get('firmware_type') or '?'})")
    if bat.get("present"):
        wear = battery_wear(bat)
        L.append(f"Batterie      : {bat.get('charge_percent', '?')} % — usure "
                 f"{str(wear) + ' %' if wear is not None else NON_LU}")
    net = [n for n in physical_networks(data) if n.get("connected")]
    for n in net:
        L.append(f"Réseau        : {n.get('name')} — {', '.join(str_list(n.get('ipv4'))) or 'sans IPv4'} — "
                 f"MAC {n.get('mac') or '?'}")
    pts = attention_points(data)
    if pts:
        L.append("")
        L.append("Points d'attention :")
        L.extend(f"  - {t}" for _, t in pts)
    return "\n".join(L)
