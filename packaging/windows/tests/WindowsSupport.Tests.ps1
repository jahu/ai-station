# No elevation, network, WSL or OS feature mutation in normal tests.
$ErrorActionPreference='Stop'
$module=Import-Module (Join-Path $PSScriptRoot '../WindowsSupport.psm1') -Force -PassThru
& $module {
 $script:Cases=0
 function Check($condition,[string]$message){if(-not $condition){throw $message};$script:Cases++}
 $recipe=Get-StationWslInstallerRecipe
 Check ($recipe.Url -ceq 'https://github.com/microsoft/WSL/releases/download/3.0.3/wsl.3.0.3.0.x64.msi' -and $recipe.Bytes -eq 367575040 -and $recipe.Sha256 -ceq 'ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211') 'The reviewed Microsoft prerequisite recipe changed.'
 $script:events=[Collections.Generic.List[string]]::new();$script:modern=$true;$script:admin=$true;$script:badHash=$false;$script:badSignature=$false;$script:restart=$false
 function script:Assert-StationWindowsPreparationReady {}
 function script:Assert-StationWindowsSupportAdmin {if(-not $script:admin){throw 'No Windows consent'}}
 function script:Test-StationModernWsl {return $script:modern}
 function script:Receive-StationWslInstaller {param($Path,$Recipe);$script:events.Add('download')}
 function script:Open-StationVerifiedArchive {param($Path,$Sha256,$Bytes);$script:events.Add('hash');if($script:badHash){throw 'Wrong hash'};return [pscustomobject]@{Stream=[IO.MemoryStream]::new()}}
 function script:Assert-StationWslInstallerSignature {param($Path);$script:events.Add('signature');if($script:badSignature){throw 'Wrong signer'}}
 function script:Assert-StationNoReparsePath {param($Path)}
 function script:Invoke-StationWindowsFeature {param($Name);$script:events.Add($Name);return $script:restart}
 function script:Install-StationWslInstaller {param($Path);$script:events.Add('install');return $false}
 # Use a fresh empty fixture directory so cleanup never touches ambient temp files.
 $fixture=Join-Path ([IO.Path]::GetTempPath()) ('station-support-'+[guid]::NewGuid().ToString('N'));[void][IO.Directory]::CreateDirectory($fixture)
 function script:New-StationWindowsSupportDirectory {[void][IO.Directory]::CreateDirectory($fixture);return $fixture}
 try {
  $result=Invoke-StationWindowsSupport
  Check (-not $result.WslInstalled -and -not $result.RestartRequired) 'Existing modern WSL was replaced or an automatic restart invented.'
  Check (($script:events -join '|') -ceq 'VirtualMachinePlatform|Microsoft-Windows-Subsystem-Linux') 'Modern WSL was downloaded or changed unnecessarily.'
  $script:events.Clear();$script:admin=$false;$failed=$false
  try{Invoke-StationWindowsSupport|Out-Null}catch{$failed=$true}
  Check ($failed -and $script:events.Count -eq 0) 'Prerequisite changes began without Windows permission.'
  $script:admin=$true;$script:modern=$false;$script:badHash=$true;$failed=$false
  try{Invoke-StationWindowsSupport|Out-Null}catch{$failed=$true}
  Check ($failed -and ($script:events -join '|') -ceq 'download|hash') 'Features changed or code executed after a checksum failure.'
  $script:events.Clear();$script:badHash=$false;$script:badSignature=$true;$failed=$false
  try{Invoke-StationWindowsSupport|Out-Null}catch{$failed=$true}
  Check ($failed -and ($script:events -join '|') -ceq 'download|hash|signature') 'Features changed or MSI ran without a verified Microsoft signer.'
  $script:events.Clear();$script:badSignature=$false;$script:restart=$true
  $result=Invoke-StationWindowsSupport
  Check ($result.WslInstalled -and $result.RestartRequired) 'WSL preparation lost the explicit reboot requirement.'
  Check (($script:events -join '|') -ceq 'download|hash|signature|VirtualMachinePlatform|Microsoft-Windows-Subsystem-Linux|install') 'Windows changes must follow verified input and use only fixed feature names.'
  Check (-not [IO.Directory]::Exists($fixture)) 'Empty owned staging directory was not cleaned.'
 } finally {if([IO.Directory]::Exists($fixture)){[IO.Directory]::Delete($fixture)}}
 Write-Output ('PASS '+$script:Cases+' prerequisite consent, reuse, integrity, ordering and cleanup cases; no OS changes')
}
