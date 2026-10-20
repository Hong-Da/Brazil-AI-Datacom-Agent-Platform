@echo off
rem Stop and remove the Windows service LucidMesh (program, config and data are kept). Needs administrator rights.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo 需要管理员权限，正在请求 ……
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b 0
)
sc query LucidMesh >nul 2>&1
if errorlevel 1 (
  echo 没有注册服务 LucidMesh。
  goto end
)
service\lmesh-service.exe stop >nul 2>&1
service\lmesh-service.exe uninstall
if errorlevel 1 (
  echo 移除服务失败，详见 logs\lmesh-service.wrapper.log
  if "%LMESH_NO_PAUSE%"=="" pause
  exit /b 1
)
echo 已移除服务 LucidMesh。
:end
if "%LMESH_NO_PAUSE%"=="" pause
exit /b 0
