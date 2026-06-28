#!/usr/bin/env python3
"""
Ghisdiag - Diagnostic des capteurs CPU

A lancer sur une machine ou le suivi de temperature / le bench thermique ne
fonctionne pas (Celeron, Ryzen recent...). Le but est d'identifier POURQUOI la
temperature CPU ne remonte pas, avant d'ecrire un correctif.

Il rapporte, dans l'ordre des causes probables :
  1. Droits admin / elevation        (sans elevation : pas d'acces MSR)
  2. Etat du driver PawnIO            (sans PawnIO : temp/freq CPU = N/A)
  3. Presence de la DLL LibreHardwareMonitor
  4. Modele de CPU                    (utile pour verifier le support LHM)
  5. La sortie brute de sensors.ps1   (ok / error / debug_sensors)

Usage :
    python diagnose_sensors.py

Copie-colle la sortie complete pour analyse.
"""

import sys

from collectors.sensors import _PS_EXE, _SCRIPT_PATH, lhm_available
# La lecture LHM -Once (qui conserve les echecs ok=false) est centralisee dans
# sensors_health, partagee avec le rapport et le moniteur de l'app.
from collectors.sensors_health import _probe_once as _run_lhm_once

try:
    from collectors import pawnio
    _HAS_PAWNIO_MOD = True
except Exception:
    pawnio = None
    _HAS_PAWNIO_MOD = False


def _yn(b: bool) -> str:
    return "OUI" if b else "NON"


def main() -> None:
    print("=" * 70)
    print(" DIAGNOSTIC CAPTEURS CPU - Ghisdiag")
    print("=" * 70)

    # --- 1. Elevation -------------------------------------------------------
    admin = pawnio.is_admin() if _HAS_PAWNIO_MOD else None
    print("\n[1] Droits administrateur (eleve) :", _yn(admin) if admin is not None else "?")
    if admin is False:
        print("    -> Sans elevation, l'acces MSR est bloque : la temp CPU sera N/A.")
        print("       Relance ce diagnostic dans une console *Administrateur*.")

    # --- 2. PawnIO ----------------------------------------------------------
    print("\n[2] Driver PawnIO (acces MSR -> temp/freq CPU) :")
    if _HAS_PAWNIO_MOD:
        installed = pawnio.pawnio_installed()
        print("    installe        :", _yn(installed))
        print("    installeur dispo :", _yn(pawnio.installer_available()))
        if not installed:
            print("    -> C'est la cause #1 d'absence de temp CPU avec LHM 0.9.x.")
            print("       En admin, tu peux l'installer :")
            print("         tools\\PawnIO_setup.exe -install -silent")
    else:
        print("    (module collectors.pawnio indisponible)")

    # --- 3. Backend LHM (dossier actif + version, override possible) --------
    print("\n[3] Backend LibreHardwareMonitor :", _yn(lhm_available()))
    try:
        from collectors import lhm_backend
        bi = lhm_backend.info()
        print("    dossier actif :", bi["active_dir"])
        print("    version DLL   :", bi["version"])
        print("    override actif:", _yn(bi["override"]),
              "(embarque)" if not bi["override"] else "(DLL plus recente deposee)")
        print("    embarque      :", bi["embedded_dir"])
        print("    dossier maj   :", bi["user_dir"])
    except Exception as exc:
        print("    (info backend indisponible :", exc, ")")
    print("    chemin script :", _SCRIPT_PATH)
    print("    powershell.exe:", _PS_EXE)

    # --- 4. Modele CPU ------------------------------------------------------
    import os
    print("\n[4] CPU :")
    print("    PROCESSOR_IDENTIFIER :", os.environ.get("PROCESSOR_IDENTIFIER", "?"))
    print("    coeurs logiques      :", os.cpu_count())

    # --- 5. Lecture LHM brute ----------------------------------------------
    print("\n[5] Lecture LibreHardwareMonitor (sensors.ps1 -Once) :")
    sample = _run_lhm_once()
    if sample is None:
        print("    -> Aucune reponse (DLL/script absents). Voir [3].")
        _verdict(admin, sample)
        return

    if not sample.get("ok"):
        print("    ok    : False")
        print("    error :", sample.get("error"))
        _verdict(admin, sample)
        return

    print("    ok    : True")
    print("    cpu_pkg / cpu_max / cpu_avg / cpu_ref :",
          sample.get("cpu_pkg"), "/", sample.get("cpu_max"), "/",
          sample.get("cpu_avg"), "/", sample.get("cpu_ref"))
    print("    cpu_load / cpu_clock_max :",
          sample.get("cpu_load"), "/", sample.get("cpu_clock_max"))
    print("    gpu_temp :", sample.get("gpu_temp"),
          " | disques :", len(sample.get("disks") or []))

    debug = sample.get("debug_sensors") or []
    print(f"\n    --- Capteurs CPU bruts vus par LHM ({len(debug)}) ---")
    if debug:
        for s in debug:
            print(f"      {str(s.get('name')):<28} | {str(s.get('type')):<12} | {s.get('value')}")
    else:
        print("      (AUCUN capteur CPU expose par LHM)")

    _verdict(admin, sample)


