# PlanetDiag - Gestionnaire du Spooler d'impression
# Usage:
#   -Action list                                  -> statut service + nb total travaux (JSON)
#   -Action printers                              -> imprimantes + travaux par imprimante (JSON)
#   -Action cancel-job  -PrinterName <n> -JobId <id>  -> annule un travail specifique (JSON)
#   -Action cancel-all  -PrinterName <n>          -> annule tous les travaux d'une imprimante (JSON)
#   -Action fix                                   -> vide tout + redemarre service (JSON)
#
# Doit etre execute avec droits administrateur.

param(
    [ValidateSet("list", "printers", "cancel-job", "cancel-all", "fix")]
    [string]$Action = "list",

    [Parameter(Mandatory = $false)]
    [string]$PrinterName = "",

    [Parameter(Mandatory = $false)]
    [int]$JobId = -1
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$SPOOL_DIR = "$env:SystemRoot\System32\spool\PRINTERS"

function Test-SafeName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name.Length -gt 256)               { return $false }
    if ($Name -match '[;&|`$<>]')           { return $false }
    return $true
}

function Get-SpoolerStatus {
    try {
        $svc = Get-Service -Name Spooler
        return @{ status = $svc.Status.ToString(); start_type = $svc.StartType.ToString() }
    } catch {
        return @{ status = "unknown"; start_type = "unknown" }
    }
}

function Get-QueueInfo {
    try {
        $files = Get-ChildItem -Path $SPOOL_DIR -Force -ErrorAction SilentlyContinue
        $count = if ($files) { @($files).Count } else { 0 }
        $bytes = if ($files) { ($files | Measure-Object -Property Length -Sum).Sum } else { 0 }
        return @{ job_count = $count; total_bytes = [long]$bytes }
    } catch {
        return @{ job_count = -1; total_bytes = -1 }
    }
}

function Get-PrinterList {
    try {
        $printers = Get-Printer -ErrorAction Stop | Sort-Object -Property Name
        $list = foreach ($p in $printers) {
            $jobs = @()
            try {
                $rawJobs = Get-PrintJob -PrinterName $p.Name -ErrorAction SilentlyContinue
                if ($rawJobs) {
                    $jobs = @(foreach ($j in $rawJobs) {
                        $sizeKb = if ($j.Size -gt 0) { [math]::Round($j.Size / 1024, 1) } else { 0 }
                        $submitted = ""
                        try { $submitted = $j.SubmittedTime.ToString("HH:mm:ss") } catch {}
                        @{
                            id        = [int]$j.Id
                            document  = if ($j.DocumentName) { $j.DocumentName } else { "(sans nom)" }
                            user      = if ($j.UserName)     { $j.UserName }     else { "" }
                            status    = $j.JobStatus.ToString()
                            pages     = [int]$j.TotalPages
                            size_kb   = $sizeKb
                            submitted = $submitted
                        }
                    })
                }
            } catch {}

            @{
                name      = $p.Name
                status    = $p.PrinterStatus.ToString()
                is_default = [bool]$p.Default
                driver    = if ($p.DriverName)  { $p.DriverName }  else { "" }
                port      = if ($p.PortName)    { $p.PortName }    else { "" }
                job_count = $jobs.Count
                jobs      = $jobs
            }
        }
        return @{ success = $true; printers = @($list); error = $null }
    } catch {
        return @{ success = $false; printers = @(); error = $_.Exception.Message }
    }
}

# -- Action: list -------------------------------------------------------------
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

# -- Action: printers ---------------------------------------------------------
if ($Action -eq "printers") {
    $data = Get-PrinterList
    $data["action"]  = "printers"
    $data["service"] = Get-SpoolerStatus
    Write-Output ($data | ConvertTo-Json -Depth 6)
    exit 0
}

