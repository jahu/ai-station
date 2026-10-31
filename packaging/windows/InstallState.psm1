# Pure Windows installation ownership/command planning. No OS operations on import.
Set-StrictMode -Version 2.0

function ConvertTo-StationWindowsPath {
    param([Parameter(Mandatory=$true)][string]$Path)
    $value = $Path.Replace('/', '\').TrimEnd('\')
    # Registry BasePath can use an extended local-drive prefix; never accept device/UNC namespaces.
    if ($value -match '^(\\\\\?\\|\\\?\?\\)[A-Za-z]:\\') { $value = $value.Substring(4) }
    if ($value -notmatch '^[A-Za-z]:\\[^\\]+(\\[^\\]+)*$') { throw 'Use a local absolute Windows folder, not a UNC or relative path.' }
    foreach ($part in $value.Substring(3).Split('\')) {
        if ($part -in @('.', '..') -or $part -match '[<>:"|?*\x00-\x1f]' -or $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') {
            throw 'The installation path contains an unsafe Windows component.'
        }
    }
    return $value
}

function New-StationInstallState {
    param([Parameter(Mandatory=$true)][string]$Root, [Parameter(Mandatory=$true)][string]$PackageSha256)
    if ($PackageSha256 -cnotmatch '^[a-f0-9]{64}$') { throw 'A complete audited package hash is required.' }
    $rootPath = ConvertTo-StationWindowsPath $Root
    $id = [guid]::NewGuid().ToString('N')
    return [pscustomobject][ordered]@{
        Schema = 1; InstallId = $id; Distribution = ('AIStation-' + $id)
        Root = $rootPath; Directory = ($rootPath + '\guest'); Phase = 'reserved'
        PackageSha256 = $PackageSha256; RegistrationId = $null
    }
}

function Assert-StationInstallState {
    param([Parameter(Mandatory=$true)]$State, [Parameter(Mandatory=$true)][string]$ExpectedRoot)
    $names = @($State.PSObject.Properties.Name | Sort-Object)
    $expected = @('Schema','InstallId','Distribution','Root','Directory','Phase','PackageSha256','RegistrationId' | Sort-Object)
    foreach ($field in @('InstallId','Distribution','Root','Directory','Phase','PackageSha256')) {
        if ($State.$field -isnot [string]) { throw 'Saved installation fields must be strings.' }
    }
    if ($State.Schema -is [bool] -or $State.Schema -isnot [ValueType]) { throw 'Invalid saved schema type.' }
    if (($names -join '|') -cne ($expected -join '|') -or $State.Schema -ne 1 -or $State.InstallId -cnotmatch '^[a-f0-9]{32}$' -or $State.Distribution -cne ('AIStation-' + $State.InstallId) -or $State.PackageSha256 -cnotmatch '^[a-f0-9]{64}$' -or $State.Phase -cnotin @('reserved','importing','registered','ready')) { throw 'The saved installation identity is invalid.' }
    $rootPath = ConvertTo-StationWindowsPath $ExpectedRoot
    $savedRoot = ConvertTo-StationWindowsPath $State.Root
    $savedDirectory = ConvertTo-StationWindowsPath $State.Directory
    if (-not $rootPath.Equals($savedRoot, [StringComparison]::OrdinalIgnoreCase) -or -not $savedDirectory.Equals(($rootPath + '\guest'), [StringComparison]::OrdinalIgnoreCase)) { throw 'The saved installation belongs to a different private folder.' }
    if ($null -ne $State.RegistrationId -and $State.RegistrationId -cnotmatch '^\{[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\}$') { throw 'The saved distribution registration is invalid.' }
    if ($State.Phase -in @('registered','ready') -and $null -eq $State.RegistrationId) { throw 'A registered installation must retain its registry identity.' }
}

function Get-StationImportPlan {
    param([Parameter(Mandatory=$true)]$State, [Parameter(Mandatory=$true)][string]$ExpectedRoot,
          [Parameter(Mandatory=$true)][string]$Archive, [AllowEmptyCollection()][object[]]$Inventory = @(),
          [bool]$ExistingDisk = $false)
    Assert-StationInstallState $State $ExpectedRoot
    $archivePath = ConvertTo-StationWindowsPath $Archive
    $matches = @($Inventory | Where-Object { $_.DistributionName -ieq $State.Distribution })
    if ($matches.Count -gt 1) { throw 'Multiple registrations claim the saved distribution name.' }
    foreach ($item in $Inventory) {
        try { $base = ConvertTo-StationWindowsPath $item.BasePath } catch {
            if ($item.DistributionName -ieq $State.Distribution) { throw }
            continue # Preserve unrelated registrations using a path format this installer does not manage.
        }
        if ($base.Equals($State.Directory, [StringComparison]::OrdinalIgnoreCase) -and $item.DistributionName -ine $State.Distribution) { throw 'Another distribution already owns this folder. Nothing was adopted or removed.' }
    }
    if ($matches.Count -eq 0) {
        if ($State.Phase -in @('registered','ready')) { throw 'The saved distribution disappeared. Preserve its data and inspect before reinstalling.' }
        if ($ExistingDisk) { return [pscustomobject]@{ Kind = 'InspectIncompleteDisk'; Arguments = @() } }
        return [pscustomobject]@{ Kind = 'Import'; Arguments = @('--import',$State.Distribution,$State.Directory,$archivePath,'--version','2') }
    }
    $registration = $matches[0]
    $base = ConvertTo-StationWindowsPath $registration.BasePath
    if (-not $base.Equals($State.Directory,[StringComparison]::OrdinalIgnoreCase) -or $registration.Version -ne 2) { throw 'This name belongs to a different folder or unsupported WSL version. Nothing was changed.' }
    if ($State.RegistrationId -and $State.RegistrationId -ine $registration.Id) { throw 'The saved registration was replaced. Do not adopt or remove it.' }
    return [pscustomobject]@{ Kind = 'VerifyGuest'; Arguments = @('--distribution',$State.Distribution,'--user','station','--exec','/usr/bin/cat','--','/usr/lib/ai-station-wsl-build.json') }
}

function Get-StationLifecyclePlan {
    param([Parameter(Mandatory=$true)]$State, [Parameter(Mandatory=$true)][string]$ExpectedRoot,
          [Parameter(Mandatory=$true)][ValidateSet('start','status','open','stop')][string]$Action)
    Assert-StationInstallState $State $ExpectedRoot
    if ($State.Phase -cne 'ready') { throw 'Verify the imported guest before starting this installation.' }
    return [string[]]@('--distribution',$State.Distribution,'--user','station','--exec','/usr/libexec/ai-station/wsl-control',$Action.ToLowerInvariant())
}

Export-ModuleMember -Function ConvertTo-StationWindowsPath,New-StationInstallState,Assert-StationInstallState,Get-StationImportPlan,Get-StationLifecyclePlan
