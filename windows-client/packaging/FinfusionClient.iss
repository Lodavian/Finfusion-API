#define MyAppName "FinfusionClient"
#define MyAppDisplayName "Finfusion Client"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0-rc1"
#endif
#ifndef MyFileVersion
  #define MyFileVersion "1.0.0.1"
#endif
#define MyAppExeName "FinfusionClient.exe"

; The installer has two deliberately separate release lanes.  The build
; script supplies exactly one of these defines; keeping the decision here
; means the generated RC can never accidentally inherit release signing
; settings.
#ifdef InternalUnsignedRc
  #ifdef FormalSigned
    #error InternalUnsignedRc and FormalSigned are mutually exclusive
  #endif
  #define MyAppPublisher "FinfusionClient Internal Candidate"
  #ifndef MyOutputBaseFilename
    #define MyOutputBaseFilename "FinfusionClient-Setup-1.0.0-rc1"
  #endif
#else
  #ifndef FormalSigned
    #error Exactly one installer release mode must be selected
  #endif
  #ifndef MyAppPublisher
    #error MyAppPublisher must be supplied by the formal release build
  #endif
  #ifndef SignToolName
    #error SignToolName must be supplied by the formal signed release build
  #endif
  #ifndef MyOutputBaseFilename
    #define MyOutputBaseFilename "FinfusionClient-Setup-1.0.0"
  #endif
#endif

; Override with /DStagingDir=... when compiling from CI. The staging tree must
; contain the already-built one-folder application and no runtime data.
#ifndef StagingDir
  #define StagingDir "..\dist\FinfusionClient"
#endif

