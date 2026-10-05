; ============================================================
; LocalRecord.iss —— Inno Setup 6 安装器脚本（可选产物）
; 构建: iscc /DAppSource="dist\Local Record" installer\LocalRecord.iss
; 说明: 未签名安装器首次运行会被 SmartScreen 拦截，
;       属正常现象：更多信息 → 仍要运行。
; ============================================================
#ifndef AppSource
  #define AppSource "dist\Local Record"
#endif

#define MyAppName "Local Record"
#define MyAppVersion "1.0.0"
; 注意：PyInstaller spec 里的 name="Local Record"，所以 exe 名带空格。
; 写错会导致快捷方式和安装后自动启动都指向不存在的文件。
#define MyAppExeName "Local Record.exe"

[Setup]
AppId={{8F4C0B2E-3D5A-4B6C-9E7F-1A2B3C4D5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Local Record
DefaultDirName={userpf}\LocalRecord
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; 注意：Inno 的相对路径是相对**脚本所在目录**（SourceDir）解析的，
; 所以这里写 ..\dist 才是项目的 dist\；SetupIconFile 直接写同目录文件名。
OutputDir=..\dist
OutputBaseFilename=LocalRecord-setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
; x64compatible 是 Inno Setup 6.3+ 推荐写法（旧的 x64 会提示 deprecated）
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=LocalRecord.ico

[Languages]
; 简体中文语言包**不在** Inno Setup 默认安装里，需要单独放到编译器的 Languages\ 目录：
;   https://jrsoftware.org/files/istrans/ChineseSimplified.isl
;   （国内可用 GitHub 代理，例如 https://ghfast.top/https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/ChineseSimplified.isl）
; 这里用 ISPP 条件判断：有就编译成中文安装器，没有也不会让整个构建失败。
#if FileExists(CompilerPath + "\Languages\ChineseSimplified.isl")
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
