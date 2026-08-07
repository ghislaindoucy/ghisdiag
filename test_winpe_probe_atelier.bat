@echo off
setlocal enabledelayedexpansion

rem Ghisdiag - Lanceur de la sonde WinPE (chantier GhisdiagDisk, phase 0).
rem
rem ATTENTION : ce .bat ne sert QU'AUX ESSAIS SUR UN WINDOWS NORMAL. WinPE
rem n'embarque aucun Python : sur la cle bootable, c'est WinPEProbe.exe qu'on
rem lance (build : py -m PyInstaller --clean --noconfirm WinPEProbe.spec).
rem
rem L'acces disque brut exige l'elevation : lancer en tant qu'administrateur,
rem sinon l'enumeration des disques remontera vide.

cd /d "%~dp0"

net session >nul 2>nul
if errorlevel 1 (
    echo [!] Pas de droits administrateur : l'acces disque brut va echouer.
    echo     Relance ce script par clic droit ^> Executer en tant qu'administrateur.
    echo.
)

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"

if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo [ERREUR] Python introuvable sur cette machine.
    echo Installe Python via winget install Python.Python.3.12, puis relance.
    echo.
    pause
    exit /b 1
)

echo Interpreteur utilise : %PYEXE%
echo.
%PYEXE% "%~dp0atelier_winpe_probe.py"

echo.
pause
