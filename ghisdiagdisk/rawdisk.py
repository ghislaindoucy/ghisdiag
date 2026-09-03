r"""
GhisdiagDisk - acces disque brut Win32 (ctypes, sans dependance).

Extraction de la mecanique validee par la sonde de phase 0
(atelier_winpe_probe.py, 5 executions en Hiren's BootCD PE le 03/09/2026).
La sonde reste FIGEE comme reference de terrain ; ce module est la version
reutilisable, avec les memes offsets et les memes pieges documentes.

Tout est en LECTURE SEULE : GENERIC_READ, jamais d'ecriture. Le niveau T3
(ecriture brute) passera par un module separe, protege par le fichier-marqueur
(voir niveaux.py) - pas par un drapeau ici.

Regles issues des campagnes (ROADMAP) reprises telles quelles :
  - enumerer par index \\.\PhysicalDriveN, jamais par lettre de lecteur (en
    WinPE les volumes ne sont pas montes) ;
  - offsets de STORAGE_DEVICE_DESCRIPTOR : 12/16/20/24, PAS 8/12/16/20 (la
    revision de firmware passait pour un numero de serie) ;
  - FILE_FLAG_NO_BUFFERING + tampon aligne page (VirtualAlloc), sinon on mesure
    le cache Windows et non le disque ;
  - le disque porteur de l'exe ET le support de boot du PE sont a exclure.
"""

import ctypes
import platform
import socket
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Optional

_WINDOWS = sys.platform == "win32"

# --- Constantes Win32 --------------------------------------------------------

GENERIC_READ            = 0x80000000
FILE_SHARE_READ         = 0x00000001
FILE_SHARE_WRITE        = 0x00000002
OPEN_EXISTING           = 3
FILE_FLAG_NO_BUFFERING  = 0x20000000
INVALID_HANDLE_VALUE    = ctypes.c_void_p(-1).value

MEM_COMMIT_RESERVE = 0x3000
MEM_RELEASE        = 0x8000
PAGE_READWRITE     = 0x04

IOCTL_DISK_GET_LENGTH_INFO           = 0x0007405C
IOCTL_DISK_GET_DRIVE_GEOMETRY        = 0x00070000
IOCTL_STORAGE_QUERY_PROPERTY         = 0x002D1400
IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000

MAX_DISQUES = 16          # PhysicalDrive0..15 : au-dela, ce n'est plus un poste

# STORAGE_BUS_TYPE - sert directement aux regles d'exclusion.
BUS_TYPES = {
    0: "inconnu", 1: "SCSI", 2: "ATAPI", 3: "ATA", 4: "IEEE1394", 5: "SSA",
    6: "FibreChannel", 7: "USB", 8: "RAID", 9: "iSCSI", 10: "SAS", 11: "SATA",
    12: "SD", 13: "MMC", 14: "virtuel", 15: "virtuel-fichier", 16: "StorageSpaces",
    17: "NVMe", 18: "SCM", 19: "UFS",
}

if _WINDOWS:
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
else:  # pragma: no cover - les tests unitaires n'ouvrent jamais un disque
    _k32 = None


# --- Chemins -----------------------------------------------------------------

def dossier_exe() -> Path:
    r"""Dossier OU ECRIRE (rapports, sessions) : a cote de l'exe, jamais dans
    le bundle. En onedir PyInstaller 6, `__file__` pointe dans `_internal\`.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.resolve()
    return Path(__file__).parent.parent.resolve()


def dossier_bundle() -> Path:
    r"""Dossier OU LIRE les ressources embarquees (tools\smartctl.exe)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).parent.parent.resolve()


# --- Contexte d'execution ----------------------------------------------------

def contexte() -> dict:
    """Ou tourne-t-on : WinPE ou Windows, eleve ou non.

    Le marqueur WinPE est la cle MiniNT (validee le 03/09 en Hiren's PE). C'est
    lui qui decide si le moteur a le droit de CONCLURE sur les latences : sous
    Windows les maximums par bloc sont pollues par l'I/O de fond de l'OS
    (jusqu'a 4,4x la mediane sur un disque sain).
    """
    winpe = False
    if _WINDOWS:
        try:
            import winreg
            try:
                winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                               r"SYSTEM\CurrentControlSet\Control\MiniNT").Close()
                winpe = True
            except OSError:
                pass
        except Exception:
            pass
    admin = False
    if _WINDOWS:
        try:
            admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            admin = False
    hostname = socket.gethostname()
    return {
        "environnement":   "winpe" if winpe else ("windows" if _WINDOWS else "autre"),
        "winpe":           winpe,
        "admin":           admin,
        "hostname":        hostname,
        "hostname_inutile": hostname.upper() in ("MINWINPC", ""),
        "windows":         platform.platform(),
        "gele":            bool(getattr(sys, "frozen", False)),
        "python":          sys.version.split()[0],
    }


