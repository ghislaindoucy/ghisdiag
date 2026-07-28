# Ghisdiag - Etat d'alimentation de la machine
#
# Releve ce qui plafonne (ou non) la puissance du CPU : mode d'alimentation
# Windows, plan actif, bornes de l'etat du processeur, secteur/batterie et
# charge en cours. A lancer AVANT et APRES un bench thermique quand deux runs
# de la meme machine ne donnent pas la meme temperature.
#
# Motif : deux benches du meme Altyk, tous deux sur secteur, ont donne 25 W et
# 40 W de consommation CPU - donc 70 C contre 96 C. Le budget de puissance
# avait change, mais rien ne l'enregistrait.
#
# Usage :  powershell -ExecutionPolicy Bypass -File dump_power_state.ps1
#
# Pas de caractere non-ASCII (regle PS du projet).

$ErrorActionPreference = "SilentlyContinue"

$out = New-Object System.Collections.Generic.List[string]
function Say([string]$t) { $out.Add($t); Write-Host $t }

Say "=============================================================="
Say " GHISDIAG - ETAT D'ALIMENTATION"
Say " $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')  -  $env:COMPUTERNAME"
Say "=============================================================="

# --- Mode d'alimentation Windows 11 (superposition du plan) ------------------
# Les trois modes du menu deroulant sont des "overlays" identifies par GUID.
$overlays = @{
    "961cc777-2547-4f9d-8174-7d86181b8a7a" = "Efficacite optimale (bride le turbo)"
    "00000000-0000-0000-0000-000000000000" = "Equilibre (recommande)"
    "ded574b5-45a0-4f42-8737-46345c09c238" = "Performances optimales"
}
$ov = (Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Power\User\PowerSchemes" `
                        -Name "ActiveOverlayAcPowerScheme").ActiveOverlayAcPowerScheme
Say ""
if ($ov) {
    $nom = $overlays[[string]$ov]
    if (-not $nom) { $nom = "inconnu ($ov)" }
    Say "Mode d'alimentation (secteur) : $nom"
} else {
    Say "Mode d'alimentation (secteur) : non renseigne (= Equilibre)"
}

# --- Plan d'alimentation actif ----------------------------------------------
$scheme = powercfg /getactivescheme
Say "Plan actif                    : $scheme"

# --- Bornes de l'etat du processeur -----------------------------------------
# PROCTHROTTLEMAX < 100 % coupe le turbo net : c'est LA cause a eliminer quand
# deux runs de la meme machine ne chauffent pas pareil.
Say ""
Say "Etat du processeur (100 % = turbo autorise) :"

# Les libelles de powercfg sont localises. On s'accroche donc aux seuls mots
# stables et sans accent : "alternatif" / "continu" en francais, "AC" / "DC" en
# anglais. La valeur est le dernier champ hexadecimal de la ligne.
function Get-PowerIndex($setting, $courant) {
    $lignes = powercfg /q SCHEME_CURRENT SUB_PROCESSOR $setting 2>$null
    foreach ($l in $lignes) {
        $est = if ($courant -eq "AC") { $l -match "alternatif|AC Power Setting" }
               else { $l -match "continu|DC Power Setting" }
        if ($est -and $l -match "0x([0-9a-fA-F]{8})") {
            return [Convert]::ToInt32($matches[1], 16)
        }
    }
    return $null
}

$maxAc = Get-PowerIndex "PROCTHROTTLEMAX" "AC"
$maxDc = Get-PowerIndex "PROCTHROTTLEMAX" "DC"
$minAc = Get-PowerIndex "PROCTHROTTLEMIN" "AC"

if ($null -ne $maxAc) {
    $alerte = if ($maxAc -lt 100) { "   <-- TURBO BRIDE" } else { "" }
    Say "   maximum sur secteur   : $maxAc %$alerte"
}
if ($null -ne $maxDc) { Say "   maximum sur batterie  : $maxDc %" }
if ($null -ne $minAc) { Say "   minimum sur secteur   : $minAc %" }
if ($null -eq $maxAc -and $null -eq $maxDc) {
    Say "   (powercfg n'a rien renvoye - relance dans un PowerShell administrateur)"
}

# --- Secteur / batterie ------------------------------------------------------
Say ""
$bs = Get-CimInstance -Namespace root\wmi -ClassName BatteryStatus -ErrorAction SilentlyContinue |
      Select-Object -First 1
$bat = Get-CimInstance -ClassName Win32_Battery -ErrorAction SilentlyContinue |
       Select-Object -First 1

if ($bs) {
    Say "Sur secteur                   : $(if ($bs.PowerOnline) { 'OUI' } else { 'NON (batterie)' })"
    Say "Batterie en charge            : $(if ($bs.Charging) { 'OUI  <-- rogne le budget CPU' } else { 'non' })"
    Say "Batterie en decharge          : $(if ($bs.Discharging) { 'OUI' } else { 'non' })"
}
if ($bat) {
    Say "Niveau de batterie            : $($bat.EstimatedChargeRemaining) %"
}
if (-not $bs -and -not $bat) {
    Say "Aucune batterie detectee (poste fixe ?)"
}

Say ""
Say "=============================================================="
Say " A relever avant ET apres un bench, et a me transmettre avec"
Say " le JSON de session."
Say "=============================================================="

$dest = Join-Path ([Environment]::GetFolderPath("Desktop")) "ghisdiag_alimentation.txt"
$out | Set-Content -Path $dest -Encoding utf8
Write-Host ""
Write-Host "Fichier : $dest"
