# Windows native controls: accessibility and display scaling

Follow-up to the private preserving-update and physical-storage qualification
(PRs #555 and #556), supporting NR-13. This is a qualification/implementation
contract, not a claim of completed Windows consumer support.

Keep the existing native shell and its typed owned-guest operations. This work
adds no executor, workload permission, Windows-drive mount or application API.
Preserve the same account, guest, models and application data. GUI-only builds
reuse the already checked guest package and do not rebuild/download AI models.

## Acceptance

- Record actual native control roles, supported automation patterns, names,
  enabled states, keyboard focus order and screen geometry before changing code.
- Verify ordinary Tab/Shift+Tab navigation and intentional Enter/Space actions.
  Focus must be visible; disabled actions must not run. Do not send Enter to a
  different foreground window or trigger Start as an incidental keyboard test.
- Check real Windows display scaling at 100%, 150% and 200% in the disposable
  owned Windows fixture. Record the selected OS scale, actual window bounds and
  working area; inspect the rendered result. Do not infer the scale solely from
  a DPI-unaware process reporting 96 DPI.
- Keep every action reachable on the available desktop. If actual qualification
  shows clipping, adapt to the working area while retaining the visual hierarchy,
  readable explanations and existing status/background/Stop behavior.
- Inspect ordinary idle/checking/running/Stop and recovery states. Status changes
  must not steal keyboard focus. Preserve the private readiness handoff and
  instance-bound Stop; close normally and release the UI lease after tests.
- Distinguish automation semantics and actual keyboard qualification from a
  screen-reader audition. Do not report Narrator as tested without using it.
- Restore fixture display settings after qualification. No physical Ubuntu host
  display, driver, CUDA, global PowerShell configuration or other WSL policy changes.

## Runtime compatibility

The GUI uses built-in Windows PowerShell and .NET Framework. Modern .NET
`SetHighDpiMode` examples do not establish compatibility with this host.
Microsoft documents [Framework high-DPI configuration](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/high-dpi-support-in-windows-forms?view=netframeworkdesktop-4.8)
as opt-in, including dynamic scaling. Its [GetDpiForWindow contract](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow)
returns values according to the window's awareness mode, not an independent
measurement of the selected desktop scale.

Inspect the installed host before choosing a fix. If legacy automation semantics
are confirmed, prefer process-local [documented accessibility switches](https://learn.microsoft.com/en-us/dotnet/framework/configure-apps/file-schema/runtime/appcontextswitchoverrides-element)
before loading Windows Forms, with actual Windows verification. Never edit the
operating system's `powershell.exe.config` or silently add another desktop runtime.

Private fixture evidence stays under the existing acceptance directory. Public
documentation must state exactly which scale, keyboard and accessibility
behaviors were observed; broader hardware, signing, macOS and release QA remain
separate gates.

## Actual private qualification, 2026-11-01

The unchanged native payload from PR #556 was inspected under ordinary Windows
PowerShell 5.1 on the existing Windows 11 x64 CPU fixture (1280 × 800). Windows
Settings confirmed 100% and 125% display scaling. The complete stopped-state
window was visually inspected at 125%; the heading, descriptions, actions and
footer remained visible. The original 100% setting was restored through Settings.
This fixture offers only 100% and 125% as standard choices at that resolution.
150%, 200%, per-monitor changes and screen-reader speech remain unqualified.

The original bare PowerShell UI Automation observer reported WinForms actions
as generic panes without action patterns. A fresh observer and a separate form
with process-local accessibility switches reproduced that result. Registering
the built-in `UIAutomationClientsideProviders` in the **observer** exposed the
unchanged application's real Button/Hyperlink roles, names and Invoke patterns.
No application or global .NET accessibility switch was needed or changed.
Microsoft documents this client registration in
[RegisterClientSideProviderAssembly](https://learn.microsoft.com/en-us/dotnet/api/system.windows.automation.clientsettings.registerclientsideproviderassembly?view=netframework-4.8.1).

Actual Tab navigation at 125% traversed Check setup → Start → Set up Windows
support → Check setup; Shift+Tab reversed it. Disabled Open app and Stop were
skipped. Keyboard delivery and focus observation must be allowed to settle;
an immediate read after `SendWait` is not proof that focus failed to move.
These tests sent no Enter/Space or workload action. Narrator, running-state
focus retention and action activation remain separate acceptance checks.
The same reusable probe passed at restored 100%, including rejection of a
different process and a different script. Normal tray exit then released the
native UI lease with the station still stopped; no process was force-killed.

The reusable native probe refuses a different process, script or Windows owner.
Its default only reads automation properties. Explicit `-ExerciseKeyboard`
sets focus and sends Tab/Shift+Tab, rechecking owner focus before each key;
it never invokes a button, prepares WSL, starts a workload or changes scale:

```powershell
& .\packaging\windows\tests\native\DesktopAccessibility.Tests.ps1 `
  -OwnerProcessId <visible-controls-pid> `
  -ExpectedScript '<installed-version>\WindowsSetup.ps1' `
  -ExerciseKeyboard
```

Run it with the built-in Windows PowerShell, against your own visible controls.
Record the actual scale in Windows Settings and inspect the rendered window
separately; a DPI-unaware observer's 96-DPI coordinates cannot prove OS scaling.
The probe returns observations as an object and does not create a public report
or claim screen-reader compatibility. Operator QA case SETUP-154 covers the
manual journey; its results remain blank until an operator performs it.
