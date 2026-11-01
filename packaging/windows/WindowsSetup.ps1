# Native onboarding/lifecycle shell. Workloads remain in the existing control plane.
param([string]$PackageFolder=$PSScriptRoot)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'NativeWsl.psm1')
Import-Module (Join-Path $PSScriptRoot 'DesktopResult.psm1')
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) { throw 'The native Windows setup requires Windows.' }
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
try {
 Assert-StationWindowsHost
 if ($PSVersionTable.PSEdition -ne 'Desktop') { throw 'Launch this package with the built-in Windows PowerShell desktop launcher.' }
} catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'AI Station','OK','Error');exit 1 }
[Windows.Forms.Application]::EnableVisualStyles()

# One local session window per OS user. Other accounts cannot signal this event.
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$hasher=[Security.Cryptography.SHA256]::Create()
try { $suffix=[BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($sid.Value))).Replace('-','').Substring(0,24) } finally { $hasher.Dispose() }
$mutexSecurity=[Security.AccessControl.MutexSecurity]::new()
$eventSecurity=[Security.AccessControl.EventWaitHandleSecurity]::new()
foreach ($identity in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
 $mutexSecurity.AddAccessRule([Security.AccessControl.MutexAccessRule]::new($identity,[Security.AccessControl.MutexRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow))
 $eventSecurity.AddAccessRule([Security.AccessControl.EventWaitHandleAccessRule]::new($identity,[Security.AccessControl.EventWaitHandleRights]::FullControl,[Security.AccessControl.AccessControlType]::Allow))
}
$created=$false
$mutex=[Threading.Mutex]::new($false,('Local\AIStation-Desktop-'+$suffix),[ref]$created,$mutexSecurity)
$ownsMutex=$mutex.WaitOne(0)
if (-not $ownsMutex) {
 try { $existing=[Threading.EventWaitHandle]::OpenExisting('Local\AIStation-Show-'+$suffix);[void]$existing.Set();$existing.Dispose() } finally { $mutex.Dispose() }
 exit
}
$created=$false
$showEvent=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::AutoReset,('Local\AIStation-Show-'+$suffix),[ref]$created,$eventSecurity)
Import-Module (Join-Path $PSScriptRoot 'PrivateStore.psm1')
try { $uiLease=Open-StationUiLease } catch { [void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'AI Station','OK','Error');$showEvent.Dispose();$mutex.ReleaseMutex();$mutex.Dispose();exit 1 }
$script:worker=$null;$script:station=$null;$script:reader=$null;$script:stderr=$null
$script:ready=$null;$script:running=$false;$script:prepared=$false;$script:stopPending=$false;$script:exitAfterStop=$false;$script:allowExit=$false
$script:nextCheck=[DateTime]::UtcNow;$script:lastError='';$script:attention=$false
$script:updateAvailable=$false;$script:updatePending=$false;$script:refreshAfterFailure=$false

