# Launch one harmless PowerShell child through the actual shared transport.
# Import only this module: caller-global imports must not supply dependencies.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot '../NativeGuest.psm1') -Force
$folder=Join-Path ([IO.Path]::GetTempPath()) ('station-guest-transport-'+[Guid]::NewGuid().ToString('N'))
[void][IO.Directory]::CreateDirectory($folder)
$process=$null;$old=$env:WSLENV
try{
 $env:WSLENV='SYNTHETIC_SHOULD_NOT_REACH_GUEST'
 $script='[Console]::WriteLine((@{fixture="native-transport";stdin_closed=($null -eq [Console]::ReadLine());no_forwarding=([string]::IsNullOrEmpty($env:WSLENV))}|ConvertTo-Json -Compress))'
 $encoded=[Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
 $binary=$(if($PSVersionTable.PSEdition -eq 'Desktop'){'powershell.exe'}elseif([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT){'pwsh.exe'}else{'pwsh'})
 $process=Start-StationWslProcess (Join-Path $PSHOME $binary) @('-NoProfile','-NonInteractive','-EncodedCommand',$encoded) $folder
 $read=$process.StandardOutput.ReadToEndAsync();$errors=$process.StandardError.ReadToEndAsync()
 if(-not $process.WaitForExit(30000)){throw 'The owned harmless transport child did not finish'}
 $body=$read.GetAwaiter().GetResult()|ConvertFrom-Json -ErrorAction Stop
 if($process.ExitCode -ne 0 -or $body.fixture -cne 'native-transport' -or $body.stdin_closed -isnot [bool] -or -not $body.stdin_closed -or $body.no_forwarding -isnot [bool] -or -not $body.no_forwarding -or $errors.GetAwaiter().GetResult()) {throw 'Shared transport changed framing, stdin lifetime or guest environment'}
 Write-Output 'PASS shared native transport with actual owned child; no WSL, installer or model was run'
}finally{
 $env:WSLENV=$old
 if($null -ne $process){try{if(-not $process.HasExited){$process.Kill();[void]$process.WaitForExit(10000)}}finally{$process.Dispose()}}
 [IO.Directory]::Delete($folder,$true)
}
