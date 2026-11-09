$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../AutomaticUpdate.psm1') -Force
$module=Get-Module AutomaticUpdate
& $module {
 $script:root=Join-Path ([IO.Path]::GetTempPath()) ('ai-station-completion-'+[Guid]::NewGuid().ToString('N'))
 [void][IO.Directory]::CreateDirectory($script:root)
 $script:events=[Collections.Generic.List[string]]::new();$script:bindings=0
 $script:op=[pscustomobject]@{schema=1;phase='guest_update';run_id=[Guid]::NewGuid().ToString('D');channel_id=[Guid]::NewGuid().ToString('D');request=[pscustomobject]@{fingerprint=('a'*64)};target=[pscustomobject]@{version='0.5.1';installer_sha256=('b'*64)};install_root='C:\Synthetic';original_record=[pscustomobject]@{State=[pscustomobject]@{InstallId='fixed'}};proof=$null;updated_at=1}
 $script:target=[pscustomobject]@{Folder=([IO.Path]::GetDirectoryName((Get-Module AutomaticUpdate).Path));Hash=('c'*64);Manifest=[pscustomobject]@{package=[pscustomobject]@{Version='0.5.1'}}}
 # The fake child is never executed; System is empty on a portable Unix host.
 function script:Join-Path {param([AllowEmptyString()][string]$Path,[string]$ChildPath);return [IO.Path]::Combine($Path,$ChildPath)}
 function script:New-StationPrivateStore {$script:lastLease=[IO.MemoryStream]::new();return [pscustomobject]@{Root=$script:root;Stream=$script:lastLease}}
 function script:Get-StationUpdateDirectory {param($Lease);return $script:root}
 function script:Assert-StationPrivateAcl {param($Path)}
 function script:Read-StationUpdateObject {param($Lease,$Name);return $script:op}
 function script:Write-StationUpdateObject {param($Lease,$Name,$Value);$script:op=$Value;$script:events.Add('phase:'+$Value.phase)}
 function script:Get-StationRegisteredUpdateTarget {param($InstallRoot,$TargetVersion);if($TargetVersion -cne '0.5.1'){throw 'Wrong target'};return $script:target}
 function script:Read-StationInstallRecord {param($Lease);return $script:op.original_record}
 function script:Invoke-StationSetup {param($PackageFolder,[switch]$AllowUpdate,$AutomaticUpdate,$OriginalUpdateRecord);$script:events.Add('preserving-update');return [pscustomobject]@{UpdateProof=[pscustomobject]@{data_preserved=$true;backup_available=$true}}}
 function script:Connect-StationUpdateOwner {param($Lease,$Record,$PackageFolder);if($PackageFolder -cne $script:target.Folder){throw 'Wrong native binding'};$script:bindings++;$script:events.Add('bind');return $true}
 function script:Start-StationUpdateChild {param($Info);if($Info.Arguments -notlike '*-StartAutomatically'){throw 'Unexpected installer or child replay'};$script:events.Add('start-ui');return [IO.MemoryStream]::new()}
 function script:Invoke-StationDesktop {throw 'Readiness must not acquire the target UI installation lock'}
 function script:Read-StationUpdateGuestReady {param($Root,$Record);if($Root -cne $script:root -or $script:lastLease.CanWrite){throw 'Health polling retained an installation lease'};$script:events.Add('ready');return 'fixed private readiness frame'}
 function script:Read-StationReadyFrame {param($Text);return [pscustomobject]@{InstanceId=('d'*32)}}
 function script:Confirm-StationBrowserTarget {param($Ready);$script:events.Add('health')}
 function script:Send-StationNativeUpdateResult {
  param($Lease,$Record,$Operation,$Phase,$Proof)
  if($script:bindings -ne 2 -or $script:events[$script:events.Count-1] -cne 'bind'){throw 'The native owner was not renewed after slow startup'}
  if($Phase -cne 'applied' -or $Proof.host_manifest_sha256 -cne ('c'*64) -or -not $Proof.data_preserved -or -not $Proof.backup_available){throw 'Completion proof was not preserved'}
  $script:events.Add('ack');return [pscustomobject]@{phase='succeeded'}
 }
 try{
  Complete-StationAutomaticGuestUpdate
  if($script:op.phase -cne 'complete' -or $script:bindings -ne 2){throw 'The original operation was not completed through its renewed native owner'}
  if(($script:events -join '|') -cne 'preserving-update|phase:restarting|bind|start-ui|ready|health|bind|ack|phase:complete'){throw 'The actual completion ordering changed'}
  $before=$script:events.Count;$refused=$false
  try{Complete-StationAutomaticGuestUpdate}catch{$refused=$true}
  if(-not $refused -or $script:events.Count -ne $before){throw 'Completed continuation replayed startup or acknowledgement'}
  Write-Output 'PASS native completion renews presence after healthy startup, retains backup proof and refuses replay; fake OS only'
 }finally{[IO.Directory]::Delete($script:root,$true)}
}
