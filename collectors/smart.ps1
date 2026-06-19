# Ghisdiag - Collecteur Sante SMART
# Lit les donnees SMART/NVMe via smartctl.exe (smartmontools 7.5+)
# Necessite des droits admin pour acceder aux registres SMART.
# Retourne un objet JSON.

param(
    [switch]$AsJson
)

$ErrorActionPreference = "SilentlyContinue"

. "$PSScriptRoot\_common.ps1"

$result = @{
    available        = $false
    smartctl_path    = $null
    smartctl_version = $null
    disks            = @()
    collector_errors = @()
    collector_notes  = @()
}

# Resolution du binaire smartctl (embarque via PyInstaller --add-binary)
$smartctl = Join-Path $PSScriptRoot "..\tools\smartctl.exe"
$smartctl = [System.IO.Path]::GetFullPath($smartctl)

if (-not (Test-Path $smartctl)) {
    $result.collector_notes += "smartctl.exe introuvable a l'emplacement attendu : $smartctl"
    $result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $result["collector"] = "disk_health"
    $result | ConvertTo-Json -Depth 12 -Compress
    return
}

$result.smartctl_path = $smartctl
$result.available = $true

# ─────────────────────────────────────────────────────────────────────────────
# Helper : appel smartctl via [System.Diagnostics.Process] (timeout strict).
# Plus fiable que Start-Process -PassThru / WaitForExit qui peut bloquer en
# PS 5.1 (cf. https://github.com/PowerShell/PowerShell/issues/3970).
# ─────────────────────────────────────────────────────────────────────────────
function Start-SmartctlProc {
    param([string[]]$ArgList)

    # Quoting des arguments contenant des espaces
    $quotedArgs = $ArgList | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $smartctl
    $psi.Arguments              = ($quotedArgs -join ' ')
    $psi.UseShellExecute        = $false
    $psi.CreateNoWindow         = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    # Eviter le hijacking : pas d'heritage de window station
    $psi.WindowStyle            = [System.Diagnostics.ProcessWindowStyle]::Hidden

    $proc = [System.Diagnostics.Process]::new()
    $proc.StartInfo = $psi
    [void]$proc.Start()

    # Lire stdout en async pour ne pas bloquer si le buffer pipe se remplit
    # (smartctl -a peut sortir 10-15 ko). Sans ca, le proc peut bloquer en
    # ecriture si on attend uniquement WaitForExit.
    $stdoutTask = $proc.StandardOutput.ReadToEndAsync()

    return @{
        proc       = $proc
        stdoutTask = $stdoutTask
    }
}

# Attente d'un job (Wait avec timeout strict) et collecte de la sortie
function Wait-SmartctlProc {
    param($Job, [int]$TimeoutMs)

    $proc       = $Job.proc
    $stdoutTask = $Job.stdoutTask

    try {
        $finished = $proc.WaitForExit($TimeoutMs)
    } catch {
        $finished = $false
    }

    if (-not $finished) {
        try { $proc.Kill() } catch {}
        try { $proc.WaitForExit(2000) } catch {}
        try { $proc.Dispose() } catch {}
        return @{ ok = $false; error = "timeout apres $($TimeoutMs)ms"; data = $null; raw = "" }
    }

    $text = ""
    try {
        # Attendre la fin de la lecture async (avec safety net)
        if ($stdoutTask.Wait(3000)) {
            $text = $stdoutTask.Result
        }
    } catch {}

    try { $proc.Dispose() } catch {}

    if ([string]::IsNullOrWhiteSpace($text)) {
        return @{ ok = $false; error = "sortie vide"; data = $null; raw = "" }
    }

    try {
        $obj = $text | ConvertFrom-Json -ErrorAction Stop
        return @{ ok = $true; error = $null; data = $obj; raw = $text }
    } catch {
        return @{ ok = $false; error = "JSON invalide: $($_.Exception.Message)"; data = $null; raw = $text }
    }
}

# Appel synchrone (lancement + attente) - utilise pour --scan
function Invoke-Smartctl {
    param([string[]]$ArgList, [int]$TimeoutMs = 15000)
    $job = Start-SmartctlProc -ArgList $ArgList
    return Wait-SmartctlProc -Job $job -TimeoutMs $TimeoutMs
}

