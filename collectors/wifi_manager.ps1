param(
    [string]$Action      = "",
    [string]$ProfileName = "",
    [string]$FilePath    = "",
    [string]$Password    = "",
    [string]$Auth        = ""
)

Set-StrictMode -Version Latest

# Valide le nom de profil WiFi contre l'injection dans les arguments netsh
function Test-ProfileName([string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name.Length -gt 256) { return $false }
    # Interdit les caracteres dangereux pour name="..." dans netsh
    if ($Name -match '["\r\n|<>&]') { return $false }
    return $true
}

# Genere le XML d'un profil WiFi (WPA2PSK ou open) sans recourir au here-string
function New-WifiProfileXml([string]$Ssid, [string]$HexSsid, [string]$Pwd, [bool]$IsOpen) {
    # Echapper les caracteres XML speciaux dans le nom et le MDP
    $safeSsid = $Ssid.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
    $safePwd  = $Pwd.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')

    $x  = '<?xml version="1.0"?>' + "`n"
    $x += '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">' + "`n"
    $x += "  <name>$safeSsid</name>`n"
    $x += "  <SSIDConfig><SSID><hex>$HexSsid</hex><name>$safeSsid</name></SSID></SSIDConfig>`n"
    $x += "  <connectionType>ESS</connectionType>`n"
    $x += "  <connectionMode>manual</connectionMode>`n"
    $x += "  <MSM><security><authEncryption>`n"
    if ($IsOpen) {
        $x += "    <authentication>open</authentication>`n"
        $x += "    <encryption>none</encryption>`n"
        $x += "    <useOneX>false</useOneX>`n"
        $x += "  </authEncryption></security></MSM>`n"
    } else {
        $x += "    <authentication>WPA2PSK</authentication>`n"
        $x += "    <encryption>AES</encryption>`n"
        $x += "    <useOneX>false</useOneX>`n"
        $x += "  </authEncryption>`n"
        $x += "  <sharedKey><keyType>passPhrase</keyType><protected>false</protected>"
        $x += "<keyMaterial>$safePwd</keyMaterial></sharedKey>`n"
        $x += "  </security></MSM>`n"
    }
    $x += "</WLANProfile>"
    return $x
}

# Extrait les noms de profils utilisateurs depuis la sortie de "netsh wlan show profiles"
function Get-ProfileNames {
    $raw = $null
    try { $raw = netsh wlan show profiles 2>&1 } catch {}
    $names = @()
    $seen  = @{}
    if ($raw) {
        $inSection = $false
        foreach ($line in $raw) {
            $t = $line.Trim()
            if ($t -match '^Profils utilisateurs|^User Profiles|^All User Profiles') {
                $inSection = $true; continue
            }
            if ($t -match '^Profils sur l|^Profiles on interface') {
                $inSection = $false; continue
            }
            if ($inSection -and $t -match ':\s+(.+)$') {
                $n = $Matches[1].Trim()
                if ($n -and $n -ne '<Aucun>' -and $n -ne '<None>' -and -not $seen.ContainsKey($n)) {
                    $seen[$n] = $true
                    $names += $n
                }
            }
        }
    }
    return $names
}

