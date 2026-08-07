# -*- mode: python ; coding: utf-8 -*-
#
# Sonde WinPE — configuration de compilation PyInstaller (mode ONEDIR).
#
# Pourquoi un exe alors que la sonde est un simple script : WinPE n'embarque
# AUCUN interpréteur Python. Le .bat de lancement ne sert donc qu'aux essais
# sur un Windows normal ; en PE, seul cet exe fonctionne.
#
# Build :  py -m PyInstaller --clean --noconfirm WinPEProbe.spec
#          (même invocation que build.bat — `pyinstaller` tout court n'est pas
#           dans le PATH quand le paquet est installé sans ses scripts)
# Puis copier tout dist\WinPEProbe\ à la racine de la clé USB bootable.
#
# console=True : on veut voir le déroulé et le verdict à l'écran en PE, où il
# n'y a ni Explorateur ni visionneuse JSON commode.
#
# Périmètre volontairement maigre — c'est ce qui distinguera aussi le futur
# GhisdiagDisk : pas de collecteurs PowerShell, pas de DLL .NET
# (LibreHardwareMonitor), pas de PawnIO. WinPE n'a ni .NET ni PowerShell.
# Seul smartctl.exe est embarqué.
#
# upx=False, comme Ghisdiag.spec : la compression est un marqueur de packer qui
# alourdit le score heuristique des antivirus sur un binaire sain.

a = Analysis(
    ['atelier_winpe_probe.py'],
    pathex=[],
    binaries=[('tools\\smartctl.exe', 'tools')],
    datas=[],
    hiddenimports=['tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'psutil', 'requests', 'cryptography', 'PIL'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WinPEProbe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # L'accès disque brut (\\.\PhysicalDriveN) exige l'élévation sur un Windows
    # normal. En WinPE le contexte est déjà privilégié, le manifeste est neutre.
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='WinPEProbe',
)