# ─────────────────────────────────────────────────────────────────────────────
# Scan des devices
# ─────────────────────────────────────────────────────────────────────────────
$scanRes = Invoke-Smartctl -ArgList @("--scan", "-j") -TimeoutMs 10000
if ($scanRes.ok -and $scanRes.data.smartctl -and $scanRes.data.smartctl.version) {
    $result.smartctl_version = ($scanRes.data.smartctl.version -join ".")
}
if (-not $scanRes.ok) {
    $result.collector_errors += "Echec --scan : $($scanRes.error)"
    $result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $result["collector"] = "disk_health"
    $result | ConvertTo-Json -Depth 12 -Compress
    return
}

$rawDevices = @($scanRes.data.devices)
if ($rawDevices.Count -eq 0) {
    $result.collector_notes += "Aucun device detecte par smartctl --scan"
    $result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $result["collector"] = "disk_health"
    $result | ConvertTo-Json -Depth 12 -Compress
    return
}

# ─────────────────────────────────────────────────────────────────────────────
# Pre-filtrage des devices : retirer les drives optiques (DVD/BD/CD) qui font
# hanger smartctl sur le SMART read. On utilise Get-PhysicalDisk + Get-CimInstance
# pour cross-checker. Si le device n'est pas un HDD/SSD/NVMe, on le skip.
# ─────────────────────────────────────────────────────────────────────────────
$opticalSignatures = @()
try {
    # MediaType=5 = DVD/CD ; FriendlyName contenant DVD/BD/CD-ROM
    $opticals = Get-CimInstance Win32_CDROMDrive -ErrorAction SilentlyContinue -OperationTimeoutSec 3
    foreach ($od in @($opticals)) {
        if ($od.Name)  { $opticalSignatures += ([string]$od.Name).Trim() }
        if ($od.Model) { $opticalSignatures += ([string]$od.Model).Trim() }
        if ($od.Caption) { $opticalSignatures += ([string]$od.Caption).Trim() }
    }
} catch {}

function Test-IsOpticalName {
    param([string]$Name)
    if (-not $Name) { return $false }
    # Match par sous-chaine connue (DVDRAM, DVD-RW, BD-RE, BLU-RAY, etc.)
    if ($Name -match '(?i)dvd|blu[- ]?ray|bd[- ]?re|bd[- ]?rom|cd[- ]?rom|cd[- ]?rw') {
        return $true
    }
    return $false
}

$devices = @()
foreach ($dev in $rawDevices) {
    if (-not $dev) { continue }
    if (-not $dev.name) { continue }
    # Filtre 1 : info_name explicite optique
    if ($dev.info_name -and (Test-IsOpticalName $dev.info_name)) {
        $result.collector_notes += "Skip $($dev.name) : drive optique detecte ($($dev.info_name))"
        continue
    }
    $devices += $dev
}

# ─────────────────────────────────────────────────────────────────────────────
# Decoder le bitfield NVMe critical_warning -> liste de chaines lisibles
# ─────────────────────────────────────────────────────────────────────────────
function Decode-NvmeCriticalWarning {
    param([int]$Bits)
    $flags = @()
    if ($Bits -band 1)  { $flags += "spare_space_below_threshold" }
    if ($Bits -band 2)  { $flags += "temperature_outside_threshold" }
    if ($Bits -band 4)  { $flags += "nvm_subsystem_reliability_degraded" }
    if ($Bits -band 8)  { $flags += "read_only_mode" }
    if ($Bits -band 16) { $flags += "volatile_memory_backup_failed" }
    if ($Bits -band 32) { $flags += "persistent_memory_region_unreliable" }
    return $flags
}

# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 : lancer tous les smartctl en parallele
# ─────────────────────────────────────────────────────────────────────────────
$PARALLEL_TIMEOUT_MS = 15000   # deadline globale partagee par tous les devices
$parallelJobs = [System.Collections.Generic.List[hashtable]]::new()
$startAll = Get-Date

foreach ($dev in $devices) {
    $devName = $dev.name
    $devType = $dev.type
    if (-not $devName) { continue }

    $argList = @("-a", $devName, "-j")
    if ($devType) { $argList = @("-d", $devType) + $argList }

    try {
        $job = Start-SmartctlProc -ArgList $argList
        $parallelJobs.Add(@{
            job     = $job
            devName = $devName
            devType = $devType
        })
    } catch {
        $result.collector_errors += "Lancement impossible pour ${devName} : $($_.Exception.Message)"
    }
}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 2 : collecter les resultats avec deadline globale stricte
# Chaque WaitForExit() respecte sa borne grace a System.Diagnostics.Process
# ─────────────────────────────────────────────────────────────────────────────
$seenSerials = @{}   # deduplication des doublons (ex: CSMI vs SATA pour le meme disque)

