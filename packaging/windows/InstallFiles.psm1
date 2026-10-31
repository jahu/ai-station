# Private installer file primitives. The Windows factory must establish the root ACL first.
Set-StrictMode -Version 2.0

function Assert-StationRegularFile {
    param([Parameter(Mandatory=$true)][string]$Path)
    $attributes = [IO.File]::GetAttributes($Path)
    if (($attributes -band ([IO.FileAttributes]::Directory -bor [IO.FileAttributes]::ReparsePoint)) -ne 0) { throw 'Installer files must be regular files, not links or directories.' }
}

function New-StationFileLease {
    param([Parameter(Mandatory=$true)][string]$Root)
    $full = [IO.Path]::GetFullPath($Root).TrimEnd([IO.Path]::DirectorySeparatorChar)
    if (-not [IO.Directory]::Exists($full) -or ([IO.File]::GetAttributes($full) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'The verified private installer directory is unavailable.' }
    $lockPath = [IO.Path]::Combine($full,'install.lock')
    if ([IO.File]::Exists($lockPath)) { Assert-StationRegularFile $lockPath }
    $stream = [IO.File]::Open($lockPath,[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    return [pscustomobject]@{ Root=$full; Stream=$stream }
}

function Assert-StationFileLease {
    param([Parameter(Mandatory=$true)]$Lease)
    if ($Lease.Stream -isnot [IO.FileStream] -or -not $Lease.Stream.CanWrite -or -not $Lease.Stream.Name.Equals([IO.Path]::Combine($Lease.Root,'install.lock'),[StringComparison]::OrdinalIgnoreCase)) { throw 'Hold the private installation lock before reading or publishing state.' }
}

function Read-StationStateFile {
    param([Parameter(Mandatory=$true)]$Lease)
    Assert-StationFileLease $Lease
    $path = [IO.Path]::Combine($Lease.Root,'install-state.json')
    if (-not [IO.File]::Exists($path)) { return $null }
    Assert-StationRegularFile $path
    $source = [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if ($source.Length -gt 65536) { throw 'The saved installation state exceeds its expected size.' }
        $reader = [IO.StreamReader]::new($source,[Text.UTF8Encoding]::new($false,$true),$false)
        try { $text=$reader.ReadToEnd() } finally { $reader.Dispose() }
        return ($text | ConvertFrom-Json -ErrorAction Stop)
    } finally { $source.Dispose() }
}

function Write-StationStateFile {
    param([Parameter(Mandatory=$true)]$Lease,[Parameter(Mandatory=$true)]$State)
    Assert-StationFileLease $Lease
    $path=[IO.Path]::Combine($Lease.Root,'install-state.json')
    $temporary=[IO.Path]::Combine($Lease.Root,('.state-'+[guid]::NewGuid().ToString('N')+'.json'))
    $bytes=[Text.UTF8Encoding]::new($false,$true).GetBytes(($State | ConvertTo-Json -Depth 8 -Compress))
    if ($bytes.Length -gt 65536) { throw 'The installation state exceeds its expected size.' }
    try {
        $target=[IO.File]::Open($temporary,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
        try { $target.Write($bytes,0,$bytes.Length); $target.Flush($true) } finally { $target.Dispose() }
        if ([IO.File]::Exists($path)) {
            Assert-StationRegularFile $path
            [IO.File]::Replace($temporary,$path,[NullString]::Value)
        } else { [IO.File]::Move($temporary,$path) }
    } finally { if ([IO.File]::Exists($temporary)) { [IO.File]::Delete($temporary) } }
}

function Open-StationVerifiedArchive {
    param([Parameter(Mandatory=$true)][string]$Path,[Parameter(Mandatory=$true)][string]$Sha256,[Parameter(Mandatory=$true)][long]$Bytes)
    if ($Sha256 -cnotmatch '^[a-f0-9]{64}$' -or $Bytes -le 0 -or $Bytes -gt 17179869184) { throw 'The reviewed archive identity or byte length is invalid.' }
    Assert-StationRegularFile $Path
    # On Windows this sharing mode denies writes/deletion while WSL reads the archive.
    $stream=[IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        if ($stream.Length -ne $Bytes) { throw 'The installation archive byte length differs from its manifest.' }
        $hasher=[Security.Cryptography.SHA256]::Create()
        try { $actual=[BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() } finally { $hasher.Dispose() }
        if ($actual -cne $Sha256) { throw 'The installation archive checksum differs from its manifest.' }
        $stream.Position=0
        return [pscustomobject]@{ Path=[IO.Path]::GetFullPath($Path); Stream=$stream; Sha256=$actual; Bytes=$Bytes }
    } catch { $stream.Dispose(); throw }
}

Export-ModuleMember -Function New-StationFileLease,Read-StationStateFile,Write-StationStateFile,Open-StationVerifiedArchive
