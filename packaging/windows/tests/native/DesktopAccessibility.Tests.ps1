# Read-only native qualification; optional Tab navigation never activates an action.
param(
 [Parameter(Mandatory=$true)][ValidateRange(1,2147483647)][int]$OwnerProcessId,
 [Parameter(Mandatory=$true)][string]$ExpectedScript,
 [switch]$ExerciseKeyboard
)
$ErrorActionPreference='Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'Run this qualification on Windows.' }
$expected=[IO.Path]::GetFullPath($ExpectedScript)
if ([IO.Path]::GetFileName($expected) -cne 'WindowsSetup.ps1' -or -not [IO.File]::Exists($expected)) { throw 'Select the installed WindowsSetup.ps1.' }
$owner=Get-CimInstance Win32_Process -Filter ('ProcessId='+$OwnerProcessId)
if ($null -eq $owner -or $owner.Name -ine 'powershell.exe' -or $owner.CommandLine -notmatch ('(?i)-File\s+"'+[regex]::Escape($expected)+'"(?:\s|$)')) { throw 'The selected process does not own that installed UI.' }
$identity=Invoke-CimMethod -InputObject $owner -MethodName GetOwnerSid
if ($identity.ReturnValue -ne 0 -or $identity.Sid -cne [Security.Principal.WindowsIdentity]::GetCurrent().User.Value) { throw 'Only inspect your own ordinary-user UI.' }
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName UIAutomationClientsideProviders
# WinForms/MSAA controls otherwise appear as generic HWND panes in a bare
# PowerShell client. Fix the observer, not the application or global OS settings.
[Windows.Automation.ClientSettings]::RegisterClientSideProviderAssembly([UIAutomationClientsideProviders.UIAutomationClientSideProviders].Assembly.GetName())
$window=[Windows.Automation.AutomationElement]::RootElement.FindFirst([Windows.Automation.TreeScope]::Children,[Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty,$OwnerProcessId))
if ($null -eq $window) { throw 'Show the selected controls window before qualification.' }
$elements=@($window.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition))
$controls=@($elements|Where-Object{$_.Current.ControlType -eq [Windows.Automation.ControlType]::Button -or $_.Current.ControlType -eq [Windows.Automation.ControlType]::Hyperlink})
if ($controls.Count -eq 0) { throw 'No semantic native controls were exposed.' }
$observations=@()
foreach($control in $controls) {
 $c=$control.Current
 if (-not $c.Name) { throw 'A native action has no accessible name.' }
 $invoke=$null
 if (-not $control.TryGetCurrentPattern([Windows.Automation.InvokePattern]::Pattern,[ref]$invoke)) { throw ('Missing action semantics: '+$c.Name) }
 $r=$c.BoundingRectangle
 $observations+=@{name=$c.Name;role=$c.ControlType.ProgrammaticName;enabled=$c.IsEnabled;focusable=$c.IsKeyboardFocusable;offscreen=$c.IsOffscreen;bounds=@{x=$r.X;y=$r.Y;width=$r.Width;height=$r.Height}}
}
$focusNames=@();$reverse=$null
if ($ExerciseKeyboard) {
 Add-Type -AssemblyName System.Windows.Forms
 $candidates=@($controls|Where-Object{$_.Current.IsEnabled -and $_.Current.IsKeyboardFocusable -and -not $_.Current.IsOffscreen})
 if ($candidates.Count -eq 0) { throw 'No enabled visible action can receive focus.' }
 $first=$candidates[0];$first.SetFocus()
 # Focus/keyboard delivery is asynchronous even when SendWait returns. Bound
 # every observation and stop before another key if focus leaves this owner.
 function Await-Focus([string]$Previous,[bool]$MustChange) {
  $deadline=[DateTime]::UtcNow.AddSeconds(3)
  do {
   $f=[Windows.Automation.AutomationElement]::FocusedElement
   if ($null -ne $f -and $f.Current.ProcessId -eq $OwnerProcessId -and (-not $MustChange -or $f.Current.Name -cne $Previous)) { return $f }
   Start-Sleep -Milliseconds 50
  } while ([DateTime]::UtcNow -lt $deadline)
  throw 'Native focus did not settle; no further keys were sent.'
 }
 $focus=Await-Focus '' $false;$focusNames+= $focus.Current.Name
 for($n=0;$n -lt $candidates.Count;$n++) {
  $current=[Windows.Automation.AutomationElement]::FocusedElement
  if ($null -eq $current -or $current.Current.ProcessId -ne $OwnerProcessId) { throw 'Focus left the selected owner; no further keys were sent.' }
  $before=$current.Current.Name
  [Windows.Forms.SendKeys]::SendWait('{TAB}')
  $focus=Await-Focus $before ($candidates.Count -gt 1)
  if (-not $focus.Current.IsEnabled -or $focus.Current.Name -notin @($candidates|ForEach-Object{$_.Current.Name})) { throw 'Tab reached an unavailable action.' }
  $focusNames+=$focus.Current.Name
 }
 if ($focusNames[-1] -cne $focusNames[0] -or @($focusNames|Select-Object -Unique).Count -ne $candidates.Count) { throw 'Tab did not traverse each available action exactly once.' }
 $current=[Windows.Automation.AutomationElement]::FocusedElement
 if ($null -eq $current -or $current.Current.ProcessId -ne $OwnerProcessId) { throw 'Focus left the selected owner; Shift+Tab was not sent.' }
 [Windows.Forms.SendKeys]::SendWait('+{TAB}')
 $reverse=(Await-Focus $current.Current.Name ($candidates.Count -gt 1)).Current.Name
 if ($reverse -cne $focusNames[-2]) { throw 'Shift+Tab did not reverse the focus order.' }
}
$bounds=$window.Current.BoundingRectangle
[pscustomobject]@{owner_process_id=$OwnerProcessId;controls=$observations;tab_focus=$focusNames;shift_tab_focus=$reverse;window_bounds=@{x=$bounds.X;y=$bounds.Y;width=$bounds.Width;height=$bounds.Height};actions_activated=$false;Narrator_tested=$false}
