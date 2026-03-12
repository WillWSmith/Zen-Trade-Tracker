[Setup]
; --- Branding & Publisher Info ---
AppName=Zen Trade Scanner
AppVersion=1.0.0
AppPublisher=Zen Trading
AppPublisherURL=https://www.youtube.com/@ZenGaming

; --- Installation Directories ---
DefaultDirName={autopf}\Zen Trade Scanner
DefaultGroupName=Zen Trade Scanner
OutputDir=Output
OutputBaseFilename=Zen_Trade_Scanner_Installer

; --- Icons & Visuals ---
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico

; --- System Settings ---
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\trade_tracker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Zen Trade Scanner"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Zen Trade Scanner"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"

[Run]
Filename: "{app}\trade_tracker.exe"; Description: "Launch Zen Trade Scanner"; Flags: nowait postinstall skipifsilent
