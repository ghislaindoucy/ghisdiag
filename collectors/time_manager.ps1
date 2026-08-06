# Ghisdiag - Reglage de l'heure, de la date et du fuseau horaire
# Pas de caractere non-ASCII (regle PS du projet).
#
# Deux chemins volontairement independants :
#   - sync-internet : NTP via w32tm, quand la machine a du reseau
#   - set-manual    : saisie a la main, cas courant en atelier sur une machine
#                     fraichement reinstallee et pas encore connectee
# L'echec du premier ne doit jamais etre une impasse : il rend une erreur
# exploitable, et l'interface bascule sur le second.
param(
    [string]$Action     = "status",
    [string]$TimeZoneId = "",
    [string]$DateTime   = "",                 # format strict "yyyy-MM-dd HH:mm:ss"
    [string]$Server     = "time.windows.com"
)

$ErrorActionPreference = "SilentlyContinue"

$FMT      = "yyyy-MM-dd HH:mm:ss"
$INVAR    = [System.Globalization.CultureInfo]::InvariantCulture
$MIN_YEAR = 2000
$MAX_YEAR = 2100

function Get-PropSafe($obj, [string]$prop) {
    try { return $obj.$prop } catch { return $null }
}

function Test-SafeServer([string]$name) {
    # Nom d'hote NTP : lettres/chiffres/point/tiret, eventuellement plusieurs
    # separes par des virgules. Ferme la porte a une injection dans w32tm.
    return $name -match '^[a-zA-Z0-9\.\-]{1,64}$'
}

function Get-DomainJoined {
    $cs = Get-CimInstance Win32_ComputerSystem -EA SilentlyContinue
    if ($null -eq $cs) { return $false }
    return [bool](Get-PropSafe $cs 'PartOfDomain')
}

function Get-TimeState {
    $now = Get-Date
    $tz  = Get-TimeZone -EA SilentlyContinue

    $svc     = Get-Service -Name W32Time -EA SilentlyContinue

    # w32tm rend son message d'erreur sur la sortie standard (par ex. "Acces
    # refuse" sans elevation) : sans le code retour, on afficherait ce texte
    # comme s'il etait la source de temps.
    $source = (& w32tm /query /source 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { $source = $null }
    elseif ($source.Length -gt 200) { $source = $source.Substring(0, 200) }

    # Connectivite : sert seulement a orienter l'utilisateur vers la saisie
    # manuelle avant qu'il n'attende une synchro qui ne peut pas aboutir.
    $online = $false
    foreach ($p in @(Get-NetConnectionProfile -EA SilentlyContinue)) {
        if ($p.IPv4Connectivity -eq 'Internet' -or $p.IPv6Connectivity -eq 'Internet') {
            $online = $true
        }
    }

    return @{
        local_time      = $now.ToString($FMT)
        utc_time        = $now.ToUniversalTime().ToString($FMT)
        timezone_id     = if ($tz) { "$($tz.Id)" } else { $null }
        timezone_name   = if ($tz) { "$($tz.DisplayName)" } else { $null }
        utc_offset      = if ($tz) { "$($tz.BaseUtcOffset)" } else { $null }
        daylight        = if ($tz) { [bool]$tz.SupportsDaylightSavingTime } else { $null }
        is_daylight     = [bool]$now.IsDaylightSavingTime()
        w32time_status  = if ($svc) { "$($svc.Status)" } else { $null }
        w32time_start   = if ($svc) { "$($svc.StartType)" } else { $null }
        time_source     = $source
        domain_joined   = Get-DomainJoined
        internet        = $online
    }
}

switch ($Action) {

    "status" {
        try {
            @{ success = $true; state = (Get-TimeState) } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "list-timezones" {
        try {
            $zones = @(
                Get-TimeZone -ListAvailable -EA Stop |
                Sort-Object BaseUtcOffset, Id |
                ForEach-Object {
                    @{ id = "$($_.Id)"; name = "$($_.DisplayName)" }
                }
            )
            @{ success = $true; timezones = $zones } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "set-timezone" {
        try {
            if ([string]::IsNullOrWhiteSpace($TimeZoneId)) {
                @{ success = $false; error = "Aucun fuseau horaire indique." } | ConvertTo-Json
                break
            }
            # On valide l'identifiant contre la liste systeme plutot que de le
            # passer tel quel : Set-TimeZone accepte un pipeline d'objets.
            $known = @(Get-TimeZone -ListAvailable -EA Stop | ForEach-Object { $_.Id })
            if ($known -notcontains $TimeZoneId) {
                @{ success = $false
                   error   = "Fuseau horaire inconnu : $TimeZoneId" } | ConvertTo-Json
                break
            }
            Set-TimeZone -Id $TimeZoneId -EA Stop
            @{ success = $true
               message = "Fuseau horaire regle sur '$TimeZoneId'."
               state   = (Get-TimeState) } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "sync-internet" {
        try {
            if (-not (Test-SafeServer $Server)) {
                @{ success = $false
                   error   = "Nom de serveur NTP invalide : $Server" } | ConvertTo-Json
                break
            }

            $svc = Get-Service -Name W32Time -EA SilentlyContinue
            if ($null -eq $svc) {
                @{ success = $false
                   error   = "Le service de temps Windows (W32Time) est introuvable." } | ConvertTo-Json
                break
            }
            if ("$($svc.StartType)" -eq "Disabled") {
                Set-Service -Name W32Time -StartupType Manual -EA Stop
            }
            if ("$($svc.Status)" -ne "Running") {
                Start-Service -Name W32Time -EA Stop
                Start-Sleep -Milliseconds 500
            }

            # Sur une machine du domaine, la hierarchie de temps est fixee par
            # l'AD : on ne reecrit pas la liste de pairs, on demande juste une
            # resynchronisation.
            $domain = Get-DomainJoined
            $conf   = ""
            if (-not $domain) {
                $conf = (& w32tm /config "/manualpeerlist:$Server,0x9" /syncfromflags:manual /update 2>&1 | Out-String).Trim()
            }

            $out  = (& w32tm /resync /force 2>&1 | Out-String).Trim()
            $code = $LASTEXITCODE
            if ($out.Length -gt 400) { $out = $out.Substring(0, 400) }

            if ($code -ne 0) {
                @{ success = $false
                   error   = "La synchronisation a echoue. Detail : $out"
                   detail  = $out
                   domain_joined = $domain
                   state   = (Get-TimeState) } | ConvertTo-Json -Depth 4
                break
            }

            $st = Get-TimeState
            @{ success = $true
               message = "Heure synchronisee sur $Server (heure locale : $($st.local_time))."
               detail  = "$conf`n$out".Trim()
               domain_joined = $domain
               state   = $st } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "set-manual" {
        try {
            $parsed = $null
            try {
                $parsed = [datetime]::ParseExact($DateTime, $FMT, $INVAR)
            } catch {
                @{ success = $false
                   error   = "Date/heure illisible : '$DateTime' (format attendu AAAA-MM-JJ HH:MM:SS)." } | ConvertTo-Json
                break
            }
            if ($parsed.Year -lt $MIN_YEAR -or $parsed.Year -gt $MAX_YEAR) {
                @{ success = $false
                   error   = "Annee hors plage ($MIN_YEAR-$MAX_YEAR) : $($parsed.Year)." } | ConvertTo-Json
                break
            }

            Set-Date -Date $parsed -EA Stop | Out-Null

            $st = Get-TimeState
            @{ success = $true
               message = "Horloge reglee sur $($st.local_time)."
               state   = $st } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
