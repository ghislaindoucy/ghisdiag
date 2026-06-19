param(
    [string]$Action      = "",
    [string]$ProfileName = "",
    [string]$FilePath    = "",
    [string]$Password    = "",
    [string]$Auth        = ""
)

$ErrorActionPreference = "SilentlyContinue"

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
        # Forcer UTF-8 pour les SSID avec caracteres speciaux
        try { & chcp 65001 2>&1 | Out-Null } catch {}

        # Lister les interfaces WiFi et verifier l'etat de la radio
        $interfaces    = @()
        $radioDisabled = $false
        $ifRaw = @(netsh wlan show interfaces 2>&1)
        foreach ($line in $ifRaw) {
            if ($line -match '^\s*(?:Nom|Name)\s*:\s*(.+)$') {
                $iface = $Matches[1].Trim()
                if ($iface) { $interfaces += $iface }
            }
            # Detection radio logiciellement desactivee (FR: "Logiciel Desactive" / EN: "Software Off/Disabled")
            # Note: utiliser '.' pour eviter les problemes d'encodage PS5 avec les caracteres accentues
            if ($line -match 'Logiciel D.sactiv|Software\s+(Off|Disabl)') {
                $radioDisabled = $true
            }
        }

        if ($interfaces.Count -eq 0) {
            @{ success = $false; networks = @()
               error = "Aucune interface WiFi trouvee sur ce systeme" } | ConvertTo-Json -Depth 3
            break
        }

        if ($radioDisabled) {
            @{ success = $false; networks = @()
               error = "Le WiFi est desactive (mode avion ou radio off). Activez le WiFi dans les parametres Windows avant de scanner." } | ConvertTo-Json -Depth 3
            break
        }

        # Declencher un scan actif sur chaque interface
        foreach ($iface in $interfaces) {
            netsh wlan scan interface="$iface" 2>&1 | Out-Null
        }

        # Laisser Windows collecter les resultats (3 secondes)
        Start-Sleep -Seconds 3

        # Lire les reseaux detectes
        $raw = @(netsh wlan show networks mode=bssid 2>&1)

        $networks = @()
        $cur      = $null
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
                    if (-not $cur.signal) { $cur.signal = $Matches[1].Trim() }
                }
                elseif ($line -match '(?:Canal|Channel)\s*:\s*(\d+)') {
                    if (-not $cur.channel) { $cur.channel = $Matches[1].Trim() }
                }
            }
        }
        if ($null -ne $cur) { $networks += $cur }

        # Dedupliquer par SSID et trier par signal decroissant
        $seen   = @{}
        $sorted = @(
            $networks |
            Where-Object { $_.ssid -ne "" } |
            Sort-Object { if ($_.signal) { [int]$_.signal } else { 0 } } -Descending |
            Where-Object {
                if (-not $seen.ContainsKey($_.ssid)) { $seen[$_.ssid] = $true; $true }
                else { $false }
            }
        )
        # Ajouter les reseaux masques (SSID vide) a la fin
        $hidden = @($networks | Where-Object { $_.ssid -eq "" })

        @{
            success    = $true
            networks   = $sorted + $hidden
            interfaces = $interfaces
        } | ConvertTo-Json -Depth 3
        break
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

        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "ghisdiag_wifi_$([System.Guid]::NewGuid().ToString('N'))"
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

        $tempDir = Join-Path ([System.IO.Path]::GetTempPath()) "ghisdiag_wifi_restore_$([System.Guid]::NewGuid().ToString('N'))"
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
            @{ success = $false; error = "Nom de reseau invalide" } | ConvertTo-Json
            break
        }

        $existing   = Get-ProfileNames
        $hasProfile = $ProfileName -in $existing

        if (-not $hasProfile) {
            if ($Auth -ne "open" -and [string]::IsNullOrEmpty($Password)) {
                @{ success = $false; error = "Mot de passe requis pour ce reseau" } | ConvertTo-Json
                break
            }
            if ($Auth -ne "open" -and $Password.Length -lt 8) {
                @{ success = $false; error = "Mot de passe trop court (8 caracteres minimum)" } | ConvertTo-Json
                break
            }

            $bytes   = [System.Text.Encoding]::UTF8.GetBytes($ProfileName)
            $hexSSID = ($bytes | ForEach-Object { '{0:X2}' -f $_ }) -join ''
            $isOpen  = ($Auth -eq "open")
            $xmlContent = New-WifiProfileXml -Ssid $ProfileName -HexSsid $hexSSID -Pwd $Password -IsOpen $isOpen

            $tmpXml = Join-Path ([System.IO.Path]::GetTempPath()) "ghisdiag_conn_$([System.Guid]::NewGuid().ToString('N')).xml"
            [System.IO.File]::WriteAllText($tmpXml, $xmlContent, [System.Text.Encoding]::UTF8)

            $addResult = @(netsh wlan add profile filename="$tmpXml" user=all 2>&1)
            Remove-Item -Path $tmpXml -Force -ErrorAction SilentlyContinue

            $addOutput = ($addResult -join " ").Trim()
            if ($addOutput -notmatch "(?i)ajout|added|mis.+jour|updated") {
                @{ success = $false; error = "Impossible de creer le profil : $addOutput" } | ConvertTo-Json
                break
            }
        }

        # Envoyer la demande de connexion (asynchrone Windows)
        $connectResult = @(netsh wlan connect name="$ProfileName" 2>&1)
        $connectOutput = ($connectResult -join " ").Trim()
        # "r.ussi" couvre "reussi" (masc.) et "reussie" (fem.) sans accent dans le pattern
        $requested = $connectOutput -match "(?i)r.ussi|success|cours|progress|envoy"

        if (-not $requested) {
            @{
                success         = $false
                error           = "Commande de connexion refusee : $connectOutput"
                created_profile = $false
            } | ConvertTo-Json
            break
        }

        # Verifier la connexion effective (max 10 secondes, sondage toutes les 1.5s)
        $deadline  = (Get-Date).AddSeconds(10)
        $connected = $false

        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 1500
            $statusRaw = @(netsh wlan show interfaces 2>&1)
            $isConn  = $false
            $curSSID = ""
            foreach ($sline in $statusRaw) {
                # Etat/State suivi de "connect*" (connecte, connected, connecting...)
                if ($sline -match '(?i):\s*connect') { $isConn = $true }
                # Ligne SSID (pas BSSID)
                if ($sline -match '^\s*SSID\s+:\s*(.+)') { $curSSID = $Matches[1].Trim() }
            }
            if ($isConn -and $curSSID -eq $ProfileName) {
                $connected = $true
                break
            }
        }

        if ($connected) {
            @{
                success         = $true
                profile         = $ProfileName
                created_profile = (-not $hasProfile)
            } | ConvertTo-Json
        } else {
            # Supprimer le profil cree si mauvais MDP (evite les profils orphelins)
            if (-not $hasProfile -and $Auth -ne "open") {
                netsh wlan delete profile name="$ProfileName" 2>&1 | Out-Null
            }
            @{
                success         = $false
                error           = "Connexion echouee - verifiez le mot de passe ou la disponibilite du reseau"
                created_profile = $false
            } | ConvertTo-Json
        }
        break
    }

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
