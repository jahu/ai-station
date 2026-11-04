# Complete the private background runspace without losing PowerShell's wrapped
# native process/string results. This module has no Windows or UI side effects.
Import-Module (Join-Path $PSScriptRoot 'DesktopProcess.psm1')

function Get-StationFailurePresentation {
    param($Failure)
    $message=$(if($Failure -is [Exception]) {$Failure.Message} else {[string]$Failure})
    $cause=$Failure
    for($depth=0; $depth -lt 16 -and $cause -is [Exception]; $depth++) {
        if($cause.Data['AIStationWslFailure'] -ceq 'disk_busy') {
            return [pscustomobject]@{
                Title='Local data disk is busy'
                Description='Close backup or disk tools and try again. If it stays busy, save other work and restart Windows, then reopen AI Station.'
                Details=$cause.Message
            }
        }
        $cause=$cause.InnerException
    }
    return [pscustomobject]@{
        Title='Needs attention'
        Description='Your saved work is preserved. Try again, or check Windows support. Details can help diagnose the problem.'
        Details=$message
    }
}

function Get-StationDesktopCompletion {
    param([Parameter(Mandatory=$true)]$Process,[Parameter(Mandatory=$true)]$ErrorTask,
          [string]$Output='', [bool]$Ready=$false)
    # Ready means a validated handoff was observed during this client's lifetime,
    # even if a subsequent normal Stop/status has cleared the current UI link.
    # EOF is not evidence that the owned process or its diagnostic pipe ended.
    # The UI polls these facts; it never blocks its event loop or drops a live
    # client in order to try another startup.
    if(-not $Process.HasExited -or -not $ErrorTask.IsCompleted) {
        return [pscustomobject]@{Completed=$false;Failure=$null}
    }
    $failure=$null
    if(-not $Ready) {
        $fallback='The station stopped before its browser connection became ready.'
        $errorText=''
        try { $errorText=$ErrorTask.GetAwaiter().GetResult() } catch {}
        $failure=$(if($Process.ExitCode -ne 0) {New-StationWslFailure $Output $errorText $fallback} else {[InvalidOperationException]::new($fallback)})
    }
    return [pscustomobject]@{Completed=$true;Failure=$failure}
}

function Receive-StationActionResult {
    param([Parameter(Mandatory=$true)]$Engine,[Parameter(Mandatory=$true)]$Handle)
    $values=$Engine.EndInvoke($Handle)
    if ($Engine.Streams.Error.Count -gt 0) { throw $Engine.Streams.Error[0] }
    if ($values.Count -ne 1 -or $null -eq $values[0]) { throw 'The background operation did not return one lifecycle result.' }
    # PowerShell handles the wrapper. Explicit BaseObject access returns null
    # for native results or discards PSCustomObject's extended properties.
    return $values[0]
}
Export-ModuleMember -Function Receive-StationActionResult,Get-StationFailurePresentation,Get-StationDesktopCompletion
