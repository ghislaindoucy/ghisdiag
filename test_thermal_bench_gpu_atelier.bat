@echo off
setlocal enabledelayedexpansion

rem Ghisdiag - Lanceur du test de terrain MOTEUR DE BENCH GPU (chantier M3).
rem Bench GPU complet (repos 15s -> charge 60s -> refroidissement 30s) via le
rem moteur thermal_bench generalise. Ecrit un rapport JSON horodate a cote de
rem ce fichier. Se place tout seul dans son dossier (marche depuis une cle USB).

cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"
if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    set "ERRFILE=%~dp0ghisdiag_thermal_bench_gpu_ERREUR_%COMPUTERNAME%.txt"
    echo Python introuvable sur cette machine.> "!ERRFILE!"
    echo Installer Python via winget install Python.Python.3.12, puis relancer.>> "!ERRFILE!"
    echo [ERREUR] Python introuvable. Voir !ERRFILE!
    echo.
    pause
    exit /b 1
)

echo Interpreteur utilise : %PYEXE%
echo.
echo Ce test va lancer un BENCH THERMIQUE GPU COMPLET (~1min45).
echo L'ecran peut devenir saccade pendant la charge : c'est normal.
echo.
%PYEXE% "%~dp0atelier_thermal_bench_gpu.py"

echo.
pause
