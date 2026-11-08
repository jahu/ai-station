# Pure admission tests run on Linux PowerShell and native Windows PowerShell 5.1.
# No version spoofing establishes native Windows installation qualification.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../NativeWsl.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../DesktopResult.psm1') -Force
$module=Get-Module NativeWsl
& $module {
 $cases=0
 foreach($version in @('10.0.19044','10.0.19045','10.0.22000','10.0.22631','10.0.26100')) {
  Assert-StationWindowsCompatibility Win32NT ([version]$version) X64 $true
  $cases++
 }
 foreach($case in @(
  @('Win32NT','6.3.9600','X64',$true),@('Win32NT','10.0.17763','X64',$true),
  @('Win32NT','10.0.19041','X64',$true),@('Win32NT','10.0.19043','X64',$true),
  @('Win32NT','10.0.19045','X86',$false),@('Win32NT','10.0.22631','Arm64',$true),
  @('Win32NT','10.0.22631','X64',$false),@('Unix','10.0.19045','X64',$true)
 )) {
  $refused=$false
  try { Assert-StationWindowsCompatibility $case[0] ([version]$case[1]) $case[2] $case[3] } catch {$refused=$true}
  if(-not $refused){throw 'An unsupported OS/architecture was admitted.'};$cases++
 }
 Write-Output ('PASS '+$cases+' Windows host admission boundaries')
}
$cases=0
foreach($text in @('WSL version: 0.67.6','WSL version: 0.67.6.0','WSL version: 2.6.3.0',"Wersja WSL: 2.6.3.0`r`nWersja jadra: 6.6.0",([string]::Join([string][char]0,'WSL version: 2.6.3.0'.ToCharArray())))) {
 Assert-StationWslVersion $text;$cases++
}
foreach($text in @('','WSL version: 0.67.5','WSL version: 0.66.2.0','Invalid command line option: --version',"Help text`nWSL version: 2.6.3.0",'WSL version: 2.6.3.0-preview','WSL version: 99999999.1.1',('x'*16385))) {
 $failure=$null;try{Assert-StationWslVersion $text}catch{$failure=$_.Exception}
 if($null -eq $failure){throw 'An old or unknown WSL installation was admitted.'}
 $view=Get-StationFailurePresentation ([InvalidOperationException]::new('Wrapped background failure',$failure))
 if($view.Title -cne 'Update Windows support' -or $view.WindowsSupportAction -cne 'update' -or $view.Details -notmatch 'wsl --update' -or $view.Details -match 'Invalid command line option'){throw 'WSL recovery guidance was lost or raw output exposed.'};$cases++
}
$installer=[IO.File]::ReadAllText((Join-Path $PSScriptRoot '../installer/ai-station.iss'))
if($installer -notmatch '(?m)^MinVersion=10\.0\.19044\r?$'){throw 'Native preflight and installer minimum diverged.'}
if([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT){Assert-StationWindowsHost}
Write-Output ('PASS '+$cases+' WSL version/recovery cases and matching installer minimum; no WSL/OS mutation')
