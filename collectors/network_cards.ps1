# PlanetDiag - Gestionnaire de Cartes Reseau
# Usage:
#   -Action list                    -> liste tous les adaptateurs reseau (JSON)
#   -Action reset -AdapterName <n>  -> desactive puis reactive l'adaptateur (JSON)
#
# Doit etre execute avec droits administrateur.

param(
    [ValidateSet("list", "reset")]
    [string]$Action = "list",

    [Parameter(Mandatory = $false)]
    [string]$AdapterName = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Validation du nom d'adaptateur (autorise lettres, chiffres, tirets, espaces, parentheses)
function Test-AdapterName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    if ($Name.Length -gt 256)               { return $false }
    # Interdit les caracteres dangereux pour PowerShell / injection
    if ($Name -match '[;&|`$<>]')           { return $false }
    return $true
}

function Get-AdapterList {
    try {
        $adapters = Get-NetAdapter -ErrorAction Stop | Sort-Object -Property InterfaceIndex
        $list = foreach ($a in $adapters) {
            $ipv4 = ""
            $ipv6 = ""
            try {
                $addrs = Get-NetIPAddress -InterfaceIndex $a.InterfaceIndex -ErrorAction SilentlyContinue
                $ipv4 = ($addrs | Where-Object { $_.AddressFamily -eq "IPv4" } | Select-Object -First 1).IPAddress
                $ipv6 = ($addrs | Where-Object { $_.AddressFamily -eq "IPv6" -and $_.IPAddress -notlike "fe80*" } | Select-Object -First 1).IPAddress
            } catch {}

            $mac = if ($a.MacAddress) { $a.MacAddress } else { "" }

            [ordered]@{
                name          = $a.Name
                description   = $a.InterfaceDescription
                status        = $a.Status.ToString()
                media_type    = $a.MediaType
                link_speed    = $a.LinkSpeed
                mac           = $mac
                ipv4          = if ($ipv4) { $ipv4 } else { "" }
                ipv6          = if ($ipv6) { $ipv6 } else { "" }
                index         = $a.InterfaceIndex
            }
        }
        return @{ success = $true; adapters = @($list); error = $null }
    } catch {
        return @{ success = $false; adapters = @(); error = $_.Exception.Message }
    }
}

# -- Action: list -------------------------------------------------------------
if ($Action -eq "list") {
    $result = Get-AdapterList
    $result["action"] = "list"
    Write-Output ($result | ConvertTo-Json -Depth 5)
    exit 0
}

# -- Action: reset ------------------------------------------------------------
if ($Action -eq "reset") {
    if (-not (Test-AdapterName -Name $AdapterName)) {
        $err = @{
            action  = "reset"
            success = $false
            error   = "Nom d'adaptateur invalide ou non fourni."
            steps   = @()
        }
        Write-Output ($err | ConvertTo-Json -Depth 3)
        exit 1
    }

    $steps    = [System.Collections.Generic.List[string]]::new()
    $success  = $true
    $errorMsg = $null

    try {
        # Verifier l'existence de l'adaptateur (par nom exact)
        $adapter = Get-NetAdapter -Name $AdapterName -ErrorAction Stop

        # 1. Desactivation
        $steps.Add("Desactivation de '$AdapterName'...")
        Disable-NetAdapter -Name $AdapterName -Confirm:$false -ErrorAction Stop

        # Attendre que l'adaptateur soit desactive (max 15s)
        $deadline = (Get-Date).AddSeconds(15)
        while ((Get-NetAdapter -Name $AdapterName).Status -ne "Disabled" -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 300
        }
        $statusAfterDisable = (Get-NetAdapter -Name $AdapterName).Status
        $steps.Add("Adaptateur desactive (statut : $statusAfterDisable).")

        # 2. Reactivation
        $steps.Add("Reactivation de '$AdapterName'...")
        Enable-NetAdapter -Name $AdapterName -Confirm:$false -ErrorAction Stop

        # Attendre connexion (max 20s)
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-NetAdapter -Name $AdapterName).Status -notin @("Up", "Disconnected") -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
        }
        $finalStatus = (Get-NetAdapter -Name $AdapterName).Status.ToString()
        $steps.Add("Adaptateur reactive (statut : $finalStatus).")

    } catch {
        $success  = $false
        $errorMsg = $_.Exception.Message
        $steps.Add("ERREUR : $errorMsg")
        # Tentative de reactivation meme en cas d'erreur
        try {
            Enable-NetAdapter -Name $AdapterName -Confirm:$false -ErrorAction SilentlyContinue
        } catch {}
    }

    # Recuperation du statut final
    $adapterFinal = $null
    try {
        $a = Get-NetAdapter -Name $AdapterName -ErrorAction SilentlyContinue
        if ($a) {
            $adapterFinal = @{
                name   = $a.Name
                status = $a.Status.ToString()
            }
        }
    } catch {}

    $result = @{
        action        = "reset"
        adapter_name  = $AdapterName
        success       = $success
        error         = $errorMsg
        steps         = @($steps)
        adapter_final = $adapterFinal
    }
    Write-Output ($result | ConvertTo-Json -Depth 4)
    exit $(if ($success) { 0 } else { 1 })
}
