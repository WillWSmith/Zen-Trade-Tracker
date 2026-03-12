[Setup]
; --- Branding & Publisher Info ---
AppName=Zen Portfolios
AppVersion=1.0.0
AppPublisher=Zen Trading
AppPublisherURL=https://www.youtube.com/@ZenGaming

; --- Installation Directories ---
DefaultDirName={autopf}\Zen Portfolios
DefaultGroupName=Zen Portfolios
OutputDir=Output
OutputBaseFilename=Zen_Portfolios_Installer

; --- Icons & Visuals ---
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
WizardStyle=modern
WizardImageFile=splash.png
WizardSmallImageFile=splash.png

; --- System Settings ---
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\trade_tracker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Zen Portfolios"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Zen Portfolios"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\trade_tracker.exe"; Description: "Launch Zen Portfolios"; Flags: nowait postinstall skipifsilent
