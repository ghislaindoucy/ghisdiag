# Ghisdiag - Collecteur Système
# Collecte les informations système, matériel et BIOS
# Retourne un objet JSON

param(
    [switch]$AsJson
)

$ErrorActionPreference = "SilentlyContinue"
$result = @{}
$errors = @()

. "$PSScriptRoot\_common.ps1"

# ── OS ──────────────────────────────────────────────────────────────────────
$os = Safe-Get { Get-CimInstance Win32_OperatingSystem } "OS"
$cs = Safe-Get { Get-CimInstance Win32_ComputerSystem } "ComputerSystem"
$bios = Safe-Get { Get-CimInstance Win32_BIOS } "BIOS"
$board = Safe-Get { Get-CimInstance Win32_BaseBoard } "BaseBoard"

$installDate = $null
$lastBoot    = $null
$uptimeStr   = $null

if ($os) {
    try { $installDate = $os.InstallDate.ToString("yyyy-MM-dd HH:mm:ss") } catch {}
    try { $lastBoot    = $os.LastBootUpTime.ToString("yyyy-MM-dd HH:mm:ss") } catch {}
    try {
        $uptime = (Get-Date) - $os.LastBootUpTime
        $uptimeStr = "{0}j {1}h {2}m" -f [int]$uptime.TotalDays, $uptime.Hours, $uptime.Minutes
    } catch {}
}

$result["os"] = @{
    caption        = if ($os) { $os.Caption } else { "N/A" }
    version        = if ($os) { $os.Version } else { "N/A" }
    build_number   = if ($os) { $os.BuildNumber } else { "N/A" }
    architecture   = if ($os) { $os.OSArchitecture } else { "N/A" }
    install_date   = $installDate
    last_boot      = $lastBoot
    uptime         = $uptimeStr
    locale         = if ($os) { $os.Locale } else { "N/A" }
    system_drive   = if ($os) { $os.SystemDrive } else { "N/A" }
    windows_dir    = if ($os) { $os.WindowsDirectory } else { "N/A" }
}

# ── Ordinateur ──────────────────────────────────────────────────────────────
$currentUser = $env:USERNAME
$domain      = if ($cs -and $cs.Domain) { $cs.Domain } else { $env:USERDOMAIN }

$result["computer"] = @{
    name         = $env:COMPUTERNAME
    domain       = $domain
    current_user = $currentUser
    manufacturer = if ($cs) { $cs.Manufacturer } else { "N/A" }
    model        = if ($cs) { $cs.Model } else { "N/A" }
    system_type  = if ($cs) { $cs.SystemType } else { "N/A" }
    part_of_domain = if ($cs) { $cs.PartOfDomain } else { $false }
    workgroup    = if ($cs -and -not $cs.PartOfDomain) { $cs.Workgroup } else { $null }
}

# ── BIOS ────────────────────────────────────────────────────────────────────
$biosDate = $null
if ($bios -and $bios.ReleaseDate) {
    try { $biosDate = $bios.ReleaseDate.ToString("yyyy-MM-dd") } catch {}
}

$result["bios"] = @{
    manufacturer   = if ($bios) { $bios.Manufacturer } else { "N/A" }
    version        = if ($bios) { $bios.SMBIOSBIOSVersion } else { "N/A" }
    release_date   = $biosDate
    serial_number  = if ($bios) { $bios.SerialNumber } else { "N/A" }
    firmware_type  = if (Test-Path "HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State") { "UEFI" } else { "Legacy BIOS" }
}

$result["baseboard"] = @{
    manufacturer = if ($board) { $board.Manufacturer } else { "N/A" }
    product      = if ($board) { $board.Product } else { "N/A" }
    serial       = if ($board) { $board.SerialNumber } else { "N/A" }
}

# ── CPU ─────────────────────────────────────────────────────────────────────
$cpus = Safe-Get { Get-CimInstance Win32_Processor } "CPU"
$cpuList = @()

foreach ($cpu in @($cpus)) {
    if (-not $cpu) { continue }
    $cpuList += @{
        name              = $cpu.Name.Trim()
        manufacturer      = $cpu.Manufacturer
        max_clock_speed   = $cpu.MaxClockSpeed
        current_clock_speed = $cpu.CurrentClockSpeed
        cores             = $cpu.NumberOfCores
        logical_processors = $cpu.NumberOfLogicalProcessors
        load_percentage   = $cpu.LoadPercentage
        socket            = $cpu.SocketDesignation
        architecture      = switch ($cpu.Architecture) {
            0 { "x86" } 9 { "x64" } 5 { "ARM" } default { "Unknown" }
        }
        l2_cache_kb       = [math]::Round($cpu.L2CacheSize / 1, 0)
        l3_cache_kb       = [math]::Round($cpu.L3CacheSize / 1, 0)
    }
}

$result["cpu"] = $cpuList

