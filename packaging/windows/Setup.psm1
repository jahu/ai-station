# Native installation orchestration. Not an HTTP/tool/agent execution surface.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
foreach ($name in @('InstallState','InstallFiles','NativeWsl','PrivateStore','GuestManifest','GuestUpdate','DesktopPort','DesktopProcess','NativeGuest','UpdateBridge')) { Import-Module (Join-Path $PSScriptRoot ($name+'.psm1')) }

function Confirm-StationGuest {
    param($Lease,$Record,[string]$Executable,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None,$AlternativeManifest=$null)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationNoReparsePath $Record.State.Directory
    $inventory=@(Get-StationWslRegistrations)
    $plan=Get-StationImportPlan $Record.State $Lease.Root ([IO.Path]::Combine($Lease.Root,'accepted-rootfs.tar.gz')) -Inventory $inventory
    if ($plan.Kind -cne 'VerifyGuest') { throw 'The private guest is not registered yet. Existing setup and files were preserved.' }
    $text=Wait-StationWslProcess (Start-StationWslProcess $Executable $plan.Arguments $Lease.Root) -KeepOutput $true -CancellationToken $CancellationToken
    $guest=$text | ConvertFrom-Json -ErrorAction Stop
    if ($null -ne $AlternativeManifest) {
        Assert-StationUpdateRecipe $Record.Manifest $AlternativeManifest
        try { Assert-StationImportedGuest $Record.Manifest $guest }
        catch { Assert-StationImportedGuest $AlternativeManifest $guest }
    } else { Assert-StationImportedGuest $Record.Manifest $guest }
    $description=Wait-StationWslProcess (Start-StationWslProcess $Executable @('--distribution',$Record.State.Distribution,'--user','station','--exec','/usr/libexec/ai-station/wsl-control','describe') $Lease.Root) -KeepOutput $true -CancellationToken $CancellationToken
    $capabilities=$description | ConvertFrom-Json -ErrorAction Stop
    if ($capabilities.desktop_protocol -ne 2) { throw 'This guest does not support browser identity and Windows port selection.' }
    $after=@(Get-StationWslRegistrations)
    [void](Get-StationImportPlan $Record.State $Lease.Root ([IO.Path]::Combine($Lease.Root,'accepted-rootfs.tar.gz')) -Inventory $after)
    $before=@($inventory | Where-Object { $_.DistributionName -ieq $Record.State.Distribution })
    $current=@($after | Where-Object { $_.DistributionName -ieq $Record.State.Distribution })
    if ($before.Count -ne 1 -or $current.Count -ne 1 -or $before[0].Id -ine $current[0].Id) { throw 'The guest registration changed during verification. Nothing was adopted.' }
    $CancellationToken.ThrowIfCancellationRequested()
    if ($Record.State.RegistrationId -ine $current[0].Id -or $Record.State.Phase -cne 'ready') {
        $Record.State.RegistrationId=$current[0].Id; $Record.State.Phase='ready'
        Write-StationStateFile $Lease $Record
    }
}

function Read-StationGuestUpdateProgram {
    $programPath=Join-Path $PSScriptRoot 'guest_update.py'
    $publisherPath=Join-Path $PSScriptRoot 'windows-host-manifest.json'
    Assert-StationNoReparsePath $programPath
    Assert-StationNoReparsePath $publisherPath
    if ([IO.FileInfo]::new($publisherPath).Length -gt 65536 -or [IO.FileInfo]::new($programPath).Length -gt 65536) { throw 'The fixed update source receipt exceeds its limit.' }
    $publisher=[IO.File]::ReadAllText($publisherPath,[Text.UTF8Encoding]::new($false,$true)) | ConvertFrom-Json -ErrorAction Stop
    if ($publisher.schema -ne 1 -or $publisher.files.'guest_update.py' -cnotmatch '^[a-f0-9]{64}$') { throw 'The native update source lacks its publisher identity.' }
    $program=[IO.File]::ReadAllBytes($programPath)
    $hasher=[Security.Cryptography.SHA256]::Create()
    try { $actual=[BitConverter]::ToString($hasher.ComputeHash($program)).Replace('-','').ToLowerInvariant() } finally { $hasher.Dispose() }
    if ($actual -cne $publisher.files.'guest_update.py') { throw 'The installed update source changed. Reinstall this application version.' }
    return ,$program
}

