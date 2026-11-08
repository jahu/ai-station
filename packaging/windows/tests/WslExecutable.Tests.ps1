$ErrorActionPreference='Stop'
$module=Import-Module (Join-Path $PSScriptRoot '../NativeWsl.psm1') -Force -PassThru
& $module {
 $root=Join-Path ([IO.Path]::GetTempPath()) ('station-wsl-selection-'+[guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($root)
 $system=Join-Path $root 'system-wsl.exe';$modern=Join-Path $root 'modern-wsl.exe';[IO.File]::WriteAllText($system,'Not an executable; never launched.')
 $script:signature='Valid';$script:subject='CN=Microsoft Windows, O=Microsoft Corporation, C=US';$cases=0
 function script:Get-AuthenticodeSignature {param($LiteralPath,$ErrorAction);return [pscustomobject]@{Status=$script:signature;SignerCertificate=[pscustomobject]@{Subject=$script:subject}}}
 try {
  if((Select-StationWslExecutable @($modern,$system)) -cne $system){throw 'System WSL fallback failed'};$cases++
  [IO.File]::WriteAllText($modern,'Not an executable; never launched.')
  if((Select-StationWslExecutable @($modern,$system)) -cne $modern){throw 'Current Microsoft MSI launcher was not preferred to the legacy system stub'};$cases++
  foreach($bad in @('NotSigned','HashMismatch','UnknownError')){
   $script:signature=$bad;$failed=$false;try{Select-StationWslExecutable @($modern,$system)|Out-Null}catch{$failed=$_.Exception.Message -like '*signature*'}
   if(-not $failed){throw 'An untrusted preferred launcher was silently bypassed'};$cases++
  }
  $script:signature='Valid';$script:subject='CN=Fixture, O=Another Publisher';$failed=$false;try{Select-StationWslExecutable @($modern,$system)|Out-Null}catch{$failed=$true}
  if(-not $failed){throw 'A different publisher was admitted'};$cases++
  [IO.File]::Delete($modern);[IO.File]::Delete($system);$failure=$null;try{Select-StationWslExecutable @($modern,$system)|Out-Null}catch{$failure=$_.Exception}
  if($null -eq $failure -or $failure.Data['AIStationWslAction'] -cne 'install'){throw 'Missing launchers lost installation guidance'};$cases++
 } finally {[IO.Directory]::Delete($root,$true)}
 Write-Output ('PASS '+$cases+' deterministic Microsoft WSL selection/trust cases; no executable launched')
}
