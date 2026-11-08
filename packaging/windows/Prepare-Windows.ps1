# Fixed, explicitly OS-consented prerequisite preparation; no workload interface.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'WindowsSupport.psm1')
Add-Type -AssemblyName System.Windows.Forms
try {
 $result=Invoke-StationWindowsSupport
 $message=$(if($result.RestartRequired){'Windows support is installed. Save your work and restart Windows, then reopen AI Station and choose Prepare.'}else{'Windows support is ready. Return to AI Station and choose Prepare.'})
 [void][Windows.Forms.MessageBox]::Show($message,'AI Station — Windows support','OK','Information')
} catch {
 [void][Windows.Forms.MessageBox]::Show(($_.Exception.Message+' No distributions were adopted or deleted. Complete Windows Update if Windows cannot enable virtualization, then try again.'),'AI Station — Windows support','OK','Error')
 exit 1
}
