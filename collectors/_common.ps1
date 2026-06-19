# Ghisdiag - Helpers PowerShell partagés
# Dot-sourcer avec : . "$PSScriptRoot\_common.ps1"
# PREREQUIS : le script appelant doit avoir initialisé $script:errors = @()

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null)
    try {
        $val = & $Block
        if ($null -eq $val) { return $Default }
        return $val
    } catch {
        $script:errors += "[$Name] $($_.Exception.Message)"
        return $Default
    }
}
