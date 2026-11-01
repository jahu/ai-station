# Native installation orchestration. Not an HTTP/tool/agent execution surface.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
foreach ($name in @('InstallState','InstallFiles','NativeWsl','PrivateStore','GuestManifest','GuestUpdate','DesktopPort','DesktopProcess')) { Import-Module (Join-Path $PSScriptRoot ($name+'.psm1')) }

function Read-StationPublishedManifest {
    param([string]$PackageFolder)
    Assert-StationNoReparsePath $PackageFolder
    $path=[IO.Path]::Combine($PackageFolder,'windows-guest-manifest.json')
    Assert-StationNoReparsePath $path
    if ([IO.FileInfo]::new($path).Length -gt 16384) { throw 'The guest manifest exceeds its expected size.' }
    $manifest=[IO.File]::ReadAllText($path,[Text.UTF8Encoding]::new($false,$true)) | ConvertFrom-Json -ErrorAction Stop
    Assert-StationGuestManifest $manifest
    return $manifest
}

function Read-StationInstallRecord {
    param($Lease)
    $record=Read-StationStateFile $Lease
    if ($null -eq $record) { return $null }
    if ($record.RecordSchema -ne 1 -or (($record.PSObject.Properties.Name | Sort-Object) -join '|') -cne 'Manifest|RecordSchema|State') { throw 'The private installation receipt is invalid.' }
    Assert-StationInstallState $record.State $Lease.Root
    Assert-StationGuestManifest $record.Manifest
    if ($record.State.PackageSha256 -cne $record.Manifest.package_sha256) { throw 'The saved package identities disagree.' }
    return $record
}

function Start-StationWslProcess {
    param([string]$Executable,[string[]]$Arguments,[string]$Directory,[switch]$KeepInput)
    # Only callers inside this module provide the typed planner's fixed operations.
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$Executable; $info.Arguments=Format-StationWslArguments $Arguments; $info.WorkingDirectory=$Directory
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false,$true)
    $info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false,$true)
    $info.EnvironmentVariables['WSLENV']='' # Do not carry Windows secrets or shell/loader overrides into the guest.
    $process=[Diagnostics.Process]::Start($info)
    if (-not $KeepInput) { $process.StandardInput.Close() } # Only the fixed offline update receives bytes.
    return $process
}

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
    param($Lease,$Record,$Manifest,[string]$PackageFolder,[string]$Executable,[Threading.CancellationToken]$CancellationToken)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationNoReparsePath $Record.State.Directory
    $inventory=@(Get-StationWslRegistrations)
    $ownership=Get-StationImportPlan $Record.State $Lease.Root ([IO.Path]::Combine($PackageFolder,'ai-station-wsl-rootfs.tar.gz')) -Inventory $inventory -ExistingDisk $true
    if ($ownership.Kind -cne 'VerifyGuest' -or $Record.State.Phase -cne 'ready') { throw 'Inspect the existing installation before updating. No second import was started.' }
    $program=Read-StationGuestUpdateProgram
    $stable=Test-StationFixedGuestFile $Lease $Record $Executable '/var/lib/ai-station-updates/python/bin/python3' -ExecutableFile -RootUser
    $plan=Get-StationGuestUpdatePlan $Record.State $Lease.Root $Record.Manifest $Manifest $program -StablePython:$stable
    $packagePath=[IO.Path]::Combine($PackageFolder,'station.deb')
    Assert-StationNoReparsePath $packagePath
    $archive=Open-StationVerifiedArchive $packagePath $Manifest.package_sha256 $Manifest.package_bytes
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $process=Start-StationWslProcess $Executable $plan.Arguments $Lease.Root -KeepInput
        [void](Send-StationGuestUpdate $process $archive $plan.Header -CancellationToken $CancellationToken)
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
    param($Lease,$Record,[string]$Executable,[ValidateSet('/var/lib/ai-station-updates/python/bin/python3','/usr/lib/ai-station-wsl-update-pending.json')][string]$Path,[switch]$ExecutableFile,[switch]$RootUser)
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
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None,[switch]$AllowUpdate)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationWindowsHost
    Assert-StationWindowsPreparationReady
    $PackageFolder=ConvertTo-StationWindowsPath $PackageFolder
    $executable=Get-StationWslExecutable
    foreach ($probe in @('--version','--status')) {
        $CancellationToken.ThrowIfCancellationRequested()
        Wait-StationWslProcess (Start-StationWslProcess $executable @($probe) ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData))) -CancellationToken $CancellationToken
    }
    $manifest=Read-StationPublishedManifest $PackageFolder
    $lease=New-StationPrivateStore
    $archive=$null
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $record=Read-StationInstallRecord $lease
        if ($null -eq $record) {
            $record=[pscustomobject]@{RecordSchema=1;State=(New-StationInstallState $lease.Root $manifest.package_sha256);Manifest=$manifest}
        } elseif ($record.Manifest.rootfs_sha256 -cne $manifest.rootfs_sha256) {
            if (-not $AllowUpdate) { throw 'An update is available. Choose Update AI Station; saved work must be stopped normally first.' }
            $record=Invoke-StationGuestUpdate $lease $record $manifest $PackageFolder $executable $CancellationToken
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
        return [pscustomobject]@{Status='ready';Distribution=$record.State.Distribution;Root=$lease.Root}
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
        if ($Action -ieq 'start') {
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
            return ($body | ConvertTo-Json -Compress)
        }
        return $result
    } finally { $lease.Stream.Dispose() }
}

Export-ModuleMember -Function Invoke-StationSetup,Invoke-StationDesktop
