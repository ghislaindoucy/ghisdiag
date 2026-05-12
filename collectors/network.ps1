# PlanetDiag - Collecteur Réseau
# Collecte adaptateurs, connectivité, partages, connexions TCP

$ErrorActionPreference = "SilentlyContinue"
$result = @{}
$errors = @()

function Safe-Get {
    param([scriptblock]$Block, [string]$Name, $Default = $null)
    try { $val = & $Block; if ($null -eq $val) { return $Default }; return $val }
    catch { $script:errors += "[$Name] $($_.Exception.Message)"; return $Default }
}

# ── Adaptateurs réseau ────────────────────────────────────────────────────────
$adapters = Safe-Get {
    @(Get-NetAdapter | ForEach-Object {
        $adapter = $_

        # LinkSpeed : certains pilotes retournent "287 Mbps" (string) au lieu d'un entier en bps
        $linkMbps = $null
        try {
            $raw = $adapter.LinkSpeed
            if ($raw -is [int64] -or $raw -is [uint64] -or $raw -is [int32]) {
                $linkMbps = [math]::Round($raw / 1MB, 0)
            } elseif ([string]$raw -match '(\d+[\.,]?\d*)\s*(G|M|K)?bps') {
                $num = [double]($Matches[1] -replace ',', '.')
                $linkMbps = switch ($Matches[2]) {
                    'G' { [int]($num * 1000) }
                    'K' { [int]($num / 1000) }
                    default { [int]$num }
                }
            }
        } catch {}

        $ipConfig = Get-NetIPAddress -InterfaceIndex $adapter.InterfaceIndex -ErrorAction SilentlyContinue
        $ipv4 = $ipConfig | Where-Object { $_.AddressFamily -eq "IPv4" } | Select-Object -First 1
        $ipv6 = $ipConfig | Where-Object { $_.AddressFamily -eq "IPv6" } | Select-Object -First 1
        $route = Get-NetRoute -InterfaceIndex $adapter.InterfaceIndex -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue | Select-Object -First 1
        $dns   = @(Get-DnsClientServerAddress -InterfaceIndex $adapter.InterfaceIndex -ErrorAction SilentlyContinue | Select-Object -ExpandProperty ServerAddresses)

        @{
            name            = [string]$adapter.Name
            description     = [string]$adapter.InterfaceDescription
            status          = [string]$adapter.Status
            mac_address     = [string]$adapter.MacAddress
            link_speed_mbps = $linkMbps
            media_type      = [string]$adapter.MediaType
            ipv4_address    = if ($ipv4) { [string]$ipv4.IPAddress }   else { $null }
            ipv4_prefix     = if ($ipv4) { [int]$ipv4.PrefixLength }   else { $null }
            ipv4_dhcp       = if ($ipv4) { [bool]($ipv4.PrefixOrigin -eq "Dhcp") } else { $null }
            ipv6_address    = if ($ipv6) { [string]$ipv6.IPAddress }   else { $null }
            gateway         = if ($route) { [string]$route.NextHop }   else { $null }
            dns_servers     = $dns
        }
    })
} "Adapters" @()

# ── Test de connectivité ──────────────────────────────────────────────────────
function Test-PingTarget {
    param([string]$Target, [string]$Label)
    try {
        $ping = Test-Connection -ComputerName $Target -Count 2 -Quiet -ErrorAction Stop
        $rtt  = (Test-Connection -ComputerName $Target -Count 2 -ErrorAction Stop |
                 Measure-Object -Property ResponseTime -Average).Average
        return @{ target = $Target; label = $Label; reachable = $ping; avg_rtt_ms = [math]::Round($rtt, 1) }
    } catch {
        return @{ target = $Target; label = $Label; reachable = $false; avg_rtt_ms = $null; error = $_.Exception.Message }
    }
}

$gateway = ($adapters | Where-Object { $_["gateway"] -and $_["status"] -eq "Up" } | Select-Object -First 1)["gateway"]

$connectivity = @(
    Test-PingTarget "8.8.8.8"   "Google DNS"
    Test-PingTarget "1.1.1.1"   "Cloudflare DNS"
    Test-PingTarget "google.com" "Résolution DNS"
)

if ($gateway) {
    $connectivity = @(Test-PingTarget $gateway "Passerelle") + $connectivity
}

# ── Partages réseau ──────────────────────────────────────────────────────────
$shares = Safe-Get {
    Get-SmbShare | Where-Object { $_.Name -notlike "*$" } | ForEach-Object {
        @{
            name        = $_.Name
            path        = $_.Path
            description = $_.Description
            type        = $_.ShareType
        }
    }
} "Shares" @()

# ── Connexions TCP actives ───────────────────────────────────────────────────
$tcpConnections = Safe-Get {
    Get-NetTCPConnection -State Established | ForEach-Object {
        $proc = try { Get-Process -Id $_.OwningProcess -ErrorAction Stop } catch { $null }
        @{
            local_address  = $_.LocalAddress
            local_port     = $_.LocalPort
            remote_address = $_.RemoteAddress
            remote_port    = $_.RemotePort
            state          = $_.State
            pid            = $_.OwningProcess
            process_name   = if ($proc) { $proc.ProcessName } else { "N/A" }
        }
    } | Sort-Object { $_["remote_port"] } | Select-Object -First 50
} "TCP" @()

$listeningPorts = Safe-Get {
    Get-NetTCPConnection -State Listen | Select-Object LocalPort, OwningProcess |
    Sort-Object LocalPort | ForEach-Object {
        $proc = try { Get-Process -Id $_.OwningProcess -ErrorAction Stop } catch { $null }
        @{ port = $_.LocalPort; pid = $_.OwningProcess; process = if ($proc) { $proc.ProcessName } else { "N/A" } }
    }
} "ListeningPorts" @()

$result["adapters"]         = $adapters
$result["connectivity"]     = $connectivity
$result["shares"]           = $shares
$result["tcp_connections"]  = $tcpConnections
$result["listening_ports"]  = $listeningPorts
$result["internet_ok"]      = (($connectivity | Where-Object { $_["target"] -eq "8.8.8.8" })["reachable"] -eq $true)
$result["dns_ok"]           = (($connectivity | Where-Object { $_["target"] -eq "google.com" })["reachable"] -eq $true)

$result["collector_errors"] = $errors
$result["collected_at"]     = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
$result["collector"]        = "network"

$result | ConvertTo-Json -Depth 10 -Compress
