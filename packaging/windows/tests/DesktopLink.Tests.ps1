param([string]$ProbeUrl='',[string]$ExpectedIdentity='', [switch]$RejectProbe)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../DesktopLink.psm1') -Force
$script:Cases=0
function Check($Condition,[string]$Message) { if (-not $Condition) { throw $Message };$script:Cases++ }
function Refuses([scriptblock]$Action) { $failed=$false;try { & $Action | Out-Null } catch { $failed=$true };Check $failed 'The private browser handoff was incorrectly accepted.' }
function Frame([string]$Url,[string]$Id=('a'*32)) { return ('AI_STATION_READY '+(@{url=$Url;instance_id=$Id}|ConvertTo-Json -Compress)) }
$url='http://127.0.0.1:8766/#/setup/models?setup_token='+('z'*43)
$ready=Read-StationReadyFrame (Frame $url)
Check ($ready.Url -ceq $url -and $ready.InstanceId -ceq ('a'*32)) 'The private handoff must retain its exact URL and identity.'
Check ($null -eq (Read-StationReadyFrame 'Starting your local station')) 'Ordinary stages must not become browser authority.'
foreach ($bad in @('https://127.0.0.1:8766/','http://evil.example:8766/','http://127.0.0.1:80/','http://user:pass@127.0.0.1:8766/','http://127.0.0.1:8766/other','http://127.0.0.1:8766/?setup_token=abc','http://127.0.0.1:8766/#/javascript','http://127.0.0.1:8766/#/setup/models?setup_token=short','http://127.0.0.1.example:8766/')) { Refuses { Read-StationReadyFrame (Frame $bad) } }
Refuses { Read-StationReadyFrame (Frame $url 'short') }
Refuses { Read-StationReadyFrame ('AI_STATION_READY '+(@{url=$url}|ConvertTo-Json -Compress)) }
Refuses { Read-StationReadyFrame ('AI_STATION_READY '+(@{url=$url;instance_id=('a'*32);command='anything'}|ConvertTo-Json -Compress)) }
Refuses { Read-StationReadyFrame ('x'*4097) }
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { Refuses { Open-StationBrowser $ready } }
if ($ProbeUrl) {
 $target=Read-StationReadyFrame (Frame $ProbeUrl $ExpectedIdentity)
 if ($RejectProbe) { Refuses { Confirm-StationBrowserTarget $target } } else { Confirm-StationBrowserTarget $target;Check $true 'Expected instance must pass actual HTTP verification.' }
}
Write-Output ('PASS '+$script:Cases+' desktop handoff assertions; native Windows browser rendering remains pending')