switch ($Action) {

    "list-profiles" {
        $names    = Get-ProfileNames
        $profiles = @()
        foreach ($n in $names) { $profiles += @{ name = $n } }
        [PSCustomObject]@{ success = $true; profiles = $profiles } | ConvertTo-Json -Depth 3
        exit 0
    }

    "show-password" {
        if (-not (Test-ProfileName $ProfileName)) {
            [PSCustomObject]@{ success = $false; error = "Nom de profil invalide" } | ConvertTo-Json
            exit 0
        }

        $raw = $null
        try { $raw = netsh wlan show profile name="$ProfileName" key=clear 2>&1 } catch {}

        $password = $null
        $auth     = $null

        foreach ($line in $raw) {
            # MDP clair bilingue — [^:]* gere les accents dans "cle" / "key" selon locale
            if ($line -match '(?:Contenu de la cl|Key Content)[^:]*:\s*(.+)') {
                $password = $Matches[1].Trim()
            }
            if ($line -match '(?:Authentification|Authentication)\s*:\s*(.+)') {
                $auth = $Matches[1].Trim()
            }
        }

        [PSCustomObject]@{
            success        = $true
            profile        = $ProfileName
            password       = $password
            authentication = $auth
        } | ConvertTo-Json
        exit 0
    }

    "delete-profile" {
        if (-not (Test-ProfileName $ProfileName)) {
            [PSCustomObject]@{ success = $false; error = "Nom de profil invalide" } | ConvertTo-Json
            exit 0
        }

        $raw = $null
        try { $raw = netsh wlan delete profile name="$ProfileName" 2>&1 } catch {}

        $output  = ($raw -join " ").Trim()
        $success = $output -match "(?i)supprim|deleted"

        [PSCustomObject]@{
            success = [bool]$success
            profile = $ProfileName
            message = $output
        } | ConvertTo-Json
        exit 0
    }

    "scan" {
        $raw = $null
        try { $raw = netsh wlan show networks mode=bssid 2>&1 } catch {}

        $networks = @()

        if ($raw) {
            $cur = $null
            foreach ($line in $raw) {
                if ($line -match '^SSID\s+\d+\s*:\s*(.*)') {
                    if ($null -ne $cur) { $networks += $cur }
                    $cur = @{
                        ssid           = $Matches[1].Trim()
                        signal         = ""
                        authentication = ""
                        encryption     = ""
                        channel        = ""
                    }
                }
                elseif ($null -ne $cur) {
                    if ($line -match '(?:Authentification|Authentication)\s*:\s*(.+)') {
                        $cur.authentication = $Matches[1].Trim()
                    }
                    elseif ($line -match '(?:Chiffrement|Encryption)\s*:\s*(.+)') {
                        $cur.encryption = $Matches[1].Trim()
                    }
                    elseif ($line -match 'Signal\s*:\s*(\d+)%') {
                        if (-not $cur.signal) { $cur.signal = $Matches[1] }
                    }
                    elseif ($line -match '(?:Canal|Channel)\s*:\s*(\d+)') {
                        if (-not $cur.channel) { $cur.channel = $Matches[1] }
                    }
                }
            }
            if ($null -ne $cur) { $networks += $cur }
        }

        [PSCustomObject]@{ success = $true; networks = $networks } | ConvertTo-Json -Depth 3
        exit 0
    }

    "backup-all" {
        if ([string]::IsNullOrWhiteSpace($FilePath)) {
            [PSCustomObject]@{ success = $false; error = "Chemin de sortie manquant" } | ConvertTo-Json
            exit 0
        }
        $parentDir = Split-Path -Parent $FilePath
        if (-not $parentDir -or -not (Test-Path $parentDir -PathType Container)) {
            [PSCustomObject]@{ success = $false; error = "Dossier de destination introuvable" } | ConvertTo-Json
            exit 0
        }

        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "planetdiag_wifi_$([System.Guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

        $names    = Get-ProfileNames
        $exported = @()
        $errors   = @()

        foreach ($name in $names) {
            # @() force le tableau meme si Get-ChildItem retourne $null ou 1 objet (StrictMode .Count)
            $before = @(Get-ChildItem -Path $tempDir -Filter "*.xml" -ErrorAction SilentlyContinue).Count
            $null   = netsh wlan export profile name="$name" folder="$tempDir" key=clear 2>&1
            $after  = @(Get-ChildItem -Path $tempDir -Filter "*.xml" -ErrorAction SilentlyContinue).Count
            if ($after -gt $before) { $exported += $name }
            else { $errors += "Echec export : $name" }
        }

        if (-not $exported) {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            [PSCustomObject]@{ success = $false; error = "Aucun profil exporte"; errors = $errors } | ConvertTo-Json -Depth 3
            exit 0
        }

        try {
            Compress-Archive -Path "$tempDir\*" -DestinationPath $FilePath -Force
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            [PSCustomObject]@{
                success        = $true
                zip_path       = $FilePath
                profiles_count = $exported.Count
                profiles       = $exported
                errors         = $errors
            } | ConvertTo-Json -Depth 3
        } catch {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            [PSCustomObject]@{ success = $false; error = "Erreur compression ZIP : $_" } | ConvertTo-Json
        }
        exit 0
    }

    "restore-all" {
        if ([string]::IsNullOrWhiteSpace($FilePath) -or -not (Test-Path $FilePath -PathType Leaf)) {
            [PSCustomObject]@{ success = $false; error = "Fichier ZIP introuvable" } | ConvertTo-Json
            exit 0
        }
        if ([System.IO.Path]::GetExtension($FilePath).ToLower() -ne '.zip') {
            [PSCustomObject]@{ success = $false; error = "Le fichier doit etre un .zip" } | ConvertTo-Json
            exit 0
        }

        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "planetdiag_wifi_restore_$([System.Guid]::NewGuid().ToString('N'))"
        New-Item -ItemType Directory -Path $tempDir -Force | Out-Null

        try {
            Expand-Archive -Path $FilePath -DestinationPath $tempDir -Force
        } catch {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            [PSCustomObject]@{ success = $false; error = "Erreur decompression ZIP : $_" } | ConvertTo-Json
            exit 0
        }

        # Traiter uniquement les .xml (securite : pas d'executables)
        $xmlFiles = Get-ChildItem -Path $tempDir -Filter "*.xml" -File -Recurse -ErrorAction SilentlyContinue

        if (-not $xmlFiles) {
            Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
            [PSCustomObject]@{ success = $false; error = "Aucun fichier XML trouve dans le ZIP" } | ConvertTo-Json
            exit 0
        }

        $imported = @()
        $errors   = @()

        foreach ($xml in $xmlFiles) {
            $result = $null
            try { $result = netsh wlan add profile filename="$($xml.FullName)" user=all 2>&1 } catch {}
            $output = ($result -join " ").Trim()
            # Succes FR : "ajout" / "mis a jour" — EN : "added" / "updated"
            if ($output -match "(?i)ajout|added|mis.+jour|updated") {
                $imported += $xml.BaseName
            } else {
                $errors += "$($xml.BaseName) : $output"
            }
        }

        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        [PSCustomObject]@{
            success        = $true
            imported_count = $imported.Count
            imported       = $imported
            errors         = $errors
        } | ConvertTo-Json -Depth 3
        exit 0
    }

    "connect" {
        if (-not (Test-ProfileName $ProfileName)) {
            [PSCustomObject]@{ success = $false; error = "Nom de reseau invalide" } | ConvertTo-Json
            exit 0
        }

        # Verifier si un profil sauvegarde existe deja pour ce SSID
        $existing   = Get-ProfileNames
        $hasProfile = $ProfileName -in $existing

        if (-not $hasProfile) {
            if ($Auth -ne "open" -and [string]::IsNullOrEmpty($Password)) {
                [PSCustomObject]@{ success = $false; error = "Mot de passe requis pour ce reseau" } | ConvertTo-Json
                exit 0
            }
            if ($Auth -ne "open" -and $Password.Length -lt 8) {
                [PSCustomObject]@{ success = $false; error = "Mot de passe trop court (8 caracteres minimum)" } | ConvertTo-Json
                exit 0
            }

            # Encoder le SSID en hex UTF-8 pour le XML
            $bytes   = [System.Text.Encoding]::UTF8.GetBytes($ProfileName)
            $hexSSID = ($bytes | ForEach-Object { '{0:X2}' -f $_ }) -join ''
            $isOpen  = ($Auth -eq "open")

            $xmlContent = New-WifiProfileXml -Ssid $ProfileName -HexSsid $hexSSID -Pwd $Password -IsOpen $isOpen

            $tmpXml = Join-Path ([System.IO.Path]::GetTempPath()) "planetdiag_conn_$([System.Guid]::NewGuid().ToString('N')).xml"
            [System.IO.File]::WriteAllText($tmpXml, $xmlContent, [System.Text.Encoding]::UTF8)

            $addResult = netsh wlan add profile filename="$tmpXml" user=all 2>&1
            Remove-Item -Path $tmpXml -Force -ErrorAction SilentlyContinue

            $addOutput = ($addResult -join " ").Trim()
            if ($addOutput -notmatch "(?i)ajout|added|mis.+jour|updated") {
                [PSCustomObject]@{ success = $false; error = "Impossible de creer le profil : $addOutput" } | ConvertTo-Json
                exit 0
            }
        }

        # Lancer la connexion (asynchrone cote Windows : netsh retourne avant connexion effective)
        $connectResult = netsh wlan connect name="$ProfileName" 2>&1
        $connectOutput = ($connectResult -join " ").Trim()
        # Succes FR : "reussie" / "en cours" — EN : "success" / "progress"
        $success = $connectOutput -match "(?i)r.ussie|success|cours|progress|envoy"

        [PSCustomObject]@{
            success         = [bool]$success
            profile         = $ProfileName
            message         = $connectOutput
            created_profile = (-not $hasProfile)
        } | ConvertTo-Json
        exit 0
    }

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
