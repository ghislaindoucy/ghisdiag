# Ghisdiag - Fiche machine (onglet Setup / MAJ, sous-onglet Machine)
# Resume de la machine pour le technicien, affiche a l'ouverture de l'app :
# identite, Windows, processeur, memoire, stockage, comptes, securite,
# batterie, reseau, peripheriques en erreur.
#
# LECTURE SEULE. Doit rester rapide (quelques secondes) : il tourne au
# lancement, en meme temps que le moniteur et la verification SMART. Pas de
# Windows Update ici (COM qui peut bloquer 30 s) : c'est le role du diagnostic.
#
# Les valeurs brutes sont renvoyees telles quelles (codes SMBIOS, statut de
# licence, types de chassis) : leur traduction vit dans machine_info.py, ou
# elle est testable.
#
# Pas de caractere non-ASCII (regle PS du projet).

$ErrorActionPreference = "SilentlyContinue"
$errors = @()
. "$PSScriptRoot\_common.ps1"

$result = @{}

# Duree de chaque section (s), renvoyee dans collector_timings : c'est la page
# affichee a l'ouverture, une section lente doit se voir sans rejouer a la main.
$timings = [ordered]@{}
$sw = [Diagnostics.Stopwatch]::StartNew()
function Mark([string]$name) {
    $script:timings[$name] = [math]::Round($script:sw.Elapsed.TotalSeconds, 2)
    $script:sw.Restart()
}

# BitLocker (Win32_EncryptableVolume) et Win32_Tpm exigent les droits admin, et
# mettent 5 s chacun a renvoyer le refus (mesure). Sans droits on ne les
# interroge pas : ils restent "non lus", ce qui est la verite.
$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

function Format-Date($d) {
    if (-not $d) { return $null }
    try { return $d.ToString("yyyy-MM-dd HH:mm:ss") } catch { return $null }
}

function Test-RegKey([string]$path) {
    try { return [bool](Test-Path -Path $path -ErrorAction Stop) } catch { return $false }
}

$os   = Safe-Get { Get-CimInstance Win32_OperatingSystem -ErrorAction Stop } "OS"
$cs   = Safe-Get { Get-CimInstance Win32_ComputerSystem -ErrorAction Stop } "ComputerSystem"
$bios = Safe-Get { Get-CimInstance Win32_BIOS -ErrorAction Stop } "BIOS"
$csp  = Safe-Get { Get-CimInstance Win32_ComputerSystemProduct -ErrorAction Stop | Select-Object -First 1 } "Product"
$encl = Safe-Get { Get-CimInstance Win32_SystemEnclosure -ErrorAction Stop | Select-Object -First 1 } "Enclosure"

Mark "cim_base"

# -- Identite ------------------------------------------------------------------
# dsregcmd dit si la machine est jointe a Entra ID (ex-Azure AD) : un poste
# d'entreprise ne se reinstalle pas comme un poste particulier.
$azureJoined = $null
$dsreg = Safe-Get { & dsregcmd.exe /status 2>$null } "dsregcmd"
if ($dsreg) {
    $line = @($dsreg) | Where-Object { $_ -match '^\s*AzureAdJoined\s*:' } | Select-Object -First 1
    if ($line) { $azureJoined = ($line -match 'YES') }
}

$result["machine"] = @{
    name            = $env:COMPUTERNAME
    manufacturer    = if ($cs) { "$($cs.Manufacturer)".Trim() } else { $null }
    model           = if ($cs) { "$($cs.Model)".Trim() } else { $null }
    # Lenovo range le nom commercial ici (Model = "20L5CTO1WW", Version = "ThinkPad T480")
    product_version = if ($csp) { "$($csp.Version)".Trim() } else { $null }
    serial          = if ($bios) { "$($bios.SerialNumber)".Trim() } else { $null }
    chassis_types   = if ($encl -and $encl.ChassisTypes) { @($encl.ChassisTypes | ForEach-Object { [int]$_ }) } else { @() }
    part_of_domain  = if ($cs) { [bool]$cs.PartOfDomain } else { $null }
    domain          = if ($cs -and $cs.PartOfDomain) { $cs.Domain } else { $null }
    workgroup       = if ($cs -and -not $cs.PartOfDomain) { $cs.Workgroup } else { $null }
    azure_ad_joined = $azureJoined
    bios_version    = if ($bios) { $bios.SMBIOSBIOSVersion } else { $null }
    bios_date       = if ($bios) { Format-Date $bios.ReleaseDate } else { $null }
}

Mark "identite"

# -- Windows -------------------------------------------------------------------
$cv = Safe-Get { Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion" -ErrorAction Stop } "CurrentVersion"

$uptimeHours = $null
if ($os -and $os.LastBootUpTime) {
    try { $uptimeHours = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1) } catch {}
}

# Canal Windows : filtre cote WMI (la classe entiere est lente a enumerer).
$lic = Safe-Get {
    Get-CimInstance -ClassName SoftwareLicensingProduct -OperationTimeoutSec 20 -ErrorAction Stop `
        -Filter "ApplicationID='55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey IS NOT NULL" |
        Select-Object -First 1
} "Activation"
# Presence d'une cle OEM dans le firmware (reinstallation sans cle a saisir).
# La cle elle-meme n'est pas renvoyee.
$oa3 = Safe-Get {
    (Get-CimInstance -ClassName SoftwareLicensingService -OperationTimeoutSec 20 -ErrorAction Stop).OA3xOriginalProductKey
} "OEMKey"

$result["windows"] = @{
    caption         = if ($os) { "$($os.Caption)".Trim() } else { $null }
    edition_id      = if ($cv) { $cv.EditionID } else { $null }
    display_version = if ($cv -and $cv.DisplayVersion) { $cv.DisplayVersion } elseif ($cv) { $cv.ReleaseId } else { $null }
    build           = if ($os) { $os.BuildNumber } else { $null }
    ubr             = if ($cv) { $cv.UBR } else { $null }
    architecture    = if ($os) { $os.OSArchitecture } else { $null }
    install_date    = if ($os) { Format-Date $os.InstallDate } else { $null }
    last_boot       = if ($os) { Format-Date $os.LastBootUpTime } else { $null }
    uptime_hours    = $uptimeHours
    license_status  = if ($lic) { [int]$lic.LicenseStatus } else { $null }
    license_channel = if ($lic) { $lic.ProductKeyChannel } else { $null }
    oem_key_in_firmware = [bool]$oa3
    reboot_pending  = (
        (Test-RegKey "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending") -or
        (Test-RegKey "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired")
    )
}

Mark "windows"

# -- Processeur ----------------------------------------------------------------
# -Property : sans elle, Win32_Processor calcule LoadPercentage et coute ~1 s.
$cpus = @(Safe-Get {
    Get-CimInstance Win32_Processor -Property Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed -ErrorAction Stop
} "CPU" @())

# Charge : deux releves BRUTS a 1 s d'intervalle. La classe "Formatted" renvoie
# souvent 0 au premier appel d'un processus neuf - une valeur fausse affichee
# comme vraie. Les noms de compteurs de Get-Counter sont traduits, pas ceux-ci.
$cpuLoad = $null
try {
    $f = "Name='_Total'"
    $a = Get-CimInstance Win32_PerfRawData_PerfOS_Processor -Filter $f -ErrorAction Stop
    Start-Sleep -Milliseconds 1000
    $b = Get-CimInstance Win32_PerfRawData_PerfOS_Processor -Filter $f -ErrorAction Stop
    $dt = [double]$b.Timestamp_Sys100NS - [double]$a.Timestamp_Sys100NS
    $di = [double]$b.PercentProcessorTime - [double]$a.PercentProcessorTime
    if ($dt -gt 0) {
        $cpuLoad = [math]::Round((1 - ($di / $dt)) * 100, 0)
        if ($cpuLoad -lt 0)   { $cpuLoad = 0 }
        if ($cpuLoad -gt 100) { $cpuLoad = 100 }
    }
} catch {
    $errors += "[CPULoad] $($_.Exception.Message)"
}

$result["cpu"] = @{
    name         = if ($cpus.Count -gt 0) { "$($cpus[0].Name)".Trim() } else { $null }
    sockets      = $cpus.Count
    cores        = [int](($cpus | Measure-Object -Property NumberOfCores -Sum).Sum)
    threads      = [int](($cpus | Measure-Object -Property NumberOfLogicalProcessors -Sum).Sum)
    max_mhz      = if ($cpus.Count -gt 0) { $cpus[0].MaxClockSpeed } else { $null }
    load_percent = $cpuLoad
}

Mark "processeur"

# -- Memoire -------------------------------------------------------------------
$totalBytes = if ($cs) { [double]$cs.TotalPhysicalMemory } else { 0 }
$freeBytes  = if ($os) { [double]$os.FreePhysicalMemory * 1KB } else { 0 }
$modules = @(Safe-Get { Get-CimInstance Win32_PhysicalMemory -ErrorAction Stop } "RAMModules" @())
$arrays  = @(Safe-Get { Get-CimInstance Win32_PhysicalMemoryArray -ErrorAction Stop } "RAMArray" @())

$result["memory"] = @{
    total_gb    = if ($totalBytes -gt 0) { [math]::Round($totalBytes / 1GB, 1) } else { $null }
    used_gb     = if ($totalBytes -gt 0) { [math]::Round(($totalBytes - $freeBytes) / 1GB, 1) } else { $null }
    used_percent = if ($totalBytes -gt 0) { [math]::Round((($totalBytes - $freeBytes) / $totalBytes) * 100, 0) } else { $null }
    slots_total = [int](($arrays | Measure-Object -Property MemoryDevices -Sum).Sum)
    modules     = @($modules | Where-Object { $_ } | ForEach-Object {
        @{
            slot         = $_.DeviceLocator
            capacity_gb  = [math]::Round([double]$_.Capacity / 1GB, 0)
            speed_mhz    = if ($_.ConfiguredClockSpeed) { $_.ConfiguredClockSpeed } else { $_.Speed }
            smbios_type  = $_.SMBIOSMemoryType
            manufacturer = "$($_.Manufacturer)".Trim()
            part_number  = "$($_.PartNumber)".Trim()
        }
    })
}

Mark "memoire"

# -- Stockage ------------------------------------------------------------------
$bitlocker = @{}
$enc = @()
if ($elevated) {
    $enc = Safe-Get {
        Get-CimInstance -Namespace "root/cimv2/Security/MicrosoftVolumeEncryption" `
            -ClassName Win32_EncryptableVolume -ErrorAction Stop
    } "BitLocker" @()
}
foreach ($v in @($enc)) {
    if ($v -and $v.DriveLetter) { $bitlocker[$v.DriveLetter] = [int]$v.ProtectionStatus }
}

# Lettre de lecteur -> numero de disque, pour ranger les volumes sous leur disque.
# Association WMI plutot que Get-Partition : le module Storage coute ~1,5 s a
# charger, sur une page affichee a l'ouverture.
$letterToDisk = @{}
foreach ($l in @(Safe-Get { Get-CimInstance Win32_LogicalDiskToPartition -ErrorAction Stop } "DiskToPartition" @())) {
    if ($l -and "$($l.Antecedent.DeviceID)" -match 'Disk #(\d+)') {
        $letterToDisk["$($l.Dependent.DeviceID)"] = [int]$Matches[1]
    }
}

# Codes numeriques (MediaType, BusType, HealthStatus) traduits dans machine_info.py.
$physical = @(Safe-Get {
    Get-CimInstance -Namespace "root/Microsoft/Windows/Storage" -ClassName MSFT_PhysicalDisk -ErrorAction Stop
} "PhysicalDisk" @())
$result["disks"] = @($physical | Where-Object { $_ } | Sort-Object { [int]$_.DeviceId } | ForEach-Object {
    @{
        number     = [int]$_.DeviceId
        model      = "$($_.FriendlyName)".Trim()
        media_type = [int]$_.MediaType
        bus_type   = [int]$_.BusType
        size_gb    = [math]::Round([double]$_.Size / 1GB, 0)
        health     = [int]$_.HealthStatus
    }
})

