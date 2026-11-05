; 2Wings installer for Inno Setup 6.
; Build dist\2Wings first, then compile this file with ISCC.exe.

#define MyAppName "2Wings"
#define MyAppVersion "2.0.3"
#define MyAppPublisher "2Wings"
#define MyAppExeName "2Wings.exe"
#define MyAppId "{{CB93C415-8593-4898-99D8-D1B69E7C8C38}"
#define MyAppSourceDir SourcePath + "..\dist\2Wings"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
SetupIconFile={#MyAppSourceDir}\assets\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
OutputDir=..\dist\installer
OutputBaseFilename=2Wings-Setup-{#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Never package a locally downloaded third-party runtime by accident.
Source: "{#MyAppSourceDir}\*"; DestDir: "{app}"; Excludes: "bin\*;\lua\*;utils\*;lists\*;runtime-version.txt;engine-version.txt"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall shellexec runascurrentuser; Check: ShouldLaunchTwoWings

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""2Wings Autostart"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTwoWingsAutostart"

[UninstallDelete]
; Runtime and updates downloaded after installation are not tracked by Inno Setup.
Type: filesandordirs; Name: "{app}"
; Copy of TwoWingsUpdate that 2Wings runs outside Program Files (src/modules/updates/splash_launcher.py).
Type: filesandordirs; Name: "{localappdata}\2Wings\updater"
Type: filesandordirs; Name: "{localappdata}\Tigo\updater"

[InstallDelete]
; Files of the version called Tigo: same AppId, so this install replaces it in place.
Type: files; Name: "{app}\Tigo.exe"
Type: filesandordirs; Name: "{app}\flet_client"
Type: filesandordirs; Name: "{app}\updater"
Type: filesandordirs; Name: "{app}\assets\fonts"
Type: files; Name: "{autoprograms}\Tigo.lnk"
Type: files; Name: "{autodesktop}\Tigo.lnk"

[Code]
var
  LastProgressStep: Integer;

{ The updater of versions up to 1.5.8 still calls this installer with the old switch names. }
function UpdaterParam(const Name, LegacyName, Default: String): String;
begin
  Result := ExpandConstant('{param:' + Name + '|}');
  if Result = '' then
    Result := ExpandConstant('{param:' + LegacyName + '|' + Default + '}');
end;

{ The version called Tigo may still be running from the install folder, and Windows will
  not close it for us: none of the new files replace it. Never kill its process tree here:
  its updater and this installer are its children. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Tigo.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -Command "Get-Process flet -ErrorAction SilentlyContinue | Where-Object { $_.Path -like ''' +
    ExpandConstant('{app}') + '\*'' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;

{ TwoWingsUpdate passes /TWOWINGSPROGRESS=<file> and draws "current max" from it as the install bar. }
procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  ProgressFile: String;
  Step: Integer;
begin
  ProgressFile := UpdaterParam('TWOWINGSPROGRESS', 'TIGOPROGRESS', '');
  if (ProgressFile = '') or (MaxProgress <= 0) then
    Exit;
  Step := CurProgress div (MaxProgress div 200 + 1);
  if Step = LastProgressStep then
    Exit;
  LastProgressStep := Step;
  SaveStringToFile(ProgressFile, IntToStr(CurProgress) + ' ' + IntToStr(MaxProgress), False);
end;

function ShouldLaunchTwoWings(): Boolean;
begin
  Result := (not WizardSilent) or
    (CompareText(UpdaterParam('TWOWINGSRELAUNCH', 'TIGORELAUNCH', '0'), '1') = 0);
end;
