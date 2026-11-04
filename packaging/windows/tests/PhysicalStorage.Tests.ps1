$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../Setup.psm1') -Force
$module=Get-Module Setup
& $module {
 $script:Cases=0
 function Check($Value,[string]$Reason){if(-not $Value){throw $Reason};$script:Cases++}
 if([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
  # Real, read-only Windows quota observation under the ordinary current user.
  $volume=Get-StationPhysicalVolume $env:LOCALAPPDATA
  Check ($volume.Total -gt 0 -and $volume.Free -ge 0 -and $volume.Free -le $volume.Total) 'Invalid actual Windows capacity'
 }
 $script:Seen=@();$script:Present=$true;$script:Reply='{"status":"observed"}'
 $record=[pscustomobject]@{State=[pscustomobject]@{Directory='C:\Private\guest';Distribution='AIStation-private-fixture'}}
 $lease=[pscustomobject]@{Root='C:\Private'}
 function script:Get-StationPhysicalVolume {param($Directory);Check ($Directory -ceq 'C:\Private\guest') 'Observed an unrelated volume';return [pscustomobject]@{Total=[long]100000000000;Free=[long]20000000000}}
 function script:Test-StationFixedGuestFile {param($Lease,$Record,$Executable,$Path,[switch]$ExecutableFile,[switch]$RootUser);Check ($Path -ceq '/usr/lib/ai-station/host-runner/ai_station_runner/windows_storage.py' -and -not $RootUser) 'Unexpected helper inspection';return $script:Present}
 function script:Start-StationWslProcess {param($Executable,$Arguments,$Directory);$script:Seen+=,@($Arguments);return [pscustomobject]@{Arguments=$Arguments}}
 function script:Wait-StationWslProcess {param($Process,[bool]$KeepOutput,$CancellationToken);Check $KeepOutput 'Missing fixed helper receipt';return $script:Reply}
 $observed=Update-StationPhysicalStorage $lease $record 'fixed-wsl.exe'
 Check ($observed -is [bool] -and $observed) 'Successful observation was not confirmed'
 Check ($script:Seen.Count -eq 1) 'Missing capacity observation'
 $expected=@('--distribution','AIStation-private-fixture','--user','station','--exec','/usr/lib/ai-station/python/bin/python3','-IBS','/usr/lib/ai-station/host-runner/ai_station_runner/windows_storage.py','100000000000','20000000000')
 Check (($script:Seen[0] -join '|') -ceq ($expected -join '|')) 'Capacity operation exposed a path, shell or root execution'
 $script:Present=$false
 $observed=Update-StationPhysicalStorage $lease $record 'fixed-wsl.exe'
 Check ($observed -is [bool] -and -not $observed) 'Old guest falsely confirmed a capacity observation'
 Check ($script:Seen.Count -eq 1) 'Old guest received an unsupported helper operation'
 $script:Present=$true;$script:Reply='{"status":"other"}';$failed=$false
 try{Update-StationPhysicalStorage $lease $record 'fixed-wsl.exe'}catch{$failed=$true}
 Check $failed 'Unconfirmed helper reply was accepted'
 Write-Output ('PASS '+$script:Cases+' fixed capacity transport assertions; ordinary Windows quota read when available; fake WSL only')
}
