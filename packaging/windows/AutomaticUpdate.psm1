# Native SID-scoped one-click update. No operation is exposed to tools or HTTP.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
foreach($name in @('PrivateStore','InstallFiles','NativeWsl','NativeGuest','DesktopProcess','DesktopLink','ReleaseChannel','UpdateBridge','Setup')){Import-Module (Join-Path $PSScriptRoot ($name+'.psm1'))}

function Start-StationUpdateChild {
 param([Diagnostics.ProcessStartInfo]$Info)
 return [Diagnostics.Process]::Start($Info)
}

function Get-StationHostPayloadIdentity {
 param([string]$Folder,[string]$ExpectedHash='')
 Assert-StationNoReparsePath $Folder
 $path=[IO.Path]::Combine($Folder,'windows-host-manifest.json')
 Assert-StationNoReparsePath $path
 if([IO.FileInfo]::new($path).Length -gt 65536){throw 'The native publisher manifest exceeds its bound.'}
 $digest=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
 if($ExpectedHash -and $digest -cne $ExpectedHash){throw 'The retained native payload differs from its installer registration.'}
 $receipt=[IO.File]::ReadAllText($path,[Text.UTF8Encoding]::new($false,$true))|ConvertFrom-Json -ErrorAction Stop
 if($receipt.schema -ne 1 -or $receipt.source_head -cnotmatch '\A[a-f0-9]{40}\z' -or @($receipt.files.PSObject.Properties).Count -gt 80){throw 'The native publisher identity is invalid.'}
 foreach($entry in $receipt.files.PSObject.Properties){
  if($entry.Name -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9._-]{0,100}\z' -or $entry.Value -isnot [string] -or $entry.Value -cnotmatch '\A[a-f0-9]{64}\z'){throw 'The native manifest contains an invalid file identity.'}
  $file=[IO.Path]::Combine($Folder,$entry.Name)
  Assert-StationNoReparsePath $file
  Assert-StationRegularFile $file
  if((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.Value){throw 'A retained native application file changed. Inspect this installation.'}
 }
 foreach($required in @('AIStation.exe','WindowsSetup.ps1','AutomaticUpdate.psm1','Apply-Update.ps1','station.deb','windows-guest-manifest.json')){if($receipt.files.PSObject.Properties.Name -notcontains $required){throw 'The native payload is incomplete.'}}
 $manifest=Read-StationPublishedManifest $Folder
 [void](ConvertTo-StationStableVersion $manifest.package.Version)
 return [pscustomobject]@{Folder=[IO.Path]::GetFullPath($Folder);Hash=$digest;Manifest=$manifest}
}

function Get-StationRegisteredUpdateTarget {
 param([string]$InstallRoot,[string]$TargetVersion)
 $key=[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\AI Station\Desktop')
 if($null -eq $key){throw 'The target installer did not publish its native identity. It will not be launched again.'}
 try{$root=$key.GetValue('InstallRoot');$hash=$key.GetValue('CurrentPayloadSHA256')}finally{$key.Dispose()}
 if($root -isnot [string] -or $hash -isnot [string] -or $hash -cnotmatch '\A[a-f0-9]{64}\z' -or -not $root.Equals($InstallRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'The installed target belongs to another native application root.'}
 $identity=Get-StationHostPayloadIdentity ([IO.Path]::Combine($root,'versions',$hash.Substring(0,16))) $hash
 if($identity.Manifest.package.Version -cne $TargetVersion){throw 'The registered native payload is not the approved target version.'}
 return $identity
}

function Read-StationNativeUpdate {
 $root=[IO.Path]::Combine([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData),'AIStation-Desktop')
 if(-not [IO.File]::Exists([IO.Path]::Combine($root,'install-state.json'))){return $null}
 $operation=Read-StationUpdateObject ([pscustomobject]@{Root=$root}) 'operation.json'
 if($null -ne $operation -and $operation.phase -notin @('complete','failed')){
  $alive=$false;$path=[IO.Path]::Combine($root,'automatic-updates','helper.lock')
  if([IO.File]::Exists($path)){
   Assert-StationPrivateAcl $path
   try{$probe=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None);$probe.Dispose()}catch [IO.IOException]{$alive=$true}
  }
  $operation|Add-Member -NotePropertyName 'helper_alive' -NotePropertyValue $alive
 }
 return $operation
}

function Start-StationAutomaticUpdate {
 param($Lease,$Record,$Pending,[string]$PackageFolder)
 Assert-StationUpdateRequest $Pending (Get-StationUpdateChannel $Lease)
 if($Pending.phase -cne 'apply_requested'){return $false}
 $previous=Read-StationUpdateObject $Lease 'operation.json'
 if($null -ne $previous -and $previous.phase -notin @('complete','failed')){
  if($previous.run_id -cne $Pending.run_id){throw 'Another native update requires inspection.'}
  return $false # No helper or installer replay on repeated status polling.
 }
 $identity=Get-StationHostPayloadIdentity $PackageFolder
 if($identity.Manifest.package.Version -cne $Pending.request.current_version){throw 'The update was approved for a different installed app.'}
 $folder=[IO.Directory]::GetParent($identity.Folder)
 if($folder.Name -cne 'versions' -or $identity.Folder -ine [IO.Path]::Combine($folder.FullName,$identity.Hash.Substring(0,16))){throw 'Automatic updates require an installed retained native payload.'}
 $operation=[pscustomobject]@{
  schema=1;updated_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();run_id=$Pending.run_id;channel_id=(Get-StationUpdateChannel $Lease);phase='created'
  request=$Pending.request;target=$Pending.target;source_hash=$identity.Hash;source_folder=$identity.Folder
  install_root=$folder.Parent.FullName;original_record=$Record;proof=$null
 }
 Write-StationUpdateObject $Lease 'operation.json' $operation
 $powershell=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'WindowsPowerShell\v1.0\powershell.exe'
 $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$powershell;$info.WorkingDirectory=$identity.Folder
 $info.Arguments='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $identity.Folder 'Apply-Update.ps1')+'"'
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $process=(Start-StationUpdateChild $info);$process.Dispose()
 return $true
}

function Send-StationNativeUpdateResult {
 param($Lease,$Record,$Operation,[ValidateSet('applying','applied','failed','inspection_required')][string]$Phase,$Proof=$null)
 $body=[pscustomobject]@{channel_id=$Operation.channel_id;run_id=$Operation.run_id;fingerprint=$Operation.request.fingerprint;phase=$Phase;proof=$Proof}
 return Invoke-StationUpdateGuestControl $Lease $Record 'update-result' $body
}

function Set-StationNativeUpdatePhase {
 param($Lease,$Operation,[string]$Phase)
 $Operation.phase=$Phase
 $Operation.updated_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
 Write-StationUpdateObject $Lease 'operation.json' $Operation
}

function Invoke-StationAutomaticUpdate {
 # Independent process: only the private immutable operation may choose inputs.
 $lease=New-StationPrivateStore
 $helper=$null;$payload=$null;$operation=$null;$installer=$null
 try{
  $operation=Read-StationUpdateObject $lease 'operation.json'
  if($null -eq $operation -or $operation.schema -ne 1 -or $operation.phase -in @('complete','failed')){return}
  Assert-StationUpdateRequest $operation $operation.channel_id
  if($operation.channel_id -cne (Get-StationUpdateChannel $lease)){throw 'The original Windows update channel changed.'}
  $helperPath=[IO.Path]::Combine((Get-StationUpdateDirectory $lease),'helper.lock')
  if([IO.File]::Exists($helperPath)){Assert-StationPrivateAcl $helperPath}
  $helper=[IO.File]::Open($helperPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  if($operation.phase -ceq 'inspection_required'){
   if($operation.PSObject.Properties.Name -notcontains 'resume_phase'){throw 'Inspect the original native update stage before continuing.'}
   $operation.phase=$operation.resume_phase
  }
  $source=Get-StationHostPayloadIdentity $operation.source_folder $operation.source_hash
  $record=Read-StationInstallRecord $lease
  if($record.State.InstallId -cne $operation.original_record.State.InstallId -or $record.State.RegistrationId -ine $operation.original_record.State.RegistrationId -or $record.State.Distribution -cne $operation.original_record.State.Distribution){throw 'The original distribution ownership changed.'}
  if($null -ne $operation.proof -and $operation.phase -in @('restarting','guest_update')){
   # The guest may have acknowledged completion before the host journal write.
   # Recover that ACK against the exact retained native target and live health;
   # a completed original Run must not require another Stop or root transaction.
   $ack=Invoke-StationUpdateGuestControl $lease $record 'update-status' ([pscustomobject]@{channel_id=$operation.channel_id;run_id=$operation.run_id})
   if($ack.phase -ceq 'succeeded'){
    $target=Get-StationRegisteredUpdateTarget $operation.install_root $operation.target.version
    if($operation.proof.host_manifest_sha256 -cne $target.Hash -or $operation.proof.version -cne $operation.target.version -or $operation.proof.installer_sha256 -cne $operation.target.installer_sha256 -or $operation.proof.data_preserved -isnot [bool] -or -not $operation.proof.data_preserved){throw 'The original native completion proof changed.'}
    # The guest's succeeded stage already binds the actual ready receipt and
    # original native health acknowledgement. A later user Stop does not undo it.
    Set-StationNativeUpdatePhase $lease $operation 'complete'
    return
   }
  }
  if($operation.phase -in @('installer_dispatched','native_installed','guest_update','restarting')){
   $operation|Add-Member -NotePropertyName 'resume_after_stop' -NotePropertyValue $operation.phase -Force
   Set-StationNativeUpdatePhase $lease $operation 'stop_requested'
  }
  if($operation.phase -in @('created','staging')){
   Set-StationNativeUpdatePhase $lease $operation 'staging'
   $offer=Get-StationOfficialReleaseOffer $operation.request.release_id $operation.request.current_version $operation.request.fingerprint
   $payload=Receive-StationWindowsPackage $lease $record $operation $operation.channel_id $offer
   Set-StationNativeUpdatePhase $lease $operation 'activation_requested'
  }
  if($operation.phase -eq 'activation_requested'){
   # Intent precedes IPC: a lost acknowledgement is inspected, not a new install.
   [void](Send-StationNativeUpdateResult $lease $record $operation 'applying')
   Set-StationNativeUpdatePhase $lease $operation 'stop_requested'
  }
  # Release install.lock before the UI's normal Stop. helper.lock remains owned.
  $root=$lease.Root;$lease.Stream.Dispose();$lease=$null
  if($operation.phase -eq 'stop_requested'){
   $deadline=[DateTime]::UtcNow.AddMinutes(3);$exclusive=$null
   while($null -eq $exclusive){
    if([DateTime]::UtcNow -ge $deadline){throw 'The old application did not finish normal shutdown. No installer was dispatched.'}
    try{$exclusive=[IO.File]::Open([IO.Path]::Combine($root,'ui-active.lock'),[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)}catch [IO.IOException]{[Threading.Thread]::Sleep(250)}
   }
   try{
    $status=Invoke-StationDesktop 'status' -PackageFolder $operation.source_folder|ConvertFrom-Json
    if($status.running -or ($status.PSObject.Properties.Name -contains 'inspection_required' -and $status.inspection_required)){throw 'The owned station has not stopped safely.'}
    $lease=New-StationPrivateStore
    $record=Read-StationInstallRecord $lease
    if($operation.PSObject.Properties.Name -contains 'resume_after_stop' -and $null -ne $operation.resume_after_stop){
     $resume=$operation.resume_after_stop;$operation.resume_after_stop=$null
     Set-StationNativeUpdatePhase $lease $operation $resume
    }else{
    # The private host copy is opened and rehashed under a deny-write handle.
    $path=[IO.Path]::Combine((Get-StationUpdateDirectory $lease),($operation.run_id+'.exe'))
    $archive=Open-StationVerifiedArchive $path $operation.target.installer_sha256 $operation.target.installer_bytes
    try{
     Set-StationNativeUpdatePhase $lease $operation 'installer_dispatched' # Never dispatched twice.
     $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$path;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
     $info.WorkingDirectory=Get-StationUpdateDirectory $lease
     $info.Arguments='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="'+$operation.install_root+'"'
     $installer=(Start-StationUpdateChild $info)
     # Wait for this exact child; never kill a possibly active installer.
     if(-not $installer.WaitForExit(900000)){throw 'The owned installer is still running; inspect before continuing.'}
     if($installer.ExitCode -ne 0){throw 'The installer did not confirm completion. It will not be dispatched again.'}
    }finally{$archive.Stream.Dispose()}
    Set-StationNativeUpdatePhase $lease $operation 'native_installed'
    }
   }finally{if($null -ne $exclusive){$exclusive.Dispose()}}
  }
  if($null -eq $lease){$lease=New-StationPrivateStore}
  # On lost installer ACK, inspect its exact registration rather than replaying EXE.
  $target=Get-StationRegisteredUpdateTarget $operation.install_root $operation.target.version
  Set-StationNativeUpdatePhase $lease $operation 'guest_update'
  $lease.Stream.Dispose();$lease=$null
  # Run target source in a fresh PowerShell to avoid an old imported module.
  $powershell=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'WindowsPowerShell\v1.0\powershell.exe'
  $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$powershell;$info.UseShellExecute=$false;$info.CreateNoWindow=$true
  $info.WorkingDirectory=$target.Folder
  $info.Arguments='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $target.Folder 'Apply-Update.ps1')+'" -FinishGuest'
  $finish=(Start-StationUpdateChild $info)
  try{if(-not $finish.WaitForExit(1200000) -or $finish.ExitCode -ne 0){throw 'The preserving guest update needs inspection. No installer was dispatched again.'}}finally{$finish.Dispose()}
 }catch{
  if($null -eq $lease){$lease=New-StationPrivateStore}
  if($null -ne $operation){
   $phase=$(if($operation.phase -in @('created','staging')){'failed'}else{'inspection_required'})
   $operation | Add-Member -NotePropertyName 'resume_phase' -NotePropertyValue $operation.phase -Force
   Set-StationNativeUpdatePhase $lease $operation $phase
   try{[void](Send-StationNativeUpdateResult $lease $operation.original_record $operation $phase)}catch{}
  }
  throw
 }finally{if($null -ne $installer){$installer.Dispose()};if($null -ne $lease){$lease.Stream.Dispose()};if($null -ne $helper){$helper.Dispose()}}
}

function Complete-StationAutomaticGuestUpdate {
 $lease=New-StationPrivateStore;$finisher=$null
 try{
  $lockPath=[IO.Path]::Combine((Get-StationUpdateDirectory $lease),'finisher.lock')
  if([IO.File]::Exists($lockPath)){Assert-StationPrivateAcl $lockPath}
  $finisher=[IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  $operation=Read-StationUpdateObject $lease 'operation.json'
  if($null -eq $operation -or $operation.phase -cne 'guest_update'){throw 'No exact native guest update is awaiting continuation.'}
  $target=Get-StationRegisteredUpdateTarget $operation.install_root $operation.target.version
  if(-not $target.Folder.Equals($PSScriptRoot,[StringComparison]::OrdinalIgnoreCase)){throw 'Continue only from the verified target application.'}
  $context=[pscustomobject]@{channel_id=$operation.channel_id;run_id=$operation.run_id;fingerprint=$operation.request.fingerprint}
  $lease.Stream.Dispose();$lease=$null
  $outcome=Invoke-StationSetup -PackageFolder $target.Folder -AllowUpdate -AutomaticUpdate $context -OriginalUpdateRecord $operation.original_record
  if($null -eq $outcome.UpdateProof -or -not $outcome.UpdateProof.data_preserved){throw 'The original preserving transaction has no completion proof.'}
  $lease=New-StationPrivateStore
  $record=Read-StationInstallRecord $lease
  $operation.proof=[pscustomobject]@{host_manifest_sha256=$target.Hash;version=$target.Manifest.package.Version;installer_sha256=$operation.target.installer_sha256;data_preserved=$true;backup_available=$outcome.UpdateProof.backup_available}
  Set-StationNativeUpdatePhase $lease $operation 'restarting'
  [void](Connect-StationUpdateOwner $lease $record $target.Folder)
  $lease.Stream.Dispose();$lease=$null
  $powershell=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'WindowsPowerShell\v1.0\powershell.exe'
  $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$powershell;$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.WorkingDirectory=$target.Folder
  $info.Arguments='-NoLogo -NoProfile -STA -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+(Join-Path $target.Folder 'WindowsSetup.ps1')+'" -StartAutomatically'
  $ui=(Start-StationUpdateChild $info);$ui.Dispose()
  $deadline=[DateTime]::UtcNow.AddMinutes(10)
  while([DateTime]::UtcNow -lt $deadline){
   [Threading.Thread]::Sleep(1000)
   try{
    $line=Invoke-StationDesktop 'open' -PackageFolder $target.Folder
    $ready=Read-StationReadyFrame ([string]$line).Trim()
    if($null -eq $ready){continue}
    Confirm-StationBrowserTarget $ready
    $lease=New-StationPrivateStore
    $record=Read-StationInstallRecord $lease
    $result=Send-StationNativeUpdateResult $lease $record $operation 'applied' $operation.proof
    if($result.phase -cne 'succeeded'){throw 'The new guest has not confirmed readiness for this original Run.'}
    Set-StationNativeUpdatePhase $lease $operation 'complete'
    return
   }catch{if($null -ne $lease){$lease.Stream.Dispose();$lease=$null}}
  }
  throw 'The updated station did not confirm readiness. Preserve this operation for inspection.'
 }finally{if($null -ne $lease){$lease.Stream.Dispose()};if($null -ne $finisher){$finisher.Dispose()}}
}

Export-ModuleMember -Function Get-StationHostPayloadIdentity,Get-StationRegisteredUpdateTarget,Read-StationNativeUpdate,Start-StationAutomaticUpdate,Invoke-StationAutomaticUpdate,Complete-StationAutomaticGuestUpdate

function Resume-StationAutomaticUpdate {
 # Explicit local Continue only. A live helper's exclusive handle prevents replay.
 $lease=New-StationPrivateStore;$probe=$null
 try{
  $operation=Read-StationUpdateObject $lease 'operation.json'
  if($null -eq $operation -or $operation.phase -in @('complete','failed')){throw 'No native application update needs continuation.'}
  $path=[IO.Path]::Combine((Get-StationUpdateDirectory $lease),'helper.lock')
  if([IO.File]::Exists($path)){Assert-StationPrivateAcl $path}
  $probe=[IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
  $source=Get-StationHostPayloadIdentity $operation.source_folder $operation.source_hash
  $probe.Dispose();$probe=$null
  $powershell=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'WindowsPowerShell\v1.0\powershell.exe'
  $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$powershell;$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.WorkingDirectory=$source.Folder
  $info.Arguments='-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "'+(Join-Path $source.Folder 'Apply-Update.ps1')+'"'
  $process=(Start-StationUpdateChild $info);$process.Dispose()
 }finally{if($null -ne $probe){$probe.Dispose()};$lease.Stream.Dispose()}
}
Export-ModuleMember -Function Resume-StationAutomaticUpdate
