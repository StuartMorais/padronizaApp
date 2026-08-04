#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName "Padroniza"
#define MyAppPublisher "Padroniza"
#define MyAppExeName "Padroniza.exe"

[Setup]
AppId=Padroniza.Desktop
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
SetupIconFile=..\assets\padroniza.ico

DefaultDirName={localappdata}\Programs\Padroniza
DefaultGroupName=Padroniza
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

OutputDir=..\release
OutputBaseFilename=Padroniza-Setup-v{#MyAppVersion}

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

UninstallDisplayIcon={app}\{#MyAppExeName}

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "..\dist\installer\Padroniza\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Padroniza"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Padroniza"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Padroniza"; Flags: nowait postinstall skipifsilent