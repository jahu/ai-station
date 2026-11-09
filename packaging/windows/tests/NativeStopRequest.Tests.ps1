$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$source=[IO.File]::ReadAllText((Join-Path $PSScriptRoot '../WindowsSetup.ps1'),[Text.UTF8Encoding]::new($false,$true))
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if($errors.Count){throw 'The actual native UI source did not parse'}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Invoke-StationPendingStop'},$true)
. ([scriptblock]::Create($function.Extent.Text))
$script:stops=0;$script:closes=0
$status=[pscustomobject]@{Text=''}
$form=[pscustomobject]@{}
$form|Add-Member -MemberType ScriptMethod -Name Close -Value {$script:closes++}
function Begin-StationAction($Action){if($Action -cne 'stop'){throw 'Exit dispatched startup or another action'};$script:stops++;$script:worker=[pscustomobject]@{Action=$Action}}
$script:exitAfterStop=$true;$script:stopPending=$false;$script:allowExit=$false;$script:running=$true;$script:station=$null
$script:worker=[pscustomobject]@{Action='status'}
Invoke-StationPendingStop
if($script:stops -or $script:closes -or -not $script:exitAfterStop){throw 'A busy status job lost or prematurely dispatched the tray Stop request'}
$script:worker=$null
Invoke-StationPendingStop
Invoke-StationPendingStop
if($script:stops -ne 1 -or $script:closes){throw 'The deferred tray request did not dispatch exactly one normal Stop'}
$script:worker=$null;$script:stopPending=$true
Invoke-StationPendingStop
if($script:stops -ne 1 -or $script:closes){throw 'Stop was replayed while shutdown remained pending'}
$script:stopPending=$false;$script:running=$false;$script:station=[pscustomobject]@{}
Invoke-StationPendingStop
if($script:closes -or $status.Text -cne 'Finishing startup before stopping'){throw 'Exit abandoned a live startup client'}
$script:station=$null
Invoke-StationPendingStop
if($script:closes -ne 1 -or -not $script:allowExit){throw 'Confirmed shutdown did not release the native window'}
Invoke-StationPendingStop
if($script:closes -ne 1){throw 'The confirmed exit closed the window twice'}
$script:exitAfterStop=$false;$script:running=$true
Invoke-StationPendingStop
if($script:stops -ne 1){throw 'The native window stopped without an explicit exit request'}
Write-Output 'PASS actual native UI deferred Stop policy; no OS process or installer launched'
