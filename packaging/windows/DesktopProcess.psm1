# Private native installer subprocess supervision, never a workload command API.
function Wait-StationWslProcess {
    param($Process,[bool]$KeepOutput=$false,
          [Threading.CancellationToken]$CancellationToken=[Threading.CancellationToken]::None)
    $output=$Process.StandardOutput.ReadToEndAsync()
    $errors=$Process.StandardError.ReadToEndAsync()
    try {
        while (-not $Process.WaitForExit(200)) { $CancellationToken.ThrowIfCancellationRequested() }
        $CancellationToken.ThrowIfCancellationRequested()
        $text=$output.GetAwaiter().GetResult();[void]$errors.GetAwaiter().GetResult()
        if ($Process.ExitCode -ne 0) { throw 'The Windows preparation step did not finish. Saved state and guest data were retained; check preparation before retrying.' }
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
Export-ModuleMember -Function Wait-StationWslProcess
