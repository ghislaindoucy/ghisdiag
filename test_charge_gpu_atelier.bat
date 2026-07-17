@echo off
setlocal enabledelayedexpansion

rem Ghisdiag - Lanceur du test de CHARGE GPU d'atelier (chantier M2).
rem Chauffe le GPU ~30 s et ecrit un rapport JSON horodate a cote de ce fichier.
rem Se place tout seul dans son dossier (marche depuis une cle USB).

cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    set "ERRFILE=%~dp0ghisdiag_charge_gpu_ERREUR_%COMPUTERNAME%.txt"
    echo Python introuvable sur cette machine.> "!ERRFILE!"
    echo Installer Python via winget install Python.Python.3.12, puis relancer.>> "!ERRFILE!"
    echo [ERREUR] Python introuvable. Voir !ERRFILE!
    echo.
    pause
    exit /b 1
)

echo Interpreteur utilise : %PYEXE%
echo.
echo Ce test va CHAUFFER le GPU pendant 30 secondes.
echo L'ecran peut devenir saccade pendant ce temps : c'est normal.
echo.
%PYEXE% "%~dp0atelier_gpu_load.py"

echo.
pause
