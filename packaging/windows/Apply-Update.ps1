# Independent fixed native update owner. Inputs come only from the SID-private journal.
param([switch]$FinishGuest)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'AutomaticUpdate.psm1')
try{
 if($FinishGuest){Complete-StationAutomaticGuestUpdate}else{Invoke-StationAutomaticUpdate}
}catch{
 # Keep diagnostics local; normal UI/Run status uses the fixed user-safe error.
 Import-Module (Join-Path $PSScriptRoot 'PrivateStore.psm1')
 $root=[IO.Path]::Combine([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData),'AIStation-Desktop','automatic-updates')
 Assert-StationPrivateAcl $root
 $path=[IO.Path]::Combine($root,'native-error.log')
 if([IO.File]::Exists($path)){Assert-StationPrivateAcl $path}
 $message=$_.Exception.ToString()+[Environment]::NewLine+$_.ScriptStackTrace
 if($message.Length -gt 16384){$message=$message.Substring(0,16384)}
 [IO.File]::WriteAllText($path,$message,[Text.UTF8Encoding]::new($false))
 exit 1
}
