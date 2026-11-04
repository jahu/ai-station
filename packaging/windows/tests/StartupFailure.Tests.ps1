$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../DesktopProcess.psm1') -Force
Import-Module (Join-Path $PSScriptRoot '../DesktopResult.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if(-not $Condition){throw $Message};$script:Cases++ }
function Child([string]$Script) {
 $info=[Diagnostics.ProcessStartInfo]::new()
 $info.FileName=[Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
 $info.Arguments='-NoLogo -NoProfile -NonInteractive -EncodedCommand '+[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Script))
 $info.UseShellExecute=$false;$info.CreateNoWindow=$true
 $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
 return [Diagnostics.Process]::Start($info)
}
$code='Wsl/Service/CreateInstance/MountDisk/HCS/ERROR_SHARING_VIOLATION'
$secret='PRIVATE-BOOTSTRAP-TOKEN'
foreach($text in @($code,('Error code: '+$code),('Kod: '+$code),([string]::Join([string][char]0,('Error code: '+$code).ToCharArray())),($code+[char]13+[char]10),($code+[char]10))) {
 foreach($stream in @('stdout','stderr')) {
  $failure=$(if($stream -eq 'stdout'){New-StationWslFailure $text ''}else{New-StationWslFailure '' $text})
  $view=Get-StationFailurePresentation ([InvalidOperationException]::new('wrapped',$failure))
  Check ($view.Title -ceq 'Local data disk is busy') 'The stable WSL disk-lock code was lost through an exception wrapper.'
  Check ($view.Description -match 'restart Windows' -and $view.Details -notmatch $secret) 'Disk-lock guidance or private error handling differs.'
 }
}
foreach($text in @(('prefix '+$code),($code+'/extra'),('https://example.invalid/#'+$code),('x'*65537+$code))) {
 $failure=New-StationWslFailure $text ''
 Check ((Get-StationFailurePresentation $failure).Title -ceq 'Needs attention') 'An incomplete, oversized or non-error URL was accepted as a WSL code.'
}
foreach($stream in @('stdout','stderr')) {
 $payload='C:\Private-user\'+$secret+' https://127.0.0.1:8765/#setup='+$secret+[Environment]::NewLine+'Error code: '+$code
 $script=$(if($stream -eq 'stdout'){"[Console]::WriteLine('"+$payload+"');exit 7"}else{"[Console]::Error.WriteLine('"+$payload+"');exit 7"})
 $caught=$null
 try{Wait-StationWslProcess (Child $script)|Out-Null}catch{$caught=$_.Exception}
 Check ($null -ne $caught) 'A failed actual process was reported as successful.'
 $view=Get-StationFailurePresentation $caught
 Check ($view.Title -ceq 'Local data disk is busy') ('Actual failed process output lost its disk-lock explanation; title='+$view.Title)
 Check ($view.Details -notmatch $secret -and $view.Details -notmatch 'Private-user') 'Raw native output leaked into the user-facing error.'
}
$engine=[PowerShell]::Create()
try {
 [void]$engine.AddCommand('Import-Module').AddParameter('Name',(Join-Path $PSScriptRoot '../DesktopProcess.psm1'))
 [void]$engine.AddStatement()
 [void]$engine.AddCommand('Wait-StationWslProcess').AddParameter('Process',(Child ("[Console]::WriteLine('"+$code+"');exit 7")))
 $handle=$engine.BeginInvoke();$caught=$null
 try{Receive-StationActionResult $engine $handle|Out-Null}catch{$caught=$_.Exception}
 Check ($null -ne $caught -and (Get-StationFailurePresentation $caught).Title -ceq 'Local data disk is busy') 'Background native operation wrappers discarded the actionable failure.'
} finally {$engine.Dispose()}
$child=Child '[Threading.Thread]::Sleep(800);exit 7'
$drain=[Threading.Tasks.TaskCompletionSource[string]]::new()
try {
 $watch=[Diagnostics.Stopwatch]::StartNew()
 $pending=Get-StationDesktopCompletion $child $drain.Task $code
 Check (-not $pending.Completed -and $watch.ElapsedMilliseconds -lt 500 -and -not $child.HasExited) 'A live owned startup client was dropped or blocked the UI event loop.'
 Check ($child.WaitForExit(10000)) 'The disposable startup fixture did not exit normally.'
 $pending=Get-StationDesktopCompletion $child $drain.Task $code
 Check (-not $pending.Completed) 'Actual process exit was mistaken for completed diagnostic drain.'
 $drain.SetResult('Error code: '+$code)
 $done=Get-StationDesktopCompletion $child $drain.Task $code
 Check ($done.Completed -and (Get-StationFailurePresentation $done.Failure).Title -ceq 'Local data disk is busy') 'Pre-readiness completion lost the actionable failure.'
 $afterReady=Get-StationDesktopCompletion $child $drain.Task $code $true
 Check ($afterReady.Completed -and $null -eq $afterReady.Failure) 'A previously ready bridge was misclassified as a startup failure.'
} finally {
 if(-not $child.HasExited){$child.WaitForExit(10000)|Out-Null}
 $child.Dispose()
}
$child=Child 'exit 0'
$drain=[Threading.Tasks.TaskCompletionSource[string]]::new();$drain.SetResult($code)
try {
 Check ($child.WaitForExit(10000)) 'The zero-exit fixture did not complete.'
 $done=Get-StationDesktopCompletion $child $drain.Task $code
 Check ($done.Completed -and (Get-StationFailurePresentation $done.Failure).Title -ceq 'Needs attention') 'Success output without a readiness handoff must not fabricate a WSL disk error or startup success.'
} finally {$child.Dispose()}
Write-Output ('PASS '+$script:Cases+' startup failure/privacy/owned-completion assertions; no WSL, data-disk, service or OS setting changed')
