# Ghisdiag - Collecteur Logiciels & Drivers
# Collecte logiciels installés, MAJ Windows, drivers

$ErrorActionPreference = "SilentlyContinue"
$result  = @{}
$errors  = @()
$timings = @{}

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null)
    $t0 = Get-Date
    try {
        $val = & $Block
        $script:timings[$Name] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
        if ($null -eq $val) { return $Default }
        return $val
    } catch {
        $script:errors  += "[$Name] $($_.Exception.Message)"
        $script:timings[$Name] = [math]::Round(((Get-Date) - $t0).TotalSeconds, 2)
        return $Default
    }
}

# ── Logiciels installés ───────────────────────────────────────────────────────
$t0sw = Get-Date
$regPaths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
    "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
)

$software = [System.Collections.Generic.List[hashtable]]::new()
$seen     = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($path in $regPaths) {
    try {
        Get-ItemProperty $path -ErrorAction Stop |
        Where-Object { $_.DisplayName -and $_.DisplayName.Trim() -ne "" } |
        ForEach-Object {
            $key = $_.DisplayName.Trim()
            if ($seen.Add($key)) {
                $installDate = $null
                if ($_.InstallDate -match "^\d{8}$") {
                    try { $installDate = [datetime]::ParseExact($_.InstallDate,"yyyyMMdd",$null).ToString("yyyy-MM-dd") } catch {}
                }
                $software.Add(@{
                    name         = $key
                    version      = $_.DisplayVersion
                    publisher    = $_.Publisher
                    install_date = $installDate
                    size_mb      = if ($_.EstimatedSize) { [math]::Round($_.EstimatedSize/1024,1) } else { $null }
                })
            }
        }
    } catch { $errors += "[Software:$path] $($_.Exception.Message)" }
}

$timings["Software_Registry"] = [math]::Round(((Get-Date) - $t0sw).TotalSeconds, 2)
$software = @($software | Sort-Object { $_["name"] })

# ── Mises à jour Windows ─────────────────────────────────────────────────────
$wuHistory = Safe-Get -Name "WUHistory" -Default @() -Block {
    @(Get-HotFix -ErrorAction Stop |
      Sort-Object InstalledOn -Descending |
      Select-Object -First 10 |
      ForEach-Object {
        @{
            hotfix_id    = $_.HotFixID
            description  = $_.Description
            installed_by = $_.InstalledBy
            installed_on = if ($_.InstalledOn) { $_.InstalledOn.ToString("yyyy-MM-dd") } else { "N/A" }
        }
      })
}

# ── Drivers : pré-chargement unique de Win32_PnPEntity (évite le N+1) ────────
# ANCIENNE APPROCHE (lente) : un Get-CimInstance Win32_PnPEntity par driver
#   → 200+ requêtes WMI séquentielles, 60-120s, timeout possible
# NOUVELLE APPROCHE : 1 seule requête groupée → hashtable DeviceID → O(1) lookup
$t0pnp = Get-Date
$pnpMap = @{}
try {
    Get-CimInstance Win32_PnPEntity -OperationTimeoutSec 30 -ErrorAction Stop |
    ForEach-Object { $pnpMap[$_.DeviceID] = $_.ConfigManagerErrorCode }
    $timings["PnPEntity_Bulk"] = [math]::Round(((Get-Date) - $t0pnp).TotalSeconds, 2)
} catch {
    $errors += "[PnPEntity] $($_.Exception.Message)"
    $timings["PnPEntity_Bulk"] = [math]::Round(((Get-Date) - $t0pnp).TotalSeconds, 2)
}

