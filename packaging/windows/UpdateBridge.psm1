# Finite ordinary-guest transport owned by the native Windows supervisor.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
foreach($name in @('PrivateStore','InstallFiles','InstallState','NativeWsl','DesktopProcess','ReleaseChannel','NativeGuest')){Import-Module (Join-Path $PSScriptRoot ($name+'.psm1'))}

function Get-StationUpdateDirectory {
 param($Lease)
 Assert-StationPrivateAcl $Lease.Root
 $path=[IO.Path]::Combine($Lease.Root,'automatic-updates')
 Assert-StationNoReparsePath $path
 if(-not [IO.Directory]::Exists($path)){[void][IO.Directory]::CreateDirectory($path)}
 Assert-StationPrivateAcl $path
 return $path
}

function Read-StationUpdateObject {
 param($Lease,[ValidateSet('channel.json','operation.json')][string]$Name)
 Assert-StationPrivateAcl $Lease.Root
 $directory=[IO.Path]::Combine($Lease.Root,'automatic-updates')
 Assert-StationNoReparsePath $directory
 if(-not [IO.Directory]::Exists($directory)){return $null}
 Assert-StationPrivateAcl $directory
 $path=[IO.Path]::Combine($directory,$Name)
 if(-not [IO.File]::Exists($path)){return $null}
 Assert-StationPrivateAcl $path
 if([IO.FileInfo]::new($path).Length -gt 65536){throw 'The native update journal exceeds its bound.'}
 return ([IO.File]::ReadAllText($path,[Text.UTF8Encoding]::new($false,$true))|ConvertFrom-Json -ErrorAction Stop)
}

function Write-StationUpdateObject {
 param($Lease,[ValidateSet('channel.json','operation.json')][string]$Name,$Value)
 $directory=Get-StationUpdateDirectory $Lease
 $path=[IO.Path]::Combine($directory,$Name)
 if([IO.File]::Exists($path)){Assert-StationPrivateAcl $path}
 $temporary=[IO.Path]::Combine($directory,([Guid]::NewGuid().ToString('N')+'.partial'))
 $bytes=[Text.UTF8Encoding]::new($false,$true).GetBytes(($Value|ConvertTo-Json -Depth 12 -Compress))
 if($bytes.Length -gt 65536){throw 'The native update journal exceeds its bound.'}
 $stream=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
 try{
  Assert-StationPrivateAcl $temporary
  if([IO.File]::Exists($path)){[IO.File]::Replace($temporary,$path,[NullString]::Value)}else{[IO.File]::Move($temporary,$path)}
 }finally{if([IO.File]::Exists($temporary)){[IO.File]::Delete($temporary)}}
}

