$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../DesktopResult.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if (-not $Condition) { throw $Message };$script:Cases++ }
function Run([string]$Source,[switch]$Reject) {
 $engine=[PowerShell]::Create()
 try {
  [void]$engine.AddScript($Source)
  $handle=$engine.BeginInvoke()
  if ($Reject) {
   $failed=$false
   try { Receive-StationActionResult $engine $handle | Out-Null } catch { $failed=$true }
   Check $failed 'Invalid/failed background output was accepted.'
  } else { return (Receive-StationActionResult $engine $handle) }
 } finally { $engine.Dispose() }
}
$record=Run '[pscustomobject]@{Status="ready";Distribution="AIStation-fixture"}'
Check ($record.Status -ceq 'ready') 'Preparation lost its runspace result.'
$text=Run '''{"running":false}'''
Check ($text -is [string] -and -not ($text|ConvertFrom-Json).running) 'Status lost its JSON string.'
$process=Run '[Diagnostics.Process]::GetCurrentProcess()'
try {
 Check ($process -is [Diagnostics.Process] -and $process.Id -eq $PID) 'Startup lost its native process object.'
} finally { $process.Dispose() } # Dispose the test handle only; never stop this or another process.
Run 'Write-Error "fixture failure";"ignored"' -Reject
Run '$null' -Reject
Run '"one";"two"' -Reject
Write-Output ('PASS '+$script:Cases+' actual background runspace results; native Windows UI remains unqualified')