# -- Action: cancel-job -------------------------------------------------------
if ($Action -eq "cancel-job") {
    if (-not (Test-SafeName -Name $PrinterName) -or $JobId -lt 0) {
        $err = @{ action = "cancel-job"; success = $false; error = "Parametres invalides." }
        Write-Output ($err | ConvertTo-Json -Depth 2)
        exit 1
    }
    try {
        Remove-PrintJob -PrinterName $PrinterName -Id $JobId -ErrorAction Stop
        $result = @{ action = "cancel-job"; success = $true; error = $null;
                     printer = $PrinterName; job_id = $JobId }
    } catch {
        $result = @{ action = "cancel-job"; success = $false; error = $_.Exception.Message;
                     printer = $PrinterName; job_id = $JobId }
    }
    Write-Output ($result | ConvertTo-Json -Depth 2)
    exit $(if ($result.success) { 0 } else { 1 })
}

# -- Action: cancel-all -------------------------------------------------------
if ($Action -eq "cancel-all") {
    if (-not (Test-SafeName -Name $PrinterName)) {
        $err = @{ action = "cancel-all"; success = $false; error = "Nom d'imprimante invalide." }
        Write-Output ($err | ConvertTo-Json -Depth 2)
        exit 1
    }
    try {
        $jobs = Get-PrintJob -PrinterName $PrinterName -ErrorAction Stop
        $count = if ($jobs) { @($jobs).Count } else { 0 }
        if ($count -gt 0) {
            $jobs | Remove-PrintJob -ErrorAction Stop
        }
        $result = @{ action = "cancel-all"; success = $true; error = $null;
                     printer = $PrinterName; cancelled = $count }
    } catch {
        $result = @{ action = "cancel-all"; success = $false; error = $_.Exception.Message;
                     printer = $PrinterName; cancelled = 0 }
    }
    Write-Output ($result | ConvertTo-Json -Depth 2)
    exit $(if ($result.success) { 0 } else { 1 })
}

# -- Action: fix --------------------------------------------------------------
$steps    = [System.Collections.Generic.List[string]]::new()
$success  = $true
$errorMsg = $null

try {
    $steps.Add("Arret du service Spooler...")
    $svc = Get-Service -Name Spooler
    if ($svc.Status -ne "Stopped") {
        Stop-Service -Name Spooler -Force -ErrorAction Stop
        $deadline = (Get-Date).AddSeconds(30)
        while ((Get-Service -Name Spooler).Status -ne "Stopped" -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
        if ((Get-Service -Name Spooler).Status -ne "Stopped") {
            throw "Le service Spooler n'a pas pu s'arreter dans les 30 secondes."
        }
    }
    $steps.Add("Service Spooler arrete.")

    $steps.Add("Suppression des travaux en attente...")
    $queueBefore = Get-QueueInfo
    if (Test-Path $SPOOL_DIR) {
        $items   = Get-ChildItem -Path $SPOOL_DIR -Force -ErrorAction SilentlyContinue
        $removed = 0
        foreach ($item in $items) {
            try {
                Remove-Item -Path $item.FullName -Force -Recurse -ErrorAction Stop
                $removed++
            } catch {
                $steps.Add("Impossible de supprimer : $($item.Name)")
            }
        }
        $steps.Add("$removed fichiers supprimes.")
    } else {
        $steps.Add("Dossier spool introuvable - ignore.")
    }
    $queueAfter = Get-QueueInfo

    $steps.Add("Redemarrage du service Spooler...")
    Start-Service -Name Spooler -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Service -Name Spooler).Status -ne "Running" -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500
    }
    if ((Get-Service -Name Spooler).Status -ne "Running") {
        throw "Le service Spooler n'a pas pu demarrer dans les 30 secondes."
    }
    $steps.Add("Service Spooler redemarre avec succes.")

} catch {
    $success  = $false
    $errorMsg = $_.Exception.Message
    $steps.Add("ERREUR : $errorMsg")
    try { Start-Service -Name Spooler -ErrorAction SilentlyContinue } catch {}
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