function Invoke-StationGuestUpdate {
    param($Lease,$Record,$Manifest,[string]$PackageFolder,[string]$Executable,[Threading.CancellationToken]$CancellationToken,$AutomaticUpdate=$null,[ref]$UpdateOutcome)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationNoReparsePath $Record.State.Directory
    $inventory=@(Get-StationWslRegistrations)
    $ownership=Get-StationImportPlan $Record.State $Lease.Root ([IO.Path]::Combine($PackageFolder,'ai-station-wsl-rootfs.tar.gz')) -Inventory $inventory -ExistingDisk $true
    if ($ownership.Kind -cne 'VerifyGuest' -or $Record.State.Phase -cne 'ready') { throw 'Inspect the existing installation before updating. No second import was started.' }
    $program=Read-StationGuestUpdateProgram
    $stable=Test-StationFixedGuestFile $Lease $Record $Executable '/var/lib/ai-station-updates/python/bin/python3' -ExecutableFile -RootUser
    $plan=Get-StationGuestUpdatePlan $Record.State $Lease.Root $Record.Manifest $Manifest $program -StablePython:$stable -AutomaticUpdate $AutomaticUpdate
    $packagePath=[IO.Path]::Combine($PackageFolder,'station.deb')
    Assert-StationNoReparsePath $packagePath
    $archive=Open-StationVerifiedArchive $packagePath $Manifest.package_sha256 $Manifest.package_bytes
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $process=Start-StationWslProcess $Executable $plan.Arguments $Lease.Root -KeepInput
        $proof=Send-StationGuestUpdate $process $archive $plan.Header -CancellationToken $CancellationToken
        if($null -ne $UpdateOutcome){$UpdateOutcome.Value=$proof}
        $CancellationToken.ThrowIfCancellationRequested()
        $candidate=$Record | ConvertTo-Json -Depth 8 | ConvertFrom-Json
        $candidate.Manifest=$Manifest
        $candidate.State.PackageSha256=$Manifest.package_sha256
        # This verifies registry ownership and the exact target receipt/protocol
        # before the old Windows receipt is replaced. Lost acknowledgements resume
        # the same old/target pair; they never import or recreate the distribution.
        Confirm-StationGuest $Lease $candidate $Executable -CancellationToken $CancellationToken
        Write-StationStateFile $Lease $candidate
        return $candidate
    } finally { $archive.Stream.Dispose() }
}

function Test-StationFixedGuestFile {
    param($Lease,$Record,[string]$Executable,[ValidateSet('/var/lib/ai-station-updates/python/bin/python3','/usr/lib/ai-station-wsl-update-pending.json','/usr/lib/ai-station/host-runner/ai_station_runner/windows_storage.py')][string]$Path,[switch]$ExecutableFile,[switch]$RootUser)
    $arguments=@('--distribution',$Record.State.Distribution,'--user',$(if($RootUser){'root'}else{'station'}),'--exec','/usr/bin/test',$(if($ExecutableFile){'-x'}else{'-e'}),$Path)
    $process=Start-StationWslProcess $Executable $arguments $Lease.Root
    try {
        $output=$process.StandardOutput.ReadToEndAsync();$errors=$process.StandardError.ReadToEndAsync()
        if(-not $process.WaitForExit(60000)){
            $process.Kill()
            if(-not $process.WaitForExit(10000)){throw 'The owned inspection client is still stopping; inspect this installation.'}
            throw 'The guest filesystem inspection did not finish; no update was started.'
        }
        [void]$output.GetAwaiter().GetResult();[void]$errors.GetAwaiter().GetResult()
        if($process.ExitCode -notin @(0,1)){throw 'The guest filesystem state requires inspection.'}
        return $process.ExitCode -eq 0
    } finally {$process.Dispose()}
}

