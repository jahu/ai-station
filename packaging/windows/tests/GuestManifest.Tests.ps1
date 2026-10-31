$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../GuestManifest.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if (-not $Condition) { throw $Message }; $script:Cases++ }
function Refuses([scriptblock]$Action) { $failed=$false;try { & $Action | Out-Null } catch { $failed=$true };Check $failed 'Unverified metadata was accepted.' }
function Fixture {
 return [pscustomobject]@{schema=1;source_head=('a'*40);base=('ubuntu:24.04@sha256:'+('b'*64));package_sha256=('c'*64);rootfs_sha256=('d'*64);image_id=('sha256:'+('e'*64));rootfs_bytes=435188534;package=[pscustomobject]@{Package='ai-station';Architecture='amd64';Version='0.1.0~preview.42'};sources=[pscustomobject]@{'guest.Dockerfile'=('1'*64);'wsl.conf'=('2'*64);'guest_control.py'=('3'*64)}}
}
$prior=[Globalization.CultureInfo]::CurrentCulture
try {
 foreach ($culture in @('en-US','pl-PL','tr-TR')) {
  [Globalization.CultureInfo]::CurrentCulture=[Globalization.CultureInfo]::GetCultureInfo($culture)
  $manifest=Fixture;Assert-StationGuestManifest $manifest;Assert-StationImportedGuest $manifest (Fixture)
  Check $true 'Publisher source identity must not depend on the Windows language/collation.'
 }
} finally { [Globalization.CultureInfo]::CurrentCulture=$prior }
foreach ($field in @('source_head','base','package_sha256','rootfs_sha256','image_id')) { $m=Fixture;$m.$field='unverified';Refuses { Assert-StationGuestManifest $m } }
foreach ($size in @(-1,0,17179869185,$true)) { $m=Fixture;$m.rootfs_bytes=$size;Refuses { Assert-StationGuestManifest $m } }
$m=Fixture;$m.package.Architecture='arm64';Refuses { Assert-StationGuestManifest $m }
$m=Fixture;$m.sources.PSObject.Properties.Remove('guest_control.py');Refuses { Assert-StationGuestManifest $m }
$m=Fixture;$m.sources | Add-Member -NotePropertyName 'extra.py' -NotePropertyValue ('4'*64);Refuses { Assert-StationGuestManifest $m }
foreach ($field in @('source_head','base','package_sha256')) { $guest=Fixture;$guest.$field='different';Refuses { Assert-StationImportedGuest (Fixture) $guest } }
$guest=Fixture;$guest.sources.'guest_control.py'='0'*64;Refuses { Assert-StationImportedGuest (Fixture) $guest }
$guest=Fixture;$guest.package.Version='different';Refuses { Assert-StationImportedGuest (Fixture) $guest }
Write-Output ('PASS '+$script:Cases+' publisher/imported guest identity assertions; no WSL invocation')