$t0drv = Get-Date
$drivers = Safe-Get -Name "Drivers" -Default @() -Block {
    @(Get-CimInstance Win32_PnPSignedDriver -OperationTimeoutSec 30 -ErrorAction Stop |
      ForEach-Object {
        $errCode = if ($pnpMap.ContainsKey($_.DeviceID)) { $pnpMap[$_.DeviceID] } else { 0 }
        $status  = switch ($errCode) {
            0  { "OK" }
            1  { "Erreur: code de configuration" }
            10 { "Erreur: impossible de démarrer" }
            18 { "Réinstallation requise" }
            22 { "Désactivé" }
            28 { "Drivers non installés" }
            43 { "Erreur signalée par périphérique" }
            default { if ($errCode -gt 0) { "Erreur (code $errCode)" } else { "OK" } }
        }

        $driverDate = $null
        if ($_.DriverDate) { try { $driverDate = $_.DriverDate.ToString("yyyy-MM-dd") } catch {} }

        @{
            device_name    = $_.DeviceName
            manufacturer   = $_.Manufacturer
            driver_version = $_.DriverVersion
            driver_date    = $driverDate
            inf_name       = $_.InfName
            device_class   = [string]$_.DeviceClass
            is_signed      = $_.IsSigned
            signer         = [string]$_.Signer
            present        = $pnpMap.ContainsKey($_.DeviceID)
            status         = $status
            is_ok          = ($errCode -eq 0 -or $errCode -eq $null)
        }
      })
}

$thirtyDaysAgo    = (Get-Date).AddDays(-30).ToString("yyyy-MM-dd")
$driversWithError = @($drivers | Where-Object { -not $_["is_ok"] })
$recentDrivers    = @($drivers | Where-Object { $_["driver_date"] -and $_["driver_date"] -gt $thirtyDaysAgo })

# ── Pilotes non signés / obsolètes (v1.8.0) ──────────────────────────────────
# Garde-fous anti-faux-positifs :
#  - périphérique PRÉSENT uniquement (DeviceID vu par Win32_PnPEntity) : les
#    périphériques fantômes traînent de vieux drivers sans aucun impact ;
#  - obsolescence : drivers "boîte" Windows exclus — ils sont datés volontairement
#    (souvent 2006-06-21) et maintenus via Windows Update. Attention : les drivers
#    vendeurs WHQL sont signés "Microsoft Windows Hardware Compatibility
#    Publisher" ; seul le signataire EXACT "Microsoft Windows" désigne un driver
#    boîte, d'où le -ne strict et non un -match ;
#  - classes pertinentes uniquement (GPU, réseau, audio, stockage, USB, BT) :
#    un vieux driver d'imprimante n'explique ni lenteur ni instabilité.
$fiveYearsAgo    = (Get-Date).AddYears(-5).ToString("yyyy-MM-dd")
$relevantClasses = @("DISPLAY", "NET", "MEDIA", "HDC", "SCSIADAPTER", "USB", "BLUETOOTH")

$unsignedDrivers = @($drivers | Where-Object {
    $_["present"] -and ($_["is_signed"] -eq $false)
})

$outdatedDrivers = @($drivers | Where-Object {
    $_["present"] -and $_["driver_date"] -and ($_["driver_date"] -lt $fiveYearsAgo) -and
    ($relevantClasses -contains $_["device_class"].ToUpper()) -and
    ($_["manufacturer"] -notmatch "^Microsoft") -and
    ($_["signer"] -ne "Microsoft Windows")
})

# Dédoublonnage : le même INF apparaît une fois par périphérique (hubs USB…) ;
# un driver = un problème, pas dix. Tri du plus ancien au plus récent.
$seenDrv = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
$outdatedDrivers = @($outdatedDrivers |
    Where-Object { $seenDrv.Add("$($_["inf_name"])|$($_["driver_version"])") } |
    Sort-Object { $_["driver_date"] } |
    Select-Object -First 30)
$unsignedDrivers = @($unsignedDrivers | Select-Object -First 30)

$result["software"] = @{
    count = $software.Count
    items = $software
}

$result["windows_updates"] = @{
    count = $wuHistory.Count
    items = $wuHistory
}

$result["drivers"] = @{
    total            = $drivers.Count
    errors_count     = $driversWithError.Count
    recent_count     = $recentDrivers.Count
    error_drivers    = $driversWithError
    recent_drivers   = $recentDrivers
    unsigned_count   = $unsignedDrivers.Count
    outdated_count   = $outdatedDrivers.Count
    unsigned_drivers = $unsignedDrivers
    outdated_drivers = $outdatedDrivers
}

$result["collector_errors"]  = $errors
$result["collector_timings"] = $timings
$result["collected_at"]      = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]         = "software"

$result | ConvertTo-Json -Depth 10 -Compress
