; 透网 LucidMesh Windows 安装程序（NSIS 3，Unicode）。由 scripts/build_release.py 调用 makensis 生成：
;   makensis /INPUTCHARSET UTF8 /DVERSION=0.5.0 /DVINUM=0.5.0.0 /DSTAGE=<离线包目录> /DOUTFILE=<输出 exe> /DICON=<app.ico> installer.nsi
; 默认装到 %LOCALAPPDATA%\Programs\LucidMesh，不需要管理员权限；配置、数据、日志在安装目录内。
; 静默安装：setup.exe /S [/D=目录]；静默卸载：uninstall.exe /S（静默时保留配置与数据）。

Unicode true
ManifestDPIAware true

!ifndef VERSION | STAGE | OUTFILE | ICON | VINUM
  !error "需要 /DVERSION /DVINUM /DSTAGE /DOUTFILE /DICON"
!endif

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "Sections.nsh"
!include "x64.nsh"

!define APP "LucidMesh"
!define REGKEY "Software\${APP}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP}"

Name "${APP} ${VERSION}"
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${REGKEY}" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 64
BrandingText "${APP} ${VERSION}"
ShowInstDetails show
ShowUninstDetails show

VIProductVersion "${VINUM}"
VIFileVersion "${VINUM}"

Var OldVersion
Var KeepData

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_COMPONENTSPAGE_SMALLDESC
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "$(RunNow)"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "PortugueseBR"
!insertmacro MUI_RESERVEFILE_LANGDLL

VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductName" "${APP}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=${LANG_ENGLISH} "FileDescription" "${APP} ${VERSION} Setup"
VIAddVersionKey /LANG=${LANG_ENGLISH} "LegalCopyright" "LucidMesh"

; ---------- 文案（中文 / English / Português (Brasil)） ----------
LangString SecProgramName ${LANG_SIMPCHINESE} "程序（必选）"
LangString SecProgramName ${LANG_ENGLISH} "Program (required)"
LangString SecProgramName ${LANG_PORTUGUESEBR} "Programa (obrigatório)"
LangString SecShortcutsName ${LANG_SIMPCHINESE} "开始菜单快捷方式"
LangString SecShortcutsName ${LANG_ENGLISH} "Start menu shortcuts"
LangString SecShortcutsName ${LANG_PORTUGUESEBR} "Atalhos no menu Iniciar"
LangString SecDesktopName ${LANG_SIMPCHINESE} "桌面快捷方式"
LangString SecDesktopName ${LANG_ENGLISH} "Desktop shortcut"
LangString SecDesktopName ${LANG_PORTUGUESEBR} "Atalho na área de trabalho"
LangString SecServiceName ${LANG_SIMPCHINESE} "注册为 Windows 服务（需要管理员权限）"
LangString SecServiceName ${LANG_ENGLISH} "Register as a Windows service (needs administrator)"
LangString SecServiceName ${LANG_PORTUGUESEBR} "Registrar como serviço do Windows (requer administrador)"
LangString SecProgramDesc ${LANG_SIMPCHINESE} "程序、自带的 Python 运行时与依赖、知识库。配置、数据、日志放在安装目录内，升级时保留。"
LangString SecProgramDesc ${LANG_ENGLISH} "Program, bundled Python runtime and dependencies, knowledge base. Config, data and logs live in the install folder and are kept on upgrade."
LangString SecProgramDesc ${LANG_PORTUGUESEBR} "Programa, runtime Python e dependências embutidos, base de conhecimento. Configuração, dados e logs ficam na pasta de instalação e são mantidos na atualização."
LangString SecShortcutsDesc ${LANG_SIMPCHINESE} "开始菜单中的启动、命令行、部署说明与卸载。"
LangString SecShortcutsDesc ${LANG_ENGLISH} "Start menu entries: start, command line, deployment guide, uninstall."
LangString SecShortcutsDesc ${LANG_PORTUGUESEBR} "Entradas no menu Iniciar: iniciar, linha de comando, guia de implantação, desinstalar."
LangString SecDesktopDesc ${LANG_SIMPCHINESE} "在桌面放一个启动快捷方式。"
LangString SecDesktopDesc ${LANG_ENGLISH} "Put a start shortcut on the desktop."
LangString SecDesktopDesc ${LANG_PORTUGUESEBR} "Colocar um atalho de início na área de trabalho."
LangString SecServiceDesc ${LANG_SIMPCHINESE} "开机自动启动、崩溃后自动重启（WinSW 服务包装器，MIT 许可证）。会请求管理员权限。"
LangString SecServiceDesc ${LANG_ENGLISH} "Start at boot and restart on failure (WinSW wrapper, MIT license). Asks for administrator rights."
LangString SecServiceDesc ${LANG_PORTUGUESEBR} "Iniciar com o sistema e reiniciar em caso de falha (WinSW, licença MIT). Solicita direitos de administrador."
LangString RunNow ${LANG_SIMPCHINESE} "立即启动 LucidMesh"
LangString RunNow ${LANG_ENGLISH} "Start LucidMesh now"
LangString RunNow ${LANG_PORTUGUESEBR} "Iniciar o LucidMesh agora"
LangString MsgSame ${LANG_SIMPCHINESE} "已安装同一版本 ${VERSION}。要重新安装（修复）吗？配置与数据会保留。"
LangString MsgSame ${LANG_ENGLISH} "Version ${VERSION} is already installed. Reinstall (repair)? Config and data are kept."
LangString MsgSame ${LANG_PORTUGUESEBR} "A versão ${VERSION} já está instalada. Reinstalar (reparar)? Configuração e dados são mantidos."
LangString MsgUpgrade ${LANG_SIMPCHINESE} "将从 $OldVersion 升级到 ${VERSION}：配置与数据保留，SQLite 数据库先备份到 backup\，安装后执行数据库迁移并合并新版本自带的知识库。请先关闭正在运行的 LucidMesh。降级（新版本号比已安装的旧）可能导致数据库不兼容。继续吗？"
LangString MsgUpgrade ${LANG_ENGLISH} "Upgrading from $OldVersion to ${VERSION}: config and data are kept, the SQLite database is backed up to backup\, then the database is migrated and the bundled knowledge base merged. Close any running LucidMesh first. Downgrading may leave the database incompatible. Continue?"
LangString MsgUpgrade ${LANG_PORTUGUESEBR} "Atualizando de $OldVersion para ${VERSION}: configuração e dados são mantidos, o banco SQLite é copiado para backup\, depois o banco é migrado e a base de conhecimento embutida é mesclada. Feche o LucidMesh antes. Rebaixar a versão pode deixar o banco incompatível. Continuar?"
LangString MsgKeep ${LANG_SIMPCHINESE} "保留配置与数据（config、data、logs、backup）吗？$\r$\n选“是”只删除程序文件，以后重新安装可继续使用。"
LangString MsgKeep ${LANG_ENGLISH} "Keep config and data (config, data, logs, backup)?$\r$\nYes removes only the program files, so a later reinstall can reuse them."
LangString MsgKeep ${LANG_PORTUGUESEBR} "Manter configuração e dados (config, data, logs, backup)?$\r$\nSim remove apenas os arquivos do programa, para reutilizá-los numa reinstalação."
LangString LnkCli ${LANG_SIMPCHINESE} "LucidMesh 命令行"
LangString LnkCli ${LANG_ENGLISH} "LucidMesh command line"
LangString LnkCli ${LANG_PORTUGUESEBR} "LucidMesh linha de comando"
LangString LnkDocs ${LANG_SIMPCHINESE} "部署说明"
LangString LnkDocs ${LANG_ENGLISH} "Deployment guide"
LangString LnkDocs ${LANG_PORTUGUESEBR} "Guia de implantação"
LangString LnkUninst ${LANG_SIMPCHINESE} "卸载 LucidMesh"
LangString LnkUninst ${LANG_ENGLISH} "Uninstall LucidMesh"
LangString LnkUninst ${LANG_PORTUGUESEBR} "Desinstalar o LucidMesh"

