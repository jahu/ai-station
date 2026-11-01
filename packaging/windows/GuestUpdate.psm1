# Trusted native installer helpers; never exported through HTTP, Runner or agent tools.
Set-StrictMode -Version 2.0
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'InstallState.psm1')
Import-Module (Join-Path $PSScriptRoot 'GuestManifest.psm1')
Import-Module (Join-Path $PSScriptRoot 'DesktopProcess.psm1')

function Assert-StationUpdateRecipe {
 param($Previous,$Target)
 Assert-StationGuestManifest $Previous
 Assert-StationGuestManifest $Target
 if ($Previous.base -cne $Target.base) { throw 'This package needs a different guest OS. The existing distribution was preserved.' }
 foreach($name in @('guest.Dockerfile','wsl.conf','guest_control.py')) {
  if ($Previous.sources.$name -cne $Target.sources.$name) { throw 'A guest OS or bridge change needs its separately qualified migration.' }
 }
}

function Get-StationGuestUpdatePlan {
 param($State,[string]$Root,$Previous,$Target,[byte[]]$Program,[switch]$StablePython)
 Assert-StationInstallState $State $Root
 Assert-StationUpdateRecipe $Previous $Target
 if ($State.Phase -cne 'ready' -or $State.PackageSha256 -cne $Previous.package_sha256) { throw 'Verify the existing registered application before updating.' }
 if ($Target.PSObject.Properties.Name -notcontains 'package_bytes' -or $Target.package_bytes -is [bool] -or ($Target.package_bytes -isnot [int] -and $Target.package_bytes -isnot [long]) -or $Target.package_bytes -le 0 -or $Target.package_bytes -ge 1073741824 -or $Target.package_bytes -ne [long]$Target.package_bytes) { throw 'The update needs its complete checked application package.' }
 if ($Program.Length -le 0 -or $Program.Length -gt 65536) { throw 'The fixed updater exceeds its reviewed source bound.' }
 $buffer=[IO.MemoryStream]::new()
 try {
  $compress=[IO.Compression.GZipStream]::new($buffer,[IO.Compression.CompressionMode]::Compress,$true)
  try {$compress.Write($Program,0,$Program.Length)} finally {$compress.Dispose()}
  $encoded=[Convert]::ToBase64String($buffer.ToArray())
 } finally {$buffer.Dispose()}
 $code="exec(__import__('gzip').decompress(__import__('base64').b64decode('"+$encoded+"')))"
 $python=$(if($StablePython){'/var/lib/ai-station-updates/python/bin/python3'}else{'/usr/lib/ai-station/python/bin/python3'})
 $arguments=[string[]]@('--distribution',$State.Distribution,'--user','root','--exec',$python,'-IBS','-c',$code,$State.Distribution)
 if ((Format-StationWslArguments $arguments).Length -gt 30000) { throw 'The fixed Windows updater exceeds the native argument limit.' }
 $header=[Text.UTF8Encoding]::new($false,$true).GetBytes((@{previous=$Previous;target=$Target;package_bytes=[long]$Target.package_bytes}|ConvertTo-Json -Depth 8 -Compress)+"`n")
 if ($header.Length -gt 16384) { throw 'The update identity exceeds its private input limit.' }
 return [pscustomobject]@{Arguments=$arguments;Header=$header}
}

function Wait-StationUpdateInput {
 param([Threading.Tasks.Task]$Transfer,[Threading.CancellationToken]$CancellationToken)
 # Windows PowerShell's synchronous anonymous pipes do not interrupt a pending
 # WriteAsync/CopyToAsync when its token is canceled. Keep the owner responsive;
 # its finally block closes the exact child, unblocking the pending pipe write.
 while (-not $Transfer.IsCompleted) {
  $CancellationToken.ThrowIfCancellationRequested()
  [Threading.Thread]::Sleep(25)
 }
 $CancellationToken.ThrowIfCancellationRequested()
 [void]$Transfer.GetAwaiter().GetResult()
}

function Send-StationGuestUpdate {
 param($Process,$Archive,[byte[]]$Header,[Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
 $deadline=[Threading.CancellationTokenSource]::CreateLinkedTokenSource($CancellationToken)
 $deadline.CancelAfter([TimeSpan]::FromMinutes(15))
 $waiting=$false
 try {
  $deadline.Token.ThrowIfCancellationRequested()
  $headerTransfer=$Process.StandardInput.BaseStream.WriteAsync($Header,0,$Header.Length,$deadline.Token)
  Wait-StationUpdateInput $headerTransfer $deadline.Token
  $transfer=$Archive.Stream.CopyToAsync($Process.StandardInput.BaseStream,65536,$deadline.Token)
  Wait-StationUpdateInput $transfer $deadline.Token
  $Process.StandardInput.Close()
  $waiting=$true # Wait owns this exact client and its disposal from this point.
  $text=Wait-StationWslProcess $Process -KeepOutput $true -CancellationToken $deadline.Token
  $result=$text|ConvertFrom-Json -ErrorAction Stop
  if ((@($result.PSObject.Properties.Name|Sort-Object)-join '|') -cne 'backup_available|data_preserved|status' -or $result.status -cne 'updated' -or $result.data_preserved -isnot [bool] -or -not $result.data_preserved -or $result.backup_available -isnot [bool]) { throw 'The guest did not confirm the exact preserved-data update. Inspect before starting.' }
  return $result
 } finally {
  if (-not $waiting) {
   try {
    # Closing a stream first can itself wait for the blocked native pipe write.
    # Reap only our saved process handle before disposing that stream.
    if (-not $Process.HasExited) {
     try { $Process.Kill() } catch { if (-not $Process.HasExited) { throw } }
    }
    if (-not $Process.WaitForExit(10000)) { throw 'The update client is still stopping. Preserve its recorded operation and inspect.' }
   } finally {
    try { $Process.StandardInput.Close() } finally { $Process.Dispose() }
   }
  }
  $deadline.Dispose()
 }
}

Export-ModuleMember -Function Assert-StationUpdateRecipe,Get-StationGuestUpdatePlan,Send-StationGuestUpdate
