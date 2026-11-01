$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../Setup.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../InstallState.psm1') -Force
$module=Get-Module Setup
& $module {
 $script:Cases=0
 function Check($value,[string]$reason){if(-not $value){throw $reason};$script:Cases++}
 function Clone($value){return ($value|ConvertTo-Json -Depth 8|ConvertFrom-Json)}
 function Manifest([string]$hash){return [pscustomobject]@{
  schema=1;desktop_protocol=2;source_head=('a'*40);base=('ubuntu:24.04@sha256:'+('a'*64));package_sha256=($hash*64);package_bytes=100
  rootfs_sha256=($hash*64);rootfs_bytes=200;image_id=('sha256:'+('e'*64))
  package=[pscustomobject]@{Package='ai-station';Architecture='amd64';Version='0.1.0~preview.2+bbbbbbbbbbbbbbbb';'X-AI-Station-Desktop-Protocol'='2'}
  sources=[pscustomobject]@{'guest.Dockerfile'=('f'*64);'guest_control.py'=('a'*64);'wsl.conf'=('b'*64)}
 }}
 $script:Root='C:\Users\Synthetic\AppData\Local\AIStation-Desktop';$script:Old=Manifest 'b';$script:Target=Manifest 'c'
 $state=New-StationInstallState $script:Root $script:Old.package_sha256;$state.Phase='ready';$state.RegistrationId='{12345678-1234-4234-8234-123456789abc}'
 $script:Original=[pscustomobject]@{RecordSchema=1;State=$state;Manifest=$script:Old}
 function ResetFixture {
  $script:Saved=Clone $script:Original;$script:Guest=Clone $script:Old;$script:Events=[Collections.Generic.List[string]]::new()
  $script:Pending=$false;$script:LostAck=$false;$script:Busy=$false;$script:ReplaceRegistration=$false
 }
 # Only the native orchestration is exercised here. All OS/WSL operations are
 # fake, immutable manifests and the real typed planners/confirmation remain.
 function script:Assert-StationWindowsHost {}
 function script:Assert-StationWindowsPreparationReady {}
 function script:Assert-StationNoReparsePath {param($Path)}
 function script:Get-StationWslExecutable {return 'C:\Windows\System32\wsl.exe'}
 function script:Read-StationPublishedManifest {param($PackageFolder);return (Clone $script:Target)}
 function script:New-StationPrivateStore {return [pscustomobject]@{Root=$script:Root;Stream=[IO.MemoryStream]::new()}}
 function script:Read-StationInstallRecord {param($Lease);return (Clone $script:Saved)}
 function script:Write-StationStateFile {param($Lease,$Record);$script:Saved=Clone $Record;$script:Events.Add('saved-target')}
 function script:Read-StationGuestUpdateProgram {return ,[Text.Encoding]::UTF8.GetBytes('print(1)')}
 function script:Open-StationVerifiedArchive {param($Path,$Sha256,$Bytes);Check ($Sha256 -ceq $script:Target.package_sha256 -and $Bytes -eq 100) 'Wrong package admitted';return [pscustomobject]@{Stream=[IO.MemoryStream]::new([byte[]]::new(100),$false)}}
 function script:Get-StationWslRegistrations {
  $id=$script:Original.State.RegistrationId
  if($script:ReplaceRegistration -and $script:Events.Contains('updated-guest')){$id='{abcdefab-1234-4234-8234-123456789abc}'}
  return [pscustomobject]@{Id=$id;DistributionName=$script:Original.State.Distribution;BasePath=$script:Original.State.Directory;Version=2}
 }
 function script:Start-StationWslProcess {param($Executable,$Arguments,$Directory,[switch]$KeepInput)
  if($Arguments -contains '--distribution'){Check ($Directory -ceq $script:Root) 'Wrong private working directory'}
  if($Arguments -contains '--import'){throw 'An update must never import a distro'}
  if($Arguments -contains 'root'){Check $KeepInput 'Updater stdin was closed';$script:Events.Add('root-update')}
  elseif($Arguments -contains 'start'){$script:Events.Add('start')}
  return [pscustomobject]@{Arguments=$Arguments}
 }
 function script:Wait-StationWslProcess {param($Process,[bool]$KeepOutput,$CancellationToken)
  $args=$Process.Arguments
  if($args[-1] -ceq '/usr/lib/ai-station-wsl-build.json'){return ($script:Guest|ConvertTo-Json -Depth 8)}
  if($args[-1] -ceq 'describe'){return '{"desktop_protocol":2}'}
  if($args -contains '-c'){return [string]$script:Pending}
  return '{"running":false}'
 }
 function script:Send-StationGuestUpdate {param($Process,$Archive,[byte[]]$Header,$CancellationToken)
  $body=[Text.Encoding]::UTF8.GetString($Header)|ConvertFrom-Json
  Check ($body.previous.package_sha256 -ceq $script:Old.package_sha256 -and $body.target.package_sha256 -ceq $script:Target.package_sha256) 'Lost old/target identity'
  if($script:Busy){throw 'Synthetic active Run: finish saved work first'}
  $script:Guest=Clone $script:Target;$script:Events.Add('updated-guest')
  if($script:LostAck){$script:LostAck=$false;throw 'Synthetic lost acknowledgement'}
  return [pscustomobject]@{status='updated';data_preserved=$true;backup_available=$true}
 }
 function script:Get-StationAvailablePort {return 8765}
 function script:Test-StationFixedGuestFile {param($Lease,$Record,$Executable,$Path,[switch]$ExecutableFile,[switch]$RootUser);if($Path -eq '/var/lib/ai-station-updates/python/bin/python3'){Check ($RootUser -and $ExecutableFile) 'Wrong stable interpreter inspection';return $false};Check (-not $RootUser -and -not $ExecutableFile) 'Status/Stop acquired root authority';return $script:Pending}

 ResetFixture
 $refused=$false;try{Invoke-StationSetup -PackageFolder 'C:\Package'|Out-Null}catch{$refused=$true}
 Check $refused 'An update was installed without an explicit Update action'
 Check (-not $script:Events.Contains('root-update')) 'Implicit root operation'
 Invoke-StationSetup -PackageFolder 'C:\Package' -AllowUpdate|Out-Null
 Check ($script:Saved.Manifest.package_sha256 -ceq $script:Target.package_sha256) 'Windows receipt did not advance'
 Check ($script:Saved.State.InstallId -ceq $script:Original.State.InstallId -and $script:Saved.State.RegistrationId -ceq $script:Original.State.RegistrationId) 'Distribution ownership changed'
 Check ($script:Events[-1] -ceq 'saved-target') 'Windows receipt was not published after target verification'

 ResetFixture;$script:LostAck=$true
 $refused=$false;try{Invoke-StationSetup -PackageFolder 'C:\Package' -AllowUpdate|Out-Null}catch{$refused=$true}
 Check $refused 'Lost acknowledgement was treated as success'
 Check ($script:Saved.Manifest.package_sha256 -ceq $script:Old.package_sha256) 'Unconfirmed target was published'
 Check ($script:Guest.package_sha256 -ceq $script:Target.package_sha256) 'Lost-ack fixture never completed guest side'
 Invoke-StationSetup -PackageFolder 'C:\Package' -AllowUpdate|Out-Null
 Check ($script:Saved.Manifest.package_sha256 -ceq $script:Target.package_sha256) 'Exact-target resume failed'

 ResetFixture;$script:Busy=$true
 $refused=$false;try{Invoke-StationSetup -PackageFolder 'C:\Package' -AllowUpdate|Out-Null}catch{$refused=$true}
 Check ($refused -and $script:Saved.Manifest.package_sha256 -ceq $script:Old.package_sha256) 'Busy work was replaced'
 [void](Invoke-StationDesktop -Action start -PackageFolder 'C:\Package')
 Check ($script:Events.Contains('start')) 'Cannot start previous version to finish queued work'

 ResetFixture;$script:Pending=$true
 $status=Invoke-StationDesktop -Action status -PackageFolder 'C:\Package'|ConvertFrom-Json
 Check ($status.update_available -and $status.update_pending -and -not $status.running) 'Pending state was not projected'
 $refused=$false;try{Invoke-StationDesktop -Action start -PackageFolder 'C:\Package'|Out-Null}catch{$refused=$true}
 Check ($refused -and -not $script:Events.Contains('start')) 'Pending update started a potentially incomplete package'
 Invoke-StationDesktop -Action stop -PackageFolder 'C:\Package'|Out-Null
 Check (-not $script:Events.Contains('root-update')) 'Stop acquired package/root authority'

 ResetFixture;$script:ReplaceRegistration=$true
 $refused=$false;try{Invoke-StationSetup -PackageFolder 'C:\Package' -AllowUpdate|Out-Null}catch{$refused=$true}
 Check ($refused -and $script:Saved.Manifest.package_sha256 -ceq $script:Old.package_sha256) 'Changed registry identity was adopted'
 Write-Output ('PASS '+$script:Cases+' update coordinator assertions; fake WSL only')
}