# ── RAM ─────────────────────────────────────────────────────────────────────
$totalRamGB  = if ($cs) { [math]::Round($cs.TotalPhysicalMemory / 1GB, 2) } else { 0 }
$availableRamGB = if ($os) { [math]::Round($os.FreePhysicalMemory / 1MB, 2) } else { 0 }
$usedRamGB   = [math]::Round($totalRamGB - $availableRamGB, 2)
$ramUsagePct = if ($totalRamGB -gt 0) { [math]::Round(($usedRamGB / $totalRamGB) * 100, 1) } else { 0 }

$ramModules = Safe-Get { Get-CimInstance Win32_PhysicalMemory } "RAM_Modules"
$ramList = @()
foreach ($mod in @($ramModules)) {
    if (-not $mod) { continue }
    $ramList += @{
        slot         = $mod.DeviceLocator
        bank         = $mod.BankLabel
        capacity_gb  = [math]::Round($mod.Capacity / 1GB, 2)
        speed_mhz    = $mod.Speed
        manufacturer = $mod.Manufacturer
        part_number  = $mod.PartNumber.Trim()
        memory_type  = switch ($mod.MemoryType) {
            20 { "DDR" } 21 { "DDR2" } 24 { "DDR3" } 26 { "DDR4" } 34 { "DDR5" }
            default { "Unknown($($mod.MemoryType))" }
        }
    }
}

$result["ram"] = @{
    total_gb      = $totalRamGB
    used_gb       = $usedRamGB
    available_gb  = $availableRamGB
    usage_percent = $ramUsagePct
    slots_used    = $ramList.Count
    modules       = $ramList
}

# ── GPU ─────────────────────────────────────────────────────────────────────
$gpus = Safe-Get { Get-CimInstance Win32_VideoController } "GPU"
$gpuList = @()
foreach ($gpu in @($gpus)) {
    if (-not $gpu) { continue }
    $gpuList += @{
        name              = $gpu.Name
        adapter_ram_gb    = [math]::Round($gpu.AdapterRAM / 1GB, 2)
        driver_version    = $gpu.DriverVersion
        driver_date       = if ($gpu.DriverDate) { try { $gpu.DriverDate.ToString("yyyy-MM-dd") } catch { "N/A" } } else { "N/A" }
        resolution        = "$($gpu.CurrentHorizontalResolution)x$($gpu.CurrentVerticalResolution)"
        refresh_rate_hz   = $gpu.CurrentRefreshRate
        status            = $gpu.Status
    }
}

$result["gpu"] = $gpuList

# ── Disques ─────────────────────────────────────────────────────────────────
$disks = Safe-Get { Get-CimInstance Win32_DiskDrive } "DiskDrive"
$partitions = Safe-Get { Get-CimInstance Win32_LogicalDisk } "LogicalDisk"

$diskList = @()
foreach ($disk in @($disks)) {
    if (-not $disk) { continue }
    $mediaType = "Unknown"
    try {
        $msftDisk = Get-Disk -Number $disk.Index -ErrorAction SilentlyContinue
        if ($msftDisk) { $mediaType = $msftDisk.MediaType }
    } catch {}

    $diskList += @{
        model        = $disk.Model.Trim()
        index        = $disk.Index
        size_gb      = [math]::Round($disk.Size / 1GB, 2)
        interface    = $disk.InterfaceType
        media_type   = $mediaType
        serial       = $disk.SerialNumber.Trim()
        status       = $disk.Status
        partitions   = $disk.Partitions
    }
}

$volList = @()
foreach ($vol in @($partitions)) {
    if (-not $vol -or $vol.DriveType -ne 3) { continue }
    $freeGB  = [math]::Round($vol.FreeSpace / 1GB, 2)
    $sizeGB  = [math]::Round($vol.Size / 1GB, 2)
    $usedGB  = [math]::Round($sizeGB - $freeGB, 2)
    $usedPct = if ($sizeGB -gt 0) { [math]::Round(($usedGB / $sizeGB) * 100, 1) } else { 0 }

    $volList += @{
        drive_letter  = $vol.DeviceID
        label         = $vol.VolumeName
        filesystem    = $vol.FileSystem
        size_gb       = $sizeGB
        used_gb       = $usedGB
        free_gb       = $freeGB
        used_percent  = $usedPct
        low_space     = ($freeGB -lt 10 -or $usedPct -gt 90)
    }
}

$result["disks"] = @{
    physical = $diskList
    volumes  = $volList
}

# ── Températures (via OpenHardwareMonitor/WMI si dispo) ─────────────────────
$temps = @()
$tempsNote = $null
try {
    $hwSensors = Get-CimInstance -Namespace "root/OpenHardwareMonitor" -ClassName Sensor -ErrorAction Stop |
                 Where-Object { $_.SensorType -eq "Temperature" }
    foreach ($s in $hwSensors) {
        $temps += @{ name = $s.Name; value_c = $s.Value; hardware = $s.Hardware }
    }
} catch {
    # OpenHardwareMonitor n'est pas installé — comportement normal, pas une erreur
    $tempsNote = "OpenHardwareMonitor non installé : températures non disponibles"
}

$result["temperatures"]      = $temps
$result["temperatures_note"] = $tempsNote
$result["collector_errors"]  = $errors
$result["collected_at"] = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"] = "system_info"

$result | ConvertTo-Json -Depth 10 -Compress
