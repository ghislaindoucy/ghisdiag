param(
    [string]$Action      = "",
    [string]$ProfileName = ""
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

switch ($Action) {

    "list-profiles" {
        $raw = $null
        try { $raw = netsh wlan show profiles 2>&1 } catch {}

        $profiles = @()
        $seen     = @{}

        if ($raw) {
            $inUserSection = $false
            foreach ($line in $raw) {
                $trimmed = $line.Trim()
                # Detecter le debut de la section profils utilisateurs (FR/EN)
                if ($trimmed -match '^Profils utilisateurs|^User Profiles|^All User Profiles') {
                    $inUserSection = $true
                    continue
                }
                # Nouvelle interface : rester dans la section pour cette interface aussi
                if ($trimmed -match '^Profils sur l|^Profiles on interface') {
                    $inUserSection = $false
                    continue
                }
                # Dans la section utilisateur : extraire les noms apres le dernier ':'
                if ($inUserSection -and $trimmed -match ':\s+(.+)$') {
                    $n = $Matches[1].Trim()
                    if ($n -and $n -ne '<Aucun>' -and $n -ne '<None>' -and -not $seen.ContainsKey($n)) {
                        $seen[$n] = $true
                        $profiles += @{ name = $n }
                    }
                }
            }
        }

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
        # netsh indique le succes par "supprime" (FR) ou "deleted" (EN)
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
                # Nouvelle entree SSID (peut etre vide pour les reseaux masques)
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
                        # Garder le premier BSSID (signal le plus fort)
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

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
