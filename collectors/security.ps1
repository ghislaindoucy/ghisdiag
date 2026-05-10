# PlanetDiag - Collecteur Sécurité
# Collecte antivirus, pare-feu, MAJ Windows, UAC, connexions utilisateur

$ErrorActionPreference = "SilentlyContinue"
$result  = @{}
$errors  = @()
$timings = @{}

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null, [int]$TimeoutSec = 0)
    $t0 = Get-Date
    try {
        if ($TimeoutSec -gt 0) {
            # Exécution dans un job avec timeout pour éviter les blocages COM/WMI
            $job = Start-Job -ScriptBlock $Block
            $done = Wait-Job $job -Timeout $TimeoutSec
            if (-not $done) {
                Stop-Job $job; Remove-Job $job -Force
                # WindowsUpdate COM peut bloquer sur certains PC — timeout normal, pas une panne
            $script:errors += "[$Name] Timeout après ${TimeoutSec}s (Windows Update lent ou indisponible)"
                $script:timings[$Name] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
                return $Default
            }
            $val = Receive-Job $job
            Remove-Job $job -Force
        } else {
            $val = & $Block
        }
        $script:timings[$Name] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
        if ($null -eq $val) { return $Default }
        return $val
    } catch {
        $script:errors  += "[$Name] $($_.Exception.Message)"
        $script:timings[$Name] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
        return $Default
    }
}

# ── Antivirus (Windows Security Center) ─────────────────────────────────────
$antivirus = Safe-Get -Name "Antivirus" -Default @() -Block {
    # @() force un tableau même si un seul produit — évite la sérialisation en objet seul
    @(Get-CimInstance -Namespace "root/SecurityCenter2" -ClassName AntiVirusProduct `
        -OperationTimeoutSec 15 -ErrorAction Stop | ForEach-Object {
        $stateHex = "{0:X6}" -f $_.productState
        $realtime  = [Convert]::ToInt32($stateHex.Substring(2, 2), 16)
        $defStatus = [Convert]::ToInt32($stateHex.Substring(4, 2), 16)
        @{
            name             = [string]$_.displayName   # cast explicite → évite DateTime/Object
            state_hex        = $stateHex
            realtime_enabled = [bool]($realtime -eq 16)
            definitions_ok   = [bool]($defStatus -eq 0)
            # timestamp retiré : DateTime PS5.1 se sérialise en objet complexe non parsable
            path             = [string]$_.pathToSignedProductExe
        }
    })
}

# ── Pare-feu Windows ─────────────────────────────────────────────────────────
$firewall = Safe-Get -Name "Firewall" -Default @() -Block {
    @(Get-NetFirewallProfile -ErrorAction Stop | ForEach-Object {
        @{
            profile          = [string]$_.Name
            enabled          = [bool]$_.Enabled
            default_inbound  = [string]$_.DefaultInboundAction
            default_outbound = [string]$_.DefaultOutboundAction
        }
    })
}

# ── Mises à jour Windows (via Job avec timeout 45s — COM peut se bloquer) ────
$wuSession = Safe-Get -Name "WindowsUpdate_Pending" -Default @{
    pending_count = -1; pending_items = @()
    note = "Service Windows Update non disponible ou timeout"
} -TimeoutSec 30 -Block {
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $pending  = $searcher.Search("IsInstalled=0 and Type='Software'")
    @{
        pending_count = $pending.Updates.Count
        pending_items = @($pending.Updates | ForEach-Object {
            @{ title = $_.Title; severity = $_.MsrcSeverity }
        } | Select-Object -First 10)
    }
}

$installedUpdates = Safe-Get -Name "WindowsUpdate_History" -Default @() -TimeoutSec 30 -Block {
    $session  = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $total    = $searcher.GetTotalHistoryCount()
    @($searcher.QueryHistory(0, [Math]::Min($total, 10)) | ForEach-Object {
        @{
            title       = $_.Title
            date        = if ($_.Date) { $_.Date.ToString("yyyy-MM-dd") } else { "N/A" }
            result_code = $_.ResultCode
            success     = ($_.ResultCode -eq 2)
        }
    })
}

# ── UAC ──────────────────────────────────────────────────────────────────────
$uac = Safe-Get -Name "UAC" -Default @{ enabled = $null; prompt_level = $null } -Block {
    $key = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" `
           -ErrorAction Stop
    @{
        enabled      = ($key.EnableLUA -eq 1)
        prompt_level = $key.ConsentPromptBehaviorAdmin
        prompt_label = switch ($key.ConsentPromptBehaviorAdmin) {
            0 { "Elevate without prompting (RISQUE)" }
            1 { "Prompt for credentials (sécurisé)" }
            2 { "Prompt for consent on secure desktop" }
            5 { "Prompt for consent (défaut)" }
            default { "Unknown" }
        }
    }
}

# ── Dernières connexions utilisateur (journal Sécurité) ───────────────────────
$lastLogons = Safe-Get -Name "LastLogons" -Default @() -TimeoutSec 20 -Block {
    @(Get-WinEvent -FilterHashtable @{
        LogName   = 'Security'
        Id        = @(4624, 4625)
        StartTime = (Get-Date).AddDays(-7)
    } -MaxEvents 50 -ErrorAction Stop | ForEach-Object {
        $msg  = $_.Message
        $user = if   ($msg -match "Nom du compte :\s+(\S+)") { $Matches[1] }
                elseif ($msg -match "Account Name:\s+(\S+)")  { $Matches[1] }
                else { "N/A" }
        @{
            time  = [string]$_.TimeCreated.ToString("yyyy-MM-dd HH:mm:ss")
            event = [string](if ($_.Id -eq 4624) { "Succès" } else { "Échec" })
            user  = [string]$user
            id    = [int]$_.Id
        }
    })
}

$result["antivirus"]         = $antivirus
$result["firewall"]          = $firewall
$result["windows_update"]    = $wuSession
$result["installed_updates"] = $installedUpdates
$result["uac"]               = $uac
$result["last_logons"]       = $lastLogons
$result["logon_failures"]    = @($lastLogons | Where-Object { $_["id"] -eq 4625 }).Count

$result["collector_errors"]  = $errors
$result["collector_timings"] = $timings
$result["collected_at"]      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]         = "security"

$result | ConvertTo-Json -Depth 10 -Compress
