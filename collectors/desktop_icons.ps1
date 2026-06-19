# Ghisdiag - Icones du bureau (Ce PC, Fichiers utilisateur, Corbeille)
param(
    [string]$Action = "check"   # check | enable
)

$ErrorActionPreference = "SilentlyContinue"

# Catalogue des icones. default = 1 => visible par defaut quand la valeur registre est absente.
$Icons = @(
    @{ key = "user";    name = "Fichiers de l'utilisateur"; clsid = "{59031a47-3f72-44a7-89c5-5595fe6b30ee}"; default = 0 }
    @{ key = "thispc";  name = "Ce PC";                      clsid = "{20D04FE0-3AEA-1069-A2D8-08002B30309D}"; default = 0 }
    @{ key = "recycle"; name = "Corbeille";                  clsid = "{645FF040-5081-101B-9F08-00AA002F954E}"; default = 1 }
)

$RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"

function Test-IconVisible($icon) {
    $val = (Get-ItemProperty -Path $RegPath -Name $icon.clsid -EA SilentlyContinue).($icon.clsid)
    if ($null -eq $val) { return ($icon.default -eq 1) }
    return ($val -eq 0)
}

function Update-Shell {
    # Force le shell a rafraichir le bureau sans redemarrer explorer.
    try {
        $sig = '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int eventId, int flags, IntPtr item1, IntPtr item2);'
        $t = Add-Type -MemberDefinition $sig -Name 'PdShell' -Namespace 'Ghisdiag' -PassThru -EA SilentlyContinue
        # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0x0000
        $t::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
    } catch {}
}

switch ($Action) {

    "check" {
        $result = @()
        foreach ($icon in $Icons) {
            $result += @{
                key     = $icon.key
                name    = $icon.name
                visible = [bool](Test-IconVisible $icon)
            }
        }
        @{ success = $true; icons = $result } | ConvertTo-Json -Depth 3
        break
    }

    "enable" {
        try {
            if (-not (Test-Path $RegPath)) {
                New-Item -Path $RegPath -Force | Out-Null
            }
            $result = @()
            foreach ($icon in $Icons) {
                $wasVisible = Test-IconVisible $icon
                # 0 = icone affichee
                New-ItemProperty -Path $RegPath -Name $icon.clsid -Value 0 -PropertyType DWord -Force | Out-Null
                $result += @{
                    key     = $icon.key
                    name    = $icon.name
                    visible = $true
                    added   = (-not $wasVisible)
                }
            }
            Update-Shell
            @{ success = $true; icons = $result } | ConvertTo-Json -Depth 3
        } catch {
            @{ success = $false; error = $_.Exception.Message } | ConvertTo-Json
        }
        break
    }

    default {
        @{ success = $false; error = "Action inconnue : $Action" } | ConvertTo-Json
    }
}
