; Nexus 桌面助手 NSIS 安装脚本（Unicode / 中英双语）
; 构建入口：python build\build_release.py

Unicode true

!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "WinMessages.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "0.1.0"
!endif
!ifndef STAGE
  !define STAGE "files"
!endif
!ifndef OUTFILE
  !define OUTFILE "Nexus-Setup.exe"
!endif

!define PRODUCT_NAME "Nexus 桌面助手"
!define PRODUCT_EN "Nexus Desktop Assistant"
!define PRODUCT_PUBLISHER "Nexus"
!define UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\Nexus"
!define APP_KEY "Software\Nexus"

Name "${PRODUCT_NAME}"
Caption "${PRODUCT_NAME} ${VERSION} 安装 / Setup"
BrandingText "Nexus"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\Nexus"
InstallDirRegKey HKCU "${APP_KEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64

Icon "..\..\app\web\assets\nexus.ico"
UninstallIcon "..\..\app\web\assets\nexus.ico"

VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=2052 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=2052 "FileDescription" "${PRODUCT_NAME} 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "LegalCopyright" "Nexus"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_EN}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "FileDescription" "${PRODUCT_EN} Setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "Nexus"

; ---------------- 界面 ----------------
!define MUI_ABORTWARNING
!define MUI_ICON "..\..\app\web\assets\nexus.ico"
!define MUI_UNICON "..\..\app\web\assets\nexus.ico"

!define MUI_WELCOMEPAGE_TITLE "欢迎安装 ${PRODUCT_NAME}"
!define MUI_WELCOMEPAGE_TEXT "本向导将安装 Nexus 桌面助手。$\r$\n$\r$\n安装位置可以更改，默认安装到当前用户目录，无需管理员权限。$\r$\n$\r$\nThis wizard will install Nexus Desktop Assistant. You can change the install location; the default is under your user profile and requires no administrator rights."

!define MUI_DIRECTORYPAGE_TEXT_TOP "请选择 Nexus 的安装位置。默认位置在当前用户目录下，不需要管理员权限。$\r$\n$\r$\nChoose the install location. The default is under your user profile and needs no administrator rights."

!define MUI_FINISHPAGE_RUN "$INSTDIR\Nexus.exe"
!define MUI_FINISHPAGE_RUN_TEXT "运行 Nexus / Run Nexus"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.html"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "查看使用说明（中英双语） / View Read Me"
!define MUI_FINISHPAGE_LINK "打开安装目录 / Open install folder"
!define MUI_FINISHPAGE_LINK_LOCATION "$INSTDIR"

!insertmacro MUI_PAGE_WELCOME
Page custom ReadmePageCreate
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"

!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${APP_KEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "InstallerLanguage"

; ---------------- 说明页 ----------------
Var ReadmeBox
Var ReadmeFont

!define RS_CHILD 0x40000000
!define RS_VISIBLE 0x10000000
!define RS_TABSTOP 0x00010000
!define RS_VSCROLL 0x00200000
!define RS_BORDER 0x00800000
!define RS_MULTILINE 0x00000004
!define RS_READONLY 0x00000800
!ifndef EM_REPLACESEL
  !define EM_REPLACESEL 0x00C2
!endif
!ifndef EM_SETBKGNDCOLOR
  !define EM_SETBKGNDCOLOR 0x0443
!endif

!macro README_LINE text
  StrCpy $R0 "${text}"
  SendMessage $ReadmeBox ${EM_REPLACESEL} 0 "STR:$R0"
!macroend

Function ReadmePageCreate
  !insertmacro MUI_HEADER_TEXT "使用说明 / Read Me" "请阅读后继续 / Please read before continuing"

  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}

  System::Call 'kernel32::LoadLibraryW(w "riched20.dll") i .r1'
  nsDialogs::CreateControl "RichEdit20W" \
    ${RS_CHILD}|${RS_VISIBLE}|${RS_TABSTOP}|${RS_VSCROLL}|${RS_BORDER}|${RS_MULTILINE}|${RS_READONLY} \
    0 0 0 100% 100% ""
  Pop $ReadmeBox

  System::Call 'gdi32::CreateFontW(i 18, i 0, i 0, i 0, i 400, i 0, i 0, i 0, i 134, i 0, i 0, i 5, i 0, w "Microsoft YaHei UI") p .r2'
  StrCpy $ReadmeFont $r2
  SendMessage $ReadmeBox ${WM_SETFONT} $ReadmeFont 1
  SendMessage $ReadmeBox ${EM_SETBKGNDCOLOR} 0 0x00FFFFFF

  !insertmacro README_LINE "Nexus 桌面助手 / Nexus Desktop Assistant$\r$\n$\r$\n"
  !insertmacro README_LINE "【中文】$\r$\n"
  !insertmacro README_LINE "1. 安装向导可更改安装位置，默认安装到当前用户目录，无需管理员权限。$\r$\n"
  !insertmacro README_LINE "2. 安装完成后勾选“运行 Nexus”即可启动；首次使用请在设置里填写 DeepSeek API Key。$\r$\n"
  !insertmacro README_LINE "3. 本地数据默认保存在 %APPDATA%\Nexus。配置与历史记录均使用 AES-256-GCM 加密，$\r$\n"
  !insertmacro README_LINE "   主密钥由 Windows DPAPI 保护，绑定当前 Windows 账户和电脑。$\r$\n"
  !insertmacro README_LINE "4. 绿色包解压后用 Nexus.exe 启动，数据保存在程序目录的 data 文件夹。$\r$\n"
  !insertmacro README_LINE "5. 快捷键：Ctrl+Alt+Space 打开主界面，Ctrl+Alt+V 语音输入。$\r$\n"
  !insertmacro README_LINE "6. 卸载时会询问是否删除本地数据；选择“否”可保留数据供以后重装。$\r$\n$\r$\n"
  !insertmacro README_LINE "【English】$\r$\n"
  !insertmacro README_LINE "1. You can change the install location; the default is under your user profile and needs no admin rights.$\r$\n"
  !insertmacro README_LINE "2. After installation, tick $\"Run Nexus$\". Enter your DeepSeek API key in Settings on first use.$\r$\n"
  !insertmacro README_LINE "3. Data is stored in %APPDATA%\Nexus. Settings and history are encrypted with AES-256-GCM;$\r$\n"
  !insertmacro README_LINE "   the master key is protected by Windows DPAPI and bound to this Windows account and PC.$\r$\n"
  !insertmacro README_LINE "4. The portable build stores data in the data folder next to Nexus.exe.$\r$\n"
  !insertmacro README_LINE "5. Shortcuts: Ctrl+Alt+Space opens the main window; Ctrl+Alt+V starts voice input.$\r$\n"
  !insertmacro README_LINE "6. The uninstaller asks whether to delete local data; choose No to keep it for a later reinstall.$\r$\n"

  nsDialogs::Show
