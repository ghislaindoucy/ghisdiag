# PlanetDiag - Gestion des comptes utilisateurs locaux
param(
    [string]$Action   = "list-users",
    [string]$Username = "",
    [string]$Password = "",
    [string]$Type     = "standard",  # standard | admin
    [switch]$NoExpiry                # present = jamais d'expiration
)

$ErrorActionPreference = "SilentlyContinue"

# SIDs independants de la locale Windows
$AdminSID = "S-1-5-32-544"
$UsersSID = "S-1-5-32-545"

function Test-SafeUsername([string]$name) {
    return $name -match '^[a-zA-Z0-9_\-\.]{1,20}$'
}

function Get-PropSafe($obj, [string]$prop) {
    try { return $obj.$prop } catch { return $null }
}

switch ($Action) {

    "list-users" {
        try {
            $adminMembers = @(
                Get-LocalGroupMember -SID $AdminSID -EA SilentlyContinue |
                ForEach-Object { ($_.Name -split '\\')[-1] }
            )
            $users = @(Get-LocalUser | ForEach-Object {
                $u = $_
                $noExpiry  = Get-PropSafe $u 'PasswordNeverExpires'
                $expDate   = Get-PropSafe $u 'PasswordExpires'
                $expStr    = if ($expDate) { $expDate.ToString("dd/MM/yyyy") } else { $null }
                @{
                    Name                = $u.Name
                    Enabled             = [bool]$u.Enabled
                    FullName            = "$($u.FullName)"
                    PasswordNeverExpires = if ($null -ne $noExpiry) { [bool]$noExpiry } else { $null }
                    PasswordExpires     = $expStr
                    IsAdmin             = ($adminMembers -contains $u.Name)
                }
            })
            @{ success = $true; users = $users } | ConvertTo-Json -Depth 4
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "create-user" {
        if (-not (Test-SafeUsername $Username)) {
            @{ success = $false; error = "Nom invalide (max 20 car., lettres/chiffres/_-. uniquement)" } | ConvertTo-Json
            break
        }
        if ($Password.Length -gt 0 -and $Password.Length -lt 8) {
            @{ success = $false; error = "Mot de passe trop court (minimum 8 caracteres)" } | ConvertTo-Json
            break
        }
        try {
            $secPwd = if ($Password.Length -eq 0) {
                [System.Security.SecureString]::new()
            } else {
                ConvertTo-SecureString $Password -AsPlainText -Force
            }
            New-LocalUser -Name $Username -Password $secPwd `
                -Description "Cree par PlanetDiag" -EA Stop | Out-Null
            $groupSID = if ($Type -eq "admin") { $AdminSID } else { $UsersSID }
            Add-LocalGroupMember -SID $groupSID -Member $Username -EA Stop | Out-Null
            $typeLabel = if ($Type -eq "admin") { "Administrateur" } else { "Utilisateur standard" }
            @{ success = $true; message = "Compte '$Username' cree ($typeLabel)." } | ConvertTo-Json
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    "set-password-policy" {
        if (-not (Test-SafeUsername $Username)) {
            @{ success = $false; error = "Nom d'utilisateur invalide" } | ConvertTo-Json
            break
        }
        try {
            if ($NoExpiry) {
                Set-LocalUser -Name $Username -PasswordNeverExpires $true -EA Stop
                @{ success = $true; message = "Mot de passe de '$Username' : sans expiration." } | ConvertTo-Json
            } else {
                Set-LocalUser -Name $Username -PasswordNeverExpires $false -EA Stop
                @{ success = $true; message = "Expiration du MDP activee pour '$Username' (selon la politique systeme)." } | ConvertTo-Json
            }
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
