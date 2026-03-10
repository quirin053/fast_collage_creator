; installer/setup.iss
; Build with: ISCC.exe /DAppVersion="1.0.0" setup.iss

#define AppName "Fast Collage Creator"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppPublisher "quirin053"
#define AppExeName "FastCollageCreator.exe"
#define AppURL "https://github.com/quirin053/fast_collage_creator"

[Setup]
AppId={728728fc-e63f-4603-802b-563bf3b4c31f}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\FastCollageCreator
DefaultGroupName={#AppName}
AllowNoIcons=yes
OutputDir=Output
OutputBaseFilename=FastCollageCreator_Setup
SetupIconFile=..\icons\icon_01.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\FastCollageCreator\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