$logical = @(Safe-Get { Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3 OR DriveType=2" -ErrorAction Stop } "LogicalDisk" @())
$result["volumes"] = @($logical | Where-Object { $_ -and $_.Size -gt 0 } | ForEach-Object {
    $letter = $_.DeviceID
    $size   = [double]$_.Size
    $free   = [double]$_.FreeSpace
    @{
        letter       = $letter
        label        = $_.VolumeName
        filesystem   = $_.FileSystem
        size_gb      = [math]::Round($size / 1GB, 1)
        free_gb      = [math]::Round($free / 1GB, 1)
        used_percent = [math]::Round((($size - $free) / $size) * 100, 0)
        disk_number  = if ($letterToDisk.ContainsKey($letter)) { $letterToDisk[$letter] } else { $null }
        # 0 = non protege, 1 = protege, 2 = inconnu (verrouille) ; null = pas d'info
        bitlocker    = if ($bitlocker.ContainsKey($letter)) { $bitlocker[$letter] } else { $null }
    }
})

Mark "stockage"

# -- Comptes -------------------------------------------------------------------
$adminSids = @(Safe-Get {
    Get-LocalGroupMember -SID "S-1-5-32-544" -ErrorAction Stop | ForEach-Object { "$($_.SID)" }
} "AdminMembers" @())

$profiles = @(Safe-Get { Get-CimInstance Win32_UserProfile -ErrorAction Stop | Where-Object { -not $_.Special } } "Profiles" @())
$profileBySid = @{}
foreach ($p in $profiles) { if ($p) { $profileBySid["$($p.SID)"] = $p } }

# Adresse du compte Microsoft / Entra ID liee a un SID : Windows la met en cache
# ici. Absente = compte purement local (ou jamais ouvert).
function Get-IdentityName([string]$sid) {
    try {
        $k = "HKLM:\SOFTWARE\Microsoft\IdentityStore\Cache\$sid\IdentityCache\$sid"
        $v = (Get-ItemProperty -Path $k -ErrorAction Stop).UserName
        if ($v) { return "$v" }
    } catch {}
    # Repli : ruche de l'utilisateur, chargee quand sa session est ouverte. Le
    # nom de la sous-cle est l'adresse du compte.
    try {
        $k = "Registry::HKEY_USERS\$sid\Software\Microsoft\IdentityCRL\UserExtendedProperties"
        $n = Get-ChildItem -Path $k -ErrorAction Stop | Select-Object -First 1 -ExpandProperty PSChildName
        if ($n -and "$n" -match '@') { return "$n" }
    } catch {}
    return $null
}

$users = @(Safe-Get { Get-LocalUser -ErrorAction Stop } "LocalUsers" @())
$result["accounts"] = @($users | Where-Object { $_ } | ForEach-Object {
    $sid = "$($_.SID)"
    $rid = ($sid -split '-')[-1]
    $prof = if ($profileBySid.ContainsKey($sid)) { $profileBySid[$sid] } else { $null }
    @{
        name              = $_.Name
        full_name         = "$($_.FullName)"
        enabled           = [bool]$_.Enabled
        is_admin          = ($adminSids -contains $sid)
        # Administrateur (500), Invite (501), DefaultAccount (503), WDAGUtilityAccount (504)
        builtin           = @("500", "501", "503", "504") -contains $rid
        principal_source  = "$($_.PrincipalSource)"
        identity          = Get-IdentityName $sid
        password_required = [bool]$_.PasswordRequired
        # LastLogon n'est PAS mis a jour pour une ouverture de session par compte
        # Microsoft ou Windows Hello (constate : 2021 pour une session du jour).
        # La date d'utilisation du profil l'est : machine_info.py garde la plus recente.
        last_logon        = Format-Date $_.LastLogon
        profile_last_use  = if ($prof) { Format-Date $prof.LastUseTime } else { $null }
        profile_path      = if ($prof) { $prof.LocalPath } else { $null }
    }
})

# Profils qui ne sont PAS des comptes locaux : domaine, Entra ID (S-1-12-1-...).
$localSids = @($users | ForEach-Object { "$($_.SID)" })
$result["other_profiles"] = @($profiles | Where-Object {
    $_ -and ($localSids -notcontains "$($_.SID)") -and ("$($_.SID)" -match '^S-1-(5-21|12-1)-')
} | ForEach-Object {
    $sid = "$($_.SID)"
    @{
        sid          = $sid
        kind         = if ($sid -like "S-1-12-1-*") { "entra" } else { "domain" }
        identity     = Get-IdentityName $sid
        profile_path = $_.LocalPath
        last_use     = Format-Date $_.LastUseTime
    }
})

Mark "comptes"

# -- Securite ------------------------------------------------------------------
$secureBoot = $null
try {
    # Registre plutot que Confirm-SecureBootUEFI : lisible sans droits admin et
    # instantane. Cle absente = BIOS Legacy (secure_boot reste null).
    $sb = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State" -ErrorAction Stop
    if ($null -ne $sb.UEFISecureBootEnabled) { $secureBoot = ([int]$sb.UEFISecureBootEnabled -eq 1) }
} catch {}

$fwType = $env:firmware_type
if (-not $fwType) {
    $fwType = if (Test-RegKey "HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State") { "UEFI" } else { "Legacy" }
}

$tpmPresent = $null
$tpmEnabled = $null
$tpmVersion = $null
$tpm = $null
if ($elevated) {
    try {
        $tpm = Get-CimInstance -Namespace "root/cimv2/Security/MicrosoftTpm" -ClassName Win32_Tpm -ErrorAction Stop |
               Select-Object -First 1
    } catch {}
}
if ($tpm) {
    $tpmPresent = $true
    $tpmEnabled = [bool]$tpm.IsEnabled_InitialValue
    if ($tpm.SpecVersion) { $tpmVersion = ("$($tpm.SpecVersion)" -split ',')[0].Trim() }
} else {
    # Win32_Tpm exige les droits admin : un refus ne veut PAS dire "pas de TPM".
    # Repli lisible sans droits : le peripherique TPM (service "TPM", nom de
    # service non traduit). Absent = pas de TPM, ou TPM desactive dans le BIOS.
    try {
        $dev = Get-CimInstance Win32_PnPEntity -Filter "Service='TPM'" -ErrorAction Stop | Select-Object -First 1
        $tpmPresent = [bool]$dev
        if ($dev -and "$($dev.Name)" -match '(\d\.\d+)') { $tpmVersion = $Matches[1] }
    } catch {}
}

$av = @(Safe-Get {
    Get-CimInstance -Namespace "root/SecurityCenter2" -ClassName AntiVirusProduct `
        -OperationTimeoutSec 10 -ErrorAction Stop
} "Antivirus" @())

$result["security"] = @{
    firmware_type   = $fwType
    secure_boot     = $secureBoot
    tpm_present     = $tpmPresent
    tpm_enabled     = $tpmEnabled
    tpm_version     = $tpmVersion
    # Win32_EncryptableVolume exige les droits admin : sans eux, BitLocker n'est
    # pas "desactive", il est "non lu".
    bitlocker_readable = [bool]$enc
    antivirus       = @($av | Where-Object { $_ } | ForEach-Object {
        $hex = "{0:X6}" -f [int]$_.productState
        @{
            name     = "$($_.displayName)"
            realtime = ([Convert]::ToInt32($hex.Substring(2, 2), 16) -eq 16)
        }
    })
}

Mark "securite"

# -- Batterie ------------------------------------------------------------------
$batt = @(Safe-Get { Get-CimInstance Win32_Battery -ErrorAction Stop } "Battery" @())
if ($batt.Count -gt 0) {
    $design = Safe-Get { (Get-CimInstance -Namespace root/wmi -ClassName BatteryStaticData -ErrorAction Stop | Measure-Object -Property DesignedCapacity -Sum).Sum } "BatteryDesign"
    $full   = Safe-Get { (Get-CimInstance -Namespace root/wmi -ClassName BatteryFullChargedCapacity -ErrorAction Stop | Measure-Object -Property FullChargedCapacity -Sum).Sum } "BatteryFull"
    $cycles = Safe-Get { (Get-CimInstance -Namespace root/wmi -ClassName BatteryCycleCount -ErrorAction Stop | Select-Object -First 1).CycleCount } "BatteryCycles"
    $result["battery"] = @{
        present           = $true
        charge_percent    = $batt[0].EstimatedChargeRemaining
        on_ac             = ($batt[0].BatteryStatus -eq 2)
        design_mwh        = $design
        full_charge_mwh   = $full
        cycle_count       = $cycles
    }
} else {
    $result["battery"] = @{ present = $false }
}

Mark "batterie"

# -- Carte graphique -----------------------------------------------------------
$result["gpu"] = @(Safe-Get { Get-CimInstance Win32_VideoController -ErrorAction Stop } "GPU" @() |
    Where-Object { $_ } | ForEach-Object {
        @{
            name           = "$($_.Name)"
            driver_version = $_.DriverVersion
            driver_date    = Format-Date $_.DriverDate
        }
    })

Mark "graphique"

# -- Reseau --------------------------------------------------------------------
# WMI plutot que Get-NetAdapter + Get-NetIPAddress (~2,3 s mesures).
$cfgByIndex = @{}
foreach ($c in @(Safe-Get { Get-CimInstance Win32_NetworkAdapterConfiguration -Filter "IPEnabled=TRUE" -ErrorAction Stop } "NetConfig" @())) {
    if ($c) { $cfgByIndex[[int]$c.Index] = $c }
}
$adapters = @(Safe-Get {
    Get-CimInstance Win32_NetworkAdapter -Filter "PhysicalAdapter=TRUE AND NetConnectionID IS NOT NULL" -ErrorAction Stop
} "NetAdapter" @())
$result["network"] = @($adapters | Where-Object { $_ } | ForEach-Object {
    # Tableau calcule HORS d'un "if" : un if deroule le tableau, et ConvertTo-Json
    # rend alors une IP seule en chaine et une liste vide en {}.
    $ips = @()
    if ($cfgByIndex.ContainsKey([int]$_.DeviceID)) {
        $ips = @($cfgByIndex[[int]$_.DeviceID].IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })
    }
    @{
        name        = $_.NetConnectionID
        description = $_.Name
        connected   = ([int]$_.NetConnectionStatus -eq 2)
        mac         = $_.MACAddress
        # Carte deconnectee : Windows renvoie 2^63-1 bps, pas une vitesse.
        speed_mbps  = if ($_.Speed -and [double]$_.Speed -lt 1e12) { [math]::Round([double]$_.Speed / 1e6, 0) } else { $null }
        ipv4        = $ips
    }
})

Mark "reseau"

# -- Peripheriques en erreur ---------------------------------------------------
# Code 28 = pilote absent : le point d'entree classique apres une reinstallation.
$result["device_errors"] = @(Safe-Get {
    Get-CimInstance Win32_PnPEntity -Filter "ConfigManagerErrorCode <> 0" -ErrorAction Stop
} "PnPErrors" @() | Where-Object { $_ } | Select-Object -First 25 | ForEach-Object {
    @{
        name  = if ($_.Name) { "$($_.Name)" } else { "$($_.DeviceID)" }
        code  = [int]$_.ConfigManagerErrorCode
        class = "$($_.PNPClass)"
    }
})

Mark "peripheriques"
$result["collector_timings"] = $timings
$result["elevated"] = $elevated
$result["collector_errors"] = $errors
$result["collected_at"]     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]        = "machine_info"

$result | ConvertTo-Json -Depth 6 -Compress
