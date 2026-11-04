# Choose a port locally without stopping listeners or changing firewall/forwarding rules.
Set-StrictMode -Version 2.0
function Get-StationAvailablePort {
    for ($port=8765; $port -lt 8865; $port++) {
        $listener=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,$port)
        $listener.Server.ExclusiveAddressUse=$true
        try { $listener.Start();return $port } catch [Net.Sockets.SocketException] { continue } finally { $listener.Stop() }
    }
    throw 'No local AI Station port is available. No other application was stopped.'
}
Export-ModuleMember -Function Get-StationAvailablePort