[Setup]
AppId={{C0BFB545-5213-4D5C-BC59-FF5B2E974643}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyFileVersion}
OutputDir=..\dist\installer
CloseApplications=no
RestartApplications=no
AppVerName={#MyAppDisplayName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Finfusion Client
DefaultGroupName={#MyAppDisplayName}
; Formal value is OutputBaseFilename=FinfusionClient-Setup-0.2.0; the internal RC
; value appends -rc1 so the two artifacts cannot be confused.
OutputBaseFilename={#MyOutputBaseFilename}
MinVersion=10.0.19045
SetupArchitecture=x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
ChangesAssociations=no
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\FinfusionClient.ico
WizardStyle=modern
Compression=lzma2
SolidCompression=yes
; The application must create this named mutex before serving requests. This
; makes upgrades fail safely while FinfusionClient is still running.
AppMutex=Local\Finfusion.Client.V1
; FormalSigned injects this named command with ISCC /S; it signs setup and
; uninstaller.  InternalUnsignedRc intentionally has no SignTool directive.
#ifdef FormalSigned
SignTool={#SignToolName}
SignedUninstaller=yes
#else
SignedUninstaller=no
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："

[Files]
Source: "vendor\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Flags: dontcopy
Source: "{#StagingDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{commondesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppDisplayName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent runasoriginaluser

; Deliberately no [UninstallDelete] entries: LOCALAPPDATA data and Windows
; Credential Manager entries are user data and must survive uninstall.

[Code]
function ParseSemanticVersion(const Value: String; var Packed: Int64): Boolean;
var
  BaseValue: String;
  MajorText, MinorText, PatchText: String;
  SuffixAt, DotAt: Integer;
  Major, Minor, Patch: Integer;
begin
  { Accept prerelease upgrade inputs such as 0.9.9-qa while comparing the
    numeric semantic version components. }
  BaseValue := Value;
  SuffixAt := Pos('-', BaseValue);
  if SuffixAt > 0 then Delete(BaseValue, SuffixAt, Length(BaseValue));

  DotAt := Pos('.', BaseValue);
  if DotAt <= 1 then begin Result := False; Exit; end;
  MajorText := Copy(BaseValue, 1, DotAt - 1);
  Delete(BaseValue, 1, DotAt);

  DotAt := Pos('.', BaseValue);
  if DotAt <= 1 then begin Result := False; Exit; end;
  MinorText := Copy(BaseValue, 1, DotAt - 1);
  PatchText := Copy(BaseValue, DotAt + 1, Length(BaseValue));
  if (PatchText = '') or (Pos('.', PatchText) > 0) then begin Result := False; Exit; end;

  Major := StrToIntDef(MajorText, -1);
  Minor := StrToIntDef(MinorText, -1);
  Patch := StrToIntDef(PatchText, -1);
  Result := (Major >= 0) and (Minor >= 0) and (Patch >= 0);
  if Result then Packed := PackVersionComponents(Major, Minor, Patch, 0);
end;

function ApplicationRunning(): Boolean;
var Locator, Services, Processes: Variant;
begin
  Result := CheckForMutexes('Local\Finfusion.Client.V1');
  if Result then Exit;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('', 'root\CIMV2');
    Processes := Services.ExecQuery('SELECT ProcessId FROM Win32_Process WHERE Name="FinfusionClient.exe"');
    Result := Processes.Count > 0;
  except
    { Failed process inspection must not permit overwriting a running app. }
    Result := True;
  end;
end;

function InitializeSetup(): Boolean;
var
  InstalledVersion: String;
  InstalledPacked, CandidatePacked: Int64;
  OldSuffix, NewSuffix: Integer;
begin
  Result := True;
  if ApplicationRunning() then begin
    MsgBox('Finfusion Client 正在运行，请关闭后再安装。', mbError, MB_OK);
    Result := False; Exit;
  end;
  if RegQueryStringValue(HKLM64,
       'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C0BFB545-5213-4D5C-BC59-FF5B2E974643}_is1',
       'DisplayVersion', InstalledVersion) then
  begin
    if not ParseSemanticVersion(InstalledVersion, InstalledPacked) or
       not ParseSemanticVersion('{#MyAppVersion}', CandidatePacked) then begin
      MsgBox('无法判断已安装版本，拒绝覆盖。', mbError, MB_OK); Result := False; Exit;
    end;
    if InstalledPacked > CandidatePacked then Result := False;
    if InstalledPacked = CandidatePacked then begin
      OldSuffix := Pos('-rc', InstalledVersion);
      NewSuffix := Pos('-rc', '{#MyAppVersion}');
      if (Pos('-', InstalledVersion) = 0) and (NewSuffix > 0) then Result := False;
      if (OldSuffix > 0) and (NewSuffix > 0) and
        (StrToIntDef(Copy(InstalledVersion, OldSuffix + 3, Length(InstalledVersion)), 99999) >
         StrToIntDef(Copy('{#MyAppVersion}', NewSuffix + 3, Length('{#MyAppVersion}')), -1)) then Result := False;
    end;
    if not Result then MsgBox('检测到更高版本，禁止降级安装。', mbError, MB_OK);
  end;
end;

function RuntimePresent(): Boolean;
var Version: String;
begin
  Result := (RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
             RegQueryStringValue(HKCU32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version)) and
             (Version <> '') and (Version <> '0.0.0.0');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer; Release: Cardinal;
begin
  Result := '';
  if ApplicationRunning() then begin
    Result := 'Finfusion Client 正在运行，请关闭后重试。'; Exit;
  end;
  if not RegQueryDWordValue(HKLM64, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release) or (Release < 528040) then begin
    Result := '请先安装 Microsoft .NET Framework 4.8 或更高版本，再运行安装器。'; Exit;
  end;
  if RuntimePresent() then Exit;
  ExtractTemporaryFile('MicrosoftEdgeWebView2RuntimeInstallerX64.exe');
  if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then begin
    Result := '无法启动 WebView2 完整离线安装器。'; Exit;
  end;
  if (Code <> 0) and (Code <> 3010) then begin
    Result := 'WebView2 安装失败。退出码：' + IntToStr(Code); Exit;
  end;
  if not RuntimePresent() then Result := 'WebView2 安装后检测失败，请检查系统安装权限。';
  if Code = 3010 then NeedsRestart := True;
end;
