$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../../PrivateStore.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../../NativeWsl.psm1') -Force
Assert-StationWindowsHost
$script:Cases=0
function Check($Condition,[string]$Message) { if(-not $Condition){throw $Message};$script:Cases++ }
function Refuses([scriptblock]$Action) {
 $failed=$false;try { & $Action } catch { $failed=$true }
 Check $failed 'An unsafe native path or ACL was accepted.'
}
function New-FixtureAcl($Sid) {
 $control=[Security.AccessControl.DirectorySecurity]::new()
 $control.SetOwner($Sid);$control.SetAccessRuleProtection($true,$false)
 foreach($identity in @($Sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
  $control.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity,[Security.AccessControl.FileSystemRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow))
 }
 return $control
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('ai-station-boundary-'+[guid]::NewGuid().ToString('N'))
$target=Join-Path $root 'target';$link=Join-Path $root 'junction'
[void][IO.Directory]::CreateDirectory($target)
try {
 Assert-StationNoReparsePath (Join-Path $target 'new-child')
 Check $true 'An ordinary missing leaf must remain usable for a fresh import.'
 $info=[Diagnostics.ProcessStartInfo]::new()
 $info.FileName=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'cmd.exe'
 $info.Arguments='/d /c mklink /J "'+$link+'" "'+$target+'"'
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $proc=[Diagnostics.Process]::Start($info)
 try {
  $out=$proc.StandardOutput.ReadToEndAsync();$err=$proc.StandardError.ReadToEndAsync();$proc.WaitForExit()
  [void]$out.GetAwaiter().GetResult();[void]$err.GetAwaiter().GetResult()
  if($proc.ExitCode -ne 0){throw 'The private junction fixture could not be created.'}
 } finally {$proc.Dispose()}
 Refuses {Assert-StationNoReparsePath (Join-Path $link 'new-child')}
 [IO.Directory]::Delete($target)
 Refuses {Assert-StationNoReparsePath (Join-Path $link 'new-child')}
 [IO.Directory]::Delete($link) # Remove the junction itself, never recurse through it.
 # Build only a DACL/owner fixture. Copying Get-Acl wholesale can also request
 # SACL privileges that an ordinary desktop account deliberately does not have.
 $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
 $acl=New-FixtureAcl $sid
 Set-Acl -LiteralPath $root -AclObject $acl
 Assert-StationPrivateAcl $root
 Check $true 'A genuinely owner/SYSTEM-only native ACL must pass.'
 $extra=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-11'),[Security.AccessControl.FileSystemRights]::Read,[Security.AccessControl.AccessControlType]::Allow)
 # Set-Acl mutates a persisted descriptor on Windows PowerShell 5.1. Use a
 # fresh DACL for this separate write; never request audit/SACL privileges.
 $acl=New-FixtureAcl $sid
 $acl.AddAccessRule($extra);Set-Acl -LiteralPath $root -AclObject $acl
 Refuses {Assert-StationPrivateAcl $root}
 Write-Output ('PASS '+$script:Cases+' actual Windows ACL/existing/dangling-junction assertions')
} finally {
 try {if(([IO.File]::GetAttributes($link) -band [IO.FileAttributes]::ReparsePoint) -ne 0){[IO.Directory]::Delete($link)}} catch [IO.FileNotFoundException] {} catch [IO.DirectoryNotFoundException] {}
 if([IO.Directory]::Exists($root)){[IO.Directory]::Delete($root,$true)}
}