def _print_own_sources() -> None:
    """Sources maison (sans LHM) : GPU NVML + disques smartctl."""
    print("\n[6] Sources maison (sans LibreHardwareMonitor) :")
    try:
        from collectors import gpu
        gpus = gpu.read()
        if gpus:
            for g in gpus:
                print(f"    GPU NVML : {g['name']} | temp={g['temp']} "
                      f"load={g['load']} fan={g['fan']}%")
        else:
            print("    GPU NVML : (aucun GPU NVIDIA / nvml.dll absent)")
    except Exception as exc:
        print("    GPU NVML : indisponible —", exc)
    try:
        from collectors import disk_temp
        disks = disk_temp.read_all()
        if disks:
            for d in disks:
                print(f"    Disque   : {d['model']} ({d['proto']}) = {d['temp']} C")
        else:
            print("    Disque   : (smartctl ne remonte rien — droits admin ?)")
    except Exception as exc:
        print("    Disque   : indisponible —", exc)


def _verdict(admin, sample) -> None:
    _print_own_sources()
    print("\n" + "-" * 70)
    print(" VERDICT")
    print("-" * 70)

    s = sample if isinstance(sample, dict) else {}
    cpu_ref = s.get("cpu_ref")
    debug = s.get("debug_sensors")
    err = s.get("error") if not s.get("ok") else None

    if cpu_ref is not None:
        print(" OK - La temperature CPU remonte (cpu_ref =", cpu_ref, "). Le bench")
        print("      devrait fonctionner sur cette machine.")
        return

    print(" PROBLEME - Aucune temperature CPU (cpu_ref = None). Causes probables :")
    if admin is False:
        print("   - Console non elevee -> relance en Administrateur.")
    if _HAS_PAWNIO_MOD and not pawnio.pawnio_installed():
        print("   - PawnIO absent -> installe-le (voir [2]) puis relance.")

    if err and ("Timeout" in str(err) or "timed out" in str(err)):
        print("   - LHM SE BLOQUE (timeout) : Open()/Update() ne rend pas la main.")
        print("     Souvent un CPU trop recent (Zen 5) OU le probing carte-mere /")
        print("     controleur qui pend. Lance l'isolation pour savoir lequel :")
        print("         py diagnose_probe.py")
    elif err:
        print(f"   - LHM renvoie une erreur : {err}")
    elif debug:
        print("   - LHM expose des capteurs CPU mais aucun n'est une temperature")
        print("     reconnue : copie la liste [5] ci-dessus, on adaptera le mapping.")
    else:
        print("   - LHM n'expose AUCUN capteur CPU : probablement CPU trop recent")
        print("     pour la DLL 0.9.6 -> tester une DLL LHM plus recente.")
    print("\n   >>> Copie-colle toute cette sortie pour qu'on cible le bon correctif.")


if __name__ == "__main__":
    main()
