r"""
GhisdiagDisk - lanceur (source du second executable du depot).

Build : py -m PyInstaller --clean --noconfirm GhisdiagDisk.spec
puis copier tout dist\GhisdiagDisk\ a la racine de la cle USB bootable.

Windows normal : test_ghisdiagdisk_atelier.bat, en tant qu'administrateur.
"""

import sys
import traceback
from pathlib import Path

if getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(sys._MEIPASS).resolve()))
else:
    sys.path.insert(0, str(Path(__file__).parent.resolve()))

from ghisdiagdisk import cli   # noqa: E402


if __name__ == "__main__":
    _code = 1
    try:
        _code = cli.main()
    except KeyboardInterrupt:
        print("\nInterrompu.")
        _code = 130
    except Exception:
        traceback.print_exc()
        _code = 1
    finally:
        # Gele = lance par double-clic, en WinPE comme en atelier : sans cette
        # pause la console se referme avant qu'on ait lu le verdict.
        if getattr(sys, "frozen", False):
            try:
                input("\nAppuyer sur Entree pour fermer cette fenetre...")
            except (EOFError, KeyboardInterrupt):
                pass
    sys.exit(_code)
