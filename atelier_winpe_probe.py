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

_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_ROOT))

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

    def __init__(self, index: int, no_buffering: bool = False):
        flags = FILE_FLAG_NO_BUFFERING if no_buffering else 0
        self.handle = _k32.CreateFileW(
            f"\\\\.\\PhysicalDrive{index}", GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
        if self.handle == INVALID_HANDLE_VALUE or not self.handle:
            raise OSError(ctypes.get_last_error(),
                          f"CreateFileW PhysicalDrive{index}")

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


def _serie_via_ioctl(index: int) -> dict:
    """N0 de serie via IOCTL_STORAGE_QUERY_PROPERTY (StorageDeviceProperty).

    STORAGE_PROPERTY_QUERY : PropertyId=0, QueryType=0, AdditionalParameters[1].
    STORAGE_DEVICE_DESCRIPTOR : les champs texte sont des OFFSETS depuis le debut
    du descripteur, vers des chaines ANSI terminees par 0.
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

    return {
        # Offsets du STORAGE_DEVICE_DESCRIPTOR : Vendor=8, Product=12,
        # ProductRevision=16, SerialNumber=20.
        "fabricant":   _chaine(8),
        "modele":      _chaine(12),
        "revision":    _chaine(16),
        "numero_serie": _chaine(20),
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
        info["serie_utilisable_comme_cle"] = bool(info.get("numero_serie"))
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
    candidats = [_ROOT / "tools" / "smartctl.exe", _ROOT / "smartctl.exe"]
    if getattr(sys, "frozen", False):
        candidats.insert(0, Path(sys._MEIPASS) / "tools" / "smartctl.exe")
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
        out["peripheriques_vus"] = [d.get("name") for d in devices]
    except Exception as exc:
        out["scan_erreur"] = f"{type(exc).__name__}: {exc}"
        devices = []

    details = []
    for dev in devices[:4]:
        nom = dev.get("name")
        try:
            _, txt = _run(["-a", "--json", nom], timeout=60)
            d = json.loads(txt)
            details.append({
                "peripherique": nom,
                "modele":       (d.get("model_name") or d.get("model_family")),
                "numero_serie": d.get("serial_number"),
                "smart_actif":  (d.get("smart_status") or {}).get("passed"),
                "temperature":  (d.get("temperature") or {}).get("current"),
                "heures":       (d.get("power_on_time") or {}).get("hours"),
                "usure_nvme_pct": (d.get("nvme_smart_health_information_log") or {})
                                  .get("percentage_used"),
            })
        except Exception as exc:
            details.append({"peripherique": nom,
                            "erreur": f"{type(exc).__name__}: {exc}"})
    out["details"] = details
    out["verdict"] = ("smartctl operationnel" if details
                      else "smartctl present mais aucun disque interroge")
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


# --- Rapport -----------------------------------------------------------------

VERIFICATIONS = [
    ("contexte",              check_contexte),
    ("ecriture_rapport",      check_ecriture_rapport),
    ("disques_enumeration",   check_disques_enumeration),
    ("identite_disques",      check_identite_disques),
    ("lecture_brute",         check_lecture_brute),
    ("lecture_non_bufferisee", check_lecture_non_bufferisee),
    ("debit_et_latence",      check_debit_et_latence),
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

    rapport["verdict_phase_0"] = {
        "winpe_confirme":        _data("contexte", "winpe_detecte", False),
        "tkinter_utilisable":    bool((v.get("tkinter") or {}).get("ok")
                                      and _data("tkinter", "fenetre_ok", False)),
        "acces_disque_brut":     "OK" in str(_data("lecture_brute", "verdict", "")),
        "no_buffering":          "OK" in str(_data("lecture_non_bufferisee", "verdict", "")),
        "smartctl_operationnel": "operationnel" in str(_data("smartctl", "verdict", "")),
        "serie_disque_lisible":  _data("identite_disques", "tous_identifiables", False),
        "rapport_persistant":    _data("ecriture_rapport", "inscriptible", False)
                                 and not _data("ecriture_rapport",
                                               "probablement_ramdisk_winpe", False),
    }
    _flush()

    print("\nVerdict phase 0 :")
    for cle, val in rapport["verdict_phase_0"].items():
        print(f"  {'OUI' if val else 'NON':>3}  {cle}")
    print(f"\nRapport ecrit : {sortie}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompu.")
        sys.exit(130)
