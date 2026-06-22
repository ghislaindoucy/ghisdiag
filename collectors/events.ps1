# Ghisdiag - Collecteur Événements Windows
# Collecte les événements critiques/erreurs des 72 dernières heures

$ErrorActionPreference = "SilentlyContinue"
$result = @{}
$errors = @()

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null)
    try { $val = & $Block; if ($null -eq $val) { return $Default }; return $val }
    catch {
        $msg = $_.Exception.Message
        # "No events were found" / "Aucun événement" = journal propre, pas une erreur
        if ($msg -notmatch "No events were found|Aucun.*nement") {
            $script:errors += "[$Name] $msg"
        }
        return $Default
    }
}

$since = (Get-Date).AddHours(-72)
$maxEvents = 100
$maxMsgLen = 250

function Get-EventLog-Safe {
    param([string]$LogName, [int[]]$Levels, [int]$Max = $maxEvents)
    try {
        $filter = @{ LogName = $LogName; Level = $Levels; StartTime = $since }
        $evts = Get-WinEvent -FilterHashtable $filter -MaxEvents $Max -ErrorAction Stop
        return $evts | ForEach-Object {
            @{
                time_created  = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
                level         = switch ($_.Level) { 1 { "Critical" } 2 { "Error" } 3 { "Warning" } default { "Info" } }
                level_num     = $_.Level
                source        = $_.ProviderName
                event_id      = $_.Id
                message       = $(
                    $m = ($_.Message -replace '\r?\n', ' ')
                    if ($m.Length -gt $maxMsgLen) { $m.Substring(0, $maxMsgLen) + "…" } else { $m }
                )
            }
        }
    } catch {
        # "Aucun événement correspondant" (ErrorRecord NoMatchingEventsFound) = bonne nouvelle,
        # le journal ne contient aucune erreur sur la période. Ce n'est PAS une erreur.
        $msg = $_.Exception.Message
        if ($msg -notmatch "No events were found|Aucun.*nement") {
            $script:errors += "[Events:$LogName] $msg"
        }
        return @()
    }
}

# Fonction helper : convertit le niveau numerique WinEvent en libelle texte
# (switch-as-expression invalide en PS5.1 dans une valeur de hashtable)
function Get-LevelLabel {
    param([int]$Level)
    if ($Level -eq 2) { return "Error" }
    elseif ($Level -eq 3) { return "Warning" }
    elseif ($Level -eq 1) { return "Critical" }
    else { return "Info" }
}

# Fonction helper : tronque un message a N caracteres apres nettoyage des sauts de ligne
function Trim-Message {
    param([string]$Msg, [int]$Max = 300)
    $clean = $Msg -replace '\r?\n', ' '
    if ($clean.Length -gt $Max) { return $clean.Substring(0, $Max) }
    return $clean
}

# Fonction helper generique : evenements d'un provider / liste d'IDs sur N jours.
# Utilisee pour les journaux de fiabilite (materiel, disque, NTFS, services).
function Get-ProviderEvents {
    param(
        [string]$LogName,
        [string]$Provider = $null,
        [int[]]$Ids = $null,
        [int]$Days = 14,
        [int]$Max = 25,
        [int]$MsgLen = 300
    )
    try {
        $filter = @{ LogName = $LogName; StartTime = (Get-Date).AddDays(-$Days) }
        if ($Provider) { $filter['ProviderName'] = $Provider }
        if ($Ids)      { $filter['Id'] = $Ids }
        $evts = Get-WinEvent -FilterHashtable $filter -MaxEvents $Max -ErrorAction Stop
        if (-not $evts) { return @() }
        @($evts | ForEach-Object {
            @{
                time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
                event_id     = [int]$_.Id
                level        = Get-LevelLabel $_.Level
                source       = [string]$_.ProviderName
                message      = Trim-Message $_.Message $MsgLen
            }
        })
    } catch {
        # Journal vide OU provider absent sur cette machine = pas une vraie erreur.
        $msg = $_.Exception.Message
        if ($msg -notmatch "No events were found|Aucun.*nement|could not be found|introuvable") {
            $script:errors += "[$Provider] $msg"
        }
        return @()
    }
}