foreach ($entry in $parallelJobs) {
    $devName = $entry.devName
    $devType = $entry.devType
    $job     = $entry.job

    $waitMs   = [math]::Max(1, $PARALLEL_TIMEOUT_MS - [int]((Get-Date) - $startAll).TotalMilliseconds)
    $waitRes  = Wait-SmartctlProc -Job $job -TimeoutMs $waitMs

    if (-not $waitRes.ok) {
        $result.collector_errors += "Echec lecture ${devName} : $($waitRes.error)"
        continue
    }

    $d = $waitRes.data

    # Verification erreurs cote smartctl (exit_status est un bitfield)
    $exitStatus = 0
    if ($d.smartctl -and ($d.smartctl.PSObject.Properties.Name -contains "exit_status")) {
        $exitStatus = [int]$d.smartctl.exit_status
    }
    # bit 0 (cmd parse) ou bit 1 (open failed) = on n'a rien pu lire
    if ($exitStatus -band 3) {
        $msgs = @()
        if ($d.smartctl.messages) {
            foreach ($m in $d.smartctl.messages) { $msgs += $m.string }
        }
        $result.collector_errors += "${devName} non lisible (exit=$exitStatus) : $($msgs -join '; ')"
        continue
    }

    # Filtre post-lecture : si modele/info revele un drive optique, skip
    $modelName = [string]$d.model_name
    if (Test-IsOpticalName $modelName) {
        $result.collector_notes += "Skip ${devName} : drive optique (${modelName})"
        continue
    }
    # Filtre par signatures CDROM Win32
    foreach ($sig in $opticalSignatures) {
        if ($sig -and $modelName -and ($modelName -like "*$sig*" -or $sig -like "*$modelName*")) {
            $result.collector_notes += "Skip ${devName} : drive optique (${modelName})"
            $modelName = $null
            break
        }
    }
    if ($null -eq $modelName) { continue }

    # Deduplication par serial_number (CSMI vs SATA pour le meme SSD)
    $serial = [string]$d.serial_number
    if ($serial) {
        if ($seenSerials.ContainsKey($serial)) {
            $result.collector_notes += "Skip ${devName} : doublon de $($seenSerials[$serial]) (serial $serial)"
            continue
        }
        $seenSerials[$serial] = $devName
    }

    $entryObj = @{
        device                 = $devName
        type                   = if ($devType) { $devType } else { "unknown" }
        protocol               = if ($d.device -and $d.device.protocol) { $d.device.protocol } else { $null }
        model                  = $d.model_name
        serial                 = $d.serial_number
        firmware               = $d.firmware_version
        capacity_bytes         = if ($d.user_capacity -and $d.user_capacity.bytes) { [int64]$d.user_capacity.bytes } else { $null }
        rotation_rate          = $d.rotation_rate
        smart_supported        = $false
        smart_enabled          = $false
        smart_passed           = $null
        temperature_c          = $null
        power_on_hours         = $null
        power_cycles           = $null
        wear_percent           = $null
        reallocated_sectors    = $null
        pending_sectors        = $null
        uncorrectable_errors   = $null
        nvme_critical_warning  = @()
        nvme_available_spare   = $null
        nvme_spare_threshold   = $null
        nvme_media_errors      = $null
        nvme_unsafe_shutdowns  = $null
        ata_attributes         = @()
        smartctl_exit_status   = $exitStatus
        smartctl_messages      = @()
    }

    if ($d.smartctl -and $d.smartctl.messages) {
        foreach ($m in $d.smartctl.messages) {
            if ($m -and $m.string) { $entryObj.smartctl_messages += "$($m.severity): $($m.string)" }
        }
    }

    if ($d.smart_support) {
        $entryObj.smart_supported = [bool]$d.smart_support.available
        $entryObj.smart_enabled   = [bool]$d.smart_support.enabled
    }

    if ($d.smart_status -and ($d.smart_status.PSObject.Properties.Name -contains "passed")) {
        $entryObj.smart_passed = [bool]$d.smart_status.passed
    }

    if ($d.temperature -and ($d.temperature.PSObject.Properties.Name -contains "current")) {
        $entryObj.temperature_c = [int]$d.temperature.current
    }

    if ($d.power_on_time -and ($d.power_on_time.PSObject.Properties.Name -contains "hours")) {
        $entryObj.power_on_hours = [int]$d.power_on_time.hours
    }

    if ($d.PSObject.Properties.Name -contains "power_cycle_count") {
        $entryObj.power_cycles = [int]$d.power_cycle_count
    }

    # ── NVMe ───────────────────────────────────────────────────────────────
    if ($d.nvme_smart_health_information_log) {
        $nvme = $d.nvme_smart_health_information_log

        if ($nvme.PSObject.Properties.Name -contains "percentage_used") {
            $entryObj.wear_percent = [int]$nvme.percentage_used
        }
        if ($nvme.PSObject.Properties.Name -contains "available_spare") {
            $entryObj.nvme_available_spare = [int]$nvme.available_spare
        }
        if ($nvme.PSObject.Properties.Name -contains "available_spare_threshold") {
            $entryObj.nvme_spare_threshold = [int]$nvme.available_spare_threshold
        }
        if ($nvme.PSObject.Properties.Name -contains "media_errors") {
            $entryObj.nvme_media_errors    = [int64]$nvme.media_errors
            $entryObj.uncorrectable_errors = [int64]$nvme.media_errors
        }
        if ($nvme.PSObject.Properties.Name -contains "unsafe_shutdowns") {
            $entryObj.nvme_unsafe_shutdowns = [int64]$nvme.unsafe_shutdowns
        }
        if ($nvme.PSObject.Properties.Name -contains "critical_warning") {
            # @(...) force un tableau JSON [] meme si vide (PS 5.1 unwrap les empty arrays en $null)
            $entryObj.nvme_critical_warning = @(Decode-NvmeCriticalWarning -Bits ([int]$nvme.critical_warning))
        }
        if ($null -eq $entryObj.power_on_hours -and $nvme.PSObject.Properties.Name -contains "power_on_hours") {
            $entryObj.power_on_hours = [int]$nvme.power_on_hours
        }
        if ($null -eq $entryObj.power_cycles -and $nvme.PSObject.Properties.Name -contains "power_cycles") {
            $entryObj.power_cycles = [int]$nvme.power_cycles
        }
        if ($null -eq $entryObj.temperature_c -and $nvme.PSObject.Properties.Name -contains "temperature") {
            $entryObj.temperature_c = [int]$nvme.temperature
        }
    }

    # ── SATA / ATA ────────────────────────────────────────────────────────
    if ($d.ata_smart_attributes -and $d.ata_smart_attributes.table) {
        foreach ($attr in $d.ata_smart_attributes.table) {
            if (-not $attr) { continue }
            $rawVal = $null
            if ($attr.raw -and ($attr.raw.PSObject.Properties.Name -contains "value")) {
                $rawVal = [int64]$attr.raw.value
            }
            $rawStr = $null
            if ($attr.raw -and ($attr.raw.PSObject.Properties.Name -contains "string")) {
                $rawStr = [string]$attr.raw.string
            }
            $entryObj.ata_attributes += @{
                id          = [int]$attr.id
                name        = [string]$attr.name
                value       = if ($attr.PSObject.Properties.Name -contains "value")  { [int]$attr.value }  else { $null }
                worst       = if ($attr.PSObject.Properties.Name -contains "worst")  { [int]$attr.worst }  else { $null }
                thresh      = if ($attr.PSObject.Properties.Name -contains "thresh") { [int]$attr.thresh } else { $null }
                raw_value   = $rawVal
                raw_str     = $rawStr
                when_failed = if ($attr.PSObject.Properties.Name -contains "when_failed") { [string]$attr.when_failed } else { $null }
            }

            switch ([int]$attr.id) {
                5   { $entryObj.reallocated_sectors  = $rawVal }
                197 { $entryObj.pending_sectors      = $rawVal }
                198 { $entryObj.uncorrectable_errors = $rawVal }
                # SSD wear : attribut 169/177/202/231/233 selon constructeur
                169 { if ($null -eq $entryObj.wear_percent) { $entryObj.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                177 { if ($null -eq $entryObj.wear_percent) { $entryObj.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                202 { if ($null -eq $entryObj.wear_percent) { $entryObj.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                231 { if ($null -eq $entryObj.wear_percent) { $entryObj.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                233 { if ($null -eq $entryObj.wear_percent) { $entryObj.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
            }
        }
    }

    $result.disks += $entryObj
}

$result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"] = "disk_health"

$result | ConvertTo-Json -Depth 12 -Compress
