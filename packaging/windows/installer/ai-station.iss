; Inno Setup 7 publisher input. Native signing/installation qualification is required.
#ifndef Payload
  #error Payload directory is required
#endif
#ifndef VersionId
  #error Retained source version is required
#endif
#ifndef InstallerVersion
  #define InstallerVersion "0.1.0"
#endif
[Setup]
AppId={{556C5DB1-CA40-4920-A26F-6140E96D407C}
AppName=AI Station
AppVersion={#InstallerVersion}
AppPublisher=AI Station contributors
SetupArchitecture=x64
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
DefaultDirName={localappdata}\Programs\AI Station
PrivilegesRequired=lowest
MinVersion=10.0.22000
DisableProgramGroupPage=yes
LicenseFile={#Payload}\LICENSE
OutputBaseFilename=AI-Station-{#VersionId}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayName=AI Station
UninstallDisplayIcon={app}\versions\{#VersionId}\AIStation.exe
[Files]
Source: "{#Payload}\*"; DestDir: "{app}\versions\{#VersionId}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\AI Station"; Filename: "{app}\versions\{#VersionId}\AIStation.exe"
[Run]
Filename: "{app}\versions\{#VersionId}\AIStation.exe"; Description: "Open AI Station"; Flags: postinstall nowait skipifsilent
[Code]
var
  UiLease: TFileStream;

function RunUninstallCheck(const Mode: String): Boolean;
var
  ExitCode: Integer;
  Arguments: String;
begin
  Arguments := '-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\versions\{#VersionId}\Uninstall-Check.ps1') + '" ' + Mode;
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Arguments, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  if Result then Result := ExitCode = 0;
end;

function InitializeUninstall(): Boolean;
begin
  Result := False;
  if not RunUninstallCheck('-ValidateOnly') then
  begin
    MsgBox('Open AI Station controls, choose Stop AI Station and exit, then try again. Your saved work is preserved.', mbInformation, MB_OK);
    Exit;
  end;
  try
    { fmOpenReadWrite + fmShareExclusive; held until uninstallation ends. }
    UiLease := TFileStream.Create(ExpandConstant('{localappdata}\AIStation-Desktop\ui-active.lock'), $0012);
  except
    MsgBox('AI Station controls are still open. Stop and exit before uninstalling.', mbInformation, MB_OK);
    Exit;
  end;
  if not RunUninstallCheck('') then
  begin
    UiLease.Free;
    UiLease := nil;
    MsgBox('AI Station could not confirm a safe shutdown. Existing program files and data were retained.', mbError, MB_OK);
    Exit;
  end;
  Result := True;
end;

procedure DeinitializeUninstall();
begin
  if UiLease <> nil then UiLease.Free;
end;
