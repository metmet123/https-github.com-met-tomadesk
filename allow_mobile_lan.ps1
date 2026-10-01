#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

# The UDP connect selects an interface without sending a packet.
$probe = [System.Net.Sockets.Socket]::new(
    [System.Net.Sockets.AddressFamily]::InterNetwork,
    [System.Net.Sockets.SocketType]::Dgram,
    [System.Net.Sockets.ProtocolType]::Udp
)
try {
    $probe.Connect('1.1.1.1', 53)
    $localIp = ([System.Net.IPEndPoint]$probe.LocalEndPoint).Address.ToString()
} finally {
    $probe.Dispose()
}

$ip = [System.Net.IPAddress]::Parse($localIp).GetAddressBytes()
$isLan = $ip[0] -eq 10 -or ($ip[0] -eq 172 -and $ip[1] -ge 16 -and $ip[1] -le 31) -or
    ($ip[0] -eq 192 -and $ip[1] -eq 168)
if (-not $isLan) { throw "현재 PC의 공유기 주소를 찾지 못했습니다: $localIp" }

$ruleName = 'TomaDesk Mobile LAN TCP 47831'
if (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue) {
    Write-Output "이미 방화벽 규칙이 있습니다: $ruleName"
    exit 0
}

New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
    -Enabled True -Profile Public,Private -Protocol TCP -LocalPort 47831 `
    -LocalAddress $localIp -RemoteAddress LocalSubnet | Out-Null
Write-Output "같은 공유기 네트워크에서 이 PC의 $localIp`:47831 연결을 허용했습니다."
