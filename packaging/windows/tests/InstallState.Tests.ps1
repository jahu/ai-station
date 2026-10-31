$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../InstallState.psm1') -Force
$script:Cases = 0
function Check($Condition, [string]$Message) { if (-not $Condition) { throw $Message }; $script:Cases++ }
function Refuses([scriptblock]$Action) { $failed=$false; try { & $Action | Out-Null } catch { $failed=$true }; Check $failed 'Expected an unsafe plan to be rejected.' }
$root = 'C:\Users\Operator Łódź\AppData\Local\AI Station'
$archive = 'D:\Downloads\AI Station\rootfs.tar.gz'
$state = New-StationInstallState $root ('a' * 64)
Check ($state.Distribution -cmatch '^AIStation-[a-f0-9]{32}$') 'Distribution identity must be random and scoped.'
Assert-StationInstallState $state $root
$plan = Get-StationImportPlan $state $root $archive
Check ($plan.Kind -eq 'Import' -and $plan.Arguments.Count -eq 6 -and $plan.Arguments[2] -eq ($root+'\guest')) 'Import must target only the private recorded folder.'
Check ($plan.Arguments[-1] -eq '2') 'Import must explicitly request WSL2.'
Check ((Get-StationImportPlan $state $root $archive -ExistingDisk $true).Kind -eq 'InspectIncompleteDisk') 'Existing incomplete disks must not be overwritten.'
$entry = [pscustomobject]@{ DistributionName=$state.Distribution; BasePath=$state.Directory; Version=2; Id='{12345678-1234-1234-1234-123456789abc}' }
Check ((Get-StationImportPlan $state $root $archive -Inventory @($entry)).Kind -eq 'VerifyGuest') 'Interrupted import must verify its matching guest before use.'
$foreign = [pscustomobject]@{ DistributionName='Ubuntu'; BasePath=$state.Directory; Version=2; Id=$entry.Id }
Refuses { Get-StationImportPlan $state $root $archive -Inventory @($foreign) }
$wrong = [pscustomobject]@{ DistributionName=$state.Distribution; BasePath='C:\Unrelated'; Version=2; Id=$entry.Id }
Refuses { Get-StationImportPlan $state $root $archive -Inventory @($wrong) }
$old = [pscustomobject]@{ DistributionName=$state.Distribution; BasePath=$state.Directory; Version=1; Id=$entry.Id }
Refuses { Get-StationImportPlan $state $root $archive -Inventory @($old) }
Refuses { Get-StationImportPlan $state $root $archive -Inventory @($entry,$entry) }
Refuses { Get-StationLifecyclePlan $state $root start }
$state.RegistrationId=$entry.Id; $state.Phase='ready'
foreach ($action in @('start','status','open','stop')) {
 $args=Get-StationLifecyclePlan $state $root $action
 Check (($args -join '|') -ceq ('--distribution|'+$state.Distribution+'|--user|station|--exec|/usr/libexec/ai-station/wsl-control|'+$action)) 'Lifecycle must use the fixed ordinary-user bridge without shell/PID/URL arguments.'
}
Refuses { Get-StationLifecyclePlan $state $root shutdown }
Refuses { Get-StationImportPlan $state $root $archive }
Refuses { Get-StationLifecyclePlan $state 'C:\Other' start }
$replacement=[pscustomobject]@{ DistributionName=$state.Distribution; BasePath=$state.Directory; Version=2; Id='{abcdefab-1234-1234-1234-123456789abc}' }
Refuses { Get-StationImportPlan $state $root $archive -Inventory @($replacement) }
foreach ($unsafe in @('relative','\\server\share\app','C:\app\..\foreign','C:\app\NUL.txt','C:\app\folder.','C:\app\file:stream','C:\app\a"b',"C:\app\line`nfeed")) { Refuses { ConvertTo-StationWindowsPath $unsafe } }
$bad = $state | ConvertTo-Json | ConvertFrom-Json; $bad.Distribution='Ubuntu'
Refuses { Get-StationLifecyclePlan $bad $root stop }
$bad = $state | ConvertTo-Json | ConvertFrom-Json; $bad | Add-Member -NotePropertyName Command -NotePropertyValue 'anything'
Refuses { Get-StationLifecyclePlan $bad $root start }
Check ((ConvertTo-StationWindowsPath ('\\?\' + $root)) -eq $root) 'Extended local registry paths must reconcile to the same private drive path.'
Refuses { ConvertTo-StationWindowsPath '\\?\GLOBALROOT\Device\HarddiskVolume1' }
$bad = $state | ConvertTo-Json | ConvertFrom-Json; $bad.Schema=$true
Refuses { Get-StationLifecyclePlan $bad $root start }
Write-Output ('PASS '+$script:Cases+' native PowerShell ownership/command-planning assertions; Windows OS qualification remains pending')
