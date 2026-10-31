$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../DesktopProcess.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../DesktopResult.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if (-not $Condition) { throw $Message };$script:Cases++ }
function Child([string]$Script) {
 $info=[Diagnostics.ProcessStartInfo]::new()
 $info.FileName=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
 $info.Arguments='-NoLogo -NoProfile -NonInteractive -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardInput=$true;$info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 $p=[Diagnostics.Process]::Start($info);$p.StandardInput.Close();return $p
}
Check ((Wait-StationWslProcess (Child 'Write-Output ''ready''') -KeepOutput $true).Trim() -ceq 'ready') 'The actual native process output was lost.'
foreach($script in @('exit 7','Write-Output (''x''*17000)')) {
 $failed=$false
 try { Wait-StationWslProcess (Child $script) -KeepOutput $true | Out-Null } catch { $failed=$true }
 Check $failed 'A failed or oversized actual subprocess reply was accepted.'
}
$other=Child '[Threading.Thread]::Sleep(30000)'
$client=Child '[Threading.Thread]::Sleep(30000)'
$observer=[Diagnostics.Process]::GetProcessById($client.Id)
$cancel=[Threading.CancellationTokenSource]::new()
try {
 $cancel.CancelAfter(200);$failed=$false
 try { Wait-StationWslProcess $client -CancellationToken $cancel.Token } catch {
  $cause=$_.Exception
  while($null -ne $cause) { if($cause -is [OperationCanceledException]){$failed=$true;break};$cause=$cause.InnerException }
 }
 Check $failed 'The canceled owned client must return a cancellation, not a success.'
 Check $observer.WaitForExit(2000) 'Cancellation left its actual owned client running.'
 Check (-not $other.HasExited) 'Cancellation stopped an unrelated fixture process.'
} finally {
 if(-not $other.HasExited){$other.Kill();$other.WaitForExit()}
 if(-not $observer.HasExited){$observer.Kill();$observer.WaitForExit()}
 $observer.Dispose();$other.Dispose();$cancel.Dispose()
}
$engine=[PowerShell]::Create();$cancel=[Threading.CancellationTokenSource]::new()
$client=Child '[Threading.Thread]::Sleep(30000)'
$observer=[Diagnostics.Process]::GetProcessById($client.Id)
try {
 [void]$engine.AddCommand('Import-Module').AddParameter('Name',(Join-Path $PSScriptRoot '../DesktopProcess.psm1'))
 [void]$engine.AddStatement()
 [void]$engine.AddCommand('Wait-StationWslProcess').AddParameter('Process',$client).AddParameter('CancellationToken',$cancel.Token)
 $handle=$engine.BeginInvoke();$cancel.CancelAfter(200);$failed=$false
 try { Receive-StationActionResult $engine $handle | Out-Null } catch {
  $cause=$_.Exception
  while($null -ne $cause) { if($cause -is [OperationCanceledException]){$failed=$true;break};$cause=$cause.InnerException }
 }
 Check ($failed -and $observer.WaitForExit(2000)) 'The actual background runspace lost its cancellation or left the client alive.'
} finally {
 if(-not $observer.HasExited){$observer.Kill();$observer.WaitForExit()}
 $observer.Dispose();$cancel.Dispose();$engine.Dispose()
}
Write-Output ('PASS '+$script:Cases+' actual native process/drain/cancellation assertions; no WSL or host features changed')
