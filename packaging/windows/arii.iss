#define MyAppName "Arii"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Gabriel Anderson"
#define MyAppExeName "Arii.exe"

[Setup]
AppId={{3D0C131A-EC57-467C-A4B2-8509AC74EEAC}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Arii
DefaultGroupName=Arii
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist-installer
OutputBaseFilename=Arii-{#MyAppVersion}-windows-x64
SetupIconFile=..\..\assets\icons\arii.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
LicenseFile=..\..\LICENSE
InfoAfterFile=..\..\THIRD_PARTY_NOTICES.md

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\Arii\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Early prereleases could collect Poppler's ICU DLLs from the build-machine
; PATH. Remove those stale files during an in-place upgrade.
Type: files; Name: "{app}\_internal\icuuc.dll"
Type: files; Name: "{app}\_internal\icudt*.dll"

[Icons]
Name: "{autoprograms}\Arii"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Arii"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos adicionales:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir Arii"; Flags: nowait postinstall skipifsilent
