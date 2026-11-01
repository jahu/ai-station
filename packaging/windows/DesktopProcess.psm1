# Private native installer subprocess supervision, never a workload command API.
function Format-StationWslArguments {
    param([Parameter(Mandatory=$true)][string[]]$Arguments)
    $parts=@()
    foreach($value in $Arguments) {
        if ([string]::IsNullOrEmpty($value) -or $value -match '["\x00-\x1f]' -or $value.EndsWith('\')) { throw 'Invalid argument in the fixed WSL operation.' }
        # WSL's Windows parser does not recognize quoted switches as options.
        # Quote only whitespace-bearing data (such as the private archive path).
        if($value -match '\s') { $parts+=('"'+$value+'"') } else { $parts+=$value }
    }
    return ($parts -join ' ')
}

function New-StationWslFailure {
    param([string]$StandardOutput='', [string]$StandardError='',
          [string]$Fallback='The Windows preparation step did not finish. Saved state and guest data were retained; check preparation before retrying.')
    $busy=$false
    foreach($stream in @($StandardOutput,$StandardError)) {
        # Some Windows WSL errors arrive as NUL-padded UTF-16 text while Linux
        # bridge replies use UTF-8. Match only a complete, stable machine-code
        # line, never a local path, setup link or translated human description.
        if($stream.Length -gt 65536) { continue }
        $text=$stream.Replace([string][char]0,'')
        if($text -match '(?im)^[ \t]*(?:[^\r\n:]{1,80}:[ \t]*)?Wsl/Service/CreateInstance/MountDisk/HCS/ERROR_SHARING_VIOLATION[ \t]*\r?$') { $busy=$true }
    }
    if($busy) {
        $failure=[InvalidOperationException]::new('Windows cannot open AI Station''s local data disk because it is in use. Close backup or disk tools and try again. If it stays busy, save other work and restart Windows, then reopen AI Station. Keep the existing installation and data folder.')
        $failure.Data['AIStationWslFailure']='disk_busy'
        return $failure
    }
    return [InvalidOperationException]::new($Fallback)
}

function Wait-StationWslProcess {
    param($Process,[bool]$KeepOutput=$false,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
    $output=$Process.StandardOutput.ReadToEndAsync()
    $errors=$Process.StandardError.ReadToEndAsync()
    try {
        while (-not $Process.WaitForExit(200)) { $CancellationToken.ThrowIfCancellationRequested() }
        $CancellationToken.ThrowIfCancellationRequested()
        $text=$output.GetAwaiter().GetResult();$errorText=$errors.GetAwaiter().GetResult()
        if ($Process.ExitCode -ne 0) { throw (New-StationWslFailure $text $errorText) }
        if ($KeepOutput) {
            if ([Text.Encoding]::UTF8.GetByteCount($text) -gt 16384) { throw 'The fixed WSL response exceeds its expected size.' }
            return $text
        }
    } catch {
        if ($CancellationToken.IsCancellationRequested) {
            # This is only the process handle returned by our own fixed launch.
            # WSL's service may finish an import independently: preserve the
            # importing receipt and reconcile it; never terminate/unregister a distro.
            if (-not $Process.HasExited) { $Process.Kill() }
            if (-not $Process.WaitForExit(10000)) { throw 'The setup client is still stopping. Preserve this installation and inspect before retrying.' }
            throw [OperationCanceledException]::new('Setup canceled. Saved files were preserved; choose Prepare to inspect or resume.')
        }
        throw
    } finally { $Process.Dispose() }
}
Export-ModuleMember -Function Wait-StationWslProcess,Format-StationWslArguments,New-StationWslFailure
