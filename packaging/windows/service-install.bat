@echo off
rem Register LucidMesh as a Windows service (auto start, restart on failure). Needs administrator rights; asks via UAC.
rem Service wrapper: service\lmesh-service.exe = WinSW 2.12 (MIT license, see service\WinSW-LICENSE.txt).
rem Usage: service-install.bat [--no-start]
chcp 65001 >nul
setlocal
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo 需要管理员权限，正在请求 ……
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  exit /b 0
)
if not exist logs mkdir logs
if not exist tmp\os mkdir tmp\os
sc query LucidMesh >nul 2>&1
if not errorlevel 1 (
  echo 服务 LucidMesh 已存在，先停止并重新注册 ……
  service\lmesh-service.exe stop >nul 2>&1
  service\lmesh-service.exe uninstall || goto fail
)
service\lmesh-service.exe install || goto fail
echo 已注册服务 LucidMesh（自动启动）。
if /i "%~1"=="--no-start" goto done
service\lmesh-service.exe start || goto fail
echo 服务已启动。尚未配置时，用浏览器打开 http://127.0.0.1:9090 完成首次配置向导。
:done
echo 管理：services.msc 中的 LucidMesh，或 sc start / stop LucidMesh；卸载服务：service-uninstall.bat
if "%LMESH_NO_PAUSE%"=="" pause
exit /b 0
:fail
echo 注册服务失败，详见 logs\lmesh-service.wrapper.log
if "%LMESH_NO_PAUSE%"=="" pause
exit /b 1
