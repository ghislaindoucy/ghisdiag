# PlanetDiag - Collecteur Performance
# Collecte l'usage CPU, RAM, disque et les top processus consommateurs

$ErrorActionPreference = "SilentlyContinue"
$result = @{}
$errors = @()
$notes  = @()

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null)
    try { $val = & $Block; if ($null -eq $val) { return $Default }; return $val }
    catch { $script:errors += "[$Name] $($_.Exception.Message)"; return $Default }
}

# ── Usage CPU global ─────────────────────────────────────────────────────────
$cpuLoad = Safe-Get {
    $samples = Get-Counter '\Processor(_Total)\% Processor Time' -SampleInterval 1 -MaxSamples 3
    [math]::Round(($samples.CounterSamples | Measure-Object -Property CookedValue -Average).Average, 1)
} "CPU_Load" 0

# ── Snapshot des processus (une seule fois pour CPU + RAM) ──────────────────
$allProcs = Safe-Get {
    Get-Process | Select-Object ProcessName, Id, CPU, WorkingSet64, Threads, StartTime
} "AllProcs" @()

# ── Top processus CPU ────────────────────────────────────────────────────────
$topCpuProcs = @($allProcs | Sort-Object CPU -Descending | Select-Object -First 10 | ForEach-Object {
    @{
        name       = $_.ProcessName
        pid        = $_.Id
        cpu_sec    = [math]::Round(($_.CPU), 1)
        memory_mb  = [math]::Round($_.WorkingSet64 / 1MB, 1)
        threads    = $_.Threads.Count
        start_time = if ($_.StartTime) { try { $_.StartTime.ToString("yyyy-MM-dd HH:mm:ss") } catch { "N/A" } } else { "N/A" }
    }
})

# ── Usage RAM ────────────────────────────────────────────────────────────────
$os = Safe-Get { Get-CimInstance Win32_OperatingSystem } "OS"
$cs = Safe-Get { Get-CimInstance Win32_ComputerSystem } "CS"

$totalRamMB = if ($cs) { [math]::Round($cs.TotalPhysicalMemory / 1MB, 0) } else { 0 }
$freeRamMB  = if ($os)  { [math]::Round($os.FreePhysicalMemory / 1KB, 0) } else { 0 }
$usedRamMB  = $totalRamMB - $freeRamMB
$ramPct     = if ($totalRamMB -gt 0) { [math]::Round(($usedRamMB / $totalRamMB) * 100, 1) } else { 0 }

# ── Top processus RAM (réutilise le snapshot) ────────────────────────────────
$topRamProcs = @($allProcs | Sort-Object WorkingSet64 -Descending | Select-Object -First 10 | ForEach-Object {
    @{
        name    = $_.ProcessName
        pid     = $_.Id
        ram_mb  = [math]::Round($_.WorkingSet64 / 1MB, 1)
        cpu_sec = [math]::Round(($_.CPU), 1)
        threads = $_.Threads.Count
    }
})

# Libère la référence pour le GC
$allProcs = $null

# ── Activité disque ──────────────────────────────────────────────────────────
$diskActivity = @()
try {
    $diskCounters = Get-Counter '\PhysicalDisk(*)\Disk Read Bytes/sec',
                                '\PhysicalDisk(*)\Disk Write Bytes/sec',
                                '\PhysicalDisk(*)\% Disk Time',
                                '\PhysicalDisk(*)\Avg. Disk sec/Transfer' `
                   -SampleInterval 1 -MaxSamples 2 -ErrorAction Stop

    $byDisk = @{}
    foreach ($sample in $diskCounters.CounterSamples) {
        $disk = $sample.InstanceName
        if (-not $byDisk[$disk]) { $byDisk[$disk] = @{} }
        if ($sample.Path -like "*Read Bytes*")  { $byDisk[$disk]["read_bps"]    = [math]::Round($sample.CookedValue, 0) }
        if ($sample.Path -like "*Write Bytes*") { $byDisk[$disk]["write_bps"]   = [math]::Round($sample.CookedValue, 0) }
        if ($sample.Path -like "*Disk Time*")   { $byDisk[$disk]["busy_pct"]    = [math]::Round($sample.CookedValue, 1) }
        if ($sample.Path -like "*sec/Transfer*"){ $byDisk[$disk]["latency_ms"]  = [math]::Round($sample.CookedValue * 1000, 2) }
    }
    foreach ($k in $byDisk.Keys) {
        if ($k -ne "_total") {
            $diskActivity += @{ disk = $k } + $byDisk[$k]
        }
    }
} catch {
    # Le compteur de performance disque peut être absent selon la configuration
    # (ex. nom de compteur localisé, disque virtuel). Ce n'est pas une erreur critique.
    $notes += "[DiskActivity] Compteur non disponible sur cette configuration"
}

# ── Résumé système ───────────────────────────────────────────────────────────
$result["cpu"] = @{
    load_percent  = $cpuLoad
    top_processes = $topCpuProcs
    alert         = ($cpuLoad -gt 80)
}

$result["ram"] = @{
    total_mb      = $totalRamMB
    used_mb       = $usedRamMB
    free_mb       = $freeRamMB
    usage_percent = $ramPct
    top_processes = $topRamProcs
    alert         = ($ramPct -gt 85)
}

$result["disk_activity"] = $diskActivity

$result["collector_errors"] = $errors
$result["collector_notes"]  = $notes
$result["collected_at"]     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]        = "performance"

$result | ConvertTo-Json -Depth 10 -Compress