$form=[Windows.Forms.Form]::new()
$form.Text='AI Station';$form.ClientSize=[Drawing.Size]::new(620,422)
$form.StartPosition='CenterScreen';$form.FormBorderStyle='FixedDialog';$form.MaximizeBox=$false
$form.BackColor=[Drawing.ColorTranslator]::FromHtml('#121A16');$form.ForeColor=[Drawing.ColorTranslator]::FromHtml('#E7EEE8')
$form.Font=[Drawing.Font]::new('Segoe UI',10)
$title=[Windows.Forms.Label]::new();$title.Text='Your local AI workspace';$title.Font=[Drawing.Font]::new('Segoe UI Semibold',22)
$title.SetBounds(30,28,560,42);$form.Controls.Add($title)
$intro=[Windows.Forms.Label]::new();$intro.Text='Set up once. Choose your models in the app. Your conversations and creations stay on this computer.'
$intro.SetBounds(32,85,550,48);$form.Controls.Add($intro)
$status=[Windows.Forms.Label]::new();$status.Text='Ready to set up';$status.Font=[Drawing.Font]::new('Segoe UI Semibold',12)
$status.SetBounds(32,155,550,28);$form.Controls.Add($status)
$description=[Windows.Forms.Label]::new();$description.Text='This first step prepares the app. Choose AI models afterward, with their size and license shown before download.'
$description.SetBounds(32,191,550,58);$form.Controls.Add($description)
$progress=[Windows.Forms.ProgressBar]::new();$progress.Style='Marquee';$progress.MarqueeAnimationSpeed=30;$progress.Visible=$false
$progress.SetBounds(32,257,550,5);$form.Controls.Add($progress)
function Button([string]$Text,[int]$X,[int]$Width) {
 $button=[Windows.Forms.Button]::new();$button.Text=$Text;$button.SetBounds($X,284,$Width,42)
 $button.AccessibleRole=[Windows.Forms.AccessibleRole]::PushButton;$button.AccessibleName=$Text
 $button.FlatStyle='Flat';$button.FlatAppearance.BorderColor=[Drawing.ColorTranslator]::FromHtml('#3B5142')
 $button.BackColor=[Drawing.ColorTranslator]::FromHtml('#203327');$button.ForeColor=$form.ForeColor;$form.Controls.Add($button);return $button
}
$prepare=Button 'Prepare AI Station' 32 190
$start=Button 'Start' 234 106;$open=Button 'Open app' 352 106;$stop=Button 'Stop' 470 112
$start.Enabled=$false;$open.Enabled=$false;$stop.Enabled=$false
$prepare.BackColor=[Drawing.ColorTranslator]::FromHtml('#B9ED98');$prepare.ForeColor=[Drawing.ColorTranslator]::FromHtml('#142015')
$support=[Windows.Forms.LinkLabel]::new();$support.Text='Set up Windows support';$support.LinkColor=[Drawing.ColorTranslator]::FromHtml('#B9ED98')
$support.SetBounds(32,347,220,25);$form.Controls.Add($support)
$background=[Windows.Forms.LinkLabel]::new();$background.Text='Keep running in background';$background.LinkColor=$support.LinkColor
$background.SetBounds(290,347,210,25);$form.Controls.Add($background)
$details=[Windows.Forms.LinkLabel]::new();$details.Text='Details';$details.LinkColor=$support.LinkColor;$details.SetBounds(518,347,64,25);$details.Visible=$false;$form.Controls.Add($details)
$footer=[Windows.Forms.Label]::new();$footer.Text='Closing this window keeps your station running. Use Stop when you want to shut it down.'
$footer.Font=[Drawing.Font]::new('Segoe UI',8);$footer.ForeColor=[Drawing.ColorTranslator]::FromHtml('#A7B7AA');$footer.SetBounds(32,384,550,26);$form.Controls.Add($footer)
$tray=[Windows.Forms.NotifyIcon]::new();$tray.Icon=[Drawing.SystemIcons]::Application;$tray.Text='AI Station';$tray.Visible=$true
$menu=[Windows.Forms.ContextMenuStrip]::new();$showItem=$menu.Items.Add('Open AI Station controls');$stopExit=$menu.Items.Add('Stop AI Station and exit');$tray.ContextMenuStrip=$menu