# --- Poignee disque ----------------------------------------------------------

class Drive:
    r"""Ouvre \\.\PhysicalDriveN (ou un volume \\.\X:) en LECTURE SEULE."""

    def __init__(self, index: Optional[int] = None, no_buffering: bool = False,
                 chemin: Optional[str] = None):
        if _k32 is None:
            raise OSError(0, "acces disque brut disponible sous Windows seulement")
        flags = FILE_FLAG_NO_BUFFERING if no_buffering else 0
        self.cible = chemin or f"\\\\.\\PhysicalDrive{index}"
        self.handle = _k32.CreateFileW(
            self.cible, GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
        if self.handle == INVALID_HANDLE_VALUE or not self.handle:
            raise OSError(ctypes.get_last_error(), f"CreateFileW {self.cible}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None

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

    def read_bytes(self, offset: int, size: int) -> bytes:
        """Lecture bufferisee simple (en-tetes de partitions). Alignement
        secteur obligatoire pour offset ET size, meme sans NO_BUFFERING."""
        self.seek(offset)
        buf = ctypes.create_string_buffer(size)
        got = self.read_into(buf, size)
        return buf.raw[:got]


class TamponAligne:
    """Tampon aligne page (4096), exige par FILE_FLAG_NO_BUFFERING.

    create_string_buffer ne garantit aucun alignement ; VirtualAlloc si.
    """

    def __init__(self, taille: int):
        self.taille = taille
        self.ptr = _k32.VirtualAlloc(None, taille, MEM_COMMIT_RESERVE, PAGE_READWRITE)
        if not self.ptr:
            raise OSError(ctypes.get_last_error(), "VirtualAlloc")

    def free(self):
        if self.ptr:
            _k32.VirtualFree(self.ptr, 0, MEM_RELEASE)
            self.ptr = None

    def __del__(self):
        try:
            self.free()
        except Exception:
            pass


class LecteurDisque:
    r"""Lecteur NON BUFFERISE d'un \\.\PhysicalDriveN - la source des mesures.

    C'est l'implementation reelle du protocole attendu par scan.ScanEngine :
    `lire(offset, taille) -> octets lus`, qui leve OSError sur un secteur
    illisible. Chaque lecture repositionne explicitement le pointeur : apres
    un ReadFile en echec, sa position n'est pas definie.
    """

    def __init__(self, index: int, taille_tampon: int):
        self._drive = Drive(index, no_buffering=True)
        self._tampon = TamponAligne(taille_tampon)

    def lire(self, offset: int, taille: int) -> int:
        if taille > self._tampon.taille:
            self._tampon.free()
            self._tampon = TamponAligne(taille)
        self._drive.seek(offset)
        return self._drive.read_into(self._tampon.ptr, taille)

    def close(self):
        self._tampon.free()
        self._drive.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --- Enumeration et identite -------------------------------------------------

def geometrie(index: int) -> dict:
    """Taille et secteurs (logique + physique) d'un disque.

    Un disque 512e (512 logique / 4096 physique) se lit par 512 mais travaille
    par 4096 : le balayage s'aligne sur le secteur physique.
    """
    with Drive(index) as d:
        taille = int.from_bytes(d.ioctl(IOCTL_DISK_GET_LENGTH_INFO, 8), "little")
        geo = d.ioctl(IOCTL_DISK_GET_DRIVE_GEOMETRY, 24)
        logique = int.from_bytes(geo[20:24], "little") if len(geo) >= 24 else 512
        physique = None
        try:
            # StorageAccessAlignmentProperty = 6
            query = (6).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\x00" * 4
            raw = d.ioctl_in(IOCTL_STORAGE_QUERY_PROPERTY, query, 64)
            if len(raw) >= 24:
                physique = int.from_bytes(raw[20:24], "little") or None
        except OSError:
            pass
    return {
        "index":            index,
        "peripherique":     f"\\\\.\\PhysicalDrive{index}",
        "taille_octets":    taille,
        "taille_go":        round(taille / 1e9, 1),
        "secteur_logique":  logique or 512,
        "secteur_physique": physique or logique or 512,
    }


def enumerer() -> list:
    r"""Tous les \\.\PhysicalDriveN ouvrables, avec leur geometrie.

    Vide sans elevation sous Windows normal (l'IOCTL exige admin). En WinPE le
    contexte est deja privilegie.
    """
    out = []
    for i in range(MAX_DISQUES):
        try:
            out.append(geometrie(i))
        except OSError:
            continue
    return out


def identite_ioctl(index: int) -> dict:
    """Identite via IOCTL_STORAGE_QUERY_PROPERTY (StorageDeviceProperty = 0).

    STORAGE_DEVICE_DESCRIPTOR :
        0  DWORD  Version          16 DWORD  ProductIdOffset
        4  DWORD  Size             20 DWORD  ProductRevisionOffset
        8  BYTE   DeviceType       24 DWORD  SerialNumberOffset
        9  BYTE   DeviceTypeModifier
        10 BYTE   RemovableMedia   28 DWORD  BusType
        11 BYTE   CommandQueueing
        12 DWORD  VendorIdOffset
    Chaines ANSI terminees par 0, comptees depuis le DEBUT du descripteur.
    Se tromper de 4 octets rend la revision de firmware comme numero de serie
    - defaut invisible attrape le 08/08 par le croisement avec smartctl.
    """
    query = (0).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\x00" * 4
    with Drive(index) as d:
        raw = d.ioctl_in(IOCTL_STORAGE_QUERY_PROPERTY, query, 1024)
    return decoder_descripteur(raw)


def decoder_descripteur(raw: bytes) -> dict:
    """Decodage pur du STORAGE_DEVICE_DESCRIPTOR (testable sans disque)."""
    def _chaine(offset_pos: int):
        if len(raw) < offset_pos + 4:
            return None
        off = int.from_bytes(raw[offset_pos:offset_pos + 4], "little")
        if not off or off >= len(raw):
            return None
        fin = raw.find(b"\x00", off)
        return raw[off:fin if fin != -1 else len(raw)].decode("latin-1").strip() or None

    bus = int.from_bytes(raw[28:32], "little") if len(raw) >= 32 else None
    return {
        "fabricant":    _chaine(12),
        "modele":       _chaine(16),
        "revision":     _chaine(20),
        "numero_serie": _chaine(24),
        "amovible":     bool(raw[10]) if len(raw) > 10 else None,
        "bus":          BUS_TYPES.get(bus, f"code {bus}") if bus is not None else None,
    }


def disques_du_volume(lettre: str) -> list:
    r"""Disques physiques qui portent le volume `X:` (plusieurs si RAID/espaces).

    VOLUME_DISK_EXTENTS : NumberOfDiskExtents(4) + bourrage(4), puis des
    DISK_EXTENT de 24 octets { DiskNumber(4), bourrage(4), Debut(8), Long(8) }.
    """
    lettre = lettre.rstrip("\\/")[:2]
    with Drive(chemin=f"\\\\.\\{lettre}") as v:
        raw = v.ioctl(IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, 1024)
    nb = int.from_bytes(raw[0:4], "little")
    out = []
    for i in range(nb):
        base = 8 + i * 24
        if len(raw) >= base + 4:
            out.append(int.from_bytes(raw[base:base + 4], "little"))
    return out


def disques_a_exclure() -> dict:
    """Indices des disques que le moteur ne doit JAMAIS proposer.

    Deux sources, et ce sont parfois deux cles differentes (vu le 03/09 : la
    sonde tournait depuis PhysicalDrive2, l'ISO Hiren's etait servi par
    PhysicalDrive3 - une clé Ventoy sollicitee mesurait 4 Mo/s) :
      1. le disque qui porte l'exe (garde-fou n0 3, valide 6/6) ;
      2. le support depuis lequel le PE a demarre, via la valeur de registre
         PEBootRamdiskSourceDrive quand elle designe un volume resoluble.
    """
    porteur, boot = [], []
    dossier = str(dossier_exe())
    if len(dossier) >= 2 and dossier[1] == ":":
        try:
            porteur = disques_du_volume(dossier[:2])
        except Exception:
            porteur = []
    if _WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control") as k:
                val, _ = winreg.QueryValueEx(k, "PEBootRamdiskSourceDrive")
            src = str(val).strip()
            if len(src) >= 2 and src[1] == ":":
                boot = disques_du_volume(src[:2])
        except Exception:
            boot = []
    return {"porteur_exe": porteur, "boot_pe": boot,
            "indices": sorted(set(porteur) | set(boot))}


# --- Partitions (lues sur le disque, pas via Windows) ------------------------

GPT_TYPES = {
    "C12A7328-F81F-11D2-BA4B-00A0C93EC93B": "EFI System",
    "E3C9E316-0B5C-4DB8-817D-F92DF00215AE": "Microsoft reserve",
    "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7": "Donnees de base",
    "DE94BBA4-06D1-4D40-A16A-BFD50179D6AC": "Windows RE",
    "0FC63DAF-8483-4772-8E79-3D69D8477DE4": "Linux",
    "21686148-6449-6E6F-744E-656564454649": "BIOS boot",
    "E6D6D379-F507-44C2-A23C-238F2A3DF928": "LDM donnees",
}

MBR_TYPES = {
    0x05: "Etendue CHS", 0x07: "NTFS/exFAT", 0x0B: "FAT32", 0x0C: "FAT32 LBA",
    0x0E: "FAT16 LBA", 0x0F: "Etendue LBA", 0x27: "Recuperation",
    0x82: "Linux swap", 0x83: "Linux", 0xA5: "BSD", 0xEE: "GPT protectrice",
    0xEF: "EFI",
}


def _guid(b: bytes) -> str:
    """GUID Windows : les trois premiers champs sont en petit-boutien."""
    return (f"{int.from_bytes(b[0:4],'little'):08X}-"
            f"{int.from_bytes(b[4:6],'little'):04X}-"
            f"{int.from_bytes(b[6:8],'little'):04X}-"
            f"{b[8:10].hex().upper()}-{b[10:16].hex().upper()}")


def partitions(index: int, secteur: int) -> dict:
    """Inventaire GPT puis MBR, lu directement sur le disque.

    Seule methode qui donne le meme resultat en WinPE (volumes non montes).
    C'est aussi l'inventaire affiche avant tout test destructif (garde-fou 4).
    """
    taille_lue = max(512, secteur)
    with Drive(index) as d:
        mbr = d.read_bytes(0, taille_lue)
        entrees = []
        for i in range(4):
            e = mbr[446 + i * 16: 446 + (i + 1) * 16]
            t = e[4]
            if t:
                entrees.append({
                    "type_mbr":  f"0x{t:02X}",
                    "libelle":   MBR_TYPES.get(t, "inconnu"),
                    "debut_lba": int.from_bytes(e[8:12], "little"),
                    "taille_go": round(int.from_bytes(e[12:16], "little")
                                       * secteur / 1e9, 2),
                })
        protectrice = any(x["type_mbr"] == "0xEE" for x in entrees)
        if not protectrice:
            return {"schema": "MBR" if entrees else "aucun", "partitions": entrees}

        hdr = d.read_bytes(secteur, taille_lue)
        if hdr[0:8] != b"EFI PART":
            return {"schema": "GPT annoncee mais en-tete absente", "partitions": entrees}
        table_lba = int.from_bytes(hdr[72:80], "little")
        nb        = min(int.from_bytes(hdr[80:84], "little"), 128)
        taille_e  = int.from_bytes(hdr[84:88], "little")
        if not taille_e or not nb:
            return {"schema": "GPT", "partitions": [],
                    "note": "table de partitions vide ou illisible"}
        octets  = nb * taille_e
        octets += (-octets) % secteur
        tbl = d.read_bytes(table_lba * secteur, octets)

    parts = []
    for i in range(nb):
        e = tbl[i * taille_e:(i + 1) * taille_e]
        if len(e) < 128 or e[0:16] == b"\x00" * 16:
            continue
        type_guid = _guid(e[0:16])
        debut = int.from_bytes(e[32:40], "little")
        fin   = int.from_bytes(e[40:48], "little")
        # Couper au PREMIER NUL : plusieurs firmwares laissent des octets
        # aleatoires apres le nom (vu le 01/09).
        nom = e[56:128].decode("utf-16-le", "replace").split("\x00")[0].strip()
        parts.append({
            "numero":    i + 1,
            "type_guid": type_guid,
            "libelle":   GPT_TYPES.get(type_guid, "inconnu"),
            "nom":       nom or None,
            "debut_lba": debut,
            "taille_go": round((fin - debut + 1) * secteur / 1e9, 2),
        })
    return {"schema": "GPT", "partitions": parts}
