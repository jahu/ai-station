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
 $lease=New-StationPrivateStore
 try {$acl=Get-Acl -LiteralPath $lease.Root} finally {$lease.Stream.Dispose()}
 Set-Acl -LiteralPath $root -AclObject $acl
 Assert-StationPrivateAcl $root
 Check $true 'A genuinely owner/SYSTEM-only native ACL must pass.'
 $extra=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new('S-1-5-11'),[Security.AccessControl.FileSystemRights]::Read,[Security.AccessControl.AccessControlType]::Allow)
 $acl.AddAccessRule($extra);Set-Acl -LiteralPath $root -AclObject $acl
 Refuses {Assert-StationPrivateAcl $root}
 Write-Output ('PASS '+$script:Cases+' actual Windows ACL/existing/dangling-junction assertions')
} finally {
 try {if(([IO.File]::GetAttributes($link) -band [IO.FileAttributes]::ReparsePoint) -ne 0){[IO.Directory]::Delete($link)}} catch [IO.FileNotFoundException] {} catch [IO.DirectoryNotFoundException] {}
 if([IO.Directory]::Exists($root)){[IO.Directory]::Delete($root,$true)}
}