; ---------- 安装 ----------

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
  ReadRegStr $OldVersion HKCU "${REGKEY}" "Version"
  ${If} $OldVersion == "${VERSION}"
    MessageBox MB_YESNO|MB_ICONQUESTION "$(MsgSame)" /SD IDYES IDYES +2
    Abort
  ${ElseIf} $OldVersion != ""
    MessageBox MB_OKCANCEL|MB_ICONINFORMATION "$(MsgUpgrade)" /SD IDOK IDOK +2
    Abort
  ${EndIf}
FunctionEnd

; 停止从安装目录运行的 LucidMesh（服务需要管理员权限才能停止；停不了时文件被占用会提示重试）
!macro StopRunning un
Function ${un}StopRunning
  nsExec::Exec 'sc stop LucidMesh'
  Pop $0
  ; 安装程序是 32 位：关掉文件系统重定向，用 64 位 PowerShell，才能读到 64 位 python.exe 的路径
  ${DisableX64FSRedirection}
  nsExec::Exec 'powershell -NoProfile -Command "Get-Process python -ErrorAction SilentlyContinue | Where-Object { $$_.Path -like \"$INSTDIR\runtime\*\" } | Stop-Process -Force"'
  Pop $0
  ${EnableX64FSRedirection}
  Sleep 1500
FunctionEnd
!macroend
!insertmacro StopRunning ""
!insertmacro StopRunning "un."

