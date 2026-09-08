#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Office Tools"
#define MyAppPublisher "Office Tools"
#define MyAppExeName "OfficeTools.exe"

[Setup]
AppId={{3CE109DE-C638-43BA-A478-6EC9718AAF2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\OfficeTools
DefaultGroupName=Office Tools
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=OfficeTools-Setup-v{#MyAppVersion}
SetupIconFile=..\assets\office-tools.ico
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "..\dist\OfficeTools.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Office Tools"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Office Tools"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Office Tools"; Flags: nowait postinstall skipifsilent
