$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../DesktopPort.psm1') -Force
$port=Get-StationAvailablePort
if ($port -lt 8765 -or $port -ge 8865) { throw 'Chosen port is outside the private desktop range.' }
$occupied=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port)
$occupied.Server.ExclusiveAddressUse=$true
try {
 $occupied.Start();$other=Get-StationAvailablePort
 if ($other -eq $port -or -not $occupied.Server.IsBound) { throw 'An existing listener was reused or stopped.' }
 $probe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$other)
 try { $probe.Start() } finally { $probe.Stop() }
 Write-Output 'PASS actual .NET loopback selection skips an owned occupied port and releases its probe; Windows forwarding remains unqualified'
} finally { $occupied.Stop() }
