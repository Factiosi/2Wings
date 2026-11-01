; Tigo installer for Inno Setup 6.
; Build dist\Tigo first, then compile this file with ISCC.exe.

#define MyAppName "Tigo"
#define MyAppVersion "1.5.8"
#define MyAppPublisher "Tigo"
#define MyAppExeName "Tigo.exe"
#define MyAppId "{{CB93C415-8593-4898-99D8-D1B69E7C8C38}"
#define MyAppSourceDir SourcePath + "..\dist\Tigo"

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
OutputBaseFilename=Tigo-Setup-{#MyAppVersion}
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
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; WorkingDir: "{app}"; Flags: nowait postinstall shellexec runascurrentuser; Check: ShouldLaunchTigo

[UninstallRun]
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""Tigo Autostart"" /F"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTigoAutostart"

[UninstallDelete]
; Runtime and updates downloaded after installation are not tracked by Inno Setup.
Type: filesandordirs; Name: "{app}"
; Copy of TigoUpdate that Tigo runs outside Program Files (src/modules/updates/splash_launcher.py).
Type: filesandordirs; Name: "{localappdata}\Tigo\updater"

[Code]
var
  LastProgressStep: Integer;

{ TigoUpdate passes /TIGOPROGRESS=<file> and draws "current max" from it as the install bar. }
procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
var
  ProgressFile: String;
  Step: Integer;
begin
  ProgressFile := ExpandConstant('{param:TIGOPROGRESS|}');
  if (ProgressFile = '') or (MaxProgress <= 0) then
    Exit;
  Step := CurProgress div (MaxProgress div 200 + 1);
  if Step = LastProgressStep then
    Exit;
  LastProgressStep := Step;
  SaveStringToFile(ProgressFile, IntToStr(CurProgress) + ' ' + IntToStr(MaxProgress), False);
end;

function ShouldLaunchTigo(): Boolean;
begin
  Result := (not WizardSilent) or
    (CompareText(ExpandConstant('{param:TIGORELAUNCH|0}'), '1') = 0);
end;
