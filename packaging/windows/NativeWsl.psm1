# Native Windows read-only preflight. Never enable features, start a distro or change registry keys here.
Set-StrictMode -Version 2.0

function Assert-StationWindowsCompatibility {
    param([PlatformID]$Platform,[version]$Version,[string]$Architecture,[bool]$Is64BitProcess)
    if ($Platform -ne [PlatformID]::Win32NT) { throw 'This operation requires Windows; no operating-system change was made.' }
    if (-not $Is64BitProcess -or $Architecture -cne 'X64') { throw 'AI Station requires x64 Windows and the 64-bit desktop launcher. ARM and 32-bit Windows are not supported.' }
    if ($Version -lt [version]'10.0.19044') { throw 'AI Station requires Windows 10 version 21H2 or newer (build 19044), or Windows 11. Update Windows, then reopen AI Station.' }
}

function Assert-StationWindowsHost {
    Assert-StationWindowsCompatibility -Platform ([Environment]::OSVersion.Platform) -Version ([Environment]::OSVersion.Version) -Architecture ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()) -Is64BitProcess ([Environment]::Is64BitProcess)
}

function New-StationWslUpdateRequired {
    $failure=[InvalidOperationException]::new('Install or update Windows Subsystem for Linux (WSL 0.67.6 or newer). In an Administrator PowerShell window, run wsl --install --no-distribution, then wsl --update. Restart Windows if requested, reopen AI Station and choose Prepare. Existing distributions and saved work are preserved.')
    $failure.Data['AIStationWslFailure']='update_required'
    $failure.Data['AIStationWslAction']='update'
    return $failure
}

function Assert-StationWslVersion {
    param([string]$Output)
    # WSL localizes the label; only the numeric version on its first line is
    # significant. Older system launchers may return NUL-padded UTF-16 text.
    if ($Output.Length -gt 16384) { throw (New-StationWslUpdateRequired) }
    $first=($Output.Replace([string][char]0,'').Trim() -split '\r?\n')[0]
    if ($first -notmatch '^[^:\r\n]{1,80}:[ \t]*([0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}(?:\.[0-9]{1,5})?)[ \t]*$') { throw (New-StationWslUpdateRequired) }
    $version=$null
    if (-not [version]::TryParse($Matches[1],[ref]$version) -or $version -lt [version]'0.67.6') { throw (New-StationWslUpdateRequired) }
}

function Get-StationWslExecutable {
    Assert-StationWindowsHost
    $path = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'wsl.exe'
    if (-not [IO.File]::Exists($path)) {
        $failure=New-StationWslUpdateRequired
        $failure.Data['AIStationWslAction']='install'
        throw $failure
    }
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'The WSL launcher must be the trusted system executable.' }
    $signature = Get-AuthenticodeSignature -LiteralPath $path -ErrorAction Stop
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') { throw 'The Windows WSL launcher signature could not be verified.' }
    return $path
}

function Get-StationWslRegistrations {
    Assert-StationWindowsHost
    $registry = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Software\Microsoft\Windows\CurrentVersion\Lxss', $false)
    if ($null -eq $registry) { return }
    try {
        foreach ($name in $registry.GetSubKeyNames()) {
            if ($name -notmatch '^\{[a-fA-F0-9]{8}(-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\}$') { continue }
            $entry = $registry.OpenSubKey($name, $false)
            if ($null -eq $entry) { continue }
            try {
                [pscustomobject]@{ Id=$name; DistributionName=[string]$entry.GetValue('DistributionName'); BasePath=[string]$entry.GetValue('BasePath'); Version=[int]$entry.GetValue('Version') }
            } finally { $entry.Dispose() }
        }
    } finally { $registry.Dispose() }
}

function Assert-StationWindowsPreparationReady {
    Assert-StationWindowsHost
    foreach($path in @('SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending','SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired')) {
        $key=[Microsoft.Win32.Registry]::LocalMachine.OpenSubKey($path,$false)
        try {
            if($null -ne $key) {
                $failure=[InvalidOperationException]::new('Restart Windows to finish preparing its local environment, then reopen AI Station.')
                $failure.Data['AIStationRestartRequired']=$true
                throw $failure
            }
        } finally { if($null -ne $key){$key.Dispose()} }
    }
}

Export-ModuleMember -Function Assert-StationWindowsHost,Get-StationWslExecutable,Get-StationWslRegistrations,Assert-StationWindowsPreparationReady,Assert-StationWslVersion,New-StationWslUpdateRequired
