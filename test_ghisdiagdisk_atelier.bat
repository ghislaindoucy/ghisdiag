@echo off
setlocal enabledelayedexpansion

rem Ghisdiag - Lanceur d'essai de GhisdiagDisk sur un WINDOWS NORMAL.
rem
rem ATTENTION : hors WinPE les latences sont mesurees mais NON CONCLUANTES
rem (l'I/O de fond de l'OS pollue les maximums par bloc). Sur la cle bootable,
rem c'est GhisdiagDisk.exe qu'on lance (build : py -m PyInstaller --clean
rem --noconfirm GhisdiagDisk.spec).
rem
rem L'acces disque brut exige l'elevation : lancer en tant qu'administrateur,
rem sinon l'inventaire remontera vide.
rem
rem Arguments transmis tels quels, ex. :  test_ghisdiagdisk_atelier.bat --lister
rem                                        test_ghisdiagdisk_atelier.bat --disque 1 --mode express

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
%PYEXE% "%~dp0ghisdiagdisk_main.py" %*

echo.
pause
