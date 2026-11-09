$ErrorActionPreference='Stop'
$native=[Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
if($native){Add-Type -AssemblyName System.Windows.Forms;Add-Type -AssemblyName System.Drawing}
$tokens=$null;$errors=$null
$source=[IO.File]::ReadAllText((Join-Path $PSScriptRoot '../WindowsSetup.ps1'),[Text.UTF8Encoding]::new($false,$true))
$ast=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$errors)
if($errors.Count -ne 0){throw 'The actual native UI source did not parse'}
$function=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq 'Sync-Buttons'},$true)
. ([scriptblock]::Create($function.Extent.Text))
function New-Button {
 if($native){return [Windows.Forms.Button]::new()}
 $value=[pscustomobject]@{Text='';Visible=$false;Enabled=$false;AccessibleName='';BackColor=$null;ForeColor=$null;Bounds=$null}
 $value|Add-Member -MemberType ScriptMethod -Name SetBounds -Value {param($x,$y,$w,$h);$this.Bounds=@($x,$y,$w,$h)}
 return $value
}
$prepare=New-Button;$start=New-Button;$open=New-Button;$stop=New-Button;$support=New-Button
$form=$(if($native){[Windows.Forms.Form]::new()}else{[pscustomobject]@{ForeColor=[Drawing.Color]::White;AcceptButton=$null}})
$progress=New-Button;$background=New-Button;$stopExit=New-Button
function Reset($Operation){
 $script:worker=$null;$script:station=$null;$script:ready=$null;$script:stopPending=$false
 $script:attention=$false;$script:prepared=$true;$script:running=$false;$script:updateAvailable=$false
 $script:needsSupport=$false;$script:failureSticky=$false;$script:nativeUpdate=$Operation
}
function Operation($Phase,$Alive,[long]$Age=0){return [pscustomobject]@{phase=$Phase;helper_alive=$Alive;updated_at=([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$Age)}}
try{
 Reset (Operation 'staging' $true);$script:running=$true;Sync-Buttons
 if($start.Visible -or $open.Visible -or $stop.Visible -or $support.Visible -or $start.Enabled -or $open.Enabled -or $stop.Enabled -or $prepare.Enabled -or $stopExit.Enabled -or $null -ne $form.AcceptButton -or -not $progress.Visible -or $prepare.Text -cne 'Updating...'){throw 'Live update exposed conflicting lifecycle controls or keyboard Start'}
 Reset (Operation 'inspection_required' $true);Sync-Buttons
 if($prepare.Enabled){throw 'Continue was enabled while its helper remained alive'}
 Reset (Operation 'inspection_required' $false);Sync-Buttons
 if(-not $prepare.Enabled -or $prepare.Text -cne 'Continue update' -or $form.AcceptButton -ne $prepare -or $progress.Visible){throw 'The stopped update has no explicit Continue action'}
 Reset (Operation 'restarting' $false 31);Sync-Buttons
 if(-not $prepare.Enabled){throw 'The stopped original operation cannot be inspected and continued'}
 $script:worker=[pscustomobject]@{Action='resume-update'};Sync-Buttons
 if($prepare.Enabled -or -not $progress.Visible){throw 'Continue can be dispatched twice while a local action is in flight'}
 Reset (Operation 'complete' $false);Sync-Buttons
 if(-not $start.Visible -or -not $start.Enabled -or $prepare.Visible -or -not $stopExit.Enabled){throw 'Normal controls did not return after completion'}
 Reset $null;$script:prepared=$false;Sync-Buttons
 if(-not $prepare.Visible -or -not $prepare.Enabled -or $prepare.Text -cne 'Get started'){throw 'The initial one-action setup flow regressed'}
 Write-Output ('PASS update button policy and actual Sync-Buttons source; native WinForms controls='+$native)
}finally{
 if($native){foreach($control in @($prepare,$start,$open,$stop,$support,$form,$progress,$background,$stopExit)){$control.Dispose()}}
}
