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
            @{ available = $false; version = $null; path = $null; needs_update = $false } | ConvertTo-Json
        } else {
            try {
                $ver = (& $winget --version 2>&1) -replace '^v', ''
                $verClean = "$ver".Trim()
                $needsUpdate = $false
                $parts = $verClean.Split('.')
                if ($parts.Count -ge 2) {
                    $maj = [int]$parts[0]; $min = [int]$parts[1]
                    # Minimum viable : 1.6 (--include-unknown, sources stables)
                    $needsUpdate = ($maj -lt 1) -or ($maj -eq 1 -and $min -lt 6)
                }
                @{ available = $true; version = $verClean; path = $winget; needs_update = $needsUpdate } | ConvertTo-Json
            } catch {
                @{ available = $true; version = $null; path = $winget; needs_update = $false; error = $_.Exception.Message } | ConvertTo-Json
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

    "open-store" {
        try {
            Start-Process "ms-windows-store://pdp/?productid=9NBLGGH4NNS1"
            @{ success = $true; message = "Page Microsoft Store ouverte." } | ConvertTo-Json
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "install-from-github" {
        # Streaming pur — pas de JSON, Write-Output ligne par ligne
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $ErrorActionPreference = "Stop"

        Write-Output "Recuperation de la derniere version depuis GitHub..."
        try {
            $headers = @{ "User-Agent" = "PlanetDiag-WingetUpdater" }
            $release = Invoke-RestMethod "https://api.github.com/repos/microsoft/winget-cli/releases/latest" `
                       -Headers $headers -UseBasicParsing -TimeoutSec 30
            if (-not $release.tag_name) {
                Write-Output "ERREUR: Reponse GitHub invalide (tag_name absent). Reessayez plus tard."
                exit 1
            }
            Write-Output "Version disponible : $($release.tag_name)"
        } catch {
            Write-Output "ERREUR: Impossible de contacter GitHub - $($_.Exception.Message)"
            exit 1
        }

        $msixBundle = $release.assets | Where-Object { $_.name -match '\.msixbundle$' } | Select-Object -First 1
        if (-not $msixBundle) {
            Write-Output "ERREUR: Fichier d'installation introuvable dans la release GitHub."
            exit 1
        }

        $sizeMb  = [math]::Round($msixBundle.size / 1MB, 1)
        $tmpMsix = "$env:TEMP\winget_installer.msixbundle"
        $tmpVc   = "$env:TEMP\vclibs_x64.appx"

        try {
            Write-Output "Telechargement : $($msixBundle.name) (${sizeMb} Mo)..."
            Invoke-WebRequest -Uri $msixBundle.browser_download_url -OutFile $tmpMsix -UseBasicParsing
            Write-Output "Telechargement termine."

            Write-Output "Verification des dependances (VCLibs)..."
            try {
                $vcUrl = "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx"
                Invoke-WebRequest -Uri $vcUrl -OutFile $tmpVc -UseBasicParsing -EA Stop
                Add-AppxPackage -Path $tmpVc -EA SilentlyContinue
                Write-Output "  VCLibs : OK"
            } catch {
                Write-Output "  VCLibs : deja presentes ou non disponibles (on continue)"
            }

            Write-Output "Installation de winget $($release.tag_name)..."
            Add-AppxPackage -Path $tmpMsix
            Write-Output ""
            Write-Output "SUCCESS: winget mis a jour. Relancez PlanetDiag pour utiliser la nouvelle version."
            exit 0
        } catch {
            Write-Output ""
            Write-Output "ERREUR: $($_.Exception.Message)"
            exit 1
        } finally {
            Remove-Item $tmpMsix, $tmpVc -Force -EA SilentlyContinue
        }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
