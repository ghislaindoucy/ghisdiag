# Ghisdiag - Dump COMPLET des capteurs LibreHardwareMonitor
#
# A lancer EN ADMINISTRATEUR sur la machine qui ne remonte ni frequence CPU ni
# RPM ventilateur. Liste tout ce que LHM expose : chaque materiel, chaque
# sous-materiel, chaque capteur (type + nom + valeur), au repos PUIS sous charge.
#
# La lecture sous charge est indispensable : certaines frequences n'apparaissent
# que lorsque le CPU sort de son etat de veille.
#
# Usage :
#   powershell -ExecutionPolicy Bypass -File dump_capteurs.ps1
#   powershell -ExecutionPolicy Bypass -File dump_capteurs.ps1 -ToolsDir "C:\...\tools"
#
# Pas de caractere non-ASCII (regle PS du projet).

param(
    [string]$ToolsDir = "",
    [int]$LoadSeconds = 20,
    [switch]$NoElevate     # usage interne : marque la relance deja elevee
)

$ErrorActionPreference = "SilentlyContinue"

# --- Elevation automatique ---------------------------------------------------
# Sans droits admin, TOUTES les valeurs issues des MSR (temperatures, frequences)
# sortent a null : le dump est alors inexploitable, et rien ne le dit assez fort.
# On se relance donc soi-meme en eleve plutot que de produire un fichier vide de
# sens. -NoElevate empeche toute boucle si l'elevation echoue.
$__id = [Security.Principal.WindowsIdentity]::GetCurrent()
$__admin = (New-Object Security.Principal.WindowsPrincipal($__id)).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $__admin -and -not $NoElevate) {
    Write-Host "Droits administrateur requis (acces MSR) - relance en eleve..."
    $__args = @("-ExecutionPolicy", "Bypass", "-NoProfile",
                "-File", "`"$PSCommandPath`"",
                "-LoadSeconds", $LoadSeconds, "-NoElevate")
    if ($ToolsDir) { $__args += @("-ToolsDir", "`"$ToolsDir`"") }
    try {
        Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $__args -Wait
        Write-Host "Termine. Le fichier est sur le Bureau : ghisdiag_capteurs.txt"
    } catch {
        Write-Host "Elevation refusee. Relance ce script depuis un PowerShell administrateur."
    }
    return
}

# --- Sortie ------------------------------------------------------------------
$outFile = Join-Path ([Environment]::GetFolderPath("Desktop")) "ghisdiag_capteurs.txt"
$lines = New-Object System.Collections.Generic.List[string]
function Say([string]$t) { $lines.Add($t); Write-Host $t }

Say "=============================================================="
Say " GHISDIAG - DUMP CAPTEURS COMPLET"
Say " Date    : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
Say " Machine : $env:COMPUTERNAME"
Say " CPU     : $env:PROCESSOR_IDENTIFIER ($env:NUMBER_OF_PROCESSORS threads)"
Say "=============================================================="

# --- Elevation (etat reel de CE process) -------------------------------------
Say ""
if ($__admin) {
    Say "Administrateur : OUI"
} else {
    Say "Administrateur : NON"
    Say "  *** DUMP INEXPLOITABLE : sans elevation, les temperatures et les"
    Say "  *** frequences sortent toutes a null (acces MSR refuse). Relance"
    Say "  *** depuis un PowerShell administrateur."
}

# --- Localisation des DLL ----------------------------------------------------
$candidates = @()
# AUCUN chemin absolu de poste de developpement ici : cet outil tourne sur des
# machines clientes, depuis une cle USB. Tout est relatif au script, plus le
# dossier de surcharge documente (%LOCALAPPDATA%\Ghisdiag\tools).
if ($ToolsDir) { $candidates += $ToolsDir }
$candidates += @(
    (Join-Path $PSScriptRoot "tools"),                        # depot : collectors\..\tools
    (Join-Path $PSScriptRoot "..\tools"),
    (Join-Path $PSScriptRoot "_internal\tools"),              # onedir : script a cote de l exe
    (Join-Path $PSScriptRoot "Ghisdiag\_internal\tools"),     # onedir : script a cote du dossier
    (Join-Path $env:LOCALAPPDATA "Ghisdiag\tools")            # surcharge utilisateur (notice)
)
$toolsDir = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path (Join-Path $c "LibreHardwareMonitorLib.dll"))) {
        $toolsDir = [System.IO.Path]::GetFullPath($c); break
    }
}

