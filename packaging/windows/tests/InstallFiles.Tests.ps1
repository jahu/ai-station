$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../InstallFiles.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if (-not $Condition) { throw ($Message+'; assertion '+($script:Cases+1)) }; $script:Cases++ }
function Refuses([scriptblock]$Action) { $failed=$false; try { & $Action | Out-Null } catch { $failed=$true }; Check $failed 'Expected an unsafe file operation to be rejected.' }
$root=Join-Path ([IO.Path]::GetTempPath()) ('ai-station-file-qa-'+[guid]::NewGuid().ToString('N')+' Łódź')
[void][IO.Directory]::CreateDirectory($root)
$lease=$null;$archive=$null
try {
 $lease=New-StationFileLease $root
 Refuses { New-StationFileLease $root }
 Check ($null -eq (Read-StationStateFile $lease)) 'A new store must not fabricate existing state.'
 Write-StationStateFile $lease ([pscustomobject]@{phase='reserved';value='Łódź 🏡'})
 $state=Read-StationStateFile $lease
 Check ($state.phase -eq 'reserved' -and $state.value -eq 'Łódź 🏡') 'Actual UTF-8 state must survive publication and read.'
 Write-StationStateFile $lease ([pscustomobject]@{phase='importing';value='preserved'})
 Check ((Read-StationStateFile $lease).phase -eq 'importing') 'Atomic replacement must publish the complete newer state.'
 Check (@([IO.Directory]::EnumerateFiles($root,'.state-*')).Count -eq 0) 'Publication must not leave staging files.'
 $before=[IO.File]::ReadAllText((Join-Path $root 'install-state.json'))
 Refuses { Write-StationStateFile $lease ([pscustomobject]@{value=('x'*70000)}) }
 Check ([IO.File]::ReadAllText((Join-Path $root 'install-state.json')) -ceq $before) 'Oversized updates must retain the original state.'
 $path=Join-Path $root 'reviewed archive.bin';$bytes=[Text.Encoding]::UTF8.GetBytes('reviewed neutral public file')
 [IO.File]::WriteAllBytes($path,$bytes)
 $hash=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
 Refuses { Open-StationVerifiedArchive $path ('0'*64) $bytes.Length }
 Refuses { Open-StationVerifiedArchive $path $hash ($bytes.Length+1) }
 $archive=Open-StationVerifiedArchive $path $hash $bytes.Length
 Check ($archive.Stream.Position -eq 0 -and $archive.Sha256 -ceq $hash) 'Successful verification must retain the held read handle at its beginning.'
 if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
  Refuses { [IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite).Dispose() }
 } else {
  Check $archive.Stream.CanRead 'The actual verified read handle remains open. Windows mandatory sharing is not qualified by Linux.'
 }
 $archive.Stream.Dispose();$archive=$null
 $writer=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Write,[IO.FileShare]::None);$writer.Dispose()
 Check $true 'Verification failure/success must release a disposed handle.'
 $lease.Stream.Dispose()
 Refuses { Read-StationStateFile $lease }
 $lease=New-StationFileLease $root
 Check ((Read-StationStateFile $lease).value -eq 'preserved') 'A new actual lease must retain previously published state.'
 [IO.File]::WriteAllBytes((Join-Path $root 'install-state.json'),[byte[]]@(255,254,253))
 Refuses { Read-StationStateFile $lease }
 Write-Output ('PASS '+$script:Cases+' actual .NET file/lease/hash assertions; Windows ACL and WSL qualification remain pending')
} finally {
 if ($null -ne $archive) { $archive.Stream.Dispose() }
 if ($null -ne $lease) { $lease.Stream.Dispose() }
 [IO.Directory]::Delete($root,$true)
}
