# -*- mode: python ; coding: utf-8 -*-
#
# GhisdiagDisk — second exécutable du dépôt (outil disque autonome, bootable).
# Configuration PyInstaller en mode ONEDIR, calquée sur WinPEProbe.spec qui a
# été validé en Hiren's BootCD PE le 03/09/2026.
#
# Build :  py -m PyInstaller --clean --noconfirm GhisdiagDisk.spec
#          (même invocation que build.bat — `pyinstaller` tout court n'est pas
#           dans le PATH quand le paquet est installé sans ses scripts)
# Puis copier tout dist\GhisdiagDisk\ à la racine de la clé USB bootable.
#
# console=True : première livraison en mode console (lisible en 800×600) ;
# l'UI tkinter viendra après validation atelier du moteur.
#
# Périmètre volontairement maigre : pas de collecteurs PowerShell, pas de DLL
# .NET, pas de PawnIO. Seul smartctl.exe est embarqué. WinPE n'a ni .NET ni
# PowerShell, et c'est aussi ce qui garde ce binaire peu suspect pour les
# heuristiques antivirus (il ouvre les disques en accès brut, ce qui coche
# déjà des cases).
#
# upx=False, comme Ghisdiag.spec : la compression est un marqueur de packer.

a = Analysis(
    ['ghisdiagdisk_main.py'],
    pathex=[],
    binaries=[('tools\\smartctl.exe', 'tools')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'psutil', 'requests', 'cryptography', 'PIL', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GhisdiagDisk',
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
    # L'accès disque brut exige l'élévation sur un Windows normal. En WinPE le
    # contexte est déjà privilégié, le manifeste est neutre.
    uac_admin=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GhisdiagDisk',
)
