$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../GuestUpdate.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../InstallState.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Reason) { if(-not $Condition){throw $Reason};$script:Cases++ }
function Refuses([scriptblock]$Action) { $failed=$false;try{&$Action|Out-Null}catch{$failed=$true};Check $failed 'Invalid update was admitted' }
function Fixture([string]$Hash='b') {
 return [pscustomobject]@{
  schema=1;desktop_protocol=2;source_head=('a'*40);base=('ubuntu:24.04@sha256:'+('c'*64));package_sha256=($Hash*64);package_bytes=100
  rootfs_sha256=('d'*64);rootfs_bytes=200;image_id=('sha256:'+('e'*64))
  package=[pscustomobject]@{Package='ai-station';Architecture='amd64';Version='0.1.0~preview.2+bbbbbbbbbbbbbbbb';'X-AI-Station-Desktop-Protocol'='2'}
  sources=[pscustomobject]@{'guest.Dockerfile'=('f'*64);'guest_control.py'=('a'*64);'wsl.conf'=('b'*64)}
 }
}
$root='C:\Users\Synthetic user\AppData\Local\AIStation-Desktop'
$old=Fixture;$target=Fixture 'c'
$state=New-StationInstallState $root $old.package_sha256
$state.Phase='ready';$state.RegistrationId='{12345678-1234-4234-8234-123456789abc}'
$program=[Text.Encoding]::UTF8.GetBytes('print(1)')
$plan=Get-StationGuestUpdatePlan $state $root $old $target $program
Check (($plan.Arguments[0..7]-join '|') -ceq ('--distribution|'+$state.Distribution+'|--user|root|--exec|/usr/lib/ai-station/python/bin/python3|-IBS|-c')) 'Unexpected WSL operation'
Check ($plan.Arguments[-1] -ceq $state.Distribution) 'Updater was not bound to the saved distro'
Check ($plan.Arguments[8] -like "exec(__import__('gzip').decompress(__import__('base64').b64decode('*')*)") 'Unexpected updater program'
$match=[regex]::Match($plan.Arguments[8],"b64decode\('([A-Za-z0-9+/=]+)'\)")
$encodedStream=[IO.MemoryStream]::new([Convert]::FromBase64String($match.Groups[1].Value),$false)
$decoded=[IO.MemoryStream]::new()
try {$gzip=[IO.Compression.GZipStream]::new($encodedStream,[IO.Compression.CompressionMode]::Decompress);try{$gzip.CopyTo($decoded)}finally{$gzip.Dispose()};Check ([Text.Encoding]::UTF8.GetString($decoded.ToArray()) -ceq 'print(1)') 'Compressed updater source changed'}finally{$encodedStream.Dispose();$decoded.Dispose()}
$header=[Text.Encoding]::UTF8.GetString($plan.Header)|ConvertFrom-Json
Check ($header.package_bytes -eq 100 -and $header.previous.package_sha256 -ceq $old.package_sha256 -and $header.target.package_sha256 -ceq $target.package_sha256) 'Update identities were lost'
foreach($name in @('guest.Dockerfile','wsl.conf','guest_control.py')) {
 $bad=Fixture 'c';$bad.sources.$name='0'*64;Refuses { Get-StationGuestUpdatePlan $state $root $old $bad $program }
}
foreach($bytes in @($true,0,-1,1073741824,'100',1.5,1.0)) {
 $bad=Fixture 'c';$bad.package_bytes=$bytes;Refuses { Get-StationGuestUpdatePlan $state $root $old $bad $program }
}
$bad=Fixture 'c';$bad.PSObject.Properties.Remove('package_bytes');Refuses { Get-StationGuestUpdatePlan $state $root $old $bad $program }
Refuses { Get-StationGuestUpdatePlan $state $root $old $target ([byte[]]::new(65537)) }
$bad=Fixture 'c';$bad|Add-Member -NotePropertyName 'oversized' -NotePropertyValue ('x'*17000);Refuses { Get-StationGuestUpdatePlan $state $root $old $bad $program }
$state.PackageSha256='0'*64;Refuses { Get-StationGuestUpdatePlan $state $root $old $target $program };$state.PackageSha256=$old.package_sha256
$state.Phase='reserved';Refuses { Get-StationGuestUpdatePlan $state $root $old $target $program };$state.Phase='ready'

# Real binary native stdin transfer into one harmless owned process. No WSL,
# root, installation, network, models or production files are involved.
$folder=Join-Path ([IO.Path]::GetTempPath()) ('ai-station-update-transport-'+[guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($folder)
try {
 $receiver=@'
$stream=[Console]::OpenStandardInput();$header=[Collections.Generic.List[byte]]::new()
do{$b=$stream.ReadByte();if($b -lt 0){throw 'Missing fixture header'};if($b -ne 10){$header.Add([byte]$b)}}while($b -ne 10 -and $header.Count -lt 16384)
$value=[Text.Encoding]::UTF8.GetString($header.ToArray())|ConvertFrom-Json
if(-not $value.fixture){throw 'Wrong fixture header'}
$body=[IO.MemoryStream]::new();$stream.CopyTo($body);$data=$body.ToArray();if($data.Length -ne 262144){throw 'Wrong binary length'}
for($i=0;$i -lt $data.Length;$i++){if($data[$i] -ne [byte]($i%256)){throw 'Binary transfer changed'}}
[Console]::WriteLine('{"status":"updated","data_preserved":true,"backup_available":false}')
'@
 $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=(Get-Process -Id $PID).Path
 $info.Arguments='-NoLogo -NoProfile -NonInteractive -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($receiver));$info.UseShellExecute=$false
 $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $process=[Diagnostics.Process]::Start($info)
 $data=[byte[]]::new(262144);for($i=0;$i -lt $data.Length;$i++){$data[$i]=[byte]($i%256)}
 $memory=[IO.MemoryStream]::new($data,$false)
 try {
  $result=Send-StationGuestUpdate $process ([pscustomobject]@{Stream=$memory}) ([Text.Encoding]::UTF8.GetBytes("{`"fixture`":true}`n"))
  Check ($result.status -ceq 'updated' -and $result.data_preserved -and -not $result.backup_available) 'Binary native transport did not confirm receipt'
 } finally {$memory.Dispose()}
} finally {[IO.Directory]::Delete($folder,$true)}
Write-Output ('PASS '+$script:Cases+' update plan/refusal and real binary transport assertions; no WSL or installation')
