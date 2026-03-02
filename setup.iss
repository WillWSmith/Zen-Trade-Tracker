[Setup]
AppName=Zen Trade Tracker
AppVersion=1.0
DefaultDirName={autopf}\Zen Trade Tracker
DefaultGroupName=Zen Trade Tracker
OutputDir=Output
OutputBaseFilename=Zen_Trade_Tracker_Installer
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=admin

[Files]
Source: "dist\trade_tracker.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\Zen Trade Tracker"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"
Name: "{group}\Zen Trade Tracker"; Filename: "{app}\trade_tracker.exe"; IconFilename: "{app}\icon.ico"