Section "!$(SecProgramName)" SecProgram
  SectionIn RO
  Call StopRunning
  ${If} $OldVersion != ""
  ${AndIf} ${FileExists} "$INSTDIR\data\lmesh.db"
    CreateDirectory "$INSTDIR\backup"
    CopyFiles /SILENT "$INSTDIR\data\lmesh.db" "$INSTDIR\backup\lmesh-$OldVersion.db"
    DetailPrint "SQLite → backup\lmesh-$OldVersion.db"
  ${EndIf}
  ; 程序目录整体替换（不残留旧版本文件）；config、data、logs、backup 不动
  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\src"
  RMDir /r "$INSTDIR\knowledge"
  RMDir /r "$INSTDIR\assets"
  RMDir /r "$INSTDIR\docs"
  SetOutPath "$INSTDIR"
  File /r "${STAGE}\*.*"
  CreateDirectory "$INSTDIR\config"
  CreateDirectory "$INSTDIR\data"
  CreateDirectory "$INSTDIR\logs"
  WriteUninstaller "$INSTDIR\uninstall.exe"
  WriteRegStr HKCU "${REGKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${REGKEY}" "Version" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "透网 LucidMesh"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "LucidMesh"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\assets\brand\app.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr HKCU "${UNINSTKEY}" "QuietUninstallString" '"$INSTDIR\uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" $0
  ; 已配置（升级）时：数据库迁移、合并新版本自带的知识库（启动时也会做，这里先做好并留下记录）
  ${If} ${FileExists} "$INSTDIR\config\config.toml"
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /c ""$INSTDIR\lmesh.bat" --yes db upgrade"'
    Pop $0
    nsExec::ExecToLog '"$SYSDIR\cmd.exe" /c ""$INSTDIR\lmesh.bat" --yes kb upgrade"'
    Pop $0
  ${EndIf}
SectionEnd

Section "$(SecShortcutsName)" SecShortcuts
  CreateDirectory "$SMPROGRAMS\${APP}"
  CreateShortcut "$SMPROGRAMS\${APP}\${APP}.lnk" "$INSTDIR\start.bat" "" "$INSTDIR\assets\brand\app.ico"
  CreateShortcut "$SMPROGRAMS\${APP}\$(LnkCli).lnk" "$SYSDIR\cmd.exe" '/k cd /d "$INSTDIR" && lmesh.bat --help' "$INSTDIR\assets\brand\app.ico"
  CreateShortcut "$SMPROGRAMS\${APP}\$(LnkDocs).lnk" "$INSTDIR\docs\deploy.md"
  CreateShortcut "$SMPROGRAMS\${APP}\$(LnkUninst).lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section /o "$(SecDesktopName)" SecDesktop
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\start.bat" "" "$INSTDIR\assets\brand\app.ico"
SectionEnd

Section /o "$(SecServiceName)" SecService
  ; service-install.bat 自己请求管理员权限（UAC）
  ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\service-install.bat""'
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecProgram} "$(SecProgramDesc)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecShortcuts} "$(SecShortcutsDesc)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop} "$(SecDesktopDesc)"
  !insertmacro MUI_DESCRIPTION_TEXT ${SecService} "$(SecServiceDesc)"
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function LaunchApp
  ${If} ${SectionIsSelected} ${SecService}
    ExecShell "open" "http://127.0.0.1:9090"
  ${Else}
    Exec '"$INSTDIR\start.bat"'
  ${EndIf}
FunctionEnd

; ---------- 卸载 ----------

Function un.onInit
  !insertmacro MUI_UNGETLANGUAGE
FunctionEnd

Section "Uninstall"
  ; 注册了服务时先移除（service-uninstall.bat 自己请求管理员权限）
  nsExec::Exec 'sc query LucidMesh'
  Pop $0
  ${If} $0 == 0
    ExecWait '"$SYSDIR\cmd.exe" /c ""$INSTDIR\service-uninstall.bat""'
  ${EndIf}
  Call un.StopRunning
  StrCpy $KeepData 1
  MessageBox MB_YESNO|MB_ICONQUESTION "$(MsgKeep)" /SD IDYES IDYES +2
  StrCpy $KeepData 0

  RMDir /r "$INSTDIR\runtime"
  RMDir /r "$INSTDIR\src"
  RMDir /r "$INSTDIR\knowledge"
  RMDir /r "$INSTDIR\assets"
  RMDir /r "$INSTDIR\docs"
  RMDir /r "$INSTDIR\service"
  RMDir /r "$INSTDIR\cache"
  RMDir /r "$INSTDIR\tmp"
  Delete "$INSTDIR\start.bat"
  Delete "$INSTDIR\lmesh.bat"
  Delete "$INSTDIR\service-install.bat"
  Delete "$INSTDIR\service-uninstall.bat"
  Delete "$INSTDIR\pyproject.toml"
  Delete "$INSTDIR\VERSION"
  Delete "$INSTDIR\README.txt"
  Delete "$INSTDIR\uninstall.exe"
  ${If} $KeepData == 0
    RMDir /r "$INSTDIR\config"
    RMDir /r "$INSTDIR\data"
    RMDir /r "$INSTDIR\logs"
    RMDir /r "$INSTDIR\backup"
  ${EndIf}
  RMDir "$INSTDIR"

  RMDir /r "$SMPROGRAMS\${APP}"
  Delete "$DESKTOP\${APP}.lnk"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "${REGKEY}"
SectionEnd
