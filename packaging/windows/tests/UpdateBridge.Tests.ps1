$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../UpdateBridge.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../ReleaseChannel.psm1') -Force
$script:cases=0
function Check($value,$why){if(-not $value){throw $why};$script:cases++}
function Reject([scriptblock]$action){$failed=$false;try{& $action|Out-Null}catch{$failed=$true};Check $failed 'An unapproved package frame was accepted'}
$fixture=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fixtures/release-offer.json') -Raw|ConvertFrom-Json
$run=[Guid]::NewGuid().ToString('D');$channel=[Guid]::NewGuid().ToString('D')
$pending=[pscustomobject]@{run_id=$run;request=[pscustomobject]@{release_id=$fixture.expected.release_id;fingerprint=$fixture.expected.fingerprint;platform='windows-x64';current_version='0.5.0'}}
# Real binary boundaries without WSL/network/installer. The public contract is
# tested separately; this bounded stream exercises every byte, including newlines.
$payload=[byte[]]::new(262144);for($i=0;$i -lt $payload.Length;$i++){$payload[$i]=[byte]($i%256)}
$sha=[Security.Cryptography.SHA256]::Create();try{$digest=[BitConverter]::ToString($sha.ComputeHash($payload)).Replace('-','').ToLowerInvariant()}finally{$sha.Dispose()}
$offer=[pscustomobject]@{Version='0.5.1';Package=[pscustomobject]@{id=123;sha256=$digest;size_bytes=$payload.Length}}
$target=[pscustomobject]@{version=$offer.Version;asset_id=$offer.Package.id;installer_sha256=$digest;installer_bytes=$payload.Length}
$header=[pscustomobject]@{run_id=$run;channel_id=$channel;request=$pending.request;target=$target}
function Frame($value,$bytes){
 $stream=[IO.MemoryStream]::new();$text=[Text.UTF8Encoding]::new($false).GetBytes(($value|ConvertTo-Json -Depth 8 -Compress)+"`n");$stream.Write($text,0,$text.Length);$stream.Write($bytes,0,$bytes.Length);$stream.Position=0;return ,$stream
}
$source=Frame $header $payload;$destination=[IO.MemoryStream]::new()
try{$result=Receive-StationUpdateStream $source $destination $pending $channel $offer;Check ($result.installer_sha256 -ceq $digest -and $destination.Length -eq $payload.Length) 'Verified binary transfer failed';Check ([Convert]::ToBase64String($destination.ToArray()) -ceq [Convert]::ToBase64String($payload)) 'Binary bytes changed'}finally{$source.Dispose();$destination.Dispose()}
foreach($change in @('run','channel','fingerprint','version','asset','hash','size','extra')){
 $bad=$header|ConvertTo-Json -Depth 8|ConvertFrom-Json
 switch($change){
  'run'{$bad.run_id=[Guid]::NewGuid().ToString('D')}
  'channel'{$bad.channel_id=[Guid]::NewGuid().ToString('D')}
  'fingerprint'{$bad.request.fingerprint='0'*64}
  'version'{$bad.target.version='9.0.0'}
  'asset'{$bad.target.asset_id++}
  'hash'{$bad.target.installer_sha256='0'*64}
  'size'{$bad.target.installer_bytes++}
  'extra'{$bad|Add-Member -NotePropertyName 'path' -NotePropertyValue 'C:\arbitrary.exe'}
 }
 $source=Frame $bad $payload;$destination=[IO.MemoryStream]::new()
 try{Reject {Receive-StationUpdateStream $source $destination $pending $channel $offer};Check ($destination.Length -eq 0) 'Rejected header wrote package bytes'}finally{$source.Dispose();$destination.Dispose()}
}
foreach($length in @(0,262143,262145)){
 $bytes=[byte[]]::new($length);$source=Frame $header $bytes;$destination=[IO.MemoryStream]::new()
 try{Reject {Receive-StationUpdateStream $source $destination $pending $channel $offer}}finally{$source.Dispose();$destination.Dispose()}
}
$badBytes=[byte[]]$payload.Clone();$badBytes[100]=0;$source=Frame $header $badBytes;$destination=[IO.MemoryStream]::new()
try{Reject {Receive-StationUpdateStream $source $destination $pending $channel $offer}}finally{$source.Dispose();$destination.Dispose()}
$source=[IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes('x'*8193));$destination=[IO.MemoryStream]::new()
try{Reject {Receive-StationUpdateStream $source $destination $pending $channel $offer}}finally{$source.Dispose();$destination.Dispose()}
$source=Frame $header $payload;$destination=[IO.MemoryStream]::new();$cancel=[Threading.CancellationTokenSource]::new();$cancel.Cancel()
try{Reject {Receive-StationUpdateStream $source $destination $pending $channel $offer $cancel.Token};Check ($destination.Length -eq 0) 'Canceled transfer wrote package bytes'}finally{$source.Dispose();$destination.Dispose();$cancel.Dispose()}
$fresh=& (Get-Module UpdateBridge) {
 function script:Assert-StationPrivateAcl {param($Path)}
 function script:Assert-StationNoReparsePath {param($Path)}
 $root=Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N'))
 [void][IO.Directory]::CreateDirectory($root)
 try{
  $value=Read-StationUpdateObject ([pscustomobject]@{Root=$root}) 'operation.json'
  return $null -eq $value -and -not [IO.Directory]::Exists((Join-Path $root 'automatic-updates'))
 }finally{[IO.Directory]::Delete($root,$true)}
}
Check $fresh 'Read-only polling created unmarked data that would block first setup'
Write-Output ('PASS '+$script:cases+' bounded Windows package stream assertions; no network, WSL or installer')