# ── Journaux principaux ──────────────────────────────────────────────────────
$systemEvents = Get-EventLog-Safe "System"      @(1, 2)
$appEvents    = Get-EventLog-Safe "Application" @(1, 2)
$secEvents    = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName = 'Security'; Id = @(4625, 4648, 4776, 4740); StartTime = $since
    } -MaxEvents 50 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = $_.Id
            level        = "Security"
            source       = $_.ProviderName
            message      = ($_.Message -replace '\r?\n', ' ').Substring(0, [Math]::Min(300, ($_.Message -replace '\r?\n',' ').Length))
            description  = switch ($_.Id) {
                4625 { "Échec d'ouverture de session" }
                4648 { "Tentative de connexion avec credentials explicites" }
                4776 { "Tentative de validation de credentials" }
                4740 { "Compte verrouillé" }
                default { "Événement sécurité" }
            }
        }
    })
} "Security_Events" @()

# ── Top sources d'erreurs ────────────────────────────────────────────────────
$allEvents = @($systemEvents) + @($appEvents)
$topSources = $allEvents | Group-Object { $_["source"] } |
              Sort-Object Count -Descending | Select-Object -First 10 | ForEach-Object {
                  @{ source = $_.Name; count = $_.Count }
              }

# ── Événements lenteur session ────────────────────────────────────────────────
$sessionEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName = 'Security'; Id = @(4624); StartTime = $since
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = $_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = $_.Id
            message      = ($_.Message -replace '\r?\n', ' ').Substring(0, [Math]::Min(200, ($_.Message -replace '\r?\n',' ').Length))
        }
    })
} "SessionEvents" @()

$result["system"] = @{
    count  = $systemEvents.Count
    events = $systemEvents
}

$result["application"] = @{
    count  = $appEvents.Count
    events = $appEvents
}

$result["security"] = @{
    auth_failures_count = ($secEvents | Where-Object { $_["event_id"] -eq 4625 }).Count
    locked_accounts     = ($secEvents | Where-Object { $_["event_id"] -eq 4740 }).Count
    events              = $secEvents
}

$result["top_error_sources"] = $topSources
$result["session_events"]    = $sessionEvents
$result["period_hours"]      = 72
$result["total_errors"]      = $systemEvents.Count + $appEvents.Count

