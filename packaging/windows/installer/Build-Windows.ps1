# Publisher-only build. Does not install anything or enable Windows features.
param([Parameter(Mandatory=$true)][string]$GuestPackage,[Parameter(Mandatory=$true)][string]$Output,[string]$InnoCompiler='')
$ErrorActionPreference='Stop'
$source=Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $source 'NativeWsl.psm1')
Import-Module (Join-Path $source 'GuestManifest.psm1')
Import-Module (Join-Path $source 'InstallFiles.psm1')
Assert-StationWindowsHost
if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Build with the built-in Windows PowerShell compiler host.' }
$repo=Split-Path -Parent (Split-Path -Parent $source)
function Get-StationPublisherSource {
 $head=& git -C $repo rev-parse HEAD
 if ($LASTEXITCODE -ne 0 -or $head -cnotmatch '^[a-f0-9]{40}$') { throw 'Build from an identified source checkout.' }
 $dirty=& git -C $repo status --porcelain --untracked-files=all
 if ($LASTEXITCODE -ne 0 -or $dirty) { throw 'Commit the reviewed source before building a Windows payload.' }
 return $head
}
$sourceHead=Get-StationPublisherSource
if ([IO.Directory]::Exists($Output) -or [IO.File]::Exists($Output)) { throw 'Choose a new output directory. Existing files are never overwritten.' }
if ($InnoCompiler -and ([IO.Directory]::Exists($Output+'.installer') -or [IO.File]::Exists($Output+'.installer'))) { throw 'Choose a fresh installer output directory. Existing installers are preserved.' }
$manifest=[IO.File]::ReadAllText((Join-Path $GuestPackage 'windows-guest-manifest.json'),[Text.UTF8Encoding]::new($false,$true)) | ConvertFrom-Json -ErrorAction Stop
Assert-StationGuestManifest $manifest
$archive=Open-StationVerifiedArchive (Join-Path $GuestPackage 'ai-station-wsl-rootfs.tar.gz') $manifest.rootfs_sha256 $manifest.rootfs_bytes
$stage=$Output+'.building-'+[guid]::NewGuid().ToString('N')
try {
 [void][IO.Directory]::CreateDirectory($stage)
 $files=@('InstallState.psm1','InstallFiles.psm1','PrivateStore.psm1','NativeWsl.psm1','GuestManifest.psm1','DesktopPort.psm1','DesktopLink.psm1','DesktopResult.psm1','DesktopProcess.psm1','Setup.psm1','WindowsSetup.ps1','Uninstall-Check.ps1')
 foreach ($name in $files) {
  # A BOM keeps built-in Windows PowerShell 5.1 source decoding unambiguous.
  $text=[IO.File]::ReadAllText((Join-Path $source $name),[Text.UTF8Encoding]::new($false,$true))
  [IO.File]::WriteAllText((Join-Path $stage $name),$text,[Text.UTF8Encoding]::new($true,$true))
 }
 # Publish the validated snapshot, not a second mutable read of the input file.
 [IO.File]::WriteAllText((Join-Path $stage 'windows-guest-manifest.json'),($manifest|ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false,$true))
 $target=[IO.File]::Open((Join-Path $stage 'ai-station-wsl-rootfs.tar.gz'),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
 try { $archive.Stream.CopyTo($target);$target.Flush($true) } finally { $target.Dispose() }
 foreach ($name in @('LICENSE','NOTICE','COMMERCIAL.md')) { [IO.File]::Copy((Join-Path $repo $name),(Join-Path $stage $name),$false) }
 $parameters=[CodeDom.Compiler.CompilerParameters]::new()
 $parameters.CompilerOptions='/platform:x64 /target:winexe';$parameters.GenerateExecutable=$true;$parameters.GenerateInMemory=$false
 $parameters.OutputAssembly=Join-Path $stage 'AIStation.exe'
 [void]$parameters.ReferencedAssemblies.Add('System.dll');[void]$parameters.ReferencedAssemblies.Add('System.Core.dll')
 # Compile without loading application types into this PowerShell session.
 # Add-Type caches names and otherwise breaks a second build in the same host.
 Add-Type -AssemblyName Microsoft.CSharp
 $provider=[Microsoft.CSharp.CSharpCodeProvider]::new();$compiled=$null
 try {
  $compiled=$provider.CompileAssemblyFromSource($parameters,[string[]]@([IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Bootstrap.cs'))))
  if ($compiled.Errors.HasErrors) { throw ('Native launcher compilation failed: '+(($compiled.Errors | ForEach-Object {$_.ErrorText}) -join '; ')) }
 } finally {
  if ($null -ne $compiled) { $compiled.TempFiles.Delete() }
  $provider.Dispose()
 }
 $binary=[IO.File]::ReadAllBytes($parameters.OutputAssembly)
 if ($binary.Length -lt 256 -or $binary.Length -gt 1048576 -or [BitConverter]::ToUInt16($binary,0) -ne 0x5a4d) { throw 'The native launcher did not produce a valid executable.' }
 $pe=[BitConverter]::ToInt32($binary,0x3c)
 if ($pe -lt 0 -or $pe -gt $binary.Length-128 -or [BitConverter]::ToUInt32($binary,$pe) -ne 0x4550 -or [BitConverter]::ToUInt16($binary,$pe+4) -ne 0x8664 -or [BitConverter]::ToUInt16($binary,$pe+24) -ne 0x20b -or [BitConverter]::ToUInt16($binary,$pe+24+68) -ne 2) { throw 'The native launcher must be an actual x64 GUI executable.' }
 $hashes=[ordered]@{}
 foreach ($file in [IO.Directory]::EnumerateFiles($stage)) { $hashes[[IO.Path]::GetFileName($file)]=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() }
 if ((Get-StationPublisherSource) -cne $sourceHead) { throw 'The publisher source changed during packaging; no payload was published.' }
 $record=[pscustomobject]@{schema=1;source_head=$sourceHead;files=$hashes;qualification='Private build only. Native Windows qualification and signing remain required.'}
 [IO.File]::WriteAllText((Join-Path $stage 'windows-host-manifest.json'),($record|ConvertTo-Json -Depth 5),[Text.UTF8Encoding]::new($false,$true))
 [IO.Directory]::Move($stage,$Output)
 if ($InnoCompiler) {
  $version=(Get-FileHash -LiteralPath (Join-Path $Output 'windows-host-manifest.json') -Algorithm SHA256).Hash.ToLowerInvariant().Substring(0,16)
  & $InnoCompiler ('/DPayload='+[IO.Path]::GetFullPath($Output)) ('/DVersionId='+$version) (Join-Path $PSScriptRoot 'ai-station.iss')
  if ($LASTEXITCODE -ne 0) { throw 'The native installer compiler failed; the private payload was retained for inspection.' }
 }
} finally {
 $archive.Stream.Dispose()
 if ([IO.Directory]::Exists($stage)) { [IO.Directory]::Delete($stage,$true) }
}
