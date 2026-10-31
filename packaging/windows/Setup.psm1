# Native installation orchestration. Not an HTTP/tool/agent execution surface.
Set-StrictMode -Version 2.0
foreach ($name in @('InstallState','InstallFiles','NativeWsl','PrivateStore','GuestManifest','DesktopPort','DesktopProcess')) { Import-Module (Join-Path $PSScriptRoot ($name+'.psm1')) }

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
    param([string]$Executable,[string[]]$Arguments,[string]$Directory)
    # Only callers inside this module provide the typed planner's fixed operations.
    $quoted=@()
    foreach ($value in $Arguments) {
        if ($value -match '["\x00-\x1f]' -or $value.EndsWith('\')) { throw 'Invalid argument in the fixed WSL operation.' }
        $quoted+=('"'+$value+'"')
    }
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$Executable; $info.Arguments=($quoted -join ' '); $info.WorkingDirectory=$Directory
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $info.StandardOutputEncoding=[Text.UTF8Encoding]::new($false,$true)
    $info.StandardErrorEncoding=[Text.UTF8Encoding]::new($false,$true)
    $info.EnvironmentVariables['WSLENV']='' # Do not carry Windows secrets or shell/loader overrides into the guest.
    $process=[Diagnostics.Process]::Start($info)
    $process.StandardInput.Close() # Missing prerequisites cannot obtain implicit terminal consent.
    return $process
}

function Confirm-StationGuest {
    param($Lease,$Record,[string]$Executable,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationNoReparsePath $Record.State.Directory
    $inventory=@(Get-StationWslRegistrations)
    $plan=Get-StationImportPlan $Record.State $Lease.Root ([IO.Path]::Combine($Lease.Root,'accepted-rootfs.tar.gz')) -Inventory $inventory
    if ($plan.Kind -cne 'VerifyGuest') { throw 'The private guest is not registered yet. Existing setup and files were preserved.' }
    $text=Wait-StationWslProcess (Start-StationWslProcess $Executable $plan.Arguments $Lease.Root) -KeepOutput $true -CancellationToken $CancellationToken
    $guest=$text | ConvertFrom-Json -ErrorAction Stop
    Assert-StationImportedGuest $Record.Manifest $guest
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

function Invoke-StationSetup {
    param([Parameter(Mandatory=$true)][string]$PackageFolder,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
    $CancellationToken.ThrowIfCancellationRequested()
    Assert-StationWindowsHost
    $PackageFolder=ConvertTo-StationWindowsPath $PackageFolder
    $executable=Get-StationWslExecutable
    foreach ($probe in @('--version','--status')) {
        $CancellationToken.ThrowIfCancellationRequested()
        Wait-StationWslProcess (Start-StationWslProcess $executable @($probe) ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData))) -CancellationToken $CancellationToken
    }
    Assert-StationNoReparsePath $PackageFolder
    $manifestPath=[IO.Path]::Combine($PackageFolder,'windows-guest-manifest.json')
    Assert-StationNoReparsePath $manifestPath
    if ([IO.FileInfo]::new($manifestPath).Length -gt 16384) { throw 'The guest manifest exceeds its expected size.' }
    $manifest=[IO.File]::ReadAllText($manifestPath,[Text.UTF8Encoding]::new($false,$true)) | ConvertFrom-Json -ErrorAction Stop
    Assert-StationGuestManifest $manifest
    $lease=New-StationPrivateStore
    $archive=$null
    try {
        $CancellationToken.ThrowIfCancellationRequested()
        $record=Read-StationInstallRecord $lease
        if ($null -eq $record) {
            $record=[pscustomobject]@{RecordSchema=1;State=(New-StationInstallState $lease.Root $manifest.package_sha256);Manifest=$manifest}
        } elseif ($record.Manifest.rootfs_sha256 -cne $manifest.rootfs_sha256) {
            throw 'A previous application version and its data are retained. Use the reviewed update flow rather than importing over it.'
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
    param([Parameter(Mandatory=$true)][ValidateSet('start','status','open','stop')][string]$Action)
    Assert-StationWindowsHost
    $executable=Get-StationWslExecutable
    $lease=New-StationPrivateStore
    try {
        $record=Read-StationInstallRecord $lease
        if ($null -eq $record) { throw 'Prepare this private installation before starting AI Station.' }
        Confirm-StationGuest $lease $record $executable
        if ($Action -ieq 'start') {
            $statusArgs=Get-StationLifecyclePlan $record.State $lease.Root 'status'
            $status=(Wait-StationWslProcess (Start-StationWslProcess $executable $statusArgs $lease.Root) -KeepOutput $true) | ConvertFrom-Json -ErrorAction Stop
            if ($status.running -isnot [bool]) { throw 'The guest returned an invalid lifecycle status.' }
            if ($status.running) { $arguments=Get-StationLifecyclePlan $record.State $lease.Root 'open' }
            else { $arguments=Get-StationLifecyclePlan $record.State $lease.Root 'start' -Port (Get-StationAvailablePort) }
        } else { $arguments=Get-StationLifecyclePlan $record.State $lease.Root $Action }
        $process=Start-StationWslProcess $executable $arguments $lease.Root
        if ($Action -ieq 'start') { return $process } # Native owner consumes its private pipe until Stop.
        return (Wait-StationWslProcess $process -KeepOutput $true)
    } finally { $lease.Stream.Dispose() }
}

Export-ModuleMember -Function Invoke-StationSetup,Invoke-StationDesktop
