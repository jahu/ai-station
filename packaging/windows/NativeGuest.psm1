# Shared fixed guest transport and publisher receipts; no caller-selected shell.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
foreach($name in @('InstallState','InstallFiles','PrivateStore','GuestManifest','NativeWsl')){Import-Module (Join-Path $PSScriptRoot ($name+'.psm1'))}

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

Export-ModuleMember -Function Read-StationPublishedManifest,Read-StationInstallRecord,Start-StationWslProcess
