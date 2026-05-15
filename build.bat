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
echo [1/4] Vérification des dépendances...
py -m pip install pyinstaller --quiet
py -m pip install psutil --quiet

:: Nettoyage
echo [2/4] Nettoyage des anciens fichiers...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist PlanetDiag.spec del PlanetDiag.spec

:: Création du manifest UAC (demande élévation admin)
echo [3/4] Création du manifest UAC...
(
echo ^<?xml version="1.0" encoding="UTF-8" standalone="yes"?^>
echo ^<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0"^>
echo   ^<assemblyIdentity version="1.0.0.0" processorArchitecture="X86"
echo     name="PlanetDiag" type="win32"/^>
echo   ^<trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"^>
echo     ^<security^>^<requestedPrivileges^>
echo       ^<requestedExecutionLevel level="requireAdministrator" uiAccess="false"/^>
echo     ^</requestedPrivileges^>^</security^>
echo   ^</trustInfo^>
echo ^</assembly^>
) > PlanetDiag.manifest

:: Compilation
echo [4/4] Compilation en cours...
py -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name PlanetDiag ^
    --manifest PlanetDiag.manifest ^
    --add-data "collectors;collectors" ^
    --add-data "assets;assets" ^
    --add-data "report;report" ^
    --add-binary "tools\smartctl.exe;tools" ^
    --hidden-import tkinter ^
    --hidden-import tkinter.ttk ^
    --hidden-import json ^
    --hidden-import threading ^
    --hidden-import psutil ^
    --hidden-import collectors.realtime_monitor ^
    --icon assets\icon.ico ^
    main.py

if errorlevel 1 (
    echo.
    echo ERREUR: La compilation a échoué.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Compilation réussie !
echo  Fichier : dist\PlanetDiag.exe
echo ============================================================
pause
