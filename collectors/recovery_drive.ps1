param(
    [string]$Action     = "",
    [string]$DiskNumber = ""
)

Set-StrictMode -Version Latest

# Anti-veille via SetThreadExecutionState (kernel32)
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class WakeGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
    public const uint ES_CONTINUOUS      = 0x80000000;
    public const uint ES_SYSTEM_REQUIRED = 0x00000001;
    public static void Prevent() { SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED); }
    public static void Allow()   { SetThreadExecutionState(ES_CONTINUOUS); }
}
'@

function Find-WinRE {
    # Emplacements courants de winre.wim
    $candidates = @(
        "$env:SystemRoot\System32\Recovery\winre.wim",
        "C:\Recovery\WindowsRE\winre.wim"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { return $c }
    }
    # Parcourir tous les volumes fixes
    $vols = Get-Volume -ErrorAction SilentlyContinue |
            Where-Object { $_.DriveType -eq "Fixed" -and $_.DriveLetter }
    foreach ($v in $vols) {
        $p = "$($v.DriveLetter):\Recovery\WindowsRE\winre.wim"
        if (Test-Path $p) { return $p }
    }
    return $null
}

switch ($Action) {

    "list-usb" {
        $disks = @()
        try {
            $usbDisks = Get-Disk -ErrorAction Stop | Where-Object { $_.BusType -eq "USB" }
            foreach ($d in $usbDisks) {
                $disks += @{
                    disk_number = [int]$d.Number
                    size_gb     = [math]::Round($d.Size / 1GB, 1)
                    model       = $d.FriendlyName
                    enough      = ($d.Size -ge 8GB)
                }
            }
        } catch {}
        [PSCustomObject]@{ success = $true; disks = $disks } | ConvertTo-Json -Depth 3
        exit 0
    }

    "create" {
        if ($DiskNumber -notmatch '^\d+$') {
            Write-Output "ERREUR: Numero de disque invalide."
            exit 1
        }
        $diskNum = [int]$DiskNumber

        try {
            $disk = Get-Disk -Number $diskNum -ErrorAction Stop
        } catch {
            Write-Output "ERREUR: Disque $diskNum introuvable."
            exit 1
        }
        if ($disk.BusType -ne "USB") {
            Write-Output "ERREUR: Le disque selectionne n'est pas un disque USB."
            exit 1
        }
        if ($disk.Size -lt 8GB) {
            Write-Output "ERREUR: Capacite insuffisante - 8 Go minimum requis (disque : $([math]::Round($disk.Size/1GB,1)) Go)."
            exit 1
        }

        # Empêcher la mise en veille pour toute la duree de l'operation
        [WakeGuard]::Prevent()

        $tmpDp = $null

        try {
            # ── Etape 1 : Localiser WinRE ────────────────────────────────────────
            Write-Output "[1/5] Localisation de l'environnement de recuperation Windows..."
            $wimSrc = Find-WinRE
            if (-not $wimSrc) {
                throw "winre.wim introuvable. Verifiez que Windows RE est active (reagentc /enable)."
            }
            $wimSizeMb = [math]::Round((Get-Item $wimSrc).Length / 1MB, 0)
            Write-Output "      Trouve : $wimSrc (${wimSizeMb} Mo)"

            # ── Etape 2 : Formater la cle USB ────────────────────────────────────
            Write-Output "[2/5] Formatage de la cle USB (disque $diskNum)..."
            $tmpDp = [System.IO.Path]::GetTempFileName()
            $dpScript = "select disk $diskNum`nclean`ncreate partition primary`nformat fs=fat32 quick label=`"Recovery`"`nactive`nassign`nexit"
            [System.IO.File]::WriteAllText($tmpDp, $dpScript, [System.Text.Encoding]::ASCII)
            $dpOut = diskpart /s $tmpDp 2>&1
            Remove-Item $tmpDp -Force -ErrorAction SilentlyContinue
            $tmpDp = $null
            if ($LASTEXITCODE -ne 0) {
                $dpErr = ($dpOut | Where-Object { $_ -match 'error|erreur|ERREUR' }) -join ' '
                throw "Erreur diskpart : $dpErr"
            }
            Write-Output "      Formatage termine."

            # Attendre que Windows assigne la lettre de lecteur
            Start-Sleep -Seconds 4
            $partition = Get-Partition -DiskNumber $diskNum -ErrorAction SilentlyContinue |
                         Where-Object { $_.DriveLetter } | Select-Object -First 1
            if (-not $partition -or -not $partition.DriveLetter) {
                throw "Impossible d'obtenir la lettre de lecteur de la cle USB."
            }
            $drive = "$($partition.DriveLetter):"
            Write-Output "      Lecteur assigne : $drive"

            # ── Etape 3 : Copier les fichiers de demarrage ───────────────────────
            Write-Output "[3/5] Copie des fichiers de demarrage Windows..."
            $bcdOut = bcdboot "$env:SystemRoot" /s $drive /f ALL 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw "Erreur bcdboot : $($bcdOut -join ' ')"
            }
            Write-Output "      Fichiers de demarrage copies."

            # ── Etape 4 : Copier WinRE ───────────────────────────────────────────
            Write-Output "[4/5] Copie de l'environnement de recuperation (${wimSizeMb} Mo)..."
            $destDir = "$drive\Recovery\WindowsRE"
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            Copy-Item -Path $wimSrc -Destination "$destDir\winre.wim" -Force
            Write-Output "      WinRE copie."

            # ── Etape 5 : Finalisation ───────────────────────────────────────────
            Write-Output "[5/5] Finalisation..."
            Write-Output ""
            Write-Output "SUCCESS: Cle de restauration creee avec succes sur $drive"
            exit 0

        } catch {
            Write-Output ""
            Write-Output "ERREUR: $($_.Exception.Message)"
            exit 1
        } finally {
            # La veille est toujours restauree, meme en cas d'erreur
            [WakeGuard]::Allow()
            if ($tmpDp -and (Test-Path $tmpDp -ErrorAction SilentlyContinue)) {
                Remove-Item $tmpDp -Force -ErrorAction SilentlyContinue
            }
        }
    }

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
