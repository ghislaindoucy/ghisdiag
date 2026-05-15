# PlanetDiag - Gestion winget et mises a jour applications
param(
    [string]$Action = "check"
)

Set-StrictMode -Version Latest

function Get-WingetPath {
    $candidates = @(
        "$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe",
        "$env:ProgramFiles\WindowsApps\Microsoft.DesktopAppInstaller_*\winget.exe"
    )
    foreach ($pattern in $candidates) {
        $found = Get-Item $pattern -EA SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
        if ($found) { return $found }
    }
    try {
        $w = (& where.exe winget 2>$null) | Select-Object -First 1
        if ($w -and (Test-Path $w)) { return $w }
    } catch {}
    return $null
}

$winget = Get-WingetPath

if (-not $winget -and $Action -ne "check") {
    @{ success = $false; error = "winget n'est pas installe sur ce systeme." } | ConvertTo-Json
    exit 0
}

switch ($Action) {

    "check" {
        if (-not $winget) {
            @{ available = $false; version = $null; path = $null } | ConvertTo-Json
        } else {
            try {
                $ver = (& $winget --version 2>&1) -replace '^v', ''
                @{ available = $true; version = "$ver".Trim(); path = $winget } | ConvertTo-Json
            } catch {
                @{ available = $true; version = $null; path = $winget; error = $_.Exception.Message } | ConvertTo-Json
            }
        }
        break
    }

    "list-upgradable" {
        try {
            $raw = @(& $winget upgrade --include-unknown 2>&1)
            @{
                success    = $true
                raw_output = ($raw -join "`n")
            } | ConvertTo-Json -Depth 2
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "update-all" {
        try {
            $outFile = "$env:TEMP\planetdiag_winget_out.txt"
            $errFile = "$env:TEMP\planetdiag_winget_err.txt"

            $proc = Start-Process -FilePath $winget `
                -ArgumentList "upgrade --all --silent --accept-source-agreements --accept-package-agreements" `
                -RedirectStandardOutput $outFile `
                -RedirectStandardError $errFile `
                -Wait -NoNewWindow -PassThru

            $out = if (Test-Path $outFile) { Get-Content $outFile -Raw -EA SilentlyContinue } else { "" }
            $err = if (Test-Path $errFile) { Get-Content $errFile -Raw -EA SilentlyContinue } else { "" }
            Remove-Item $outFile, $errFile -EA SilentlyContinue

            @{
                success   = ($proc.ExitCode -eq 0)
                exit_code = $proc.ExitCode
                output    = "$out".Trim()
                errors    = "$err".Trim()
            } | ConvertTo-Json -Depth 2
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "update-winget" {
        try {
            $raw = @(& $winget upgrade "Microsoft.AppInstaller" `
                --silent --accept-source-agreements --accept-package-agreements 2>&1)
            @{ success = $true; output = ($raw -join "`n") } | ConvertTo-Json
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "stream-update-all" {
        & $winget upgrade --all --silent --accept-source-agreements --accept-package-agreements --include-unknown 2>&1 |
            ForEach-Object { if ($_ -ne $null) { Write-Output "$_" } }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
