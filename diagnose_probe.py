#!/usr/bin/env python3
"""
Ghisdiag - Isolation du sous-systeme LibreHardwareMonitor qui se fige.

A lancer quand diagnose_sensors.py rapporte un TIMEOUT sur sensors.ps1 : on
ouvre LHM avec un seul sous-systeme actif a la fois (process separe + timeout
propre) pour reperer celui qui bloque.

  - Si 'cpu' est OK et seul un autre (mb / controller...) part en TIMEOUT,
    le correctif est de desactiver ce sous-systeme dans sensors.ps1.
  - Si 'cpu' lui-meme part en TIMEOUT, c'est la DLL LHM 0.9.6 qui ne supporte
    pas ce CPU (Zen 5) -> il faut une DLL plus recente.

Usage (console Administrateur) :
    python diagnose_probe.py
"""

import subprocess

from collectors.sensors import _PS_EXE, _NO_WINDOW, _base_path, active_tools_dir

_PROBE = _base_path() / "collectors" / "_probe_sensors.ps1"

# Ordre : on teste cpu en premier (c'est lui qui compte pour le bench).
_SUBS = ["cpu", "gpu", "storage", "mb", "controller"]

_TIMEOUT = 12.0


def _run(sub: str) -> str:
    args = [
        _PS_EXE, "-NonInteractive", "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", str(_PROBE), "-Enable", sub,
        "-ToolsDir", str(active_tools_dir()),
    ]
    try:
        proc = subprocess.run(
            args, capture_output=True, timeout=_TIMEOUT, shell=False,
            creationflags=_NO_WINDOW,
        )
        out = proc.stdout.decode("utf-8", errors="replace").strip()
        return out or "(aucune sortie)"
    except subprocess.TimeoutExpired:
        return f"TIMEOUT (>{_TIMEOUT:.0f}s)  <-- CE SOUS-SYSTEME BLOQUE"
    except Exception as exc:
        return f"ERREUR {type(exc).__name__}: {exc}"


def main() -> None:
    print("=" * 70)
    print(" ISOLATION SOUS-SYSTEMES LibreHardwareMonitor")
    print("=" * 70)
    if not _PROBE.is_file():
        print("\n  Probe introuvable :", _PROBE)
        return
    print(f"\n  (chaque sous-systeme teste seul, timeout {_TIMEOUT:.0f}s)\n")
    results = {}
    for sub in _SUBS:
        res = _run(sub)
        results[sub] = res
        print(f"  {sub:<11} -> {res}")

    print("\n" + "-" * 70)
    print(" LECTURE")
    print("-" * 70)
    cpu_res = results.get("cpu", "")
    blockers = [s for s, r in results.items() if "TIMEOUT" in r]
    if "TIMEOUT" in cpu_res:
        print("  Le sous-systeme CPU lui-meme se fige : la DLL LHM 0.9.6 ne gere")
        print("  pas ce processeur (Zen 5). -> Tester une DLL LHM plus recente.")
    elif cpu_res.startswith("OK"):
        print("  Le CPU s'ouvre correctement :", cpu_res)
        if blockers:
            print("  Sous-systeme(s) bloquant(s) :", ", ".join(blockers))
            print("  -> Correctif : desactiver ce(s) sous-systeme(s) dans sensors.ps1")
            print("     (le bench n'a besoin que du CPU). Je peux le faire.")
        else:
            print("  Aucun sous-systeme isole ne bloque : le figeage vient peut-etre")
            print("  d'une COMBINAISON. A creuser.")
    print("\n  >>> Copie-colle toute cette sortie.")


if __name__ == "__main__":
    main()
