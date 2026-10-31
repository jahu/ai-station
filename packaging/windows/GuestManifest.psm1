# Typed published guest metadata; this does not replace signed distribution packaging.
Set-StrictMode -Version 2.0

function Assert-StationGuestManifest {
    param([Parameter(Mandatory=$true)]$Manifest)
    if ($Manifest.schema -ne 1 -or $Manifest.source_head -cnotmatch '^[a-f0-9]{40}$' -or $Manifest.base -cnotmatch '^ubuntu:24\.04@sha256:[a-f0-9]{64}$' -or $Manifest.package_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $Manifest.rootfs_sha256 -cnotmatch '^[a-f0-9]{64}$' -or $Manifest.image_id -cnotmatch '^sha256:[a-f0-9]{64}$') { throw 'The published guest identity is invalid.' }
    if ($Manifest.rootfs_bytes -is [bool] -or $Manifest.rootfs_bytes -le 0 -or $Manifest.rootfs_bytes -gt 17179869184 -or $Manifest.package.Package -cne 'ai-station' -or $Manifest.package.Architecture -cne 'amd64' -or $Manifest.package.Version -isnot [string]) { throw 'The guest size or package architecture is invalid.' }
    $names=[string[]]@($Manifest.sources.PSObject.Properties.Name); [Array]::Sort($names,[StringComparer]::Ordinal)
    if (($names -join '|') -cne 'guest.Dockerfile|guest_control.py|wsl.conf') { throw 'The reviewed guest sources are incomplete.' }
    foreach ($name in $names) { if ($Manifest.sources.$name -cnotmatch '^[a-f0-9]{64}$') { throw 'A reviewed guest source hash is invalid.' } }
}

function Assert-StationImportedGuest {
    param([Parameter(Mandatory=$true)]$Manifest,[Parameter(Mandatory=$true)]$Guest)
    Assert-StationGuestManifest $Manifest
    if ($Guest.schema -ne 1 -or $Guest.source_head -cne $Manifest.source_head -or $Guest.base -cne $Manifest.base -or $Guest.package_sha256 -cne $Manifest.package_sha256 -or $Guest.package.Package -cne $Manifest.package.Package -or $Guest.package.Version -cne $Manifest.package.Version -or $Guest.package.Architecture -cne $Manifest.package.Architecture) { throw 'The imported guest does not match the accepted package. Its data was preserved.' }
    $names=[string[]]@($Guest.sources.PSObject.Properties.Name); [Array]::Sort($names,[StringComparer]::Ordinal)
    if (($names -join '|') -cne 'guest.Dockerfile|guest_control.py|wsl.conf') { throw 'The imported guest source receipt is incomplete.' }
    foreach ($name in $names) { if ($Guest.sources.$name -cne $Manifest.sources.$name) { throw 'The imported guest source differs from its accepted identity.' } }
}

Export-ModuleMember -Function Assert-StationGuestManifest,Assert-StationImportedGuest
