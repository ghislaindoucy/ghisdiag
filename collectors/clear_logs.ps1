# Ghisdiag - Effacement des journaux d'événements Windows
# Nécessite les droits administrateur.
#
# Vide UNIQUEMENT les journaux que le diagnostic Ghisdiag analyse réellement
# (cf. collectors/events.ps1) afin d'obtenir une base de test propre après
# une réparation : les erreurs/crashs antérieurs à la réparation restent sinon
# visibles jusqu'à 14-30 jours selon le journal.
#
# Chaque journal est vidé via `wevtutil cl` avec gestion d'erreur individuelle :
# un journal verrouillé ou protégé est ignoré sans interrompre les autres.
#
# CAS PARTICULIER — journal Security : Windows réécrit *immédiatement* un
# événement 1102 « Le journal d'audit a été effacé ». C'est une protection
# forensique impossible à supprimer ; le journal ne sera donc jamais vide.
param(
    [switch]$IncludeSecurity
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Journaux lus par le diagnostic (collectors/events.ps1). Le journal "System"
# est le plus important : il concentre BSOD, Kernel-Power, erreurs disque,
# corruption NTFS, erreurs matérielles WHEA et échecs de services.
$targets = @(
    "System",
    "Application",
    "Setup",
    "Microsoft-Windows-Diagnostics-Performance/Operational",
    "Microsoft-Windows-GroupPolicy/Operational",
    "Microsoft-Windows-User Profile Service/Operational",
    "Microsoft-Windows-NetworkProfile/Operational",
    "Microsoft-Windows-WLAN-AutoConfig/Operational"
)

# Le journal de sécurité n'est vidé que sur demande explicite (génère 1102).
if ($IncludeSecurity) {
    $targets += "Security"
}

$wevtutil = "$env:SystemRoot\System32\wevtutil.exe"

$cleared = 0
$skipped = 0

Write-Output "Effacement des journaux d'evenements analyses par le diagnostic..."
Write-Output ""

foreach ($log in $targets) {
    # `wevtutil cl` pilote tout via son code de sortie : 0 = vide,
    # != 0 = journal absent, verrouille, protege ou acces refuse (ignore).
    & $wevtutil cl "$log" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Output "  OK $log"
        $cleared++
        if ($log -eq "Security") {
            Write-Output "       (un evenement 1102 'journal d'audit efface' est reecrit par Windows : normal)"
        }
    } else {
        Write-Output "  -  $log  (ignore : absent, verrouille ou acces refuse)"
        $skipped++
    }
}

Write-Output ""
Write-Output "Termine : $cleared journal(aux) vide(s), $skipped ignore(s)."

# Code de sortie : succes tant qu'au moins un journal a ete vide.
# 0 journal vide = probablement droits administrateur manquants.
if ($cleared -eq 0) {
    exit 1
}
exit 0
