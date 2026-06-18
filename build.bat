@echo off
setlocal

echo ============================================================
echo  PlanetDiag - Compilation PyInstaller
echo ============================================================

:: Vérification Python
py --version >nul 2>&1
if errorlevel 1 (
    echo ERREUR: Python n'est pas installé ou pas dans le PATH.
    pause & exit /b 1
)

:: Installation des dépendances si besoin
echo [1/5] Vérification des dépendances...
py -m pip install pyinstaller --quiet
py -m pip install psutil --quiet
:: Dépendances de la fonctionnalité Analyse IA Mistral (sinon désactivée à l'exécution)
py -m pip install requests --quiet
py -m pip install cryptography --quiet

:: Nettoyage
echo [2/5] Nettoyage des anciens fichiers...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist PlanetDiag.spec del PlanetDiag.spec

:: Création du manifest UAC (demande élévation admin)
echo [3/5] Création du manifest UAC...
(
echo ^<?xml version="1.0" encoding="UTF-8" standalone="yes"?^>
echo ^<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"^>
echo   ^<assemblyIdentity version="1.2.0.0" processorArchitecture="X86"
echo     name="PlanetDiag" type="win32"/^>
echo   ^<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"^>
echo     ^<security^>^<requestedPrivileges^>
echo       ^<requestedExecutionLevel level="requireAdministrator" uiAccess="false"/^>
echo     ^</requestedPrivileges^>^</security^>
echo   ^</trustInfo^>
echo ^</assembly^>
) > PlanetDiag.manifest

:: Compilation
echo [4/5] Compilation en cours...
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name PlanetDiag ^
    --manifest PlanetDiag.manifest ^
    --version-file version_info.txt ^
    --add-data "collectors;collectors" ^
    --add-data "assets;assets" ^
    --add-data "report;report" ^
    --add-binary "tools\smartctl.exe;tools" ^
    --add-binary "tools\LibreHardwareMonitorLib.dll;tools" ^
    --add-binary "tools\HidSharp.dll;tools" ^
    --add-binary "tools\BlackSharp.Core.dll;tools" ^
    --add-binary "tools\DiskInfoToolkit.dll;tools" ^
    --add-binary "tools\System.Memory.dll;tools" ^
    --add-binary "tools\System.Numerics.Vectors.dll;tools" ^
    --add-binary "tools\System.Runtime.CompilerServices.Unsafe.dll;tools" ^
    --add-binary "tools\PawnIO_setup.exe;tools" ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import json ^
    --hidden-import threading ^
    --hidden-import psutil ^
    --hidden-import requests ^
    --hidden-import cryptography ^
    --hidden-import mistral_analyzer ^
    --hidden-import mistral_report ^
    --hidden-import thermal_bench ^
    --hidden-import thermal_compare ^
    --collect-submodules cryptography ^
    --hidden-import collectors.realtime_monitor ^
    --hidden-import collectors.sensors ^
    --hidden-import collectors.pawnio ^
    --icon assets\icon.ico ^
    main.py

if errorlevel 1 (
    echo.
    echo ERREUR: La compilation a échoué.
    pause & exit /b 1
)

:: ── Signature numérique ──────────────────────────────────────────────────────
:: Décommentez ce bloc APRES avoir installé un certificat Code Signing dans
:: votre magasin de certificats Windows (Personal > Certificates).
::
:: Certificat standard (~70-200 €/an) : réduit les faux positifs AV.
:: Certificat EV       (~250-400 €/an) : réputation SmartScreen immédiate.
:: Fournisseurs : Sectigo, DigiCert, GlobalSign.
::
:: signtool.exe se trouve dans le Windows SDK :
::   C:\Program Files (x86)\Windows Kits\10\bin\<version>\x64\signtool.exe
:: Ou installez-le via : winget install Microsoft.WindowsSDK.10.0.22621
::
:: echo [5/5] Signature numérique...
:: signtool sign ^
::     /tr http://timestamp.digicert.com ^
::     /td sha256 ^
::     /fd sha256 ^
::     /a ^
::     dist\PlanetDiag.exe
:: if errorlevel 1 (
::     echo ERREUR: La signature a échoué. Vérifiez votre certificat.
::     pause & exit /b 1
:: )
:: echo Signature OK.

echo [5/5] (Signature désactivée — voir commentaires dans build.bat)

echo.
echo ============================================================
echo  Compilation réussie !
echo  Fichier : dist\PlanetDiag.exe
echo ============================================================

:: Pour réduire les faux positifs antivirus, pensez à :
::   1. Activer la signature numérique ci-dessus
::   2. Soumettre dist\PlanetDiag.exe sur https://www.virustotal.com
::      puis signaler les faux positifs directement aux éditeurs AV
::   3. Voir le guide : docs/antivirus-guide.md

pause
