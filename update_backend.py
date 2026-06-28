#!/usr/bin/env python3
"""
Ghisdiag - Mise a jour du backend capteurs (LibreHardwareMonitor).

Sert a debloquer un CPU trop recent pour la DLL livree (ex. Zen 5) sans
recompiler Ghisdiag : on remplace le jeu de DLL par une version plus recente.

Usage :
    py update_backend.py                 etat + telecharge la derniere version (reseau)
    py update_backend.py chemin\\vers.zip  installe depuis une archive locale (hors ligne)
    py update_backend.py --info          affiche seulement l'etat, ne change rien

Le nouveau backend est depose dans %LOCALAPPDATA%\\Ghisdiag\\tools et prend le pas
sur la DLL embarquee au prochain demarrage de Ghisdiag.
"""

import sys

from collectors import lhm_backend


def _print_info() -> None:
    bi = lhm_backend.info()
    print("Backend capteurs actif :")
    print("  dossier   :", bi["active_dir"])
    print("  version   :", bi["version"])
    print("  override  :", "oui (DLL deposee)" if bi["override"] else "non (embarque)")
    print("  embarque  :", bi["embedded_dir"])
    print("  dossier maj:", bi["user_dir"])
    print("  ordre de recherche :")
    for c in bi["candidates"]:
        print("    -", c)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a]
    if "--info" in args or "-i" in args:
        _print_info()
        return 0

    _print_info()
    print()

    local = [a for a in args if not a.startswith("-")]
    if local:
        zip_path = local[0]
        print(f"Installation depuis l'archive locale : {zip_path}")
        res = lhm_backend.install_from_zip(zip_path)
    else:
        print("Telechargement de la derniere release LibreHardwareMonitor...")
        res = lhm_backend.update_from_github()
        if res.get("tag"):
            print("  release amont :", res["tag"], "| asset :", res.get("asset"))

    print()
    if res.get("ok"):
        print(f"OK - backend installe (v{res.get('version')}).")
        if res.get("copied"):
            print("  DLL :", ", ".join(res["copied"]))
        print("  -> Redemarre Ghisdiag pour utiliser ce backend.")
        return 0

    action = res.get("action")
    print(f"ECHEC ({action}) : {res.get('error')}")
    if action == "no_network":
        print("  Pas de reseau. Telecharge le zip net472 depuis")
        print("  https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases")
        print("  puis : py update_backend.py chemin\\vers\\le.zip")
    elif action in ("invalid", "install_invalid"):
        print("  L'archive ne contient pas LibreHardwareMonitorLib.dll.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