function Sync-Buttons {
 $preparing=$null -ne $script:worker -and $script:worker.Action -eq 'prepare'
 $busy=$null -ne $script:worker -or ($null -ne $script:station -and $null -eq $script:ready) -or $script:stopPending
 $progress.Visible=$busy -and ($null -eq $script:worker -or $script:worker.Action -ne 'status')
 $prepare.Enabled=-not $busy -and -not $script:running
 $checkOnly=$script:attention -and $null -ne $script:station -and $null -eq $script:ready
 $start.Text=$(if ($checkOnly) {'Check status'} elseif ($script:updateAvailable) {'Finish work'} else {'Start'})
 $start.Enabled=($null -eq $script:worker) -and ($checkOnly -or ($script:prepared -and -not $busy -and -not $script:running))
 $prepare.Text=$(if ($script:updateAvailable) {'Update AI Station'} elseif ($script:prepared) {'Check setup'} else {'Prepare AI Station'})
 $open.Enabled=-not $busy -and $script:running
 $stop.Text=$(if ($preparing -and $script:updateAvailable) {'Cancel update'} elseif ($preparing) {'Cancel setup'} else {'Stop'})
 $stop.Enabled=($preparing -and -not $script:worker.Cancellation.IsCancellationRequested) -or ($null -eq $script:worker -and $script:running -and -not $script:stopPending)
 $support.Enabled=-not $busy -and -not $script:running
 $known=$script:prepared -or $script:running
 $start.Visible=$known;$open.Visible=$known;$stop.Visible=$known -or $preparing
 $prepare.Width=$(if ($known) {190} elseif ($preparing) {426} else {550})
 foreach($button in @($prepare,$start,$open,$stop)) {
  $button.AccessibleName=$button.Text
  $button.BackColor=[Drawing.ColorTranslator]::FromHtml('#203327');$button.ForeColor=$form.ForeColor
 }
 $primary=$(if ($open.Enabled) {$open} elseif ($prepare.Enabled -and $script:updateAvailable) {$prepare} elseif ($start.Enabled) {$start} else {$prepare})
 $primary.BackColor=[Drawing.ColorTranslator]::FromHtml('#B9ED98');$primary.ForeColor=[Drawing.ColorTranslator]::FromHtml('#142015')
 $form.AcceptButton=$primary
 $background.Visible=$script:running -or $preparing
}
function Show-Failure([string]$Message) {
$script:lastError=$Message;$script:attention=$true;$details.Visible=$true;$status.Text='Needs attention'
 $description.Text='Your saved work is preserved. Try again, or check Windows support. Details can help diagnose the problem.'
}
function Begin-StationAction([string]$Action) {
 if ($null -ne $script:worker) { return }
 $details.Visible=$false
 $engine=[Management.Automation.PowerShell]::Create()
 $cancellation=[Threading.CancellationTokenSource]::new()
 [void]$engine.AddCommand('Microsoft.PowerShell.Core\Import-Module').AddParameter('Name',(Join-Path $PSScriptRoot 'Setup.psm1'))
 [void]$engine.AddStatement()
 if ($Action -eq 'prepare') {
  [void]$engine.AddCommand('Invoke-StationSetup').AddParameter('PackageFolder',$PackageFolder).AddParameter('CancellationToken',$cancellation.Token)
  if ($script:updateAvailable) { [void]$engine.AddParameter('AllowUpdate',$true) }
  $status.Text=$(if ($script:updateAvailable) {'Updating your station'} else {'Preparing your private workspace'})
  $description.Text=$(if ($script:updateAvailable) {'Checking the new version and preserving your accounts, models and saved work. You can leave this window in the background.'} else {'Checking the package and preparing the local environment. You can leave this window in the background.'})
 } else {
  [void]$engine.AddCommand('Invoke-StationDesktop').AddParameter('Action',$Action).AddParameter('PackageFolder',$PackageFolder)
  if ($Action -ne 'status') {
   $status.Text=$(if ($Action -eq 'stop') {'Stopping AI Station'} else {'Starting AI Station'})
   $description.Text='Your saved conversations, models and creations stay in place.'
  }
 }
 $handle=$engine.BeginInvoke();$script:worker=[pscustomobject]@{Engine=$engine;Handle=$handle;Action=$Action;Cancellation=$cancellation;Updating=($Action -eq 'prepare' -and $script:updateAvailable)}
 Sync-Buttons
}
function Open-ReadyTarget($Ready) {
 Import-Module (Join-Path $PSScriptRoot 'DesktopLink.psm1')
 Open-StationBrowser $Ready
}
$prepare.Add_Click({ Begin-StationAction 'prepare' });$start.Add_Click({ if ($script:attention -and $null -ne $script:station -and $null -eq $script:ready) { Begin-StationAction 'status' } else { Begin-StationAction 'start' } })
$open.Add_Click({ Begin-StationAction 'open' });$stop.Add_Click({
 if ($null -ne $script:worker -and $script:worker.Action -eq 'prepare') {
  $script:worker.Cancellation.Cancel();$status.Text='Canceling setup';$description.Text='Finishing the current safe step. Saved work stays in place.';Sync-Buttons
 } else { Begin-StationAction 'stop' }
})
$background.Add_LinkClicked({ $form.Hide() })
$details.Add_LinkClicked({ [void][Windows.Forms.MessageBox]::Show($form,$script:lastError,'AI Station details','OK','Information') })
$showItem.Add_Click({ $form.Show();$form.Activate() });$tray.Add_DoubleClick({ $form.Show();$form.Activate() })
$stopExit.Add_Click({
 $script:exitAfterStop=$true
 if ($null -ne $script:worker -and $script:worker.Action -eq 'prepare') { $script:worker.Cancellation.Cancel() }
 if ($null -eq $script:worker) {
  if ($script:running) { Begin-StationAction 'stop' } elseif ($null -ne $script:station) { $status.Text='Finishing startup before stopping' } else { $script:allowExit=$true;$form.Close() }
 }
})
$support.Add_LinkClicked({
 $answer=[Windows.Forms.MessageBox]::Show($form,'Windows will ask permission to install WSL2. A restart may be required; save other work first. Existing Linux distributions are not imported, deleted or adopted. Continue?','Prepare Windows support','YesNo','Question')
 if ($answer -eq [Windows.Forms.DialogResult]::Yes) {
  try {
   $exe=Get-StationWslExecutable
   $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$exe;$info.Arguments='--install --no-distribution';$info.Verb='runas';$info.UseShellExecute=$true
   [void][Diagnostics.Process]::Start($info)
   $status.Text='Complete the Windows setup';$description.Text='Follow the Windows prompt. If Windows asks for a restart, reopen AI Station afterward and choose Prepare.'
  } catch { Show-Failure $_.Exception.Message }
 }
})
$form.Add_FormClosing({
 param($sender,$eventArgs)
 if ($eventArgs.CloseReason -eq [Windows.Forms.CloseReason]::WindowsShutDown) { $script:allowExit=$true;return }
 if (-not $script:allowExit) { $eventArgs.Cancel=$true;$form.Hide() }
})
$timer=[Windows.Forms.Timer]::new();$timer.Interval=200
$timer.Add_Tick({
 try {
  if ($showEvent.WaitOne(0)) { $form.Show();$form.Activate() }
  if ($null -ne $script:worker -and $script:worker.Handle.IsCompleted) {
   $job=$script:worker;$script:worker=$null
   try {
    $value=Receive-StationActionResult $job.Engine $job.Handle
    if ($job.Action -eq 'prepare') { $job.Cancellation.Token.ThrowIfCancellationRequested() }
    switch ($job.Action) {
     'prepare' { $script:prepared=$true;$script:updateAvailable=$false;$script:updatePending=$false;if ($script:exitAfterStop) { $script:allowExit=$true;$form.Close() } else { Begin-StationAction 'start' } }
     'start' {
      $script:station=$value;$script:ready=$null
      $script:reader=$value.StandardOutput.ReadLineAsync();$script:stderr=$value.StandardError.ReadToEndAsync()
      $status.Text='Opening your station';$description.Text='Preparing the app and checking its local connection. Model setup opens in your browser.'
     }
     'open' {
      Import-Module (Join-Path $PSScriptRoot 'DesktopLink.psm1')
      $candidate=Read-StationReadyFrame ([string]$value).Trim()
      if ($null -eq $candidate) { throw 'The running station did not provide a valid browser handoff.' }
      $script:ready=$candidate;$script:running=$true;Open-ReadyTarget $candidate;$status.Text='Running locally';$description.Text='Your AI Station is open. Agents and generation keep working when this window is closed.'
     }
     'stop' { $script:stopPending=$true;$script:nextCheck=[DateTime]::UtcNow.AddSeconds(1) }
     'status' {
      $script:nextCheck=[DateTime]::UtcNow.AddSeconds(15)
      $body=([string]$value) | ConvertFrom-Json -ErrorAction Stop
      if ($body.running -isnot [bool]) { throw 'Invalid station lifecycle response.' }
      if ($body.PSObject.Properties.Name -contains 'inspection_required' -and $body.inspection_required) { throw 'The previous supervisor is still active and requires inspection. It was not replaced or stopped indiscriminately.' }
      if ($body.update_available -isnot [bool] -or $body.update_pending -isnot [bool]) { throw 'Invalid native update state.' }
      $script:updateAvailable=$body.update_available;$script:updatePending=$body.update_pending
      $script:prepared=-not $body.update_pending;$script:running=$body.running
      if (-not $body.running) {
       $script:stopPending=$false;$script:ready=$null
       $status.Text=$(if ($script:updateAvailable) {'Update available'} else {'Stopped'})
       $description.Text=$(if ($script:updatePending) {'An update needs to finish. Choose Update AI Station to inspect or resume it. Your saved work is preserved.'} elseif ($script:updateAvailable) {'Install the new version while keeping your accounts, models and saved work. Use Finish work first if you still have queued tasks.'} else {'Your saved workspace is ready for next time.'})
       if ($script:exitAfterStop) { $script:allowExit=$true;$form.Close() }
      } else {
       $status.Text=$(if ($script:stopPending) {'Stopping AI Station'} elseif ($script:updateAvailable) {'Running · update available'} else {'Running locally'})
       if ($script:updateAvailable) { $description.Text='Finish your current work, choose Stop, then Update AI Station. Nothing will be interrupted automatically.' }
      }
     }
    }
   } catch {
    if ($job.Updating) { $script:prepared=$false }
    $cause=$_.Exception;$canceled=$false;$restart=$false
    while ($null -ne $cause) {
     if ($cause -is [OperationCanceledException]) { $canceled=$true }
     if ($cause.Data['AIStationRestartRequired'] -eq $true) { $restart=$true }
     $cause=$cause.InnerException
    }
    # Preserve the explicit restart instruction. A successful read-only status
    # does not prove that Windows preparation can proceed or an interrupted
    # package is safe to start; only a later successful check may enable Start.
    if ($job.Updating) { $script:refreshAfterFailure=-not $restart }
    if ($job.Action -eq 'prepare' -and $job.Cancellation.IsCancellationRequested -and $canceled) {
     $script:prepared=$false;$status.Text='Setup canceled';$description.Text='Saved files were preserved. Choose Prepare to inspect or resume your private workspace.'
     if ($script:exitAfterStop) { $script:allowExit=$true;$form.Close() }
    } elseif ($restart) {
     $script:attention=$true;$status.Text='Restart Windows to continue'
     $description.Text='Save other work, restart Windows, then reopen AI Station. Your saved workspace stays in place.'
    } else { Show-Failure $_.Exception.Message }
   } finally { $job.Engine.Dispose();$job.Cancellation.Dispose() }
   Sync-Buttons
  }
  if ($script:refreshAfterFailure -and $null -eq $script:worker) {
   $script:refreshAfterFailure=$false;Begin-StationAction 'status'
  }
  if ($null -ne $script:reader -and $script:reader.IsCompleted) {
   $line=$script:reader.GetAwaiter().GetResult();$script:reader=$null
   if ($null -ne $line) {
    Import-Module (Join-Path $PSScriptRoot 'DesktopLink.psm1')
    $candidate=Read-StationReadyFrame $line
    if ($null -ne $candidate) {
     $script:ready=$candidate;$script:running=$true
     if ($script:exitAfterStop) { Begin-StationAction 'stop' } else { Open-ReadyTarget $candidate }
     $status.Text=$(if ($script:exitAfterStop) {'Stopping AI Station'} else {'Running locally'});$description.Text='Your AI Station is open. Agents and generation keep working when this window is closed.'
    }
    $script:reader=$script:station.StandardOutput.ReadLineAsync()
   } else {
    $script:station.Dispose();$script:station=$null
    if ($null -eq $script:worker) { Begin-StationAction 'status' }
    if ($null -eq $script:ready) { throw 'The station stopped before its browser connection became ready.' }
   }
   Sync-Buttons
  }
  if ($script:stopPending -and $null -eq $script:worker -and [DateTime]::UtcNow -ge $script:nextCheck) {
   $script:nextCheck=[DateTime]::UtcNow.AddSeconds(2);Begin-StationAction 'status'
  } elseif ($script:running -and $null -eq $script:worker -and [DateTime]::UtcNow -ge $script:nextCheck) {
   $script:nextCheck=[DateTime]::UtcNow.AddSeconds(15);Begin-StationAction 'status'
  }
 } catch { Show-Failure $_.Exception.Message;Sync-Buttons }
})
try {
 Sync-Buttons
 $timer.Start()
 $form.Add_Shown({
  $statePath=Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) 'AIStation-Desktop\install-state.json'
  if ([IO.File]::Exists($statePath)) { Begin-StationAction 'status' }
 })
 [Windows.Forms.Application]::Run($form)
} finally {
 $timer.Stop();$timer.Dispose();$tray.Visible=$false;$tray.Dispose();$form.Dispose()
 $uiLease.Dispose();$showEvent.Dispose();if ($ownsMutex) { $mutex.ReleaseMutex() };$mutex.Dispose()
}
