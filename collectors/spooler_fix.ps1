# PlanetDiag - Gestionnaire du Spooler d'impression
# Usage:
#   -Action list    → retourne l'état actuel du spooler (JSON)
#   -Action fix     → vide la file et redémarre le service (JSON)
#
# Doit être exécuté avec droits administrateur.

param(
    [ValidateSet("list", "fix")]
    [string]$Action = "list"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SPOOL_DIR = "$env:SystemRoot\System32\spool\PRINTERS"

function Get-SpoolerStatus {
    try {
        $svc = Get-Service -Name Spooler
        return @{
            status     = $svc.Status.ToString()
            start_type = $svc.StartType.ToString()
        }
    } catch {
        return @{ status = "unknown"; start_type = "unknown" }
    }
}

function Get-QueueInfo {
    try {
        $files  = Get-ChildItem -Path $SPOOL_DIR -Force -ErrorAction SilentlyContinue
        $count  = if ($files) { @($files).Count } else { 0 }
        $bytes  = if ($files) { ($files | Measure-Object -Property Length -Sum).Sum } else { 0 }
        return @{ job_count = $count; total_bytes = $bytes }
    } catch {
        return @{ job_count = -1; total_bytes = -1 }
    }
}

# ── Action: list ─────────────────────────────────────────────────────────────
if ($Action -eq "list") {
    $result = @{
        action  = "list"
        service = Get-SpoolerStatus
        queue   = Get-QueueInfo
        success = $true
        error   = $null
    }
    Write-Output ($result | ConvertTo-Json -Depth 4)
    exit 0
}

# ── Action: fix ──────────────────────────────────────────────────────────────
$steps   = [System.Collections.Generic.List[string]]::new()
$success = $true
$errorMsg = $null

try {
    # 1. Arrêt du spooler
    $steps.Add("Arrêt du service Spooler…")
    $svc = Get-Service -Name Spooler
    if ($svc.Status -ne "Stopped") {
        Stop-Service -Name Spooler -Force -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Service -Name Spooler).Status -ne "Stopped" -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
        if ((Get-Service -Name Spooler).Status -ne "Stopped") {
            throw "Le service Spooler n'a pas pu s'arrêter dans les 30 secondes."
        }
    }
    $steps.Add("Service Spooler arrêté.")

    # 2. Vidage de la file d'impression
    $steps.Add("Suppression des travaux d'impression en attente…")
    $queueBefore = Get-QueueInfo
    if (Test-Path $SPOOL_DIR) {
        $items = Get-ChildItem -Path $SPOOL_DIR -Force -ErrorAction SilentlyContinue
        $removed = 0
        foreach ($item in $items) {
            try {
                Remove-Item -Path $item.FullName -Force -Recurse -ErrorAction Stop
                $removed++
            } catch {
                $steps.Add("Impossible de supprimer : $($item.Name)")
            }
        }
        $steps.Add("$removed travaux supprimés.")
    } else {
        $steps.Add("Dossier spool introuvable — ignoré.")
    }
    $queueAfter = Get-QueueInfo

    # 3. Redémarrage du spooler
    $steps.Add("Redémarrage du service Spooler…")
    Start-Service -Name Spooler -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Service -Name Spooler).Status -ne "Running" -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    $finalStatus = (Get-Service -Name Spooler).Status.ToString()
    if ($finalStatus -ne "Running") {
        throw "Le service Spooler n'a pas pu démarrer dans les 30 secondes."
    }
    $steps.Add("Service Spooler redémarré avec succès.")

} catch {
    $success  = $false
    $errorMsg = $_.Exception.Message
    $steps.Add("ERREUR : $errorMsg")
    # Tentative de redémarrage même en cas d'erreur
    try {
        Start-Service -Name Spooler -ErrorAction SilentlyContinue
    } catch {}
}

$result = @{
    action       = "fix"
    success      = $success
    error        = $errorMsg
    steps        = @($steps)
    queue_before = if ($null -ne $queueBefore) { $queueBefore } else { @{ job_count = -1 } }
    queue_after  = Get-QueueInfo
    service      = Get-SpoolerStatus
}
Write-Output ($result | ConvertTo-Json -Depth 4)
exit $(if ($success) { 0 } else { 1 })
