#ifndef ArtifactsDir
  #error ArtifactsDir define is required
#endif
#ifndef OutputDir
  #define OutputDir "."
#endif
#ifndef ProductVersion
  #define ProductVersion "0.1.0"
#endif

[Setup]
AppId={{6CED9309-A9B0-4BF1-8A95-FE8A62A47560}
#ifdef InternalUnsignedPayload
AppName=Finfusion Server Node (INTERNAL unsigned)
#elif ReleasePayload
AppName=Finfusion Server Node
#else
AppName=Finfusion Server Node (Development - non-LIVE)
#endif
AppVersion={#ProductVersion}
AppPublisher=Finfusion
DefaultDirName={autopf}\Finfusion Node
DefaultGroupName=Finfusion Server Node
OutputDir={#OutputDir}
#ifdef InternalUnsignedPayload
OutputBaseFilename=FinfusionServer-Setup-x64-INTERNAL
#else
OutputBaseFilename=FinfusionServer-Setup-x64
#endif
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
#ifdef ReleasePayload
PrivilegesRequired=admin
#else
PrivilegesRequired=lowest
#endif
WizardStyle=modern dynamic
UninstallDisplayIcon={app}\FinfusionServer-Control.exe
SetupIconFile={#SourcePath}\assets\Finfusion.ico
SetupLogging=yes
DisableProgramGroupPage=yes

[Files]
Source: "{#ArtifactsDir}\FinfusionServer-Control.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ArtifactsDir}\FinfusionServer-NodeHost.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ArtifactsDir}\Install-FinfusionNode.ps1"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\Uninstall-FinfusionNode.ps1"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\Invoke-WslBootstrap.ps1"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\config.example.json"; DestDir: "{app}\bundle"; Flags: ignoreversion
#ifdef ReleasePayload
Source: "{#ArtifactsDir}\FinfusionServer-Control.exe"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\FinfusionServer-NodeHost.exe"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\bootstrap.tar.gz"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\debian-12-wsl-rootfs.tar.gz"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\bundle-manifest.json"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\dependencies.lock.json"; DestDir: "{app}\bundle"; Flags: ignoreversion
Source: "{#ArtifactsDir}\LICENSES\*"; DestDir: "{app}\bundle\LICENSES"; Flags: ignoreversion recursesubdirs createallsubdirs
#endif

[Icons]
Name: "{group}\Finfusion Server Control"; Filename: "{app}\FinfusionServer-Control.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\Finfusion Server Control"; Filename: "{app}\FinfusionServer-Control.exe"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

#ifdef ReleasePayload
[Run]
#ifdef InternalUnsignedPayload
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bundle\Install-FinfusionNode.ps1"" -BundleDirectory ""{app}\bundle"" -InstallRoot ""{app}"" -AllowUnsignedDevelopment"; StatusMsg: "正在安装 INTERNAL 专用 Debian WSL2 节点…"; Flags: runhidden waituntilterminated
#else
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bundle\Install-FinfusionNode.ps1"" -BundleDirectory ""{app}\bundle"" -InstallRoot ""{app}"""; StatusMsg: "正在安装专用 Debian WSL2 节点…"; Flags: runhidden waituntilterminated
#endif

[UninstallRun]
Filename: "{sys}\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\bundle\Uninstall-FinfusionNode.ps1"" -Confirm:$false"; Flags: runhidden waituntilterminated; RunOnceId: "FinfusionNodeRemove"
#endif
