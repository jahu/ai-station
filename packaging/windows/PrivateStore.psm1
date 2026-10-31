# Windows-only private NTFS storage; never repair or adopt an unsafe existing directory.
Set-StrictMode -Version 2.0
Import-Module (Join-Path $PSScriptRoot 'NativeWsl.psm1')
Import-Module (Join-Path $PSScriptRoot 'InstallFiles.psm1')

function Assert-StationNoReparsePath {
    param([Parameter(Mandatory=$true)][string]$Path)
    Assert-StationWindowsHost
    $item=[IO.Path]::GetFullPath($Path)
    while ($item) {
        if (([IO.File]::Exists($item) -or [IO.Directory]::Exists($item)) -and ([IO.File]::GetAttributes($item) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Private installation storage must not cross a Windows link or junction.' }
        $item=[IO.Path]::GetDirectoryName($item)
    }
}

function Assert-StationPrivateAcl {
    param([Parameter(Mandatory=$true)][string]$Path)
    Assert-StationWindowsHost
    Assert-StationNoReparsePath $Path
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $acl=Get-Acl -LiteralPath $Path -ErrorAction Stop
    if ($acl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne $sid) { throw 'This installer folder or file belongs to another Windows account.' }
    foreach ($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])) {
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $rule.IdentityReference.Value -notin @($sid,'S-1-5-18')) { throw 'Private installation storage is accessible by another Windows account. It was not adopted.' }
    }
}

function New-StationPrivateStore {
    Assert-StationWindowsHost
    $parent=[Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    $root=[IO.Path]::Combine($parent,'AIStation-Desktop')
    Assert-StationNoReparsePath $root
    if (-not [IO.Directory]::Exists($root)) {
        # Only this new leaf receives permissions; parent/profile ACLs are untouched.
        [void][IO.Directory]::CreateDirectory($root)
        $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl=[Security.AccessControl.DirectorySecurity]::new()
        $acl.SetOwner($sid); $acl.SetAccessRuleProtection($true,$false)
        $inherit=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
        foreach ($identity in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
            $rule=[Security.AccessControl.FileSystemAccessRule]::new($identity,[Security.AccessControl.FileSystemRights]::FullControl,$inherit,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
            [void]$acl.AddAccessRule($rule)
        }
        Set-Acl -LiteralPath $root -AclObject $acl -ErrorAction Stop
    }
    Assert-StationPrivateAcl $root
    foreach ($name in @('install.lock','install-state.json','ui-active.lock')) {
        $path=[IO.Path]::Combine($root,$name)
        if ([IO.File]::Exists($path)) { Assert-StationPrivateAcl $path }
    }
    $lease=New-StationFileLease $root
    try {
        if (-not [IO.File]::Exists([IO.Path]::Combine($root,'install-state.json'))) {
            $unknown=@([IO.Directory]::EnumerateFileSystemEntries($root) | Where-Object { [IO.Path]::GetFileName($_) -notin @('install.lock','ui-active.lock') })
            if ($unknown.Count -gt 0) { throw 'Existing unmarked data was found. It was not adopted, overwritten or deleted.' }
        }
        return $lease
    } catch { $lease.Stream.Dispose(); throw }
}

Export-ModuleMember -Function Assert-StationNoReparsePath,Assert-StationPrivateAcl,New-StationPrivateStore

# Shared lifetime marker covers every session of this OS account, independently
# of the per-session show-window mutex. Windows denies exclusive uninstall access.
function Open-StationUiLease {
    $lease=New-StationPrivateStore
    try {
        $path=[IO.Path]::Combine($lease.Root,'ui-active.lock')
        if ([IO.File]::Exists($path)) { Assert-StationPrivateAcl $path }
        return [IO.File]::Open($path,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
    } finally { $lease.Stream.Dispose() }
}
Export-ModuleMember -Function Open-StationUiLease
