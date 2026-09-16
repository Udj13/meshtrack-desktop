; MeshTrack Inno Setup script (Windows).
; Собирает installer/win/output/MeshTrackSetup-0.1.0.exe из dist/MeshTrack.
; Требования: сначала `pyinstaller installer\win\MeshTrack.spec`, затем Inno Setup 6.

#define MyAppName "MeshTrack"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "MeshTrack"
#define MyAppExeName "MeshTrack.exe"
#define MyAppDir "..\..\dist\MeshTrack"
#define MyIcon "..\..\assets\app.ico"

[Setup]
AppId={{8E4B7F2C-9D1A-4E3B-8C5F-2A9B1C7D3E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=MeshTrackSetup-{#MyAppVersion}
SetupIconFile={#MyIcon}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MyAppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent