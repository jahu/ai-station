# Fixed publisher admission for native desktop updates. Not an HTTP/tool surface.
Set-StrictMode -Version 2.0

function ConvertTo-StationStableVersion {
 param([Parameter(Mandatory=$true)]$Value)
 if($Value -isnot [string] -or $Value -cnotmatch '\A(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){2}\z'){throw 'The update needs a stable numeric release version.'}
 foreach($part in $Value.Split('.')){if([int]$part -gt 65535){throw 'The release version exceeds its numeric bound.'}}
 return [Version]::Parse($Value)
}

function ConvertTo-StationReleaseInteger {
 param($Value)
 if(($Value -isnot [int] -and $Value -isnot [long]) -or $Value -le 0){throw 'The official release identity or byte count is invalid.'}
 return [long]$Value
}

function ConvertTo-StationReleaseOffer {
 param([Parameter(Mandatory=$true)][string]$Json,[Parameter(Mandatory=$true)][long]$ReleaseId,[Parameter(Mandatory=$true)][string]$CurrentVersion,[Parameter(Mandatory=$true)][string]$ExpectedFingerprint)
 if($Json.Length -gt 1048576 -or $ExpectedFingerprint -cnotmatch '\A[a-f0-9]{64}\z'){throw 'The official release observation is invalid.'}
 [void](ConvertTo-StationReleaseInteger $ReleaseId)
 $current=ConvertTo-StationStableVersion $CurrentVersion
 $raw=$Json|ConvertFrom-Json -ErrorAction Stop
 $api='https://api.github.com/repos/jahu/ai-station'
 $web='https://github.com/jahu/ai-station'
 if((ConvertTo-StationReleaseInteger $raw.id) -ne $ReleaseId -or $raw.draft -isnot [bool] -or $raw.draft -or $raw.prerelease -isnot [bool] -or $raw.prerelease -or $raw.tag_name -isnot [string] -or -not $raw.tag_name.StartsWith('v',[StringComparison]::Ordinal)){throw 'Choose the exact published official stable release.'}
 $versionText=$raw.tag_name.Substring(1)
 $version=ConvertTo-StationStableVersion $versionText
 if($version.CompareTo($current) -le 0 -or $raw.html_url -cne ($web+'/releases/tag/v'+$versionText)){throw 'The official update must be newer than this installed app.'}
 $stamp=[DateTimeOffset]::MinValue
 # Windows PowerShell preserves JSON date strings; newer PowerShell versions
 # may materialize ISO dates. Unspecified-zone dates are rejected in both cases.
 $published=$raw.published_at
 $dated=if($published -is [DateTime]){$published.Kind -ne [DateTimeKind]::Unspecified}else{$published -is [string] -and $published -cmatch '(Z|[+-][0-9]{2}:[0-9]{2})\z' -and [DateTimeOffset]::TryParse($published,[Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None,[ref]$stamp)}
 if(-not $dated){throw 'The stable release has no valid publication time.'}
 if($raw.assets -isnot [Array] -or $raw.assets.Count -gt 40){throw 'The official package list exceeds its bound.'}
 $packages=[ordered]@{}
 foreach($platform in @('linux-amd64','windows-x64')){
  $suffix=if($platform -ceq 'linux-amd64'){'linux-amd64.deb'}else{'windows-x64-Setup.exe'}
  $name='AI-Station-'+$versionText+'-'+$suffix
  $candidates=@($raw.assets|Where-Object {$_.name -ceq $name})
  if($candidates.Count -gt 1){throw 'The official release has ambiguous update packages.'}
  if($candidates.Count -eq 0){continue}
  $asset=$candidates[0];$assetId=ConvertTo-StationReleaseInteger $asset.id;$bytes=ConvertTo-StationReleaseInteger $asset.size
  if($bytes -gt 4294967296 -or $asset.state -cne 'uploaded' -or $asset.digest -isnot [string] -or $asset.digest -cnotmatch '\Asha256:[a-f0-9]{64}\z' -or $asset.url -cne ($api+'/releases/assets/'+$assetId) -or $asset.browser_download_url -cne ($web+'/releases/download/v'+$versionText+'/'+$name)){throw 'The official update needs an exact asset identity, byte count and SHA256.'}
  # Same ASCII field order and compact encoding as the shared Python admission.
  $packages[$platform]=[ordered]@{id=$assetId;name=$name;sha256=$asset.digest.Substring(7);size_bytes=$bytes}
 }
 if(-not $packages.Contains('windows-x64')){throw 'This release has no Windows desktop update.'}
 $binding=[ordered]@{packages=$packages;release_id=$ReleaseId;version=$versionText}
 $encoded=[Text.UTF8Encoding]::new($false,$true).GetBytes(($binding|ConvertTo-Json -Depth 8 -Compress))
 $hash=[Security.Cryptography.SHA256]::Create()
 try{$fingerprint=([BitConverter]::ToString($hash.ComputeHash($encoded))).Replace('-','').ToLowerInvariant()}finally{$hash.Dispose()}
 if($fingerprint -cne $ExpectedFingerprint){throw 'The official release changed after approval. Check for updates again.'}
 return [pscustomobject]@{ReleaseId=$ReleaseId;Version=$versionText;Fingerprint=$fingerprint;Package=[pscustomobject]$packages['windows-x64']}
}

function Get-StationOfficialReleaseOffer {
 param([Parameter(Mandatory=$true)][long]$ReleaseId,[Parameter(Mandatory=$true)][string]$CurrentVersion,[Parameter(Mandatory=$true)][string]$ExpectedFingerprint)
 [void](ConvertTo-StationReleaseInteger $ReleaseId)
 [void](ConvertTo-StationStableVersion $CurrentVersion)
 if($ExpectedFingerprint -cnotmatch '\A[a-f0-9]{64}\z'){throw 'The approved release fingerprint is invalid.'}
 Add-Type -AssemblyName System.Net.Http
 $handler=[Net.Http.HttpClientHandler]::new();$handler.AllowAutoRedirect=$false;$handler.UseProxy=$false;$handler.UseCookies=$false;$handler.UseDefaultCredentials=$false
 $client=[Net.Http.HttpClient]::new($handler);$client.Timeout=[TimeSpan]::FromSeconds(30)
 $response=$null;$stream=$null;$buffer=[IO.MemoryStream]::new()
 $tls=[Net.ServicePointManager]::SecurityProtocol
 try{
  [Net.ServicePointManager]::SecurityProtocol=$tls -bor [Net.SecurityProtocolType]::Tls12
  [void]$client.DefaultRequestHeaders.TryAddWithoutValidation('User-Agent','AI-Station-Desktop-Updater')
  [void]$client.DefaultRequestHeaders.TryAddWithoutValidation('Accept','application/vnd.github+json')
  [void]$client.DefaultRequestHeaders.TryAddWithoutValidation('Accept-Encoding','identity')
  [void]$client.DefaultRequestHeaders.TryAddWithoutValidation('X-GitHub-Api-Version','2022-11-28')
  $address='https://api.github.com/repos/jahu/ai-station/releases/'+$ReleaseId
  $response=$client.GetAsync($address,[Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
  if([int]$response.StatusCode -ne 200 -or $response.RequestMessage.RequestUri.AbsoluteUri -cne $address -or @($response.Content.Headers.ContentEncoding|Where-Object {$_ -cne 'identity'}).Count -ne 0){throw 'The official release service did not confirm this observation.'}
  $stream=$response.Content.ReadAsStreamAsync().GetAwaiter().GetResult();$chunk=[byte[]]::new(65536);$deadline=[Diagnostics.Stopwatch]::StartNew()
  while($true){
   $read=$stream.ReadAsync($chunk,0,$chunk.Length)
   if(-not $read.Wait(15000)){throw 'The official release metadata timed out.'}
   $count=$read.GetAwaiter().GetResult();if($count -eq 0){break}
   if($buffer.Length+$count -gt 1048576 -or $deadline.Elapsed.TotalSeconds -gt 60){throw 'The official release metadata exceeded its bound.'}
   $buffer.Write($chunk,0,$count)
  }
  $json=[Text.UTF8Encoding]::new($false,$true).GetString($buffer.ToArray())
  return ConvertTo-StationReleaseOffer $json $ReleaseId $CurrentVersion $ExpectedFingerprint
 }finally{
  if($null -ne $stream){$stream.Dispose()};if($null -ne $response){$response.Dispose()};$buffer.Dispose();$client.Dispose();[Net.ServicePointManager]::SecurityProtocol=$tls
 }
}

Export-ModuleMember -Function ConvertTo-StationReleaseOffer,Get-StationOfficialReleaseOffer
