# Ghisdiag - Daemon capteurs (temperatures / ventilateurs / horloges)
# Charge LibreHardwareMonitorLib.dll (embarquee dans ..\tools) et expose les
# capteurs sous forme de JSON normalise.
#
# Deux modes :
#   -Once                       : ouvre, lit une fois, emet UN objet JSON, ferme.
#   (defaut) -IntervalMs N      : boucle streaming, UNE ligne JSON compacte par
#                                 tick, jusqu'a -DurationSec (0 = illimite).
#
# IMPORTANT : les capteurs CPU / carte mere exigent des droits admin (driver
# ring0). Sans elevation, seuls GPU et disques remontent. L'exe Ghisdiag
# tourne sous UAC, donc en production tout remonte.
#
# Pas de caractere non-ASCII dans ce fichier (regle PS du projet).

param(
    [switch]$Once,
    [int]$IntervalMs   = 2000,
    [int]$DurationSec  = 0
)

$ErrorActionPreference = "SilentlyContinue"

# ---------------------------------------------------------------------------
# Resolution + chargement de la DLL et de ses dependances depuis ..\tools
# ---------------------------------------------------------------------------
$toolsDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\tools"))
$libPath  = Join-Path $toolsDir "LibreHardwareMonitorLib.dll"

# Ecriture sur le handle stdout brut avec flush par ligne : indispensable pour
# le streaming temps reel (le TextWriter de l'hote bufferise par bloc sur un
# pipe, ce qui retarderait les echantillons du bench de plusieurs dizaines de
# secondes). UTF-8 sans BOM.
$__stdout = [System.Console]::OpenStandardOutput()
$__writer = New-Object System.IO.StreamWriter($__stdout, (New-Object System.Text.UTF8Encoding($false)))
$__writer.AutoFlush = $true

function Write-JsonLine([object]$obj) {
    $json = $obj | ConvertTo-Json -Depth 5 -Compress
    $__writer.WriteLine($json)
}

if (-not (Test-Path $libPath)) {
    Write-JsonLine @{ ok = $false; error = "LibreHardwareMonitorLib.dll introuvable : $libPath" }
    return
}

# Pre-chargement explicite de TOUTES les dependances, dans l'ordre (feuilles
# d'abord). On n'utilise PAS d'AssemblyResolve : un scriptblock PowerShell cast
# en ResolveEventHandler leve une ArgumentException quand le CLR l'invoque
# pendant le JIT / la serialisation (et une version a base de cmdlets boucle en
# StackOverflow). Tout pre-charger rend le resolveur inutile.
$loadOrder = @(
    "System.Runtime.CompilerServices.Unsafe.dll",
    "System.Numerics.Vectors.dll",
    "System.Memory.dll",
    "HidSharp.dll",
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "LibreHardwareMonitorLib.dll"
)

try {
    foreach ($dll in $loadOrder) {
        $p = [System.IO.Path]::Combine($toolsDir, $dll)
        if ([System.IO.File]::Exists($p)) {
            [System.Reflection.Assembly]::LoadFrom($p) | Out-Null
        }
    }
} catch {
    Write-JsonLine @{ ok = $false; error = "Echec chargement DLL : $($_.Exception.Message)" }
    return
}

# ---------------------------------------------------------------------------
# Ouverture du materiel
# ---------------------------------------------------------------------------
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsCpuEnabled         = $true
$computer.IsGpuEnabled         = $true
$computer.IsMotherboardEnabled = $true
$computer.IsStorageEnabled     = $true
$computer.IsControllerEnabled  = $true

try {
    $computer.Open()
} catch {
    Write-JsonLine @{ ok = $false; error = "Echec Computer.Open() : $($_.Exception.Message)" }
    return
}

# ---------------------------------------------------------------------------
# Construction d'un echantillon normalise
# ---------------------------------------------------------------------------
function R1($x) {
    if ($null -eq $x) { return $null }
    return [math]::Round([double]$x, 1)
}

