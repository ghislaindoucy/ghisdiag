@echo off
setlocal enabledelayedexpansion

rem Ghisdiag - Lanceur de la sonde GPU d'atelier (voir GPU_BENCH_PROGRESS.md).
rem Se place tout seul dans le dossier du script (marche depuis une cle USB,
rem quel que soit le lecteur), trouve Python (py ou python), et ecrit un
rem rapport JSON horodate a cote de ce fichier.

cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul
if not errorlevel 1 set "PYEXE=py"

if not defined PYEXE (
    where python >nul 2>nul
    if not errorlevel 1 set "PYEXE=python"
)

if not defined PYEXE (
    set "ERRFILE=%~dp0ghisdiag_gpu_test_ERREUR_%COMPUTERNAME%.txt"
    echo Python introuvable sur cette machine.> "!ERRFILE!"
    echo Installer Python via winget install Python.Python.3.12, puis relancer ce script.>> "!ERRFILE!"
    echo.
    echo [ERREUR] Python introuvable sur cette machine.
    echo Message ecrit dans : !ERRFILE!
    echo Installe Python via winget install Python.Python.3.12, puis relance ce script.
    echo.
    pause
    exit /b 1
)

echo Interpreteur utilise : %PYEXE%
echo.
%PYEXE% "%~dp0atelier_probe.py"

echo.
pause
