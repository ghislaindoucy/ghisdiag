r"""
Ghisdiag - Sonde de terrain WinPE pour le chantier GhisdiagDisk (voir ROADMAP.md,
section "Chantiers prepares" > GhisdiagDisk).

Cette sonde ne teste RIEN du futur module : elle repond aux questions bloquantes
de la phase 0, celles dont depend toute l'architecture. Tant qu'elles n'ont pas
de reponse mesuree sur une vraie machine bootee en WinPE, rien ne doit etre
developpe.

Les 6 questions :
  1. tkinter s'affiche-t-il en WinPE ? (sinon : mode console obligatoire)
  2. smartctl.exe repond-il en WinPE, et sur quels controleurs ?
  3. l'acces disque brut \\.\PhysicalDriveN fonctionne-t-il ?
  4. la lecture NON BUFFERISEE alignee secteur passe-t-elle ? (le module en depend)
  5. le n0 de serie du disque est-il lisible ? (seule cle d'identite valable :
     en WinPE le hostname est MINWINPC, il n'identifie rien)
  6. peut-on ecrire le rapport a cote de l'exe (la cle USB) ? En WinPE X: est
     un disque RAM : ce qui y est ecrit disparait a l'extinction.

STRICTEMENT EN LECTURE SEULE sur les disques : la sonde ouvre les peripheriques
en GENERIC_READ et n'ecrit que son propre rapport, a cote d'elle-meme.

Le rapport est ecrit AU FIL DE L'EAU (une ligne par verification, flush immediat)
et pas a la fin : si tkinter fait tomber le process en WinPE - c'est justement le
risque qu'on mesure - tout ce qui precede reste sur la cle. Meme principe que le
checkpoint prevu pour les balayages longs.

Usage en WinPE : lancer WinPEProbe.exe depuis la cle (Python n'existe pas en PE).
Usage sur un Windows normal : py atelier_winpe_probe.py
"""

import ctypes
import json
import os
import platform
import socket
import subprocess
import sys
import time
import traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

