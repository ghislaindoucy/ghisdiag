@echo off
setlocal

echo ============================================================
echo  Ghisdiag - Compilation PyInstaller
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
:: numpy : noyau de charge AVX du bench thermique (mode stabilite). Sans lui, le
:: bench retombe automatiquement sur la charge Python (moins intensive).
py -m pip install numpy --quiet
:: Dépendances de la fonctionnalité Analyse IA (sinon désactivée à l'exécution)
py -m pip install requests --quiet
py -m pip install cryptography --quiet

:: Nettoyage — on ne supprime PLUS Ghisdiag.spec : il est versionné (voir ci-dessous)
echo [2/5] Nettoyage des anciens fichiers...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

:: Ghisdiag.spec et Ghisdiag.manifest sont désormais versionnés dans le dépôt, et
:: c'est ce build.bat qui les consomme au lieu de les régénérer. Raison : GitHub
:: Actions compile avec exactement les mêmes options. PyInstaller ne produit pas un
:: binaire identique au bit près d'un build à l'autre, mais c'est le binaire compilé
:: par la CI qui est publié ET attesté : l'attestation lie son empreinte au commit
:: source public (docs/antivirus-guide.md).
::
:: Pour modifier une option de compilation, éditez Ghisdiag.spec.
:: Pour changer le numéro de version, éditez version_info.txt ET Ghisdiag.manifest.
echo [3/5] Vérification des fichiers de build...
if not exist Ghisdiag.spec (
    echo ERREUR: Ghisdiag.spec introuvable.
    pause & exit /b 1
)
if not exist Ghisdiag.manifest (
    echo ERREUR: Ghisdiag.manifest introuvable.
    pause & exit /b 1
)

:: Compilation depuis le .spec versionné — options identiques à celles de la CI.
:: Mode ONEDIR : la sortie est un DOSSIER dist\Ghisdiag\ (exe + DLL à côté), pas
:: un fichier unique. Voir l'en-tête de Ghisdiag.spec pour le pourquoi.
echo [4/6] Compilation en cours...
py -m PyInstaller --clean --noconfirm Ghisdiag.spec

if errorlevel 1 (
    echo.
    echo ERREUR: La compilation a échoué.
    pause & exit /b 1
)

if not exist "dist\Ghisdiag\Ghisdiag.exe" (
    echo ERREUR: dist\Ghisdiag\Ghisdiag.exe introuvable après compilation.
    pause & exit /b 1
)

:: Notice utilisateur livrée AVEC l'application, posée à côté de Ghisdiag.exe (et
:: non dans _internal\, où personne ne va la chercher). Elle est ainsi présente
:: sur la clé USB d'atelier comme dans l'archive téléchargée.
:: Erreur bloquante si elle manque : une archive publiée sans notice est un
:: oubli silencieux, exactement le genre de dérive qu'on cherche à éviter.
if not exist "docs\Notice_Ghisdiag.pdf" (
    echo ERREUR: docs\Notice_Ghisdiag.pdf introuvable.
    pause & exit /b 1
)
copy /y "docs\Notice_Ghisdiag.pdf" "dist\Ghisdiag\Notice_Ghisdiag.pdf" >nul
if errorlevel 1 (
    echo ERREUR: copie de la notice dans dist\Ghisdiag\ impossible.
    pause & exit /b 1
)

:: Archive prête à distribuer / à copier sur la clé atelier. Volontairement sans
:: numéro de version dans le nom : la version vit dans version_info.txt et
:: Ghisdiag.manifest, en rajouter une ici recréerait un endroit à bumper.
echo [5/6] Création de l'archive de distribution...
if exist "dist\Ghisdiag.zip" del "dist\Ghisdiag.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\Ghisdiag\*' -DestinationPath 'dist\Ghisdiag.zip' -Force"

if errorlevel 1 (
    echo ERREUR: La création de l'archive a échoué.
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
:: En mode onedir, signer AVANT de créer l'archive (déplacer le bloc [5/6] après
:: celui-ci), et signer l'exe ET les DLL produites par PyInstaller :
::   dist\Ghisdiag\Ghisdiag.exe et dist\Ghisdiag\_internal\*.dll
::
:: echo [6/6] Signature numérique...
:: signtool sign ^
::     /tr http://timestamp.digicert.com ^
::     /td sha256 ^
::     /fd sha256 ^
::     /a ^
::     dist\Ghisdiag\Ghisdiag.exe
:: if errorlevel 1 (
::     echo ERREUR: La signature a échoué. Vérifiez votre certificat.
::     pause & exit /b 1
:: )
:: echo Signature OK.

echo [6/6] (Signature désactivée — voir commentaires dans build.bat)

echo.
echo ============================================================
echo  Compilation réussie ^(mode onedir^)
echo.
echo  Dossier  : dist\Ghisdiag\        ^(à copier sur la clé USB^)
echo  Exe      : dist\Ghisdiag\Ghisdiag.exe
echo  Notice   : dist\Ghisdiag\Notice_Ghisdiag.pdf
echo  Archive  : dist\Ghisdiag.zip     ^(à publier en release^)
echo ============================================================

:: Pour réduire les faux positifs antivirus, pensez à :
::   1. Activer la signature numérique ci-dessus
::   2. Soumettre dist\Ghisdiag\Ghisdiag.exe sur https://www.virustotal.com
::      puis signaler les faux positifs directement aux éditeurs AV
::   3. Voir le guide : docs/antivirus-guide.md

pause