function Get-StationUpdateChannel {
 param($Lease)
 $record=Read-StationUpdateObject $Lease 'channel.json'
 if($null -eq $record){
  $record=[pscustomobject]@{schema=1;channel_id=[Guid]::NewGuid().ToString('D')}
  Write-StationUpdateObject $Lease 'channel.json' $record
 }
 $parsed=[Guid]::Empty
 if((@($record.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'channel_id|schema' -or $record.schema -ne 1 -or $record.channel_id -isnot [string] -or -not [Guid]::TryParseExact($record.channel_id,'D',[ref]$parsed) -or $parsed.ToString('D') -cne $record.channel_id){throw 'The Windows update installation identity needs inspection.'}
 return $record.channel_id
}

function Invoke-StationUpdateGuestControl {
 param($Lease,$Record,[ValidateSet('update-bind','update-poll','update-result','update-status','update-authorize')][string]$Action,$Body,[Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
 Assert-StationInstallState $Record.State $Lease.Root
 $bytes=[Text.UTF8Encoding]::new($false,$true).GetBytes(($Body|ConvertTo-Json -Depth 8 -Compress)+"`n")
 if($bytes.Length -gt 8192){throw 'The finite native update request exceeds its bound.'}
 $arguments=@('--distribution',$Record.State.Distribution,'--user','station','--exec','/usr/libexec/ai-station/wsl-control',$Action)
 $process=Start-StationWslProcess (Get-StationWslExecutable) $arguments $Lease.Root -KeepInput
 $deadline=[Threading.CancellationTokenSource]::CreateLinkedTokenSource($CancellationToken);$deadline.CancelAfter([TimeSpan]::FromSeconds(30))
 $waiting=$false
 try{
  $transfer=$process.StandardInput.BaseStream.WriteAsync($bytes,0,$bytes.Length,$deadline.Token)
  while(-not $transfer.IsCompleted){$deadline.Token.ThrowIfCancellationRequested();[Threading.Thread]::Sleep(25)}
  [void]$transfer.GetAwaiter().GetResult();$process.StandardInput.Close()
  $waiting=$true # The shared waiter owns cleanup from this boundary, including errors.
  $response=Wait-StationWslProcess $process -KeepOutput $true -CancellationToken $deadline.Token
  $process=$null
  if($response.Length -gt 8192){throw 'The native guest update reply exceeds its bound.'}
  return ($response|ConvertFrom-Json -ErrorAction Stop)
 }finally{
  if(-not $waiting -and $null -ne $process){try{if(-not $process.HasExited){$process.Kill();[void]$process.WaitForExit(10000)}}finally{$process.Dispose()}}
  $deadline.Dispose()
 }
}

function Connect-StationUpdateOwner {
 param($Lease,$Record,[string]$PackageFolder,[Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
 $manifest=Read-StationPublishedManifest $PackageFolder
 # Preview/legacy payloads keep their existing manual setup path.
 if($manifest.package.Version -cnotmatch '\A(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){2}\z'){return $false}
 $description=Wait-StationWslProcess (Start-StationWslProcess (Get-StationWslExecutable) @('--distribution',$Record.State.Distribution,'--user','station','--exec','/usr/libexec/ai-station/wsl-control','describe') $Lease.Root) -KeepOutput $true -CancellationToken $CancellationToken
 $guest=$description|ConvertFrom-Json -ErrorAction Stop
 if($guest.PSObject.Properties.Name -notcontains 'windows_update_protocol' -or $guest.windows_update_protocol -ne 1){return $false}
 $hostReceipt=[IO.Path]::Combine($PackageFolder,'windows-host-manifest.json')
 Assert-StationNoReparsePath $hostReceipt
 $hash=(Get-FileHash -LiteralPath $hostReceipt -Algorithm SHA256).Hash.ToLowerInvariant()
 $body=[pscustomobject]@{schema=1;channel_id=(Get-StationUpdateChannel $Lease);host_manifest_sha256=$hash;version=$manifest.package.Version}
 $result=Invoke-StationUpdateGuestControl $Lease $Record 'update-bind' $body -CancellationToken $CancellationToken
 if($result.channel_id -cne $body.channel_id -or $result.version -cne $body.version){throw 'The native update owner did not confirm its exact installation.'}
 return $true
}

Export-ModuleMember -Function Get-StationUpdateDirectory,Read-StationUpdateObject,Write-StationUpdateObject,Get-StationUpdateChannel,Invoke-StationUpdateGuestControl,Connect-StationUpdateOwner

function Assert-StationUpdateRequest {
 param($Pending,[string]$ChannelId)
 $id=[Guid]::Empty
 if($Pending.run_id -isnot [string] -or -not [Guid]::TryParseExact($Pending.run_id,'D',[ref]$id) -or $id.ToString('D') -cne $Pending.run_id){throw 'The native update has no canonical original Run.'}
 $request=$Pending.request
 if((@($request.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'current_version|fingerprint|platform|release_id' -or $request.platform -cne 'windows-x64' -or $request.fingerprint -isnot [string] -or $request.fingerprint -cnotmatch '\A[a-f0-9]{64}\z' -or ($request.release_id -isnot [int] -and $request.release_id -isnot [long]) -or $request.release_id -le 0){throw 'The native update request is not an approved Windows release.'}
 [void](ConvertTo-StationStableVersion $request.current_version)
 if($ChannelId -cnotmatch '\A[a-f0-9-]{36}\z'){throw 'The Windows update channel is invalid.'}
}

function Receive-StationUpdateStream {
 param([IO.Stream]$Source,[IO.Stream]$Destination,$Pending,[string]$ChannelId,$Offer,[Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
 Assert-StationUpdateRequest $Pending $ChannelId
 # Do not mix StreamReader with BaseStream: text prefetch could eat EXE bytes.
 $frame=[IO.MemoryStream]::new();$one=[byte[]]::new(1);$hash=[Security.Cryptography.SHA256]::Create()
 try{
  while($true){
   $task=$Source.ReadAsync($one,0,1,$CancellationToken)
   Wait-StationUpdateTransfer $task $CancellationToken
   if($task.GetAwaiter().GetResult() -ne 1){throw 'The Windows package header was incomplete.'}
   if($one[0] -eq 10){break}
   if($frame.Length -ge 8191){throw 'The Windows package header exceeds its bound.'}
   $frame.WriteByte($one[0])
  }
  $header=[Text.UTF8Encoding]::new($false,$true).GetString($frame.ToArray())|ConvertFrom-Json -ErrorAction Stop
  if((@($header.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'channel_id|request|run_id|target' -or $header.channel_id -cne $ChannelId -or $header.run_id -cne $Pending.run_id){throw 'The streamed package belongs to another Windows update.'}
  foreach($key in @('release_id','fingerprint','platform','current_version')){if($header.request.$key -cne $Pending.request.$key){throw 'The streamed package changed its approved request.'}}
  if((@($header.request.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'current_version|fingerprint|platform|release_id' -or (@($header.target.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'asset_id|installer_bytes|installer_sha256|version' -or $header.target.version -cne $Offer.Version -or $header.target.asset_id -ne $Offer.Package.id -or $header.target.installer_bytes -ne $Offer.Package.size_bytes -or $header.target.installer_sha256 -cne $Offer.Package.sha256){throw 'The streamed package differs from the independent official release observation.'}
  $buffer=[byte[]]::new(65536);[long]$count=0
  while($true){
   $task=$Source.ReadAsync($buffer,0,$buffer.Length,$CancellationToken)
   Wait-StationUpdateTransfer $task $CancellationToken
   $length=$task.GetAwaiter().GetResult();if($length -eq 0){break}
   $count+=$length
   if($count -gt $Offer.Package.size_bytes){throw 'The Windows package exceeds its approved size.'}
   [void]$hash.TransformBlock($buffer,0,$length,$buffer,0)
   $Destination.Write($buffer,0,$length)
  }
  [void]$hash.TransformFinalBlock([byte[]]::new(0),0,0)
  $digest=[BitConverter]::ToString($hash.Hash).Replace('-','').ToLowerInvariant()
  if($count -ne $Offer.Package.size_bytes -or $digest -cne $Offer.Package.sha256){throw 'The Windows package did not match its approved byte count and SHA256.'}
  return $header.target
 }finally{$frame.Dispose();$hash.Dispose()}
}

function Wait-StationUpdateTransfer {
 param([Threading.Tasks.Task]$Task,[Threading.CancellationToken]$CancellationToken)
 while(-not $Task.IsCompleted){$CancellationToken.ThrowIfCancellationRequested();[Threading.Thread]::Sleep(25)}
 $CancellationToken.ThrowIfCancellationRequested()
 [void]$Task.GetAwaiter().GetResult()
}

function Receive-StationWindowsPackage {
 param($Lease,$Record,$Pending,[string]$ChannelId,$Offer)
 $directory=Get-StationUpdateDirectory $Lease
 $path=[IO.Path]::Combine($directory,($Pending.run_id+'.exe'))
 if([IO.File]::Exists($path)){
  Assert-StationPrivateAcl $path
  $verified=Open-StationVerifiedArchive $path $Offer.Package.sha256 $Offer.Package.size_bytes
  $verified.Stream.Dispose();return $path
 }
 if([IO.DriveInfo]::new([IO.Path]::GetPathRoot($directory)).AvailableFreeSpace -lt $Offer.Package.size_bytes+268435456){throw 'Free more Windows disk space before installing this update.'}
 $partial=$path+'.'+[Guid]::NewGuid().ToString('N')+'.partial'
 $deadline=[Threading.CancellationTokenSource]::new();$deadline.CancelAfter([TimeSpan]::FromMinutes(15))
 $process=$null;$output=$null;$errors=$null;$errorText=''
 try{
  $process=Start-StationWslProcess (Get-StationWslExecutable) @('--distribution',$Record.State.Distribution,'--user','station','--exec','/usr/libexec/ai-station/wsl-control','update-export') $Lease.Root -KeepInput
  $errors=$process.StandardError.ReadToEndAsync()
  $bytes=[Text.UTF8Encoding]::new($false).GetBytes((@{channel_id=$ChannelId;run_id=$Pending.run_id}|ConvertTo-Json -Compress)+"`n")
  $transfer=$process.StandardInput.BaseStream.WriteAsync($bytes,0,$bytes.Length,$deadline.Token)
  Wait-StationUpdateTransfer $transfer $deadline.Token
  $process.StandardInput.Close()
  $output=[IO.File]::Open($partial,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  [void](Receive-StationUpdateStream $process.StandardOutput.BaseStream $output $Pending $ChannelId $Offer $deadline.Token)
  $output.Flush($true);$output.Dispose();$output=$null
  while(-not $process.WaitForExit(100)){$deadline.Token.ThrowIfCancellationRequested()}
  [void]$errors.GetAwaiter().GetResult()
  if($process.ExitCode -ne 0){throw 'The owned guest did not finish the verified package transfer.'}
  Assert-StationPrivateAcl $partial
  [IO.File]::Move($partial,$path)
  return $path
 }finally{
  if($null -ne $output){$output.Dispose()}
  if($null -ne $process){try{if(-not $process.HasExited){$process.Kill();[void]$process.WaitForExit(10000)}}finally{$process.Dispose()}}
  $deadline.Dispose()
  if([IO.File]::Exists($partial)){[IO.File]::Delete($partial)}
 }
}

Export-ModuleMember -Function Assert-StationUpdateRequest,Receive-StationUpdateStream,Receive-StationWindowsPackage