FunctionEnd

; ---------------- 安装 ----------------
Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
  ; 覆盖安装前结束正在运行的实例，避免文件占用
  nsExec::ExecToStack 'taskkill /IM Nexus.exe /F'
  Pop $0
  Pop $1
FunctionEnd

Section "Nexus 主程序 / Nexus application" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File /r "${STAGE}\Nexus\*.*"

  WriteUninstaller "$INSTDIR\uninstall.exe"
  CreateDirectory "$SMPROGRAMS\Nexus"
  CreateShortcut "$SMPROGRAMS\Nexus\Nexus.lnk" "$INSTDIR\Nexus.exe"
  CreateShortcut "$SMPROGRAMS\Nexus\卸载 Nexus.lnk" "$INSTDIR\uninstall.exe"

  WriteRegStr HKCU "${APP_KEY}" "InstallDir" "$INSTDIR"

  WriteRegStr HKCU "${UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayIcon" "$INSTDIR\Nexus.exe"
  WriteRegStr HKCU "${UNINST_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKCU "${UNINST_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINST_KEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINST_KEY}" "NoRepair" 1
SectionEnd

Section "桌面快捷方式 / Desktop shortcut" SecDesktop
  CreateShortcut "$DESKTOP\Nexus.lnk" "$INSTDIR\Nexus.exe"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain} "Nexus 主程序、依赖库与外置业务字节码。/ Nexus application, dependencies and external bytecode."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "在桌面创建 Nexus 快捷方式。/ Create a Nexus shortcut on the desktop."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ---------------- 卸载 ----------------
Section "Uninstall"
  nsExec::ExecToStack 'taskkill /IM Nexus.exe /F'
  Pop $0
  Pop $1

  Delete "$DESKTOP\Nexus.lnk"
  Delete "$SMPROGRAMS\Nexus\Nexus.lnk"
  Delete "$SMPROGRAMS\Nexus\卸载 Nexus.lnk"
  RMDir "$SMPROGRAMS\Nexus"

  DeleteRegKey HKCU "${UNINST_KEY}"
  DeleteRegValue HKCU "${APP_KEY}" "InstallDir"
  DeleteRegValue HKCU "${APP_KEY}" "InstallerLanguage"
  DeleteRegKey /ifempty HKCU "${APP_KEY}"

  IfSilent uninst_keep_data
  MessageBox MB_YESNO|MB_ICONQUESTION \
    "是否同时删除本地数据？$\r$\n$\r$\n将删除 %APPDATA%\Nexus（对话记录、设置、日志和本地模型）。$\r$\n选择“否”可以保留数据，供以后重新安装使用。$\r$\n$\r$\nDelete local data too?$\r$\nThis removes %APPDATA%\Nexus (history, settings, logs and local models).$\r$\nChoose No to keep it for a later reinstall." \
    IDNO uninst_keep_data
  RMDir /r "$APPDATA\Nexus"
  uninst_keep_data:

  RMDir /r "$INSTDIR"
SectionEnd