function Get-Sample {
    $cpuTemps  = New-Object System.Collections.Generic.List[double]
    $cpuClocks = New-Object System.Collections.Generic.List[double]
    $fans      = New-Object System.Collections.Generic.List[int]
    $disks     = New-Object System.Collections.Generic.List[object]

    $cpuPkg = $null; $cpuMax = $null; $cpuAvg = $null; $cpuLoad = $null; $cpuClkMax = $null
    $gpuTemp = $null; $gpuHot = $null; $gpuLoad = $null; $gpuFan = $null

    foreach ($hw in $computer.Hardware) {
        try { $hw.Update() } catch {}
        foreach ($sub in $hw.SubHardware) { try { $sub.Update() } catch {} }

        $allHw = @($hw) + @($hw.SubHardware)
        foreach ($node in $allHw) {
            foreach ($s in $node.Sensors) {
                if ($null -eq $s.Value) { continue }
                $v = [double]$s.Value
                $n = [string]$s.Name

                switch ($hw.HardwareType.ToString()) {
                    "Cpu" {
                        if ($s.SensorType -eq "Temperature") {
                            if ($n -eq "CPU Package")     { $cpuPkg = $v }
                            elseif ($n -eq "Core Max")     { $cpuMax = $v }
                            elseif ($n -eq "Core Average") { $cpuAvg = $v }
                            elseif ($n -like "CPU Core #*" -and $n -notlike "*Distance*") { $cpuTemps.Add($v) }
                        }
                        elseif ($s.SensorType -eq "Clock" -and $n -like "CPU Core #*") { $cpuClocks.Add($v) }
                        elseif ($s.SensorType -eq "Load" -and $n -eq "CPU Total") { $cpuLoad = $v }
                    }
                    { $_ -like "Gpu*" } {
                        if ($s.SensorType -eq "Temperature") {
                            if ($n -eq "GPU Core" -or $n -eq "GPU") {
                                if ($null -eq $gpuTemp -or $v -gt $gpuTemp) { $gpuTemp = $v }
                            }
                            elseif ($n -like "*Hot Spot*") { $gpuHot = $v }
                        }
                        elseif ($s.SensorType -eq "Load" -and $n -eq "GPU Core") { $gpuLoad = $v }
                        elseif ($s.SensorType -eq "Fan") {
                            if ($null -eq $gpuFan -or $v -gt $gpuFan) { $gpuFan = [int]$v }
                        }
                    }
                    "Storage" {
                        if ($s.SensorType -eq "Temperature" -and $n -eq "Temperature") {
                            $disks.Add(@{ n = $hw.Name; t = [math]::Round($v, 1) })
                        }
                    }
                    default {
                        # Carte mere / SuperIO : ventilateurs systeme
                        if ($s.SensorType -eq "Fan" -and $v -gt 0) { $fans.Add([int]$v) }
                    }
                }
            }
        }
    }

    # Fallback : si Core Max/Average absents, calcul depuis les coeurs
    if ($null -eq $cpuMax -and $cpuTemps.Count -gt 0) {
        $cpuMax = ($cpuTemps | Measure-Object -Maximum).Maximum
    }
    if ($null -eq $cpuAvg -and $cpuTemps.Count -gt 0) {
        $cpuAvg = [math]::Round(($cpuTemps | Measure-Object -Average).Average, 1)
    }
    if ($cpuClocks.Count -gt 0) {
        $cpuClkMax = [math]::Round(($cpuClocks | Measure-Object -Maximum).Maximum, 0)
    }

    # Temperature CPU de reference (pour arret d'urgence) : package sinon coeur max
    $cpuRef = if ($null -ne $cpuPkg) { $cpuPkg } else { $cpuMax }

    $h = [ordered]@{}
    $h['ts']            = [int64]([System.DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds())
    $h['ok']            = $true
    $h['cpu_pkg']       = (R1 $cpuPkg)
    $h['cpu_max']       = (R1 $cpuMax)
    $h['cpu_avg']       = (R1 $cpuAvg)
    $h['cpu_ref']       = (R1 $cpuRef)
    $h['cpu_load']      = (R1 $cpuLoad)
    $h['cpu_clock_max'] = $cpuClkMax
    $h['gpu_temp']      = (R1 $gpuTemp)
    $h['gpu_hotspot']   = (R1 $gpuHot)
    $h['gpu_load']      = (R1 $gpuLoad)
    $h['gpu_fan']       = $gpuFan
    # .ToArray() et pas @(...) : sur une List[object], l'operateur @() leve une
    # ArgumentException en PowerShell 5.1 (quirk connu) ; ToArray est sur.
    $h['fans']          = $fans.ToArray()
    $h['disks']         = $disks.ToArray()
    $h
}

# ---------------------------------------------------------------------------
# Boucle / one-shot
# ---------------------------------------------------------------------------
try {
    if ($Once) {
        Write-JsonLine (Get-Sample)
    }
    else {
        if ($IntervalMs -lt 250) { $IntervalMs = 250 }
        $deadline = if ($DurationSec -gt 0) {
            [System.DateTime]::UtcNow.AddSeconds($DurationSec)
        } else { [System.DateTime]::MaxValue }

        while ([System.DateTime]::UtcNow -lt $deadline) {
            Write-JsonLine (Get-Sample)
            Start-Sleep -Milliseconds $IntervalMs
        }
    }
}
finally {
    try { $computer.Close() } catch {}
}
