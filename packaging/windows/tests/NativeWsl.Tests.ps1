$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '../NativeWsl.psm1') -Force
if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) { throw 'This negative-host test is for non-Windows only; native qualification has separate gates.' }
$cases=0
foreach ($action in @({ Assert-StationWindowsHost }, { Get-StationWslExecutable }, { Get-StationWslRegistrations }, { Assert-StationWindowsPreparationReady })) {
    $refused=$false
    try { & $action | Out-Null } catch { $refused=$_.Exception.Message -like '*requires Windows*' }
    if (-not $refused) { throw 'A native Windows operation crossed its platform guard.' }
    $cases++
}
Write-Output ('PASS '+$cases+' non-Windows refusals before any executable or registry access; actual Windows API qualification pending')