# Repli : chercher la DLL. D'abord sous le dossier du script, puis a la racine de
# SON volume : le cas "script pose dans I:\outils\ et Ghisdiag dans I:\Ghisdiag\"
# n'est pas couvert par une recherche limitee au dossier du script.
# Profondeur bornee : on ne ratisse jamais un disque entier.
if (-not $toolsDir) {
    $roots = @($PSScriptRoot)
    $drive = [System.IO.Path]::GetPathRoot($PSScriptRoot)
    # Jamais la racine du disque systeme : un balayage de C:\ meme borne a 4
    # niveaux prend des minutes. Sur une cle (I:\, E:\...) c'est instantane.
    $sysDrive = [System.IO.Path]::GetPathRoot($env:SystemRoot)
    if ($drive -and $drive -ne $PSScriptRoot -and $drive -ne $sysDrive) {
        $roots += $drive
    }
    foreach ($root in $roots) {
        Say "Recherche de LibreHardwareMonitorLib.dll sous $root ..."
        $found = Get-ChildItem -Path $root -Filter "LibreHardwareMonitorLib.dll" `
                               -Recurse -Depth 4 -File -ErrorAction SilentlyContinue |
                 Select-Object -First 1
        if ($found) { $toolsDir = $found.Directory.FullName; break }
    }
}

if (-not $toolsDir) {
    Say ""
    Say "ERREUR : LibreHardwareMonitorLib.dll introuvable."
    Say ""
    Say "Relance en donnant le chemin explicitement :"
    Say "   .\dump_capteurs.ps1 -ToolsDir <chemin>"
    Say ""
    Say "Ou le trouver :"
    Say "   - Ghisdiag v2 (dossier portable) : <dossier Ghisdiag>\_internal\tools"
    Say "   - depot source                   : <depot>\tools"
    Say ""
    Say "Emplacements testes :"
    foreach ($c in $candidates) { Say "   $c" }
    $lines | Set-Content -Path $outFile -Encoding utf8
    return
}
Say "Dossier tools  : $toolsDir"

$loadOrder = @(
    "System.Runtime.CompilerServices.Unsafe.dll",
    "System.Numerics.Vectors.dll",
    "System.Memory.dll",
    "HidSharp.dll",
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "LibreHardwareMonitorLib.dll"
)
# Mark of the Web : l'Explorateur Windows recopie la marque " vient d'Internet "
# sur chaque fichier extrait d'une archive telechargee, et .NET refuse alors de
# charger l'assembly (HRESULT 0x80131515). Meme correctif que collectors\sensors.ps1.
try {
    Get-ChildItem -Path $toolsDir -File -ErrorAction SilentlyContinue |
        Unblock-File -ErrorAction SilentlyContinue
} catch { }

foreach ($dll in $loadOrder) {
    $p = [System.IO.Path]::Combine($toolsDir, $dll)
    if ([System.IO.File]::Exists($p)) { [System.Reflection.Assembly]::LoadFrom($p) | Out-Null }
}
$ver = (Get-Item (Join-Path $toolsDir "LibreHardwareMonitorLib.dll")).VersionInfo.ProductVersion
Say "Version LHM    : $ver"

# --- Ouverture ---------------------------------------------------------------
$computer = New-Object LibreHardwareMonitor.Hardware.Computer
$computer.IsCpuEnabled         = $true
$computer.IsGpuEnabled         = $true
$computer.IsMotherboardEnabled = $true
$computer.IsControllerEnabled  = $true
# Memes sous-systemes que collectors\sensors.ps1, volontairement : le dump doit
# montrer ce que Ghisdiag voit reellement. (Memory exige RAMSPDToolkit, absent
# des DLL embarquees ; Storage peut figer sur certaines machines.)
$computer.IsStorageEnabled     = $false
try { $computer.Open() } catch {
    Say "ERREUR Computer.Open() : $($_.Exception.Message)"
    $lines | Set-Content -Path $outFile -Encoding utf8
    return
}

function Dump-All([string]$titre) {
    Say ""
    Say "=============================================================="
    Say " $titre"
    Say "=============================================================="
    foreach ($hw in $computer.Hardware) {
        try { $hw.Update() } catch {}
        foreach ($sub in $hw.SubHardware) { try { $sub.Update() } catch {} }

        Say ""
        Say "[$($hw.HardwareType)] $($hw.Name)"
        $nodes = @($hw) + @($hw.SubHardware)
        foreach ($node in $nodes) {
            if ($node -ne $hw) { Say "   +-- sous-materiel [$($node.HardwareType)] $($node.Name)" }
            $sensors = @($node.Sensors)
            if ($sensors.Count -eq 0) { Say "       (aucun capteur)"; continue }
            foreach ($s in ($sensors | Sort-Object { $_.SensorType.ToString() }, { $_.Name })) {
                $val = if ($null -eq $s.Value) { "null" } else { "{0,10:N1}" -f [double]$s.Value }
                Say ("       {0,-14} idx {1,-3} {2,-34} = {3}" -f `
                     $s.SensorType, $s.Index, $s.Name, $val)
            }
        }
    }
}

Dump-All "LECTURE 1 : AU REPOS"

# --- Charge CPU --------------------------------------------------------------
Say ""
Say "Mise en charge du CPU pendant $LoadSeconds s (un job par thread)..."
$jobs = @()
$n = [int]$env:NUMBER_OF_PROCESSORS
if ($n -lt 1) { $n = 4 }
for ($i = 0; $i -lt $n; $i++) {
    $jobs += Start-Job -ScriptBlock {
        param($sec)
        $end = (Get-Date).AddSeconds($sec)
        $x = 0.0
        while ((Get-Date) -lt $end) { for ($k = 0; $k -lt 200000; $k++) { $x = [math]::Sqrt($k + 1.0) } }
    } -ArgumentList $LoadSeconds
}
Start-Sleep -Seconds ([math]::Max(5, $LoadSeconds - 6))

Dump-All "LECTURE 2 : SOUS CHARGE (100 % CPU)"

$jobs | Stop-Job -PassThru | Remove-Job -Force | Out-Null
try { $computer.Close() } catch {}

Say ""
Say "=============================================================="
Say " Termine. Fichier : $outFile"
Say "=============================================================="

$lines | Set-Content -Path $outFile -Encoding utf8
