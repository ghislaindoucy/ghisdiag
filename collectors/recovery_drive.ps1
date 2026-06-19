param(
    [string]$Action     = "",
    [string]$DiskNumber = ""
)

Set-StrictMode -Version Latest

# Anti-veille via SetThreadExecutionState (kernel32)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class WakeGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS      = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
    public static void Prevent() { SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED); }
    public static void Allow()   { SetThreadExecutionState(ES_CONTINUOUS); }
}
'@

function Find-WinRE {
    # Emplacements courants de winre.wim
    $candidates = @(
        "$env:SystemRoot\System32\Recovery\winre.wim",
        "C:\Recovery\WindowsRE\winre.wim"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # Parcourir tous les volumes fixes
    $vols = Get-Volume -ErrorAction SilentlyContinue |
            Where-Object { $_.DriveType -eq "Fixed" -and $_.DriveLetter }
    foreach ($v in $vols) {
        $p = "$($v.DriveLetter):\Recovery\WindowsRE\winre.wim"
        if (Test-Path $p) { return $p }
    }
    return $null
}

switch ($Action) {

    "list-usb" {
        $disks = @()
        try {
            $usbDisks = Get-Disk -ErrorAction Stop | Where-Object { $_.BusType -eq "USB" }
            foreach ($d in $usbDisks) {
                $disks += @{
                    disk_number = [int]$d.Number
                    size_gb     = [math]::Round($d.Size / 1GB, 1)
                    model       = $d.FriendlyName
                    # RecoveryDrive.exe exige 16 Go (WinRE + outils de recuperation)
                    enough      = ($d.Size -ge 16GB)
                }
            }
        } catch {}
        [PSCustomObject]@{ success = $true; disks = $disks } | ConvertTo-Json -Depth 3
        exit 0
    }

    "check-winre" {
        $wim     = Find-WinRE
        $recExe  = "$env:SystemRoot\System32\RecoveryDrive.exe"
        $enabled = $wim -ne $null
        try {
            $reagentOut = (& "$env:SystemRoot\System32\reagentc.exe" /info 2>&1) -join "`n"
            if ($reagentOut -match 'Enabled|Active') { $enabled = $true }
        } catch {}
        [PSCustomObject]@{
            success          = $true
            winre_enabled    = $enabled
            winre_path       = if ($wim) { $wim } else { $null }
            recovery_exe_ok  = (Test-Path $recExe)
        } | ConvertTo-Json -Depth 2
        exit 0
    }

    "launch-native" {
        $recExe = "$env:SystemRoot\System32\RecoveryDrive.exe"
        if (-not (Test-Path $recExe)) {
            [PSCustomObject]@{
                success = $false
                error   = "RecoveryDrive.exe introuvable sur ce systeme (Windows LTSC ou Server non supporte)."
            } | ConvertTo-Json
            exit 0
        }
        try {
            # Deja admin (Ghisdiag demande l'elevation au demarrage)
            Start-Process -FilePath $recExe
            [PSCustomObject]@{ success = $true } | ConvertTo-Json
        } catch {
            [PSCustomObject]@{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        exit 0
    }

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
