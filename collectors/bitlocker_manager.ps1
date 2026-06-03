param(
    [string]$Action   = "",
    [string]$FilePath = ""
)

Set-StrictMode -Version Latest

function Get-BitLockerInfo {
    $volumes = @()

    # Eviter d'appeler Get-BitLockerVolume si le service BDESVC n'est pas dispo :
    # sur les machines sans BitLocker le service est arrete et la cmdlet bloque indefiniment.
    $svc = Get-Service -Name "BDESVC" -ErrorAction SilentlyContinue
    if (-not $svc -or $svc.Status -ne "Running") {
        return $volumes
    }

    try {
        $blVolumes = Get-BitLockerVolume -ErrorAction Stop
        foreach ($v in $blVolumes) {
            $keys = @()
            foreach ($kp in $v.KeyProtector) {
                if ($kp.KeyProtectorType -eq "RecoveryPassword" -and $kp.RecoveryPassword) {
                    $keys += @{
                        id       = $kp.KeyProtectorID
                        password = $kp.RecoveryPassword
                    }
                }
            }
            $volumes += @{
                mount_point       = $v.MountPoint
                protection_status = $v.ProtectionStatus.ToString()
                encryption_method = $v.EncryptionMethod.ToString()
                encryption_pct    = [int]$v.EncryptionPercentage
                lock_status       = $v.LockStatus.ToString()
                recovery_keys     = @($keys)
            }
        }
    } catch {
        # Get-BitLockerVolume absent ou aucun volume — retourne tableau vide
    }
    return $volumes
}

switch ($Action) {

    "list" {
        try {
            $volumes = Get-BitLockerInfo
            [PSCustomObject]@{ success = $true; volumes = @($volumes) } | ConvertTo-Json -Depth 4
        } catch {
            [PSCustomObject]@{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        exit 0
    }

    "export" {
        if ([string]::IsNullOrWhiteSpace($FilePath)) {
            [PSCustomObject]@{ success = $false; error = "Chemin de fichier manquant" } | ConvertTo-Json
            exit 0
        }
        $parentDir = Split-Path -Parent $FilePath
        if (-not $parentDir -or -not (Test-Path $parentDir -PathType Container)) {
            [PSCustomObject]@{ success = $false; error = "Dossier de destination introuvable" } | ConvertTo-Json
            exit 0
        }

        try {
            $volumes = Get-BitLockerInfo

            $lines = @()
            $lines += "SAUVEGARDE DES CLES BITLOCKER"
            $lines += "Generee le : $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss')"
            $lines += "Machine    : $env:COMPUTERNAME"
            $lines += ("=" * 60)
            $lines += ""

            $exported = 0
            foreach ($v in $volumes) {
                if ($v.recovery_keys.Count -eq 0) { continue }
                $exported++
                $lines += "Volume     : $($v.mount_point)"
                $lines += "Statut     : $($v.protection_status)"
                $lines += "Methode    : $($v.encryption_method)"
                $lines += "Chiffrement: $($v.encryption_pct) %"
                $lines += ""
                foreach ($k in $v.recovery_keys) {
                    $lines += "  ID de la cle     : $($k.id)"
                    $lines += "  Mot de passe 48c : $($k.password)"
                    $lines += ""
                }
                $lines += ("-" * 60)
                $lines += ""
            }

            if ($exported -eq 0) {
                $lines += "Aucune cle de recuperation BitLocker trouvee sur cette machine."
                $lines += "BitLocker n'est peut-etre pas active ou les volumes n'ont pas de cle de recuperation."
            }

            [System.IO.File]::WriteAllLines($FilePath, $lines, [System.Text.UTF8Encoding]::new($false))

            [PSCustomObject]@{
                success       = $true
                file_path     = $FilePath
                volumes_count = $exported
            } | ConvertTo-Json
        } catch {
            [PSCustomObject]@{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        exit 0
    }

    default {
        [PSCustomObject]@{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
        exit 1
    }
}