function Test-StationGuestUpdatePending {
    param($Lease,$Record,[string]$Executable)
    return Test-StationFixedGuestFile $Lease $Record $Executable '/usr/lib/ai-station-wsl-update-pending.json'
}

function Invoke-StationSetup {
    param([Parameter(Mandatory=$true)][string]$PackageFolder,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None,[switch]$AllowUpdate,$AutomaticUpdate=$null,$OriginalUpdateRecord=$null)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationWindowsHost
    Assert-StationWindowsPreparationReady
    $PackageFolder=ConvertTo-StationWindowsPath $PackageFolder
    $executable=Get-StationWslExecutable
    $CancellationToken.ThrowIfCancellationRequested()
    try {
        $version=Wait-StationWslProcess (Start-StationWslProcess $executable @('--version') ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData))) -KeepOutput $true -CancellationToken $CancellationToken
    } catch {
        $CancellationToken.ThrowIfCancellationRequested()
        # Legacy inbox WSL lacks --version. Its raw localized output may contain
        # private paths; show fixed upgrade guidance before reserving any guest.
        $failure=New-StationWslUpdateRequired
        $failure.Data['AIStationWslAction']='install'
        throw $failure
    }
    Assert-StationWslVersion $version
    Wait-StationWslProcess (Start-StationWslProcess $executable @('--status') ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData))) -CancellationToken $CancellationToken
    $manifest=Read-StationPublishedManifest $PackageFolder
    $lease=New-StationPrivateStore
    $archive=$null;$updateProof=$null
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $record=Read-StationInstallRecord $lease
        if($null -ne $OriginalUpdateRecord){
            if($null -eq $AutomaticUpdate -or -not $AllowUpdate -or $null -eq $record){throw 'The original automatic update requires its existing installation.'}
            Assert-StationInstallState $OriginalUpdateRecord.State $lease.Root
            Assert-StationGuestManifest $OriginalUpdateRecord.Manifest
            if($OriginalUpdateRecord.RecordSchema -ne 1 -or $OriginalUpdateRecord.State.PackageSha256 -cne $OriginalUpdateRecord.Manifest.package_sha256 -or $record.State.InstallId -cne $OriginalUpdateRecord.State.InstallId -or $record.State.RegistrationId -ine $OriginalUpdateRecord.State.RegistrationId -or $record.State.Directory -ine $OriginalUpdateRecord.State.Directory -or $record.State.Distribution -cne $OriginalUpdateRecord.State.Distribution -or $record.Manifest.package_sha256 -cnotin @($OriginalUpdateRecord.Manifest.package_sha256,$manifest.package_sha256)){throw 'The original automatic installation identity changed.'}
            $record=Invoke-StationGuestUpdate $lease $OriginalUpdateRecord $manifest $PackageFolder $executable $CancellationToken -AutomaticUpdate $AutomaticUpdate -UpdateOutcome ([ref]$updateProof)
        } elseif ($null -eq $record) {
            $record=[pscustomobject]@{RecordSchema=1;State=(New-StationInstallState $lease.Root $manifest.package_sha256);Manifest=$manifest}
        } elseif ($record.Manifest.rootfs_sha256 -cne $manifest.rootfs_sha256) {
            if (-not $AllowUpdate) { throw 'An update is available. Choose Update AI Station; saved work must be stopped normally first.' }
            $record=Invoke-StationGuestUpdate $lease $record $manifest $PackageFolder $executable $CancellationToken -AutomaticUpdate $AutomaticUpdate -UpdateOutcome ([ref]$updateProof)
        }
        Assert-StationNoReparsePath $record.State.Directory
        $plan=Get-StationImportPlan $record.State $lease.Root ([IO.Path]::Combine($PackageFolder,'ai-station-wsl-rootfs.tar.gz')) -Inventory @(Get-StationWslRegistrations) -ExistingDisk ([IO.Directory]::Exists($record.State.Directory))
        if ($plan.Kind -in @('InspectIncompleteDisk','InspectImport')) { throw 'An interrupted import needs inspection. Its files were preserved and no second import was started.' }
        if ($plan.Kind -ceq 'Import') {
            $archive=Open-StationVerifiedArchive $plan.Arguments[3] $record.Manifest.rootfs_sha256 $record.Manifest.rootfs_bytes
            $CancellationToken.ThrowIfCancellationRequested()
            Write-StationStateFile $lease $record
            $record.State.Phase='importing';Write-StationStateFile $lease $record
            if ($CancellationToken.IsCancellationRequested) {
                # No import client has been launched: this known boundary is
                # resumable, unlike cancellation after WSL accepted the request.
                $record.State.Phase='reserved';Write-StationStateFile $lease $record
                $CancellationToken.ThrowIfCancellationRequested()
            }
            Wait-StationWslProcess (Start-StationWslProcess $executable $plan.Arguments $lease.Root) -CancellationToken $CancellationToken
        }
        Confirm-StationGuest $lease $record $executable -CancellationToken $CancellationToken
        return [pscustomobject]@{Status='ready';Distribution=$record.State.Distribution;Root=$lease.Root;UpdateProof=$updateProof}
    } finally { if ($null -ne $archive) { $archive.Stream.Dispose() }; $lease.Stream.Dispose() }
}

