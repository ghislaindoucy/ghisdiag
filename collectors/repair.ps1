# Ghisdiag - Reparation systeme (SFC et DISM)
# Necessite les droits administrateur.
# SFC n'expose pas son flux via pipe — run_ps_stream affichera
# les lignes qui passent et servira de bloc jusqu'a la fin.
# DISM expose son flux (pourcentage) via stdout.
param(
    [ValidateSet("sfc", "dism-restore")]
    [string]$Action = "sfc"
)

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

switch ($Action) {

    "sfc" {
        & "$env:SystemRoot\System32\sfc.exe" /scannow
        break
    }

    "dism-restore" {
        & "$env:SystemRoot\System32\Dism.exe" /Online /Cleanup-Image /RestoreHealth /NoRestart
        break
    }
}
