# Ghisdiag - Pose du correctif capteurs (frequences P-Core / E-Core)
#
# Remplace collectors\sensors.ps1 dans une installation Ghisdiag deja deployee,
# SANS recompiler : le build v2 embarque le dossier collectors\ en fichiers
# bruts sous _internal\. Sert a valider un correctif capteurs en atelier avant
# de refaire une release.
#
# L'original est TOUJOURS sauvegarde en sensors.ps1.bak avant ecrasement, et
# -Restore remet cet original en place.
#
# Usage (depuis le dossier qui contient ce script et sensors.ps1) :
#   powershell -ExecutionPolicy Bypass -File installer_correctif.ps1
#   powershell -ExecutionPolicy Bypass -File installer_correctif.ps1 -Cible "D:\Ghisdiag"
#   powershell -ExecutionPolicy Bypass -File installer_correctif.ps1 -Restore
#
# Pas de caractere non-ASCII (regle PS du projet).

param(
    [string]$Cible = "",
    [switch]$Restore
)

$ErrorActionPreference = "Stop"

function Trouver-Installations {
    $trouves = New-Object System.Collections.Generic.List[string]
    $pistes = @()
    if ($Cible) { $pistes += $Cible }
    $pistes += @(
        (Join-Path $PSScriptRoot "Ghisdiag"),
        (Join-Path $PSScriptRoot "..\Ghisdiag"),
        "D:\Ghisdiag", "C:\Ghisdiag",
        (Join-Path $env:LOCALAPPDATA "Programs\Ghisdiag"),
        (Join-Path $env:ProgramFiles "Ghisdiag")
    )
    foreach ($p in $pistes) {
        if (-not $p) { continue }
        $c = Join-Path $p "_internal\collectors\sensors.ps1"
        if (Test-Path $c) {
            $full = [System.IO.Path]::GetFullPath($c)
            if (-not $trouves.Contains($full)) { $trouves.Add($full) }
        }
    }
    return $trouves
}

Write-Host "=============================================================="
Write-Host " GHISDIAG - correctif capteurs (frequences Intel hybride)"
Write-Host "=============================================================="

$cibles = Trouver-Installations
if ($cibles.Count -eq 0) {
    Write-Host ""
    Write-Host "Aucune installation Ghisdiag trouvee."
    Write-Host "Relance avec le chemin du dossier qui contient Ghisdiag.exe :"
    Write-Host "   .\installer_correctif.ps1 -Cible ""D:\Ghisdiag"""
    return
}

foreach ($cible in $cibles) {
    $bak = "$cible.bak"
    Write-Host ""
    Write-Host "Installation : $cible"

    if ($Restore) {
        if (Test-Path $bak) {
            Copy-Item $bak $cible -Force
            Write-Host "   original restaure depuis $bak"
        } else {
            Write-Host "   pas de sauvegarde : rien a restaurer"
        }
        continue
    }

    $source = Join-Path $PSScriptRoot "sensors.ps1"
    if (-not (Test-Path $source)) {
        Write-Host "   ERREUR : sensors.ps1 corrige introuvable a cote de ce script."
        continue
    }

    # Sauvegarde UNE SEULE FOIS : relancer le script ne doit pas ecraser
    # l'original par une version deja corrigee.
    if (-not (Test-Path $bak)) {
        Copy-Item $cible $bak -Force
        Write-Host "   sauvegarde  -> $bak"
    } else {
        Write-Host "   sauvegarde deja presente (conservee)"
    }

    Copy-Item $source $cible -Force
    Write-Host "   correctif   -> pose"
}

Write-Host ""
if ($Restore) {
    Write-Host "Restauration terminee."
} else {
    Write-Host "Termine. Relance Ghisdiag et refais un bench :"
    Write-Host "  - si clock_samples > 0 dans le JSON, les frequences remontent ;"
    Write-Host "  - le throttling passe alors de 'indetermine' a une vraie mesure."
    Write-Host ""
    Write-Host "Pour revenir en arriere : .\installer_correctif.ps1 -Restore"
}
