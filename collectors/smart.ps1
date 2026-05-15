# PlanetDiag - Collecteur Sante SMART
# Lit les donnees SMART/NVMe via smartctl.exe (smartmontools 7.5+)
# Necessite des droits admin pour acceder aux registres SMART.
# Retourne un objet JSON.

param(
    [switch]$AsJson
)

$ErrorActionPreference = "SilentlyContinue"

. "$PSScriptRoot\_common.ps1"

$result = @{
    available     = $false
    smartctl_path = $null
    smartctl_version = $null
    disks         = @()
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

# Helper : appel smartctl + parsing JSON, gestion erreurs
function Invoke-Smartctl {
    param([string[]]$ArgList)
    try {
        # Capture stdout uniquement. En PS 5.1, "2>&1" sur un .exe natif wrappe
        # chaque ligne stderr en ErrorRecord et casse le JSON.
        $raw = & $smartctl @ArgList
        $text = ($raw | Out-String)
        if ([string]::IsNullOrWhiteSpace($text)) {
            return @{ ok = $false; error = "sortie vide"; data = $null }
        }
        $obj = $text | ConvertFrom-Json -ErrorAction Stop
        return @{ ok = $true; error = $null; data = $obj }
    } catch {
        return @{ ok = $false; error = $_.Exception.Message; data = $null }
    }
}

# Scan des devices (la version smartctl est embarquee dans la reponse)
$scanRes = Invoke-Smartctl @("--scan", "-j")
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

$devices = @($scanRes.data.devices)
if ($devices.Count -eq 0) {
    $result.collector_notes += "Aucun device detecte par smartctl --scan"
    $result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $result["collector"] = "disk_health"
    $result | ConvertTo-Json -Depth 12 -Compress
    return
}

# Decoder le bitfield NVMe critical_warning -> liste de chaines lisibles
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

# Boucle par device
foreach ($dev in $devices) {
    if (-not $dev) { continue }

    $devName = $dev.name
    $devType = $dev.type
    if (-not $devName) { continue }

    $args = @("-a", $devName, "-j")
    if ($devType) { $args = @("-d", $devType) + $args }

    $diskRes = Invoke-Smartctl $args
    if (-not $diskRes.ok) {
        $result.collector_errors += "Echec lecture $devName : $($diskRes.error)"
        continue
    }
    $d = $diskRes.data

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
        $result.collector_errors += "$devName non lisible (exit=$exitStatus) : $($msgs -join '; ')"
        continue
    }

    $entry = @{
        device          = $devName
        type            = if ($devType) { $devType } else { "unknown" }
        protocol        = if ($d.device -and $d.device.protocol) { $d.device.protocol } else { $null }
        model           = $d.model_name
        serial          = $d.serial_number
        firmware        = $d.firmware_version
        capacity_bytes  = if ($d.user_capacity -and $d.user_capacity.bytes) { [int64]$d.user_capacity.bytes } else { $null }
        rotation_rate   = $d.rotation_rate
        smart_supported = $false
        smart_enabled   = $false
        smart_passed    = $null
        temperature_c   = $null
        power_on_hours  = $null
        power_cycles    = $null
        wear_percent    = $null
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
            if ($m -and $m.string) { $entry.smartctl_messages += "$($m.severity): $($m.string)" }
        }
    }

    if ($d.smart_support) {
        $entry.smart_supported = [bool]$d.smart_support.available
        $entry.smart_enabled   = [bool]$d.smart_support.enabled
    }

    if ($d.smart_status -and ($d.smart_status.PSObject.Properties.Name -contains "passed")) {
        $entry.smart_passed = [bool]$d.smart_status.passed
    }

    if ($d.temperature -and ($d.temperature.PSObject.Properties.Name -contains "current")) {
        $entry.temperature_c = [int]$d.temperature.current
    }

    if ($d.power_on_time -and ($d.power_on_time.PSObject.Properties.Name -contains "hours")) {
        $entry.power_on_hours = [int]$d.power_on_time.hours
    }

    if ($d.PSObject.Properties.Name -contains "power_cycle_count") {
        $entry.power_cycles = [int]$d.power_cycle_count
    }

    # ── NVMe ───────────────────────────────────────────────────────────────
    if ($d.nvme_smart_health_information_log) {
        $nvme = $d.nvme_smart_health_information_log

        if ($nvme.PSObject.Properties.Name -contains "percentage_used") {
            $entry.wear_percent = [int]$nvme.percentage_used
        }
        if ($nvme.PSObject.Properties.Name -contains "available_spare") {
            $entry.nvme_available_spare = [int]$nvme.available_spare
        }
        if ($nvme.PSObject.Properties.Name -contains "available_spare_threshold") {
            $entry.nvme_spare_threshold = [int]$nvme.available_spare_threshold
        }
        if ($nvme.PSObject.Properties.Name -contains "media_errors") {
            $entry.nvme_media_errors = [int64]$nvme.media_errors
            $entry.uncorrectable_errors = [int64]$nvme.media_errors
        }
        if ($nvme.PSObject.Properties.Name -contains "unsafe_shutdowns") {
            $entry.nvme_unsafe_shutdowns = [int64]$nvme.unsafe_shutdowns
        }
        if ($nvme.PSObject.Properties.Name -contains "critical_warning") {
            # @(...) pour forcer un tableau JSON [] meme si vide (PS 5.1 unwrap les empty arrays en $null)
            $entry.nvme_critical_warning = @(Decode-NvmeCriticalWarning -Bits ([int]$nvme.critical_warning))
        }
        # Power on hours / cycles : NVMe les a aussi dans le log dedie
        if ($null -eq $entry.power_on_hours -and $nvme.PSObject.Properties.Name -contains "power_on_hours") {
            $entry.power_on_hours = [int]$nvme.power_on_hours
        }
        if ($null -eq $entry.power_cycles -and $nvme.PSObject.Properties.Name -contains "power_cycles") {
            $entry.power_cycles = [int]$nvme.power_cycles
        }
        if ($null -eq $entry.temperature_c -and $nvme.PSObject.Properties.Name -contains "temperature") {
            $entry.temperature_c = [int]$nvme.temperature
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
            $entry.ata_attributes += @{
                id        = [int]$attr.id
                name      = [string]$attr.name
                value     = if ($attr.PSObject.Properties.Name -contains "value")  { [int]$attr.value }  else { $null }
                worst     = if ($attr.PSObject.Properties.Name -contains "worst")  { [int]$attr.worst }  else { $null }
                thresh    = if ($attr.PSObject.Properties.Name -contains "thresh") { [int]$attr.thresh } else { $null }
                raw_value = $rawVal
                raw_str   = $rawStr
                when_failed = if ($attr.PSObject.Properties.Name -contains "when_failed") { [string]$attr.when_failed } else { $null }
            }

            switch ([int]$attr.id) {
                5   { $entry.reallocated_sectors  = $rawVal }
                197 { $entry.pending_sectors      = $rawVal }
                198 { $entry.uncorrectable_errors = $rawVal }
                # SSD wear : attribut 169/177/202/231/233 selon constructeur
                169 { if ($null -eq $entry.wear_percent) { $entry.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                177 { if ($null -eq $entry.wear_percent) { $entry.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                202 { if ($null -eq $entry.wear_percent) { $entry.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                231 { if ($null -eq $entry.wear_percent) { $entry.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
                233 { if ($null -eq $entry.wear_percent) { $entry.wear_percent = [math]::Max(0, 100 - [int]$attr.value) } }
            }
        }
    }

    $result.disks += $entry
}

$result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"] = "disk_health"

$result | ConvertTo-Json -Depth 12 -Compress