# ── Diagnostics-Performance (ralentissements boot / arrêt / veille) ──────────
# ID 100 = démarrage lent, 101 = appli responsable boot, 200/201 = arrêt,
# 300/301 = reprise de veille. Fenêtre 30j pour capturer démarrages rares.
$diagPerfEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-Diagnostics-Performance/Operational'
        Id        = @(100, 101, 200, 201, 300, 301)
        StartTime = (Get-Date).AddDays(-30)
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        $evId = [int]$_.Id
        $cat  = if ($evId -eq 100) { "boot" }
                elseif ($evId -eq 101) { "boot-app" }
                elseif ($evId -eq 200) { "shutdown" }
                elseif ($evId -eq 201) { "shutdown-app" }
                elseif ($evId -eq 300) { "resume" }
                elseif ($evId -eq 301) { "resume-app" }
                else { "perf" }
        $desc = if ($evId -eq 100) { "Démarrage Windows lent" }
                elseif ($evId -eq 101) { "Application a ralenti le démarrage" }
                elseif ($evId -eq 200) { "Arrêt Windows lent" }
                elseif ($evId -eq 201) { "Application a ralenti l'arrêt" }
                elseif ($evId -eq 300) { "Reprise de veille lente" }
                elseif ($evId -eq 301) { "Application a ralenti la reprise de veille" }
                else { "Événement performance" }
        $msg  = ($_.Message -replace '\r?\n', ' ')

        # Extraction des données structurées depuis le XML de l'événement
        # ID 100 : BootTsTime (ms jusqu'au premier input utilisateur), MainPathBootTime
        # ID 101 : ProcessName (application responsable), Duration
        # ID 200/201 : ShutdownDuration, ProcessName
        # ID 300/301 : StandbyDuration, ProcessName
        $appName    = $null
        $durationMs = $null
        try {
            $xmlDoc   = [xml]$_.ToXml()
            $evtData  = @{}
            $xmlDoc.Event.EventData.Data | ForEach-Object {
                if ($_.Name) { $evtData[$_.Name] = $_.'#text' }
            }
            # Nom du processus responsable
            $appName = $evtData["ProcessName"]
            if (-not $appName) { $appName = $evtData["FileName"] }
            if (-not $appName) { $appName = $evtData["AppName"] }
            # Durée du ralentissement. Pour le boot (ID 100) on privilegie
            # MainPathBootTime (temps jusqu'au bureau utilisable) : c'est la mesure
            # qui reflete la lenteur reellement ressentie, exploitee par le garde-fou
            # cote rapport pour ne pas alerter sur un demarrage normal.
            $dKey = if ($evtData["MainPathBootTime"]) { "MainPathBootTime" }
                    elseif ($evtData["BootTime"]) { "BootTime" }
                    elseif ($evtData["ShutdownDuration"]) { "ShutdownDuration" }
                    elseif ($evtData["StandbyDuration"]) { "StandbyDuration" }
                    elseif ($evtData["Duration"]) { "Duration" }
                    elseif ($evtData["BootTsTime"]) { "BootTsTime" }
                    else { $null }
            if ($dKey) { try { $durationMs = [int]$evtData[$dKey] } catch {} }
        } catch {}

        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = $evId
            category     = [string]$cat
            description  = [string]$desc
            level        = Get-LevelLabel $_.Level
            app_name     = if ($appName) { [string]$appName } else { $null }
            duration_ms  = $durationMs
            message      = [string]$msg.Substring(0, [Math]::Min(400, $msg.Length))
        }
    })
} "DiagPerf" @()

# ── Stratégie de groupe – GPO (lenteur ouverture de session réseau) ───────────
$gpoEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-GroupPolicy/Operational'
        Level     = @(2, 3)
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = [int]$_.Id
            level        = Get-LevelLabel $_.Level
            message      = Trim-Message $_.Message 300
        }
    })
} "GPO" @()

# ── Service profil utilisateur (chargement / erreurs de profil) ───────────────
$profileEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-User Profile Service/Operational'
        Level     = @(2, 3)
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = [int]$_.Id
            level        = Get-LevelLabel $_.Level
            message      = Trim-Message $_.Message 300
        }
    })
} "UserProfile" @()

# ── Profil réseau (connexions / déconnexions réseau) ─────────────────────────
$netProfileEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-NetworkProfile/Operational'
        StartTime = (Get-Date).AddDays(-3)
    } -MaxEvents 40 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = [int]$_.Id
            level        = Get-LevelLabel $_.Level
            message      = Trim-Message $_.Message 200
        }
    })
} "NetProfile" @()

# ── Wi-Fi / WLAN (déconnexions, échecs d'authentification Wi-Fi) ──────────────
$wlanEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Microsoft-Windows-WLAN-AutoConfig/Operational'
        Level     = @(2, 3)
        StartTime = (Get-Date).AddDays(-3)
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = [int]$_.Id
            level        = Get-LevelLabel $_.Level
            message      = Trim-Message $_.Message 200
        }
    })
} "WLAN" @()

# ── Journal d'installation / mises à jour Windows ────────────────────────────
$setupEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'Setup'
        StartTime = (Get-Date).AddDays(-30)
    } -MaxEvents 20 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        @{
            time_created = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id     = [int]$_.Id
            level        = Get-LevelLabel $_.Level
            message      = Trim-Message $_.Message 200
        }
    })
} "Setup" @()