function Invoke-StationDesktop {
    param([Parameter(Mandatory=$true)][ValidateSet('start','status','open','stop')][string]$Action,[string]$PackageFolder=$PSScriptRoot)
    Assert-StationWindowsHost
    $executable=Get-StationWslExecutable
    $lease=New-StationPrivateStore
    try {
        $record=Read-StationInstallRecord $lease
        if ($null -eq $record) { throw 'Prepare this private installation before starting AI Station.' }
        $manifest=Read-StationPublishedManifest (ConvertTo-StationWindowsPath $PackageFolder)
        $update=$record.Manifest.rootfs_sha256 -cne $manifest.rootfs_sha256
        Confirm-StationGuest $lease $record $executable -AlternativeManifest $(if ($update) {$manifest} else {$null})
        $pending=Test-StationGuestUpdatePending $lease $record $executable
        if ($Action -ieq 'start' -and $pending) { throw 'Finish or inspect the pending application update before starting. Status and Stop remain available.' }
        $storageReady=$false
        if ($Action -in @('start','status') -and -not $pending) {
            # This ordinary-user, fixed helper accepts only numeric byte counts.
            # Old guests without it retain their old behavior until updated.
            # Opening the app to free space and lifecycle inspection must remain
            # available. Guest download admission rejects unsafe/stale reports.
            try { $storageReady=[bool](Update-StationPhysicalStorage $lease $record $executable) } catch { $storageReady=$false }
        }
        if ($Action -ieq 'start') {
            if(-not $update -and $manifest.package.Version -cmatch '\A(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){2}\z'){[void](Connect-StationUpdateOwner $lease $record (ConvertTo-StationWindowsPath $PackageFolder))}
            $statusArgs=Get-StationLifecyclePlan $record.State $lease.Root 'status'
            $status=(Wait-StationWslProcess (Start-StationWslProcess $executable $statusArgs $lease.Root) -KeepOutput $true) | ConvertFrom-Json -ErrorAction Stop
            if ($status.running -isnot [bool]) { throw 'The guest returned an invalid lifecycle status.' }
            if ($status.running) { $arguments=Get-StationLifecyclePlan $record.State $lease.Root 'open' }
            else { $arguments=Get-StationLifecyclePlan $record.State $lease.Root 'start' -Port (Get-StationAvailablePort) }
        } else { $arguments=Get-StationLifecyclePlan $record.State $lease.Root $Action }
        $process=Start-StationWslProcess $executable $arguments $lease.Root
        if ($Action -ieq 'start') { return $process } # Native owner consumes its private pipe until Stop.
        $result=Wait-StationWslProcess $process -KeepOutput $true
        if ($Action -ieq 'status') {
            $body=$result | ConvertFrom-Json -ErrorAction Stop
            $body | Add-Member -NotePropertyName 'update_available' -NotePropertyValue $update
            $body | Add-Member -NotePropertyName 'update_pending' -NotePropertyValue $pending
            $body | Add-Member -NotePropertyName 'physical_storage_available' -NotePropertyValue $storageReady
            if($body.running -and -not $update -and -not $pending -and $manifest.package.Version -cmatch '\A(0|[1-9][0-9]{0,4})(\.(0|[1-9][0-9]{0,4})){2}\z'){
                if(Connect-StationUpdateOwner $lease $record (ConvertTo-StationWindowsPath $PackageFolder)){
                    $polled=Invoke-StationUpdateGuestControl $lease $record 'update-poll' ([pscustomobject]@{channel_id=(Get-StationUpdateChannel $lease)})
                    if($null -ne $polled.pending -and $polled.pending.phase -ceq 'apply_requested'){
                        Import-Module (Join-Path $PSScriptRoot 'AutomaticUpdate.psm1')
                        [void](Start-StationAutomaticUpdate $lease $record $polled.pending (ConvertTo-StationWindowsPath $PackageFolder))
                    }
                }
            }
            return ($body | ConvertTo-Json -Compress)
        }
        return $result
    } finally { $lease.Stream.Dispose() }
}