def _dossier_rapport() -> Path:
    r"""Dossier OU ECRIRE le rapport : a cote de l'exe, jamais dans le bundle.

    Compile en onedir avec PyInstaller 6, tout le bundle atterrit dans
    `_internal\` et `__file__` pointe DEDANS. Un rapport ecrit la serait
    invisible pour le technicien, qui regarde a cote de WinPEProbe.exe.
    `sys.executable` est le seul repere fiable une fois gele.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.resolve()


def _dossier_bundle() -> Path:
    r"""Dossier OU LIRE les ressources embarquees (tools\smartctl.exe).

    Gele : `_internal\` (= sys._MEIPASS). En sources : le dossier du script.
    C'est l'inverse de _dossier_rapport(), et les confondre est precisement
    l'erreur qui rend la sonde muette en atelier.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.resolve()


_ROOT   = _dossier_rapport()
_BUNDLE = _dossier_bundle()
sys.path.insert(0, str(_BUNDLE))

# Volume lu pour la mesure de debit. Assez pour degager une tendance, assez court
# pour ne pas fatiguer un disque deja malade (cf. l'avertissement metier du
# ROADMAP : balayer un disque mourant peut l'achever).
_THROUGHPUT_BYTES = 64 * 1024 * 1024
_BLOCK_BYTES      = 1024 * 1024

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --- Acces Win32 -------------------------------------------------------------

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ          = 0x80000000
FILE_SHARE_READ       = 0x00000001
FILE_SHARE_WRITE      = 0x00000002
OPEN_EXISTING         = 3
FILE_FLAG_NO_BUFFERING = 0x20000000
INVALID_HANDLE_VALUE  = ctypes.c_void_p(-1).value

MEM_COMMIT_RESERVE = 0x3000
MEM_RELEASE        = 0x8000
PAGE_READWRITE     = 0x04

IOCTL_DISK_GET_LENGTH_INFO   = 0x0007405C
IOCTL_DISK_GET_DRIVE_GEOMETRY = 0x00070000
IOCTL_STORAGE_QUERY_PROPERTY  = 0x002D1400
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000

# Sans argtypes explicites, ctypes tronque les HANDLE 64 bits en int 32 bits.
_k32.CreateFileW.restype  = wintypes.HANDLE
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                             ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                             wintypes.HANDLE]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.ReadFile.argtypes    = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
_k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong,
                                  ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
_k32.VirtualAlloc.restype  = ctypes.c_void_p
_k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                              wintypes.DWORD, wintypes.DWORD]
_k32.VirtualFree.argtypes  = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]


class _Drive:
    r"""Ouvre \\.\PhysicalDriveN en LECTURE SEULE. Referme toujours."""

    def __init__(self, index: int = None, no_buffering: bool = False,
                 chemin: str = None):
        flags = FILE_FLAG_NO_BUFFERING if no_buffering else 0
        cible = chemin or f"\\\\.\\PhysicalDrive{index}"
        self.handle = _k32.CreateFileW(
            cible, GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
        if self.handle == INVALID_HANDLE_VALUE or not self.handle:
            raise OSError(ctypes.get_last_error(), f"CreateFileW {cible}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        _k32.CloseHandle(self.handle)

    def ioctl(self, code: int, out_size: int) -> bytes:
        buf = ctypes.create_string_buffer(out_size)
        got = wintypes.DWORD()
        ok = _k32.DeviceIoControl(self.handle, code, None, 0,
                                  buf, out_size, ctypes.byref(got), None)
        if not ok:
            raise OSError(ctypes.get_last_error(), f"DeviceIoControl 0x{code:08X}")
        return buf.raw[:got.value]

    def ioctl_in(self, code: int, payload: bytes, out_size: int) -> bytes:
        inbuf = ctypes.create_string_buffer(payload, len(payload))
        buf   = ctypes.create_string_buffer(out_size)
        got   = wintypes.DWORD()
        ok = _k32.DeviceIoControl(self.handle, code, inbuf, len(payload),
                                  buf, out_size, ctypes.byref(got), None)
        if not ok:
            raise OSError(ctypes.get_last_error(), f"DeviceIoControl 0x{code:08X}")
        return buf.raw[:got.value]

    def seek(self, offset: int):
        newpos = ctypes.c_longlong()
        if not _k32.SetFilePointerEx(self.handle, offset, ctypes.byref(newpos), 0):
            raise OSError(ctypes.get_last_error(), "SetFilePointerEx")

    def read_into(self, ptr, size: int) -> int:
        got = wintypes.DWORD()
        if not _k32.ReadFile(self.handle, ptr, size, ctypes.byref(got), None):
            raise OSError(ctypes.get_last_error(), "ReadFile")
        return got.value


def _aligned_buffer(size: int):
    """Tampon aligne page (4096) : exige par FILE_FLAG_NO_BUFFERING.

    create_string_buffer ne garantit aucun alignement ; VirtualAlloc si.
    """
    ptr = _k32.VirtualAlloc(None, size, MEM_COMMIT_RESERVE, PAGE_READWRITE)
    if not ptr:
        raise OSError(ctypes.get_last_error(), "VirtualAlloc")
    return ptr


# --- Verifications -----------------------------------------------------------

def check_contexte() -> dict:
    """Ou tourne-t-on, et avec quels droits."""
    winpe = False
    pe_marker = None
    try:
        import winreg
        try:
            winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SYSTEM\CurrentControlSet\Control\MiniNT").Close()
            winpe, pe_marker = True, r"HKLM\SYSTEM\CurrentControlSet\Control\MiniNT"
        except OSError:
            pass
    except Exception:
        pass

    lettres = []
    try:
        mask = _k32.GetLogicalDrives()
        lettres = [chr(65 + i) + ":" for i in range(26) if mask & (1 << i)]
    except Exception:
        pass

    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        admin = False

    return {
        "hostname":        socket.gethostname(),
        "hostname_inutile": socket.gethostname().upper() in ("MINWINPC", ""),
        "windows":         platform.platform(),
        "winpe_detecte":   winpe,
        "winpe_marqueur":  pe_marker,
        "admin":           admin,
        "gele_pyinstaller": bool(getattr(sys, "frozen", False)),
        "python":          sys.version.split()[0],
        "lettres_lecteur": lettres,
        "dossier_sonde":   str(_ROOT),
    }


def check_ecriture_rapport() -> dict:
    """Peut-on ecrire a cote de la sonde (= sur la cle USB) ?

    En WinPE, X: est un disque RAM : un rapport ecrit la disparait a l'extinction.
    Si cette verification echoue, il faudra demander un dossier de sortie au
    technicien au lancement.
    """
    temoin = _ROOT / ".ghisdiag_probe_write_test"
    try:
        temoin.write_text("ok", encoding="utf-8")
        temoin.unlink()
        sur_ramdisk = str(_ROOT).upper().startswith("X:")
        return {"inscriptible": True, "chemin": str(_ROOT),
                "probablement_ramdisk_winpe": sur_ramdisk,
                "note": ("ATTENTION : dossier sur X:, le disque RAM de WinPE. "
                         "Le rapport sera perdu a l'extinction.") if sur_ramdisk
                        else "Dossier persistant (cle USB ou disque local)."}
    except OSError as exc:
        return {"inscriptible": False, "chemin": str(_ROOT), "erreur": str(exc)}


def check_disques_enumeration() -> dict:
    r"""Quels \\.\PhysicalDriveN s'ouvrent, avec quelle taille et quel secteur.

    C'est ainsi que le module devra enumerer : par index, jamais par lettre de
    lecteur (en WinPE les volumes ne sont pas forcement montes).
    """
    trouves = []
    for i in range(16):
        try:
            with _Drive(i) as d:
                taille = int.from_bytes(d.ioctl(IOCTL_DISK_GET_LENGTH_INFO, 8),
                                        "little")
                geo = d.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY, 24)
                secteur = int.from_bytes(geo[20:24], "little") if len(geo) >= 24 else None
                trouves.append({
                    "index":            i,
                    "peripherique":     f"\\\\.\\PhysicalDrive{i}",
                    "taille_octets":    taille,
                    "taille_go":        round(taille / 1e9, 1),
                    "octets_par_secteur": secteur,
                })
        except OSError:
            continue
    return {"nb_disques": len(trouves), "disques": trouves}


# STORAGE_BUS_TYPE — sert directement aux regles d'exclusion du futur module
# (USB ecarte, RAID a dedupliquer).
_BUS_TYPES = {
    0: "inconnu", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "IEEE1394", 5: "SSA",
    6: "FibreChannel", 7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA",
    12: "SD", 13: "MMC", 14: "virtuel", 15: "virtuel-fichier", 16: "StorageSpaces",
    17: "NVMe", 18: "SCM", 19: "UFS",
}


def _nettoyer_serie(brut) -> tuple:
    """Rend un n0 de serie utilisable comme NOM DE FICHIER, + un drapeau.

    Constat du 08/08 : l'IOCTL rend pour une cle USB Kingston un serie contenant
    des octets de controle non imprimables. Utilise tel quel dans le nom du
    rapport, ca produit un fichier illisible ou un echec d'ecriture. Le module
    devra assainir avant d'indexer quoi que ce soit.
    """
    if not brut:
        return None, False
    propre = "".join(c if (c.isalnum() or c in "-_") else "_"
                     for c in str(brut)).strip("_")
    return (propre or None), (propre != str(brut))


def _serie_via_ioctl(index: int) -> dict:
    """Identite du disque via IOCTL_STORAGE_QUERY_PROPERTY (StorageDeviceProperty).

    STORAGE_PROPERTY_QUERY : PropertyId=0, QueryType=0, AdditionalParameters[1].

    ATTENTION AUX OFFSETS — c'est le piege de cette structure, et la sonde s'y
    est fait prendre le 08/08 : les champs texte etaient decales de 4 octets, si
    bien que la REVISION DE FIRMWARE etait rendue comme numero de serie. Le
    defaut etait invisible (le champ etait rempli, juste faux) et aurait fait
    collisionner les rapports de deux disques de meme modele et meme firmware.

    STORAGE_DEVICE_DESCRIPTOR :
        0  DWORD  Version
        4  DWORD  Size
        8  BYTE   DeviceType
        9  BYTE   DeviceTypeModifier
        10 BYTE   RemovableMedia
        11 BYTE   CommandQueueing
        12 DWORD  VendorIdOffset
        16 DWORD  ProductIdOffset
        20 DWORD  ProductRevisionOffset
        24 DWORD  SerialNumberOffset
        28 DWORD  BusType
    Les quatre offsets pointent vers des chaines ANSI terminees par 0, comptees
    depuis le DEBUT du descripteur.
    """
    query = (0).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\x00" * 4
    with _Drive(index) as d:
        raw = d.ioctl_in(IOCTL_STORAGE_QUERY_PROPERTY, query, 1024)

    def _chaine(offset_pos: int):
        if len(raw) < offset_pos + 4:
            return None
        off = int.from_bytes(raw[offset_pos:offset_pos + 4], "little")
        if not off or off >= len(raw):
            return None
        fin = raw.find(b"\x00", off)
        return raw[off:fin if fin != -1 else len(raw)].decode("latin-1").strip() or None

    def _dword(pos: int):
        return (int.from_bytes(raw[pos:pos + 4], "little")
                if len(raw) >= pos + 4 else None)

    bus = _dword(28)
    return {
        "fabricant":    _chaine(12),
        "modele":       _chaine(16),
        "revision":     _chaine(20),
        "numero_serie": _chaine(24),
        "amovible":     bool(raw[10]) if len(raw) > 10 else None,
        "bus":          _BUS_TYPES.get(bus, f"code {bus}") if bus is not None else None,
    }


def check_identite_disques() -> dict:
    """L'identite du rapport reposera sur le n0 de serie du disque.

    En WinPE le hostname vaut MINWINPC : il n'identifie rien. Si le serie ne
    remonte pas ici, toute l'indexation des rapports sur la cle est a revoir.
    """
    out = []
    for i in range(16):
        try:
            info = _serie_via_ioctl(i)
        except OSError as exc:
            continue
        except Exception as exc:
            out.append({"index": i, "erreur": f"{type(exc).__name__}: {exc}"})
            continue
        info["index"] = i
        propre, assaini = _nettoyer_serie(info.get("numero_serie"))
        info["serie_nettoyee"] = propre
        info["serie_avait_caracteres_invalides"] = assaini
        info["serie_utilisable_comme_cle"] = bool(propre)
        out.append(info)
    return {"disques": out,
            "tous_identifiables": bool(out) and all(
                d.get("serie_utilisable_comme_cle") for d in out)}


def check_lecture_brute() -> dict:
    r"""Lecture bufferisee alignee secteur sur le premier disque ouvrable.

    Sur \\.\PhysicalDriveN, offset ET taille doivent etre multiples du secteur,
    meme sans FILE_FLAG_NO_BUFFERING.
    """
    for i in range(16):
        try:
            with _Drive(i) as d:
                geo = d.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY, 24)
                secteur = int.from_bytes(geo[20:24], "little") or 512
                taille  = max(4096, secteur)
                buf = ctypes.create_string_buffer(taille)
                d.seek(0)
                lus = d.read_into(buf, taille)
                debut = buf.raw[:16].hex(" ")
                # Signature MBR : 0x55AA en fin de premier secteur.
                mbr = buf.raw[secteur - 2:secteur] == b"\x55\xaa"
                return {"index_teste": i, "octets_demandes": taille,
                        "octets_lus": lus, "16_premiers_octets": debut,
                        "signature_mbr_gpt_vue": mbr,
                        "verdict": "lecture brute OK" if lus == taille
                                   else "lecture partielle"}
        except OSError:
            continue
    return {"verdict": "aucun disque ouvrable en lecture brute"}


def check_lecture_non_bufferisee() -> dict:
    """FILE_FLAG_NO_BUFFERING + tampon aligne page.

    C'est le mode que le module utilisera pour mesurer le disque et non le cache
    Windows. Si ce chemin echoue, les mesures de debit et de latence ne veulent
    plus rien dire.
    """
    for i in range(16):
        ptr = None
        try:
            with _Drive(i, no_buffering=True) as d:
                geo = d.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY, 24)
                secteur = int.from_bytes(geo[20:24], "little") or 512
                taille  = max(4096, secteur)
                ptr = _aligned_buffer(taille)
                d.seek(0)
                lus = d.read_into(ptr, taille)
                return {"index_teste": i, "octets_lus": lus,
                        "tampon_aligne_page": (ptr % 4096) == 0,
                        "verdict": "NO_BUFFERING OK" if lus == taille
                                   else "lecture partielle"}
        except OSError as exc:
            derniere = str(exc)
            continue
        finally:
            if ptr:
                _k32.VirtualFree(ptr, 0, MEM_RELEASE)
    return {"verdict": "NO_BUFFERING indisponible sur tous les disques"}


def check_debit_et_latence() -> dict:
    """Mini-mesure : 64 Mio sequentiels, temps par bloc de 1 Mio.

    Prouve que la mecanique de mesure du futur module tient debout en WinPE :
    un debit coherent, et surtout un temps MAXIMUM par bloc exploitable - c'est
    lui qui revelera les secteurs mourants, pas la moyenne.
    """
    for i in range(16):
        ptr = None
        try:
            with _Drive(i, no_buffering=True) as d:
                ptr = _aligned_buffer(_BLOCK_BYTES)
                d.seek(0)
                blocs, total = [], 0
                depart = time.perf_counter()
                while total < _THROUGHPUT_BYTES:
                    t0 = time.perf_counter()
                    lus = d.read_into(ptr, _BLOCK_BYTES)
                    blocs.append((time.perf_counter() - t0) * 1000.0)
                    if lus < _BLOCK_BYTES:
                        break
                    total += lus
                duree = time.perf_counter() - depart
                blocs.sort()
                return {
                    "index_teste":     i,
                    "octets_lus":      total,
                    "duree_sec":       round(duree, 2),
                    "debit_mo_s":      round(total / 1e6 / duree, 1) if duree else None,
                    "bloc_median_ms":  round(blocs[len(blocs) // 2], 2) if blocs else None,
                    "bloc_p99_ms":     round(blocs[int(len(blocs) * 0.99) - 1], 2) if blocs else None,
                    "bloc_max_ms":     round(blocs[-1], 2) if blocs else None,
                    "note": "bloc_max_ms est l'indicateur cle du futur balayage : "
                            "un bloc tres lent = secteur en train de mourir.",
                }
        except OSError:
            continue
        finally:
            if ptr:
                _k32.VirtualFree(ptr, 0, MEM_RELEASE)
    return {"verdict": "mesure impossible (aucun disque ouvrable)"}


def check_smartctl() -> dict:
    """smartctl.exe repond-il en WinPE, et sur quels controleurs ?

    On cherche le binaire a cote de la sonde (tools\\ ou dossier courant) : en
    WinPE il n'y a evidemment aucune installation systeme.
    """
    candidats = [_BUNDLE / "tools" / "smartctl.exe",   # gele : _internal\tools
                 _ROOT / "tools" / "smartctl.exe",     # a cote de l'exe / du script
                 _ROOT / "smartctl.exe"]
    exe = next((str(p) for p in candidats if p.is_file()), None)
    if not exe:
        return {"trouve": False,
                "cherche_dans": [str(p) for p in candidats],
                "verdict": "smartctl.exe absent - copier tools\\smartctl.exe "
                           "a cote de la sonde avant de tester en WinPE"}

    def _run(args, timeout=60):
        r = subprocess.run([exe] + args, capture_output=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        return r.returncode, r.stdout.decode("utf-8", "replace")

    out = {"trouve": True, "chemin": exe}
    try:
        _, version = _run(["--version"], timeout=20)
        out["version"] = version.splitlines()[0] if version else None
    except Exception as exc:
        out["version_erreur"] = f"{type(exc).__name__}: {exc}"

    try:
        _, scan = _run(["--scan-open", "--json"], timeout=60)
        devices = json.loads(scan).get("devices", []) if scan.strip() else []
        # On garde le TYPE, pas seulement le nom. Campagne du 01/09 : sur 2 des
        # 4 machines, `smartctl -a <dev>` sans -d rendait un JSON vide pour le
        # disque systeme NVMe alors que --scan-open l'avait bien identifie. Le
        # type est la moitie de la reponse, et on le jetait.
        out["peripheriques_vus"] = [{"nom": d.get("name"), "type": d.get("type")}
                                    for d in devices]
    except Exception as exc:
        out["scan_erreur"] = f"{type(exc).__name__}: {exc}"
        devices = []

    details = []
    for dev in devices[:8]:
        nom = dev.get("name")
        typ = dev.get("type")
        try:
            args = ["-a", "--json"]
            if typ:
                args += ["-d", typ]
            code, txt = _run(args + [nom], timeout=60)
            d = json.loads(txt) if txt.strip() else {}
            # Les messages de smartctl expliquent POURQUOI un disque reste
            # muet. Sans eux, un JSON tout en null est indistinguable d'un
            # disque sans SMART.
            msgs = [m.get("string") for m
                    in ((d.get("smartctl") or {}).get("messages") or [])]
            entree = {
                "peripherique": nom,
                "type_smartctl": typ,
                "modele":       (d.get("model_name") or d.get("model_family")),
                "numero_serie": d.get("serial_number"),
                "smart_actif":  (d.get("smart_status") or {}).get("passed"),
                "temperature":  (d.get("temperature") or {}).get("current"),
                "heures":       (d.get("power_on_time") or {}).get("hours"),
                # Discriminant mecanique/SSD : 0 = SSD, sinon tours/minute.
                # ATTENTION : champ ATA, donc TOUJOURS absent en NVMe (verifie
                # sur 4 NVMe le 01/09). Voir _type_support() pour la regle
                # complete, qui traite le NVMe a part.
                "rotation_rate": d.get("rotation_rate"),
                "format":        (d.get("form_factor") or {}).get("name"),
                "cycles_demarrage": (d.get("power_cycle_count")),
                "usure_nvme_pct": (d.get("nvme_smart_health_information_log") or {})
                                  .get("percentage_used"),
                "code_sortie":  code,
            }
            if msgs:
                entree["messages_smartctl"] = msgs
            entree["exploitable"] = bool(entree["modele"] or entree["numero_serie"])
            details.append(entree)
        except Exception as exc:
            details.append({"peripherique": nom, "type_smartctl": typ,
                            "exploitable": False,
                            "erreur": f"{type(exc).__name__}: {exc}"})

    out["details"] = details
    utiles = [x for x in details if x.get("exploitable")]
    out["nb_exploitables"] = len(utiles)
    out["nb_muets"] = len(details) - len(utiles)
    # Un `details` non vide ne prouve RIEN : le 01/09, deux machines rendaient
    # des entrees entierement nulles et le verdict annoncait quand meme
    # << operationnel >>. On compte les disques reellement exploitables.
    if not details:
        out["verdict"] = "smartctl present mais aucun disque interroge"
    elif not utiles:
        out["verdict"] = ("smartctl repond mais AUCUN disque exploitable - "
                          "pas de SMART sur cette machine")
    elif out["nb_muets"]:
        out["verdict"] = (f"smartctl operationnel sur {len(utiles)} disque(s), "
                          f"muet sur {out['nb_muets']}")
    else:
        out["verdict"] = "smartctl operationnel"
    return out


def check_tkinter() -> dict:
    """LA question qui decide de l'UX : tkinter s'affiche-t-il en WinPE ?

    Executee EN DERNIER et rapport deja ecrit : si le process tombe ici, tout ce
    qui precede est deja sur la cle. Si cette verification echoue, le module se
    fera en mode console - ce n'est pas redhibitoire, mais ca change l'UI.
    """
    import tkinter as tk

    res = {"import_ok": True, "version_tcl": None, "fenetre_ok": False}
    root = None
    try:
        root = tk.Tk()
        res["version_tcl"] = str(root.tk.call("info", "patchlevel"))
        root.title("Ghisdiag - sonde WinPE")
        root.geometry("420x160")
        tk.Label(root, text="Si tu lis ceci, tkinter fonctionne en WinPE.",
                 font=("Segoe UI", 10)).pack(expand=True)
        tk.Label(root, text="La fenetre se ferme seule dans 5 secondes.",
                 font=("Segoe UI", 9)).pack()
        root.update()                       # force un vrai rendu
        res["ecran"] = f"{root.winfo_screenwidth()}x{root.winfo_screenheight()}"
        res["fenetre_ok"] = True
        root.after(5000, root.destroy)
        root.mainloop()                     # prouve que la boucle tient
        res["mainloop_ok"] = True
    finally:
        try:
            if root:
                root.destroy()
        except Exception:
            pass
    res["verdict"] = ("tkinter utilisable - UI graphique possible"
                      if res["fenetre_ok"] else "tkinter KO - prevoir mode console")
    return res


def check_disque_de_la_sonde() -> dict:
    r"""Sur QUEL PhysicalDriveN tourne la sonde elle-meme ?

    Garde-fou n0 3 du ROADMAP, et il n'avait jamais ete prototype. En WinPE on
    a boote sur la cle du technicien : elle apparait dans la liste des disques
    et ne doit JAMAIS etre selectionnable. Sans cette reponse, la regle
    d'exclusion n'est qu'une intention.

    IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS sur \\.\X: rend le ou les disques
    physiques qui portent le volume (plusieurs si espaces de stockage / RAID).
    """
    lettre = str(_ROOT)[:2]
    if len(lettre) != 2 or lettre[1] != ":":
        return {"verdict": "dossier de la sonde sans lettre de lecteur (UNC ?)",
                "dossier": str(_ROOT)}
    with _Drive(chemin=f"\\\\.\\{lettre}") as v:
        raw = v.ioctl(IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, 1024)
    nb = int.from_bytes(raw[0:4], "little")
    disques = []
    for i in range(nb):
        # VOLUME_DISK_EXTENTS : NumberOfDiskExtents(4) + bourrage(4), puis les
        # DISK_EXTENT de 24 octets { DiskNumber(4), bourrage(4), Debut(8), Long(8) }.
        base = 8 + i * 24
        if len(raw) >= base + 4:
            disques.append(int.from_bytes(raw[base:base + 4], "little"))
    return {"lettre": lettre, "dossier": str(_ROOT),
            "disques_physiques": disques,
            "a_exclure_des_tests": disques,
            "verdict": (f"la sonde tourne depuis PhysicalDrive{disques}"
                        if disques else "disque porteur non identifie")}


def _secteurs_logique_physique(index: int) -> dict:
    """Secteur LOGIQUE et PHYSIQUE (StorageAccessAlignmentProperty).

    Un disque 512e (512 logique / 4096 physique) se lit par 512 mais travaille
    par 4096 : aligner le balayage sur le secteur physique evite de payer un
    cycle lecture-modification-ecriture invisible. Le module en aura besoin.
    """
    query = (6).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\x00" * 4
    with _Drive(index) as d:
        raw = d.ioctl_in(IOCTL_STORAGE_QUERY_PROPERTY, query, 64)

    def _dw(pos):
        return (int.from_bytes(raw[pos:pos + 4], "little")
                if len(raw) >= pos + 4 else None)

    return {"octets_par_secteur_logique":  _dw(16),
            "octets_par_secteur_physique": _dw(20),
            "decalage_alignement":         _dw(24)}


_GPT_TYPES = {
    "C12A7328-F81F-11D2-BA4B-00A0C93EC93B": "EFI System",
    "E3C9E316-0B5C-4DB8-817D-F92DF00215AE": "Microsoft reserve",
    "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7": "Donnees de base",
    "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC": "Windows RE",
    "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "Linux",
    "21686148-6449-6E6F-744E-656564454649": "BIOS boot",
    "E6D6D379-F507-44C2-A23C-238F2A3DF928": "LDM donnees",
}

_MBR_TYPES = {
    0x07: "NTFS/exFAT", 0x0B: "FAT32", 0x0C: "FAT32 LBA", 0x0E: "FAT16 LBA",
    0x27: "Recuperation", 0x83: "Linux", 0x82: "Linux swap",
    0xEE: "GPT protectrice", 0xEF: "EFI",
}


def _guid(b: bytes) -> str:
    """GUID Windows : les trois premiers champs sont en petit-boutien."""
    return (f"{int.from_bytes(b[0:4],'little'):08X}-"
            f"{int.from_bytes(b[4:6],'little'):04X}-"
            f"{int.from_bytes(b[6:8],'little'):04X}-"
            f"{b[8:10].hex().upper()}-{b[10:16].hex().upper()}")


def _partitions(index: int, secteur: int) -> dict:
    """Inventaire des partitions lu DIRECTEMENT sur le disque (GPT puis MBR).

    On parse le disque plutot que d'interroger Windows : c'est la seule methode
    qui donnera le meme resultat en WinPE, ou les volumes ne sont pas montes et
    n'ont pas de lettre. C'est aussi la brique de l'inventaire affiche avant un
    test destructif (garde-fou n0 4) : montrer ce qu'on va detruire.
    """
    taille_lue = max(512, secteur)
    with _Drive(index) as d:
        d.seek(0)
        buf = ctypes.create_string_buffer(taille_lue)
        d.read_into(buf, taille_lue)
        mbr = buf.raw

        entrees = []
        for i in range(4):
            e = mbr[446 + i * 16: 446 + (i + 1) * 16]
            t = e[4]
            if t:
                entrees.append({
                    "type_mbr":  f"0x{t:02X}",
                    "libelle":   _MBR_TYPES.get(t, "inconnu"),
                    "debut_lba": int.from_bytes(e[8:12], "little"),
                    "taille_go": round(int.from_bytes(e[12:16], "little")
                                       * secteur / 1e9, 2),
                })
        protectrice = any(x["type_mbr"] == "0xEE" for x in entrees)

        if not protectrice:
            return {"schema": "MBR" if entrees else "aucun",
                    "partitions": entrees}

        # GPT : en-tete en LBA1, table a l'adresse qu'elle indique.
        d.seek(secteur)
        buf = ctypes.create_string_buffer(taille_lue)
        d.read_into(buf, taille_lue)
        hdr = buf.raw
        if hdr[0:8] != b"EFI PART":
            return {"schema": "GPT annoncee mais en-tete absente",
                    "partitions": entrees}

        table_lba = int.from_bytes(hdr[72:80], "little")
        nb        = min(int.from_bytes(hdr[80:84], "little"), 128)
        taille_e  = int.from_bytes(hdr[84:88], "little")
        if not taille_e or not nb:
            return {"schema": "GPT", "partitions": [],
                    "note": "table de partitions vide ou illisible"}
        octets  = nb * taille_e
        octets += (-octets) % secteur          # arrondi au secteur superieur

        d.seek(table_lba * secteur)
        buf = ctypes.create_string_buffer(octets)
        d.read_into(buf, octets)
        tbl = buf.raw

        parts = []
        for i in range(nb):
            e = tbl[i * taille_e:(i + 1) * taille_e]
            if len(e) < 128 or e[0:16] == b"\x00" * 16:
                continue
            type_guid = _guid(e[0:16])
            debut = int.from_bytes(e[32:40], "little")
            fin   = int.from_bytes(e[40:48], "little")
            # Couper au PREMIER NUL, pas rogner la fin : plusieurs firmwares ne
            # remettent pas a zero le reste du champ, si bien qu'un rstrip
            # laissait la suite du tampon collee au nom. Vu le 01/09 :
            # << Basic data partition\x00<octets aleatoires> >>. Un nom de
            # partition en mojibake dans un rapport client serait indefendable.
            nom   = e[56:128].decode("utf-16-le", "replace").split("\x00")[0].strip()
            parts.append({
                "numero":    i + 1,
                "type_guid": type_guid,
                "libelle":   _GPT_TYPES.get(type_guid, "inconnu"),
                "nom":       nom or None,
                "debut_lba": debut,
                "taille_go": round((fin - debut + 1) * secteur / 1e9, 2),
            })
        return {"schema": "GPT", "partitions": parts}


def _latence_zone(index: int, offset: int, secteur: int, blocs: int = 16) -> dict:
    """Lit `blocs` x 1 Mio depuis un offset, et rend le profil de temps.

    Trois zones valent mieux qu'une seule au debut : sur un disque mecanique le
    debit chute fortement des pistes exterieures vers les interieures, et c'est
    exactement ce que le mode << express >> devra echantillonner plutot que de
    balayer 4 To.
    """
    offset -= offset % secteur                    # alignement obligatoire
    ptr = None
    try:
        with _Drive(index, no_buffering=True) as d:
            ptr = _aligned_buffer(_BLOCK_BYTES)
            d.seek(offset)
            temps, total = [], 0
            for _ in range(blocs):
                t0 = time.perf_counter()
                lus = d.read_into(ptr, _BLOCK_BYTES)
                temps.append((time.perf_counter() - t0) * 1000.0)
                total += lus
                if lus < _BLOCK_BYTES:
                    break
            temps.sort()
            duree = sum(temps) / 1000.0
            return {"offset_go":      round(offset / 1e9, 1),
                    "octets_lus":     total,
                    "debit_mo_s":     round(total / 1e6 / duree, 1) if duree else None,
                    "bloc_median_ms": round(temps[len(temps) // 2], 2) if temps else None,
                    "bloc_max_ms":    round(temps[-1], 2) if temps else None}
    except OSError as exc:
        return {"offset_go": round(offset / 1e9, 1), "erreur": str(exc)}
    finally:
        if ptr:
            _k32.VirtualFree(ptr, 0, MEM_RELEASE)


def check_disques_detail() -> dict:
    """Fiche complete PAR DISQUE - le coeur de la collecte.

    Les verifications precedentes ne regardent QUE le premier disque ouvrable :
    suffisant pour un feu vert de phase 0, insuffisant pour concevoir le module.
    Ici chaque disque est decrit et mesure sur trois zones (debut / milieu /
    fin), ce qui reste court (48 Mio par disque) et sans risque.
    """
    exclus = []
    try:
        exclus = check_disque_de_la_sonde().get("a_exclure_des_tests") or []
    except Exception:
        pass

    fiches = []
    for i in range(16):
        try:
            with _Drive(i) as d:
                taille = int.from_bytes(d.ioctl(IOCTL_DISK_GET_LENGTH_INFO, 8), "little")
                geo = d.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY, 24)
                secteur = int.from_bytes(geo[20:24], "little") or 512
        except OSError:
            continue

        fiche = {"index": i, "taille_go": round(taille / 1e9, 1),
                 "porte_la_sonde": i in exclus}

        for nom, fn in (("identite",   lambda i=i: _serie_via_ioctl(i)),
                        ("secteurs",   lambda i=i: _secteurs_logique_physique(i)),
                        ("partitions", lambda i=i, s=secteur: _partitions(i, s))):
            try:
                fiche[nom] = fn()
            except Exception as exc:
                fiche[nom] = {"erreur": f"{type(exc).__name__}: {exc}"}

        # Trois zones : debut, milieu, et fin moins la fenetre de lecture.
        fenetre = _BLOCK_BYTES * 16
        fiche["zones"] = [
            _latence_zone(i, 0, secteur),
            _latence_zone(i, taille // 2, secteur),
            _latence_zone(i, max(0, taille - fenetre * 2), secteur),
        ]
        debits = [z.get("debit_mo_s") for z in fiche["zones"] if z.get("debit_mo_s")]
        if len(debits) >= 2:
            fiche["ecart_debit_pct"] = round(
                (max(debits) - min(debits)) / max(debits) * 100, 1)
            # NE PAS conclure mecanique/SSD sur cet ecart. Mesure du 08/08 : un
            # NVMe sain affiche 30,7 % d'ecart entre zones sur 16 Mio (2800 /
            # 1942 / 2406 Mo/s) alors qu'un SATA du meme poste reste a 3 %.
            # L'echantillon est trop court, et un SSD varie avec son cache SLC
            # et sa temperature. Le discriminant fiable est rotation_rate rendu
            # par smartctl (0 = SSD, sinon les tours/minute), pas un debit.
            fiche["note_ecart"] = (
                "Ecart indicatif seulement : trop court pour conclure. Pour "
                "distinguer mecanique et SSD, se fier a smartctl.rotation_rate.")
        fiches.append(fiche)

    return {"nb_disques": len(fiches), "disques": fiches}


def _serie_solide(serie) -> tuple:
    """Un serie assaini n'est pas pour autant un IDENTIFIANT.

    Campagne du 01/09, deux contre-exemples qui auraient corrompu l'archive :
      - la cle USB Kingston/Generic rend \\x031, assaini en << 1 >>. N'importe
        quel autre peripherique peut produire << 1 >>.
      - les NVMe rendent par IOCTL leur EUI-64, souvent presque tout en zeros
        (0000_0000_0000_0000_0C82_D500_0000_0371), et certains fabricants
        partagent le meme prefixe sur toute une gamme.
    Un champ rempli n'est pas un champ discriminant. On qualifie, on ne suppose pas.
    """
    if not serie:
        return False, "absent"
    s = str(serie).strip("_. ")
    nu = s.replace("_", "").replace("-", "")
    if len(nu) < 6:
        return False, "trop court pour discriminer"
    if len(set(nu)) <= 1:
        return False, "un seul caractere repete"
    if len(nu.strip("0")) < 4:
        return False, "essentiellement des zeros"
    return True, "ok"


def _type_support(idt: dict, smart: dict) -> str:
    """Mecanique ou electronique ? Regle complete, apres deux corrections.

    rotation_rate reste le discriminant quand il est la, mais c'est un champ
    ATA : il est TOUJOURS absent en NVMe (verifie sur 4 NVMe le 01/09). Et
    l'ecart de debit entre zones ne conclut rien du tout (un NVMe sain monte a
    65,9 % d'ecart). D'ou cette regle en cascade.
    """
    smart = smart or {}
    bus = (idt or {}).get("bus")
    if bus == "NVMe" or smart.get("usure_nvme_pct") is not None:
        return "SSD NVMe"
    rr = smart.get("rotation_rate")
    if rr == 0:
        return "SSD"
    if isinstance(rr, int) and rr > 0:
        return f"Disque mecanique ({rr} tr/min)"
    if bus == "USB":
        return "USB - support indetermine"
    return "indetermine"


def _apparier_smart(idt: dict, smarts: list) -> dict:
    """Rapproche un PhysicalDriveN d'une entree smartctl.

    Par numero de serie d'abord, par modele ensuite. Les deux sources ne
    numerotent pas les disques pareil (smartctl voit aussi les lecteurs
    optiques et duplique derriere un controleur RST), un appariement positionnel
    serait faux.
    """
    def _n(x):
        return "".join(str(x).split()).upper().strip("_. ") if x else None

    serie = _n((idt or {}).get("numero_serie"))
    modele = _n((idt or {}).get("modele"))
    for s in smarts:
        if serie and _n(s.get("numero_serie")) == serie:
            return s
    for s in smarts:
        if modele and _n(s.get("modele")) == modele:
            return s
    return {}


def _synthese_disques(detail: dict, smart: dict) -> dict:
    """Fiche consolidee par disque - le prototype de l'inventaire du module.

    C'est ici qu'on tranche la clé d'identite en croisant les deux sources, et
    qu'on dit HONNETEMENT quand aucune des deux ne fournit d'identifiant sur
    lequel indexer un rapport.
    """
    fiches = (detail or {}).get("disques") or []
    smarts = [x for x in ((smart or {}).get("details") or []) if x.get("exploitable")]

    out, faibles = [], 0
    for f in fiches:
        idt = f.get("identite") or {}
        s   = _apparier_smart(idt, smarts)

        ser_smart = s.get("numero_serie")
        ser_ioctl = (_nettoyer_serie(idt.get("numero_serie")) or (None, None))[0]
        ok_smart, _   = _serie_solide(ser_smart)
        ok_ioctl, why = _serie_solide(ser_ioctl)

        if ok_smart:
            cle, source, conf = ser_smart, "smartctl", "forte"
        elif ok_ioctl:
            cle, source, conf = ser_ioctl, "IOCTL", "moyenne"
        else:
            # Repli explicite et non ambigu plutot qu'un identifiant douteux.
            cle = f"{idt.get('modele') or 'DISQUE'}-{f.get('taille_go')}Go-SANS-SERIE"
            cle = (_nettoyer_serie(cle) or (cle, None))[0]
            source, conf = "repli modele+taille", "faible"
            faibles += 1

        out.append({
            "index":          f.get("index"),
            "modele":         idt.get("modele") or s.get("modele"),
            "taille_go":      f.get("taille_go"),
            "bus":            idt.get("bus"),
            "type_support":   _type_support(idt, s),
            "porte_la_sonde": f.get("porte_la_sonde"),
            "cle_identite":   cle,
            "source_cle":     source,
            "confiance_cle":  conf,
            "raison_rejet_ioctl": None if ok_ioctl else why,
            "serie_smartctl": ser_smart,
            "serie_ioctl":    ser_ioctl,
            "smart_disponible": bool(s),
            "heures":         s.get("heures"),
            "usure_nvme_pct": s.get("usure_nvme_pct"),
            "temperature":    s.get("temperature"),
        })

    return {"disques": out,
            "nb_cles_faibles": faibles,
            "verdict": ("toutes les cles d'identite sont exploitables" if not faibles
                        else f"{faibles} disque(s) sans identifiant fiable - "
                             "indexation des rapports a securiser")}


# --- Rapport -----------------------------------------------------------------

VERIFICATIONS = [
    ("contexte",              check_contexte),
    ("ecriture_rapport",      check_ecriture_rapport),
    ("disque_de_la_sonde",    check_disque_de_la_sonde),
    ("disques_enumeration",   check_disques_enumeration),
    ("identite_disques",      check_identite_disques),
    ("lecture_brute",         check_lecture_brute),
    ("lecture_non_bufferisee", check_lecture_non_bufferisee),
    ("debit_et_latence",      check_debit_et_latence),
    ("disques_detail",        check_disques_detail),
    ("smartctl",              check_smartctl),
    # tkinter en dernier : c'est le seul qui peut faire tomber le process.
    ("tkinter",               check_tkinter),
]


def main() -> int:
    horodatage = datetime.now()
    machine    = socket.gethostname() or "INCONNU"
    sortie     = _ROOT / f"winpe_probe_{machine}_{horodatage:%Y%m%d_%H%M%S}.json"

    rapport = {
        "sonde":        "atelier_winpe_probe",
        "chantier":     "GhisdiagDisk - phase 0 (ROADMAP.md)",
        "lance_a":      horodatage.isoformat(timespec="seconds"),
        "verifications": {},
    }

    def _flush():
        """Ecriture immediate : un crash sur la verification suivante ne coute rien."""
        try:
            sortie.write_text(
                json.dumps(rapport, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8")
        except OSError as exc:
            print(f"  [!] rapport non ecrit ({exc}) - sortie console uniquement")

    print("Ghisdiag - sonde WinPE (phase 0 GhisdiagDisk)")
    print(f"Rapport : {sortie}\n")

    for nom, fn in VERIFICATIONS:
        print(f"  - {nom} ... ", end="", flush=True)
        depart = time.perf_counter()
        try:
            rapport["verifications"][nom] = {
                "ok": True, "data": fn(),
                "duree_sec": round(time.perf_counter() - depart, 2)}
            print("ok")
        except Exception as exc:
            rapport["verifications"][nom] = {
                "ok": False, "erreur": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "duree_sec": round(time.perf_counter() - depart, 2)}
            print(f"ECHEC - {type(exc).__name__}: {exc}")
        _flush()

    # Verdict lisible sans ouvrir le JSON.
    v = rapport["verifications"]

    def _data(nom, cle, defaut=None):
        bloc = v.get(nom) or {}
        return (bloc.get("data") or {}).get(cle, defaut) if bloc.get("ok") else defaut

    def _bloc(nom):
        """Le bloc `data` entier d'une verification reussie, sinon {}."""
        b = v.get(nom) or {}
        return (b.get("data") or {}) if b.get("ok") else {}

    # Le n0 de serie a DEUX sources et il suffit qu'une reponde : l'IOCTL exige
    # l'elevation, smartctl non (verifie le 08/08 : series remontees sans admin).
    # Ne compter que l'IOCTL afficherait "serie illisible" alors que la cle
    # d'identite des rapports est parfaitement disponible.
    serie_ioctl = bool(_data("identite_disques", "tous_identifiables", False))
    serie_smart = any((d or {}).get("numero_serie")
                      for d in (_data("smartctl", "details") or []))
    source_serie = ("les deux" if serie_ioctl and serie_smart else
                    "IOCTL" if serie_ioctl else
                    "smartctl" if serie_smart else None)

    # CROISEMENT DES DEUX SOURCES — le garde-fou qui manquait le 08/08.
    # Deux sources independantes qui ne partagent AUCUN numero de serie alors
    # qu'elles repondent toutes les deux, c'est qu'une des deux decode mal. Un
    # champ rempli n'est pas un champ juste : c'est exactement comme ca que la
    # revision de firmware est passee pour un numero de serie sans alerter.
    def _norm(s):
        return "".join(str(s).split()).upper() if s else None

    ser_i = {_norm(d.get("numero_serie"))
             for d in (_data("identite_disques", "disques") or [])
             if d.get("numero_serie")}
    ser_s = {_norm(d.get("numero_serie"))
             for d in (_data("smartctl", "details") or [])
             if d.get("numero_serie")}
    communes = ser_i & ser_s

    # Synthese par disque : appariement des deux sources, type de support et
    # cle d'identite retenue. C'est le prototype de l'inventaire du module.
    synth = _synthese_disques(_bloc("disques_detail"), _bloc("smartctl"))
    rapport["synthese_disques"] = synth

    # CROISEMENT PAR DISQUE APPARIE, et non par intersection d'ensembles.
    # Le 01/09, la comparaison globale a criè << DIVERGENTES - une des deux
    # sources decode mal >> sur une machine ou les deux sources etaient JUSTES :
    # l'IOCTL voyait le NVMe, smartctl seulement le lecteur DVD. Deux sources
    # qui decrivent des peripheriques differents ne divergent pas, elles ne se
    # recouvrent pas. Confondre les deux, c'est fabriquer une fausse alerte.
    apparies = [d for d in synth["disques"]
                if d.get("serie_smartctl") and d.get("serie_ioctl")]
    def _n2(x):
        return "".join(str(x).split()).upper().strip("_. ") if x else None
    accord = [d for d in apparies
              if _n2(d["serie_smartctl"]) == _n2(d["serie_ioctl"])]

    if not apparies:
        verdict_conc = ("aucun disque n'a repondu aux DEUX sources - "
                        "croisement impossible, ce n'est pas une divergence")
    elif len(accord) == len(apparies):
        verdict_conc = f"concordantes sur les {len(apparies)} disque(s) apparie(s)"
    else:
        verdict_conc = (f"ecart de FORMAT sur {len(apparies) - len(accord)} disque(s) : "
                        "typiquement un NVMe, dont l'IOCTL rend l'EUI-64 et non le "
                        "serie. Ce n'est pas un bug de decodage, mais deux "
                        "identifiants differents pour le meme disque")

    rapport["concordance_series"] = {
        "ioctl":            sorted(x for x in ser_i if x),
        "smartctl":         sorted(x for x in ser_s if x),
        "communes":         sorted(x for x in communes if x),
        "disques_apparies": len(apparies),
        "disques_en_accord": len(accord),
        "verdict":          verdict_conc,
    }

    rapport["verdict_phase_0"] = {
        "winpe_confirme":        _data("contexte", "winpe_detecte", False),
        "tkinter_utilisable":    bool((v.get("tkinter") or {}).get("ok")
                                      and _data("tkinter", "fenetre_ok", False)),
        "acces_disque_brut":     "OK" in str(_data("lecture_brute", "verdict", "")),
        "no_buffering":          "OK" in str(_data("lecture_non_bufferisee", "verdict", "")),
        "smartctl_operationnel": "operationnel" in str(_data("smartctl", "verdict", "")),
        "serie_disque_lisible":  serie_ioctl or serie_smart,
        "rapport_persistant":    _data("ecriture_rapport", "inscriptible", False)
                                 and not _data("ecriture_rapport",
                                               "probablement_ramdisk_winpe", False),
    }
    rapport["source_numero_serie"] = source_serie
    _flush()

    print("\nVerdict phase 0 :")
    for cle, val in rapport["verdict_phase_0"].items():
        print(f"  {'OUI' if val else 'NON':>3}  {cle}")
    if source_serie:
        print(f"       (n0 de serie lu via : {source_serie})")
    print(f"  Croisement des deux sources : {verdict_conc}")

    print("\nDisques :")
    for d in synth["disques"]:
        marque = " [PORTE LA SONDE]" if d.get("porte_la_sonde") else ""
        print(f"  #{d['index']} {str(d['taille_go']):>7} Go  {str(d['bus']):>5}  "
              f"{d['type_support']:<24} {d.get('modele') or '?'}{marque}")
        print(f"      cle={d['cle_identite']}  (source {d['source_cle']}, "
              f"confiance {d['confiance_cle']})")
    print(f"  -> {synth['verdict']}")
    print(f"\nRapport ecrit : {sortie}")
    return 0


if __name__ == "__main__":
    _code = 1
    try:
        _code = main()
    except KeyboardInterrupt:
        print("\nInterrompu.")
        _code = 130
    except Exception:
        traceback.print_exc()
        _code = 1
    finally:
        # Gele = lance par double-clic, en atelier comme en WinPE. Sans cette
        # pause la console se referme des la fin : on ne lit ni le verdict, ni
        # la trace si ca casse. En sources (lance depuis un terminal ou le .bat,
        # qui fait deja `pause`), on ne bloque pas.
        if getattr(sys, "frozen", False):
            try:
                input("\nAppuyer sur Entree pour fermer cette fenetre...")
            except (EOFError, KeyboardInterrupt):
                pass
    sys.exit(_code)