# ── Plantages & redemarrages inattendus (BSOD / crash / coupure) ─────────────
# Fenetre 14 jours : un plantage de la semaine passee doit rester visible.
# ID 41 = redemarrage sans arret propre (Kernel-Power), 1001 = BugCheck (BSOD),
# 6008 = arret systeme precedent inattendu.
$crashEvents = Safe-Get {
    $evts = Get-WinEvent -FilterHashtable @{
        LogName   = 'System'
        Id        = @(41, 1001, 6008)
        StartTime = (Get-Date).AddDays(-14)
    } -MaxEvents 30 -ErrorAction Stop
    if (-not $evts) { return @() }
    @($evts | ForEach-Object {
        $evId = [int]$_.Id
        $kind = if ($evId -eq 41) { "redemarrage-inattendu" }
                elseif ($evId -eq 1001) { "bugcheck-bsod" }
                elseif ($evId -eq 6008) { "arret-inattendu" }
                else { "crash" }
        # Code BugCheck (BSOD) : depuis les donnees XML pour l'ID 41 (0 = simple
        # coupure, pas un crash), depuis le message pour l'ID 1001.
        $bugcheck = $null
        try {
            $xmlDoc = [xml]$_.ToXml()
            $data   = @{}
            $xmlDoc.Event.EventData.Data | ForEach-Object { if ($_.Name) { $data[$_.Name] = $_.'#text' } }
            if ($evId -eq 41 -and $data["BugcheckCode"]) {
                $bc = 0
                if ([int]::TryParse([string]$data["BugcheckCode"], [ref]$bc) -and $bc -ne 0) {
                    $bugcheck = ('0x{0:X8}' -f $bc)
                }
            }
        } catch {}
        if (-not $bugcheck -and $evId -eq 1001) {
            $mm = [regex]::Match([string]$_.Message, '0x[0-9A-Fa-f]{8}')
            if ($mm.Success) { $bugcheck = $mm.Value }
        }
        @{
            time_created  = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event_id      = $evId
            kind          = [string]$kind
            level         = Get-LevelLabel $_.Level
            bugcheck_code = $bugcheck
            message       = Trim-Message $_.Message 350
        }
    })
} "Crash" @()

# ── Erreurs materielles WHEA (CPU / RAM / PCIe : corrigees ou non) ───────────
$wheaEvents = Get-ProviderEvents 'System' 'Microsoft-Windows-WHEA-Logger' $null 30 20 300

# ── Erreurs disque (I/O, secteurs defectueux, timeouts controleur) ───────────
$diskEvents = Get-ProviderEvents 'System' 'disk' @(7, 11, 51, 153) 14 20 250

# ── Corruption du systeme de fichiers NTFS ───────────────────────────────────
# IDs reellement lies a une corruption / un risque :
#   55  = structure du systeme de fichiers corrompue (chkdsk requis) — Erreur
#   57  = echec d'ecriture dans le journal de transactions (corruption possible) — Avert.
#   137 = gestionnaire de ressources transactionnelles en erreur non recuperable — Erreur
# L'ID 98 ("Volume X est sain. Aucune action n'est necessaire", niveau Info) est un
# message de BONNE SANTE emis par l'auto-verification NTFS : il ne doit PAS etre
# compte comme une corruption (sinon faux positif a chaque verification de routine).
$ntfsEvents = Get-ProviderEvents 'System' 'Microsoft-Windows-Ntfs' @(55, 57, 137) 14 20 250

# ── Services en echec (crash, timeout, demarrage impossible) ─────────────────
$scmEvents = Get-ProviderEvents 'System' 'Service Control Manager' @(7000, 7001, 7009, 7011, 7022, 7023, 7024, 7031, 7034) 7 30 250

$result["crash_events"]   = $crashEvents
$result["whea_events"]    = $wheaEvents
$result["disk_events"]    = $diskEvents
$result["ntfs_events"]    = $ntfsEvents
$result["scm_events"]     = $scmEvents

$result["diag_perf"]      = $diagPerfEvents
$result["gpo_events"]     = $gpoEvents
$result["profile_events"] = $profileEvents
$result["net_profile"]    = $netProfileEvents
$result["wlan_events"]    = $wlanEvents
$result["setup_events"]   = $setupEvents

$result["collector_errors"] = $errors
$result["collected_at"]     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]        = "events"

$result | ConvertTo-Json -Depth 10 -Compress
