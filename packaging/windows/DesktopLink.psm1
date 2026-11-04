# Private desktop-parent browser handoff. No token reaches the readiness HTTP request.
Set-StrictMode -Version 2.0

function ConvertTo-StationBrowserTarget {
    param([Parameter(Mandatory=$true)][string]$Url,[Parameter(Mandatory=$true)][string]$InstanceId)
    if ($InstanceId -cnotmatch '^[a-f0-9]{32}$') { throw 'The desktop identity is invalid.' }
    $uri=[Uri]::new($Url,[UriKind]::Absolute)
    if ($uri.Scheme -cne 'http' -or $uri.Host -cne '127.0.0.1' -or $uri.Port -lt 8765 -or $uri.Port -ge 8865 -or $uri.UserInfo -or $uri.AbsolutePath -cne '/' -or $uri.Query) { throw 'The desktop address is not an expected local station.' }
    if ($uri.Fragment -and $uri.Fragment -cnotmatch '^#/(?:setup/models)?\?setup_token=[A-Za-z0-9_-]{43}$') { throw 'The private desktop setup link is invalid.' }
    return [pscustomobject]@{Url=$uri.AbsoluteUri;InstanceId=$InstanceId}
}

function Read-StationReadyFrame {
    param([Parameter(Mandatory=$true)][string]$Line)
    if ([Text.Encoding]::UTF8.GetByteCount($Line) -gt 4096) { throw 'The desktop handoff exceeds its expected size.' }
    if (-not $Line.StartsWith('AI_STATION_READY ',[StringComparison]::Ordinal)) { return $null }
    $value=$Line.Substring(17) | ConvertFrom-Json -ErrorAction Stop
    $names=[string[]]@($value.PSObject.Properties.Name);[Array]::Sort($names,[StringComparer]::Ordinal)
    if (($names -join '|') -cne 'instance_id|url' -or $value.url -isnot [string] -or $value.instance_id -isnot [string]) { throw 'The desktop handoff requires a URL and its current instance identity.' }
    return (ConvertTo-StationBrowserTarget $value.url $value.instance_id)
}

function Confirm-StationBrowserTarget {
    param([Parameter(Mandatory=$true)]$Ready)
    $target=ConvertTo-StationBrowserTarget $Ready.Url $Ready.InstanceId
    $uri=[Uri]::new($target.Url)
    $request=[Net.HttpWebRequest]::Create($uri.GetLeftPart([UriPartial]::Authority)+'/api/health')
    $request.Proxy=$null; $request.AllowAutoRedirect=$false
    $request.Timeout=3000;$request.ReadWriteTimeout=3000
    $request.CachePolicy=[Net.Cache.RequestCachePolicy]::new([Net.Cache.RequestCacheLevel]::NoCacheNoStore)
    $response=$null;$reader=$null
    try {
        $response=$request.GetResponse()
        if ($response.StatusCode -ne [Net.HttpStatusCode]::OK) { throw 'The local station did not pass its identity check.' }
        $reader=[IO.StreamReader]::new($response.GetResponseStream(),[Text.UTF8Encoding]::new($false,$true))
        $buffer=[char[]]::new(4097);$length=0
        while ($length -lt $buffer.Length) {
            $count=$reader.Read($buffer,$length,$buffer.Length-$length)
            if ($count -eq 0) { break };$length+=$count
        }
        if ($length -gt 4096) { throw 'The local readiness response exceeds its expected size.' }
        $body=([string]::new($buffer,0,$length)) | ConvertFrom-Json -ErrorAction Stop
        if ($body.status -cne 'ok' -or $body.desktop_instance_id -isnot [string] -or $body.desktop_instance_id -cne $target.InstanceId) { throw 'Another local service answered. The private setup link was not opened.' }
    } finally { if ($null -ne $reader) { $reader.Dispose() };if ($null -ne $response) { $response.Dispose() } }
}

function Open-StationBrowser {
    param([Parameter(Mandatory=$true)]$Ready)
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'The native Windows browser action requires Windows.' }
    Confirm-StationBrowserTarget $Ready
    $target=ConvertTo-StationBrowserTarget $Ready.Url $Ready.InstanceId
    $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$target.Url;$info.UseShellExecute=$true
    [void][Diagnostics.Process]::Start($info)
}

Export-ModuleMember -Function Read-StationReadyFrame,Confirm-StationBrowserTarget,Open-StationBrowser
