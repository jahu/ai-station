# Native Windows read-only preflight. Never enable features, start a distro or change registry keys here.
Set-StrictMode -Version 2.0

function Assert-StationWindowsHost {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'This operation requires Windows; no operating-system change was made.' }
    if (-not [Environment]::Is64BitProcess -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne 'X64' -or [Environment]::OSVersion.Version.Build -lt 22000) { throw 'This installer prototype targets 64-bit Windows 11.' }
}

function Get-StationWslExecutable {
    Assert-StationWindowsHost
    $path = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'wsl.exe'
    if (-not [IO.File]::Exists($path)) { throw 'Windows Subsystem for Linux is not installed. Use the Windows setup action before continuing.' }
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

Export-ModuleMember -Function Assert-StationWindowsHost,Get-StationWslExecutable,Get-StationWslRegistrations
