# Invoked only by this application's own uninstaller, never a workload or web tool.
param([switch]$ValidateOnly)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'PrivateStore.psm1')
Import-Module (Join-Path $PSScriptRoot 'Setup.psm1')
try {
 if ($ValidateOnly) { $lease=Open-StationUiLease;$lease.Dispose();exit 0 }
 $recordPath=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'AIStation-Desktop\install-state.json'
 if (-not [IO.File]::Exists($recordPath)) { exit 0 }
 $record=[IO.File]::ReadAllText($recordPath,[Text.UTF8Encoding]::new($false,$true)) | ConvertFrom-Json -ErrorAction Stop
 if ($record.State.Phase -notin @('registered','ready')) { throw 'Finish or inspect the interrupted preparation before removing its program files.' }
 $current=(Invoke-StationDesktop 'status') | ConvertFrom-Json -ErrorAction Stop
 if ($current.PSObject.Properties.Name -contains 'inspection_required' -and $current.inspection_required) { throw 'Inspect the still-active supervisor before uninstalling.' }
 if ($current.running -isnot [bool]) { throw 'The station state could not be confirmed.' }
 if ($current.running) {
  [void](Invoke-StationDesktop 'stop')
  $deadline=[DateTime]::UtcNow.AddSeconds(60)
  do {
   Start-Sleep -Milliseconds 500
   $current=(Invoke-StationDesktop 'status') | ConvertFrom-Json -ErrorAction Stop
   if ($current.PSObject.Properties.Name -contains 'inspection_required' -and $current.inspection_required) { throw 'The supervisor still requires inspection.' }
   if ($current.running -isnot [bool]) { throw 'The station state could not be confirmed.' }
  } while ($current.running -and [DateTime]::UtcNow -lt $deadline)
  if ($current.running) { throw 'The station is still stopping; program files were retained.' }
 }
 exit 0
} catch { exit 1 } # No private replies or setup authority enter installer logs.
