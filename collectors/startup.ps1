# Ghisdiag - Collecteur Démarrage Windows
# Collecte les programmes démarrage, services, tâches planifiées, durée boot

$ErrorActionPreference = "SilentlyContinue"
$result = @{}
$errors = @()
$notes  = @()

. "$PSScriptRoot\_common.ps1"

# ── Programmes au démarrage (registre + dossier Startup) ────────────────────
$startupItems = @()

$regPaths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
)

foreach ($path in $regPaths) {
    try {
        $regKey = Get-ItemProperty -Path $path -ErrorAction Stop
        $regKey.PSObject.Properties | Where-Object { $_.Name -notlike "PS*" } | ForEach-Object {
            $startupItems += @{
                name     = $_.Name
                command  = $_.Value
                location = $path -replace "HK[LC][MU]:\\", ""
                type     = "Registry"
                hive     = if ($path -like "HKLM:*") { "HKLM" } else { "HKCU" }
            }
        }
    } catch {
        # WOW6432Node absent sur certaines configs (normal sur Windows 64-bit sans
        # applications 32-bit installées), clé inexistante = pas une erreur.
        $notes += "[Startup_Reg] Clé absente (normal) : $($path -replace 'HKLM:\\','')"
    }
}

$startupFolders = @(
    [System.Environment]::GetFolderPath("CommonStartup"),
    [System.Environment]::GetFolderPath("Startup")
)

foreach ($folder in $startupFolders) {
    if (Test-Path $folder) {
        Get-ChildItem $folder -File | ForEach-Object {
            $startupItems += @{
                name     = $_.BaseName
                command  = $_.FullName
                location = $folder
                type     = "StartupFolder"
                hive     = if ($folder -like "*All Users*" -or $folder -like "*ProgramData*") { "AllUsers" } else { "CurrentUser" }
            }
        }
    }
}

$result["startup_programs"] = $startupItems

# ── Services auto-démarrage ──────────────────────────────────────────────────
$services = Safe-Get {
    Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq "Auto" } |
    Sort-Object State, Name | ForEach-Object {
        @{
            name         = $_.Name
            display_name = $_.DisplayName
            state        = $_.State
            start_mode   = $_.StartMode
            path         = $_.PathName
            pid          = $_.ProcessId
            delayed      = ($_.StartMode -eq "Auto" -and $_.DelayedAutoStart)
        }
    }
} "Services" @()

$servicesRunning = ($services | Where-Object { $_["state"] -eq "Running" }).Count
$servicesStopped = ($services | Where-Object { $_["state"] -eq "Stopped" }).Count

$result["services"] = @{
    auto_start_total   = $services.Count
    running            = $servicesRunning
    stopped            = $servicesStopped
    items              = $services
}

# ── Tâches planifiées actives ────────────────────────────────────────────────
$tasks = Safe-Get {
    Get-ScheduledTask | Where-Object { $_.State -eq "Ready" -and $_.TaskPath -notlike "\Microsoft\*" } |
    Select-Object -First 50 | ForEach-Object {
        $info = $_ | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
        @{
            name          = $_.TaskName
            path          = $_.TaskPath
            state         = $_.State
            last_run      = if ($info.LastRunTime -and $info.LastRunTime -gt [datetime]::MinValue) {
                                try { $info.LastRunTime.ToString("yyyy-MM-dd HH:mm:ss") } catch { "N/A" }
                            } else { "Never" }
            last_result   = if ($info) { $info.LastTaskResult } else { $null }
            next_run      = if ($info.NextRunTime -and $info.NextRunTime -gt [datetime]::MinValue) {
                                try { $info.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss") } catch { "N/A" }
                            } else { "N/A" }
        }
    }
} "ScheduledTasks" @()

$result["scheduled_tasks"] = @{
    non_microsoft_count = $tasks.Count
    items               = $tasks
}

# ── Durée du dernier démarrage Windows (Event ID 6005/6006) ─────────────────
$bootEvents = Safe-Get {
    # 30 jours au lieu de 7 pour capturer les machines peu redémarrées
    $startEvent = Get-WinEvent -FilterHashtable @{
        LogName = 'System'; Id = 6005; StartTime = (Get-Date).AddDays(-30)
    } -MaxEvents 1 -ErrorAction Stop

    $shutdownEvent = Get-WinEvent -FilterHashtable @{
        LogName = 'System'; Id = 6006; StartTime = (Get-Date).AddDays(-30)
    } -MaxEvents 1 -ErrorAction Stop

    @{
        last_boot_start    = if ($startEvent)    { $startEvent.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss") }    else { "N/A" }
        last_shutdown_time = if ($shutdownEvent) { $shutdownEvent.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss") } else { "N/A" }
    }
} "BootEvents" @{ last_boot_start = "N/A"; last_shutdown_time = "N/A" }

# ── Temps de démarrage kernel via Event ID 12 (Kernel-General) ──────────────
$kernelBoot = Safe-Get {
    $ev = Get-WinEvent -FilterHashtable @{
        LogName = 'System'
        ProviderName = 'Microsoft-Windows-Kernel-General'
        Id = 12
    } -MaxEvents 1 -ErrorAction Stop
    @{ boot_time = $ev.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss") }
} "KernelBoot" @{ boot_time = "N/A" }

$result["boot_info"] = $bootEvents + $kernelBoot

$result["collector_errors"] = $errors
$result["collector_notes"]  = $notes
$result["collected_at"]     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]        = "startup"

$result | ConvertTo-Json -Depth 10 -Compress
