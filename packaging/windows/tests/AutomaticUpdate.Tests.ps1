$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../AutomaticUpdate.psm1') -Force
$module=Get-Module AutomaticUpdate
& $module {
 $script:cases=0
 function Check($value,$why){if(-not $value){throw $why};$script:cases++}
 function Clone($value){return $value|ConvertTo-Json -Depth 12|ConvertFrom-Json}
 $script:root=Join-Path ([IO.Path]::GetTempPath()) ('ai-station-native-update-'+[Guid]::NewGuid().ToString('N'))
 [void][IO.Directory]::CreateDirectory($script:root)
 [IO.File]::WriteAllText((Join-Path $script:root 'ui-active.lock'),'')
 $run=[Guid]::NewGuid().ToString('D');$channel=[Guid]::NewGuid().ToString('D')
 $record=[pscustomobject]@{State=[pscustomobject]@{InstallId='fixed';RegistrationId='fixed-registration';Distribution='AIStation-fixed'}}
 $script:original=[pscustomobject]@{schema=1;updated_at=1;phase='created';run_id=$run;channel_id=$channel;request=[pscustomobject]@{release_id=10;fingerprint=('c'*64);current_version='0.5.0';platform='windows-x64'};target=[pscustomobject]@{version='0.5.1';installer_sha256=('b'*64);installer_bytes=12};original_record=$record;source_folder='C:\Synthetic\versions\aaaaaaaaaaaaaaaa';source_hash=('a'*64);install_root='C:\Synthetic';proof=$null}
 function Reset([string]$Phase){$script:op=Clone $script:original;$script:op.phase=$Phase;$script:events=[Collections.Generic.List[string]]::new();$script:missingTarget=$false;$script:lostGuestAck=$false;$script:completedAck=$false;$script:lostFinisherAck=$false;$script:finisherComplete=$false;$script:foreignFinisher=$false}
 function script:New-StationPrivateStore {return [pscustomobject]@{Root=$script:root;Stream=[IO.MemoryStream]::new()}}
 function script:Assert-StationPrivateAcl {param($Path)}
 function script:Get-StationUpdateDirectory {param($Lease);return $script:root}
 function script:Read-StationUpdateObject {param($Lease,$Name);return (Clone $script:op)}
 function script:Write-StationUpdateObject {param($Lease,$Name,$Value);$script:op=Clone $Value;$script:events.Add('phase:'+$Value.phase)}
 function script:Get-StationUpdateChannel {param($Lease);return $script:original.channel_id}
 function script:Get-StationHostPayloadIdentity {param($Folder,$ExpectedHash);Check ($ExpectedHash -ceq ('a'*64)) 'Source publisher identity lost';return [pscustomobject]@{Folder=$Folder;Hash=$ExpectedHash}}
 function script:Read-StationInstallRecord {param($Lease);return (Clone $script:original.original_record)}
 function script:Get-StationOfficialReleaseOffer {param($ReleaseId,$CurrentVersion,$ExpectedFingerprint);Check ($ReleaseId -eq 10 -and $CurrentVersion -ceq '0.5.0' -and $ExpectedFingerprint -ceq ('c'*64)) 'Official frozen request lost';$script:events.Add('publisher');return [pscustomobject]@{Version='0.5.1'}}
 function script:Receive-StationWindowsPackage {param($Lease,$Record,$Pending,$ChannelId,$Offer);$script:events.Add('verified-transfer');return 'fixed.exe'}
 function script:Send-StationNativeUpdateResult {param($Lease,$Record,$Operation,$Phase,$Proof);$script:events.Add('guest:'+ $Phase);if($script:lostGuestAck -and $Phase -ceq 'applying'){throw 'Synthetic lost activation acknowledgement'};return [pscustomobject]@{phase='succeeded'}}
 function script:Invoke-StationDesktop {param($Action,$PackageFolder);$script:events.Add('normal-status');return '{"running":false}'}
 function script:Open-StationVerifiedArchive {param($Path,$Sha256,$Bytes);Check ($Sha256 -ceq ('b'*64) -and $Bytes -eq 12) 'Installer changed before dispatch';return [pscustomobject]@{Stream=[IO.MemoryStream]::new()}}
 function script:Get-StationRegisteredUpdateTarget {param($InstallRoot,$TargetVersion);$script:events.Add('registered-target');if($script:missingTarget){throw 'No matching target registration'};return [pscustomobject]@{Folder='C:\Synthetic\versions\bbbbbbbbbbbbbbbb';Hash=('b'*64)}}
 function script:Invoke-StationUpdateGuestControl {param($Lease,$Record,$Action,$Body);if(-not $script:completedAck -or $Action -cne 'update-status'){throw 'Unexpected guest ACK probe'};$script:events.Add('completed-ack');return [pscustomobject]@{phase='succeeded'}}
 function script:Start-StationUpdateChild {param($Info)
  $exitCode=0
  if($Info.FileName -ceq 'fixed.exe' -or $Info.FileName.EndsWith('.exe') -and $Info.Arguments.StartsWith('/VERYSILENT')){
   Check ($script:op.phase -ceq 'installer_dispatched') 'Installer launched before durable intent'
   Check ($script:events.Contains('normal-status') -and $script:events.Contains('guest:applying')) 'Installer launched before approved owned shutdown'
   $script:events.Add('installer')
  }elseif($Info.Arguments.EndsWith('-FinishGuest')){
   $script:events.Add('guest-transaction')
   if($script:lostFinisherAck){
    $script:op.phase=$(if($script:finisherComplete){'complete'}else{'restarting'})
    $script:op.proof=[pscustomobject]@{host_manifest_sha256=('b'*64);version='0.5.1';installer_sha256=('b'*64);data_preserved=$true;backup_available=$true}
    if($script:foreignFinisher){$script:op.source_hash=('f'*64)}
    $exitCode=1
   }
  }else{throw 'Unexpected native child'}
  $process=[pscustomobject]@{ExitCode=$exitCode};$process|Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {param($Timeout);return $true};$process|Add-Member -MemberType ScriptMethod -Name Dispose -Value {};return $process
 }
 # Supply a harmless platform-independent fixed System path in the only native
 # executable selection seam; all launched children above are fakes.
 function script:Join-Path {param($Path,$ChildPath);if(-not $Path){return ('C:\Windows\System32\'+$ChildPath)};return [IO.Path]::Combine($Path,$ChildPath)}
 try{
  Reset 'created'
  Invoke-StationAutomaticUpdate
  Check ($script:events.Contains('publisher') -and $script:events.Contains('verified-transfer') -and $script:events.Contains('installer') -and $script:events.Contains('guest-transaction')) 'Normal update did not traverse its actual stage planner'
  Check ($script:events.IndexOf('phase:activation_requested') -lt $script:events.IndexOf('guest:applying')) 'Activation intent did not precede native IPC'
  foreach($phase in @('installer_dispatched','native_installed','guest_update','restarting')){
   Reset $phase
   Invoke-StationAutomaticUpdate
   Check (-not $script:events.Contains('installer') -and $script:events.Contains('registered-target') -and $script:events.Contains('guest-transaction')) 'Recovery replayed an uncertain native installer'
  }
  Reset 'installer_dispatched';$script:missingTarget=$true
  $failed=$false;try{Invoke-StationAutomaticUpdate}catch{$failed=$true}
  Check ($failed -and $script:op.phase -ceq 'inspection_required' -and -not $script:events.Contains('installer') -and -not $script:events.Contains('guest-transaction')) 'Ambiguous registration was replayed or reported successful'
  Reset 'created';$script:lostGuestAck=$true
  $failed=$false;try{Invoke-StationAutomaticUpdate}catch{$failed=$true}
  Check ($failed -and $script:op.phase -ceq 'inspection_required' -and $script:op.resume_phase -ceq 'activation_requested' -and -not $script:events.Contains('installer')) 'Lost activation ACK discarded the original recovery stage'
  Reset 'native_installed';$script:lostFinisherAck=$true
  $failed=$false;try{Invoke-StationAutomaticUpdate}catch{$failed=$true}
  Check ($failed -and $script:op.phase -ceq 'inspection_required' -and $script:op.resume_phase -ceq 'restarting' -and $null -ne $script:op.proof) 'The parent overwrote the independent finisher recovery proof'
  $script:lostFinisherAck=$false;$script:completedAck=$true;$script:events.Clear()
  Invoke-StationAutomaticUpdate
  Check ($script:op.phase -ceq 'complete' -and $script:events.Contains('completed-ack') -and -not $script:events.Contains('installer') -and -not $script:events.Contains('guest-transaction')) 'Finisher exit replayed an already acknowledged update'
  Reset 'native_installed';$script:lostFinisherAck=$true;$script:finisherComplete=$true
  Invoke-StationAutomaticUpdate
  Check ($script:op.phase -ceq 'complete' -and $null -ne $script:op.proof -and -not $script:events.Contains('guest:inspection_required')) 'The parent replaced authoritative child completion with its stale state'
  Reset 'native_installed';$script:lostFinisherAck=$true;$script:foreignFinisher=$true
  $failed=$false;try{Invoke-StationAutomaticUpdate}catch{$failed=$true}
  Check ($failed -and $script:op.phase -ceq 'inspection_required' -and $script:op.resume_phase -ceq 'guest_update' -and $null -eq $script:op.proof) 'The parent adopted proof for a different frozen native source'
  Reset 'restarting';$script:completedAck=$true
  $script:op.proof=[pscustomobject]@{host_manifest_sha256=('b'*64);version='0.5.1';installer_sha256=('b'*64);data_preserved=$true;backup_available=$true}
  Invoke-StationAutomaticUpdate
  Check ($script:op.phase -ceq 'complete' -and $script:events.Contains('completed-ack') -and -not $script:events.Contains('normal-status') -and -not $script:events.Contains('installer') -and -not $script:events.Contains('guest-transaction')) 'Lost host completion write replayed a completed update'
  Reset 'complete'
  Invoke-StationAutomaticUpdate
  Check ($script:events.Count -eq 0) 'Completed operation was run again'
  Write-Output ('PASS '+$script:cases+' native update stage/recovery assertions; fake OS/installer only')
 }finally{[IO.Directory]::Delete($script:root,$true)}
}
