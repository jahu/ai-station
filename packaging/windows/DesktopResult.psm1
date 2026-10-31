# Complete the private background runspace without losing PowerShell's wrapped
# native process/string results. This module has no Windows or UI side effects.
function Receive-StationActionResult {
    param([Parameter(Mandatory=$true)]$Engine,[Parameter(Mandatory=$true)]$Handle)
    $values=$Engine.EndInvoke($Handle)
    if ($Engine.Streams.Error.Count -gt 0) { throw $Engine.Streams.Error[0] }
    if ($values.Count -ne 1 -or $null -eq $values[0]) { throw 'The background operation did not return one lifecycle result.' }
    # PowerShell handles the wrapper. Explicit BaseObject access returns null
    # for native results or discards PSCustomObject's extended properties.
    return $values[0]
}
Export-ModuleMember -Function Receive-StationActionResult
