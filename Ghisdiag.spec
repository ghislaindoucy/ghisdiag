# -*- mode: python ; coding: utf-8 -*-
#
# Ghisdiag — configuration de compilation PyInstaller (mode ONEDIR).
#
# Ce fichier est VERSIONNÉ et fait autorité : build.bat et GitHub Actions le
# consomment tous les deux (`pyinstaller --clean --noconfirm Ghisdiag.spec`).
# Toute option de compilation se change ici, nulle part ailleurs.
#
# Pourquoi onedir et non onefile :
#   - onefile décompresse ~34 Mo dans le %TEMP% de la machine cliente À CHAQUE
#     lancement. Sur une clé USB d'atelier c'est le goulot d'étranglement, et ça
#     laisse un dossier _MEI chez le client (parfois orphelin après un crash).
#   - ce même schéma « je m'extrais dans TEMP puis je m'exécute » est celui des
#     droppers : il pèse lourd dans le score heuristique des antivirus.
#     Voir docs/antivirus-guide.md.
#
# upx=False : la compression UPX est un marqueur de packer, elle ajoute des
# points au score heuristique même sur un binaire sain.

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['tkinter', 'tkinter.ttk', 'json', 'threading', 'psutil', 'numpy', 'requests', 'cryptography', 'ai_analyzer', 'ai_report', 'thermal_bench', 'thermal_compare', 'diag_compare', 'report.exec_summary', 'collectors.realtime_monitor', 'collectors.sensors', 'collectors.pawnio', 'collectors.gpu', 'collectors.gpu_load']
hiddenimports += collect_submodules('cryptography')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[('tools\\smartctl.exe', 'tools'), ('tools\\LibreHardwareMonitorLib.dll', 'tools'), ('tools\\HidSharp.dll', 'tools'), ('tools\\BlackSharp.Core.dll', 'tools'), ('tools\\DiskInfoToolkit.dll', 'tools'), ('tools\\System.Memory.dll', 'tools'), ('tools\\System.Numerics.Vectors.dll', 'tools'), ('tools\\System.Runtime.CompilerServices.Unsafe.dll', 'tools'), ('tools\\PawnIO_setup.exe', 'tools')],
    datas=[('collectors', 'collectors'), ('assets', 'assets'), ('report', 'report'), ('licenses', 'licenses'), ('THIRD-PARTY-NOTICES.md', '.')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# exclude_binaries=True : les DLL et données ne sont PAS embarquées dans l'exe,
# elles sont posées à côté par le COLLECT ci-dessous. C'est ce qui distingue
# onedir de onefile.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Ghisdiag',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version='version_info.txt',
    icon=['assets\\icon.ico'],
    manifest='Ghisdiag.manifest',
    # INDISPENSABLE : PyInstaller réécrit le <requestedExecutionLevel> du
    # manifeste fourni à partir de CE paramètre (winmanifest._set_execution_level).
    # Sans uac_admin=True, le requireAdministrator de Ghisdiag.manifest était
    # silencieusement remplacé par asInvoker — l'app se rattrapait au démarrage
    # via request_elevation() (main.py), au prix d'un double lancement du process.
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Ghisdiag',
)
