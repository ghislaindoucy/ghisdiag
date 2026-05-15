# PlanetDiag - Installation d'applications pour PC neuf via winget
param(
    [string]$Action = "check",
    [string]$App    = ""    # cle de l'application (chrome, firefox, etc.)
)

$ErrorActionPreference = "SilentlyContinue"

# Catalogue fixe des applications (tableaux pour eviter les problemes de hashtable strict)
$AppIds = @{
    chrome       = "Google.Chrome"
    firefox      = "Mozilla.Firefox"
    adobereader  = "Adobe.Acrobat.Reader.64-bit"
    libreoffice  = "TheDocumentFoundation.LibreOffice"
    anydesk      = "AnyDesk.AnyDesk"
    xnview       = "XnSoft.XnViewMP"
}
$AppNames = @{
    chrome       = "Google Chrome"
    firefox      = "Mozilla Firefox"
    adobereader  = "Adobe Acrobat Reader"
    libreoffice  = "LibreOffice"
    anydesk      = "AnyDesk"
    xnview       = "XNView MP"
}

function Get-WingetPath {
    $p = "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe"
    if (Test-Path $p) { return $p }
    $found = Get-Item "$env:ProgramFiles\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe" -EA SilentlyContinue |
             Select-Object -First 1 -ExpandProperty FullName
    if ($found) { return $found }
    try {
        $w = (& where.exe winget 2>$null) | Select-Object -First 1
        if ($w -and (Test-Path $w)) { return $w }
    } catch {}
    return $null
}

$winget = Get-WingetPath

switch ($Action) {

    "check" {
        if (-not $winget) {
            @{ winget_available = $false; apps = @{} } | ConvertTo-Json -Depth 3
            break
        }
        $installedRaw = ""
        try {
            $lines = & $winget list --accept-source-agreements 2>$null
            $installedRaw = ($lines | Where-Object { $_ -is [string] }) -join "`n"
        } catch {}

        $status = @{}
        foreach ($key in $AppIds.Keys) {
            $id   = $AppIds[$key]
            $name = $AppNames[$key]
            $installed = $installedRaw -match [regex]::Escape($id)
            $status[$key] = @{
                name      = $name
                id        = $id
                installed = [bool]$installed
            }
        }
        @{ winget_available = $true; apps = $status } | ConvertTo-Json -Depth 4
        break
    }

    "install" {
        if (-not $winget) {
            @{ success = $false; error = "winget non disponible" } | ConvertTo-Json
            break
        }
        if (-not $AppIds.ContainsKey($App)) {
            @{ success = $false; error = "Application inconnue : $App" } | ConvertTo-Json
            break
        }
        $appId   = $AppIds[$App]
        $appName = $AppNames[$App]
        try {
            $raw = @(& $winget install --id $appId `
                --silent `
                --accept-source-agreements `
                --accept-package-agreements `
                --locale fr-FR 2>&1 | Where-Object { $_ -is [string] })
            $alreadyInstalled = ($LASTEXITCODE -eq -1978335135)
            $success = ($LASTEXITCODE -eq 0 -or $alreadyInstalled)
            @{
                success           = $success
                already_installed = $alreadyInstalled
                name              = $appName
                output            = ($raw -join "`n")
            } | ConvertTo-Json -Depth 2
        } catch {
            @{ success = $false; name = $appName; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