function Get-StationPhysicalVolume {
    param([string]$Directory)
    Assert-StationNoReparsePath $Directory
    $drive=[IO.DriveInfo]::new([IO.Path]::GetPathRoot($Directory))
    if (-not $drive.IsReady -or $drive.DriveFormat -ine 'NTFS') { throw 'Inspect the Windows volume containing this private guest.' }
    $total=$drive.TotalSize;$free=$drive.AvailableFreeSpace
    if ($total -le 0 -or $total -gt [long]1152921504606846976 -or $free -lt 0 -or $free -gt $total) { throw 'Windows returned an invalid physical volume capacity.' }
    return [pscustomobject]@{Total=$total;Free=$free}
}

function Update-StationPhysicalStorage {
    param($Lease,$Record,[string]$Executable)
    $helper='/usr/lib/ai-station/host-runner/ai_station_runner/windows_storage.py'
    if (-not (Test-StationFixedGuestFile $Lease $Record $Executable $helper)) { return $false }
    $volume=Get-StationPhysicalVolume $Record.State.Directory
    $arguments=@('--distribution',$Record.State.Distribution,'--user','station','--exec','/usr/lib/ai-station/python/bin/python3','-IBS',$helper,$volume.Total.ToString([Globalization.CultureInfo]::InvariantCulture),$volume.Free.ToString([Globalization.CultureInfo]::InvariantCulture))
    $deadline=[Threading.CancellationTokenSource]::new();$deadline.CancelAfter(5000)
    try {
        $result=Wait-StationWslProcess (Start-StationWslProcess $Executable $arguments $Lease.Root) -KeepOutput $true -CancellationToken $deadline.Token
        $body=$result|ConvertFrom-Json -ErrorAction Stop
        if (($body.PSObject.Properties.Name -join '|') -cne 'status' -or $body.status -cne 'observed') { throw 'Refresh the Windows disk observation before downloading models.' }
        return $true
    } finally { $deadline.Dispose() }
}

Export-ModuleMember -Function Invoke-StationSetup,Invoke-StationDesktop
