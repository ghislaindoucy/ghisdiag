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
    vlc          = "VideoLAN.VLC"
}
$AppNames = @{
    chrome       = "Google Chrome"
    firefox      = "Mozilla Firefox"
    adobereader  = "Adobe Acrobat Reader"
    libreoffice  = "LibreOffice"
    anydesk      = "AnyDesk"
    xnview       = "XNView MP"
    vlc          = "VLC media player"
}

# Verifie qu'une invocation winget S'EXECUTE reellement (et pas seulement qu'un
# fichier existe). Le stub d'alias d'execution (0 octet) "existe" mais echoue a
# l'execution en contexte eleve : "Le fichier specifie est introuvable".
function Test-WingetRuns($cmd) {
    try {
        # winget --version affiche p.ex. "v1.28.240.0". Si l'invocation ne se lance
        # pas (stub defaillant), la sortie est vide => candidat rejete.
        $out = (& $cmd --version 2>$null | Out-String).Trim()
        return ($out -match '\d+\.\d+')
    } catch {}
    return $false
}

function Get-WingetPath {
    $candidates = New-Object System.Collections.Generic.List[string]

    # 1. Vrai exe via le package AppX (chemin reel sous Program Files\WindowsApps)
    try {
        $pkg = Get-AppxPackage -Name Microsoft.DesktopAppInstaller -EA SilentlyContinue |
               Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1
        if ($pkg -and $pkg.InstallLocation) {
            $candidates.Add((Join-Path $pkg.InstallLocation 'winget.exe'))
        }
    } catch {}

    # 2. Recherche directe dans WindowsApps (droits admin)
    try {
        Get-ChildItem "$env:ProgramFiles\WindowsApps\Microsoft.DesktopAppInstaller_*__8wekyb3d8bbwe\winget.exe" `
            -EA SilentlyContinue | Sort-Object FullName -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    } catch {}

    # 3. Commande nue : laisse l'OS resoudre l'alias d'execution (souvent le seul
    #    moyen fiable quand le chemin complet du stub echoue).
    $candidates.Add("winget")

    # 4. Stub d'alias par chemin complet (dernier recours)
    $candidates.Add("$env:LOCALAPPDATA\Microsoft\WindowsApps\winget.exe")

    foreach ($c in $candidates) {
        if (Test-WingetRuns $c) { return $c }
    }
    return $null
}

$winget = Get-WingetPath

switch ($Action) {

    "check" {
        if (-not $winget) {
            @{ winget_available = $false; apps = @{} } | ConvertTo-Json -Depth 3
            break
        }

        $status = @{}
        foreach ($key in $AppIds.Keys) {
            $id   = $AppIds[$key]
            $name = $AppNames[$key]
            $installed = $false
            try {
                # Interrogation ciblee par ID exact : evite la troncature de la colonne
                # Id de "winget list" (sortie redirigee = largeur par defaut, ID coupes).
                # winget renvoie 0 si le paquet est installe, un code != 0 sinon.
                $out = @(& $winget list --id $id --exact `
                    --accept-source-agreements 2>&1 | ForEach-Object { "$_" })
                $exit   = $LASTEXITCODE
                $joined = ($out -join "`n")
                $noMatch = $joined -match '(?i)no installed package|aucun package'
                $installed = ($exit -eq 0 -and -not $noMatch)
            } catch {}
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
            # ForEach-Object { "$_" } convertit aussi les ErrorRecord (stderr) en string,
            # contrairement a Where-Object {$_ -is [string]} qui les filtrait.
            $raw = @(& $winget install --id $appId `
                --silent `
                --accept-source-agreements `
                --accept-package-agreements 2>&1 | ForEach-Object { "$_" })
            $exitCode         = $LASTEXITCODE
            $alreadyInstalled = ($exitCode -eq -1978335135)
            $success          = ($exitCode -eq 0 -or $alreadyInstalled)

            # Extraction d'un message d'erreur lisible en cas d'echec
            $errMsg = $null
            if (-not $success) {
                $patterns = '(?i)(erreur|echec|impossible|aucun|introuvable|invalide|error|failed|cannot|not found|no.*applicable|requires)'
                $errLines = @($raw | Where-Object { $_ -match $patterns -and $_ -notmatch '^\s*$' })
                if ($errLines.Count -gt 0) {
                    $errMsg = ($errLines[-1]).Trim()
                } else {
                    $lastLine = @($raw | Where-Object { $_ -notmatch '^\s*$' }) | Select-Object -Last 1
                    if ($lastLine) { $errMsg = "$lastLine".Trim() }
                }
                if (-not $errMsg) { $errMsg = "winget exit code $exitCode" }
            }

            @{
                success           = $success
                already_installed = $alreadyInstalled
                exit_code         = $exitCode
                name              = $appName
                output            = ($raw -join "`n")
                error             = $errMsg
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
