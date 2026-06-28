# Ghisdiag - Probe d'isolation des sous-systemes LibreHardwareMonitor.
#
# Ouvre LHM avec UN SEUL sous-systeme actif, chronometre Open()+Update(), puis
# rapporte le temps et le nombre de capteurs de temperature vus. Pilote par
# diagnose_probe.py : chaque sous-systeme est lance dans un process separe avec
# son propre timeout, ce qui permet d'identifier celui qui se fige.
#
# Pas de caractere non-ASCII (regle PS du projet).

param([string]$Enable = "cpu", [string]$ToolsDir = "")

$ErrorActionPreference = "SilentlyContinue"

if ($ToolsDir -and (Test-Path (Join-Path $ToolsDir "LibreHardwareMonitorLib.dll"))) {
    $toolsDir = [System.IO.Path]::GetFullPath($ToolsDir)
} else {
    $toolsDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\tools"))
}
$libPath  = Join-Path $toolsDir "LibreHardwareMonitorLib.dll"
if (-not (Test-Path $libPath)) { Write-Output "ERR dll-introuvable"; return }

$loadOrder = @(
    "System.Runtime.CompilerServices.Unsafe.dll",
    "System.Numerics.Vectors.dll",
    "System.Memory.dll",
    "HidSharp.dll",
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "LibreHardwareMonitorLib.dll"
)
foreach ($dll in $loadOrder) {
    $p = [System.IO.Path]::Combine($toolsDir, $dll)
    if ([System.IO.File]::Exists($p)) { [System.Reflection.Assembly]::LoadFrom($p) | Out-Null }
}

$computer = New-Object LibreHardwareMonitor.Hardware.Computer
switch ($Enable) {
    "cpu"        { $computer.IsCpuEnabled         = $true }
    "gpu"        { $computer.IsGpuEnabled         = $true }
    "mb"         { $computer.IsMotherboardEnabled = $true }
    "storage"    { $computer.IsStorageEnabled     = $true }
    "controller" { $computer.IsControllerEnabled  = $true }
    default      { $computer.IsCpuEnabled         = $true }
}

$sw = [System.Diagnostics.Stopwatch]::StartNew()
try { $computer.Open() } catch { Write-Output "ERR open: $($_.Exception.Message)"; return }

$nTemp = 0
foreach ($hw in $computer.Hardware) {
    try { $hw.Update() } catch {}
    foreach ($sub in $hw.SubHardware) { try { $sub.Update() } catch {} }
    $allHw = @($hw) + @($hw.SubHardware)
    foreach ($node in $allHw) {
        foreach ($s in $node.Sensors) {
            if ($s.SensorType -eq "Temperature" -and $null -ne $s.Value) { $nTemp++ }
        }
    }
}
$sw.Stop()

Write-Output "OK $Enable $($sw.ElapsedMilliseconds)ms temps=$nTemp"
try { $computer.Close() } catch {}
