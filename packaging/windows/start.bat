@echo off
rem LucidMesh start script for the Windows offline package (bundled Python runtime, no internet needed).
rem Usage: start.bat [--check] [--setup] [--port PORT]
rem   --check  check only (version, config, database, knowledge base), do not start
rem   --setup  run the first-time setup on the command line (otherwise use the web wizard)
rem   --port   override the listening port for this run (config file unchanged)
rem Note: keep these header comments ASCII; cmd misreads multi-byte text read before chcp takes effect.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
call "%~dp0lmesh.bat" --env-only
if not exist logs mkdir logs
set "LOG=logs\start.log"
echo ==== %date% %time% start.bat %* ==== >> "%LOG%"

set CHECK=0
set SETUP=0
set PORT=
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--check" set CHECK=1& shift & goto parse
if /i "%~1"=="--setup" set SETUP=1& shift & goto parse
if /i "%~1"=="--port" set "PORT=%~2"& shift & shift & goto parse
echo 未知参数：%~1
exit /b 2
:parsed

echo [1/3] 检查配置 ……
if "%SETUP%"=="1" if not exist config\config.toml (
  "%LMESH_PY%" -m lmesh setup || (call :die "配置失败" "按提示重新填写；或不加 --setup 启动后在浏览器中完成向导" & exit /b 1)
)
if exist config\config.toml (echo       已配置) else (echo       尚未配置：启动后在浏览器中完成向导)

echo [2/3] 检查数据库与知识库 ……
if exist config\config.toml (
  "%LMESH_PY%" -m lmesh db upgrade >> "%LOG%" 2>&1 || (call :die "数据库升级失败" "检查 config\config.toml 中的 [database] url；详见 %LOG%" & exit /b 1)
  echo       数据库已是最新
) else (
  echo       配置完成后自动初始化
)

if "%CHECK%"=="1" (
  echo [3/3] 检查完成（--check，不启动）
  "%LMESH_PY%" -m lmesh status
  exit /b %errorlevel%
)

echo [3/3] 启动 ……（按 Ctrl+C 停止）
if defined PORT ("%LMESH_PY%" -m lmesh serve --port %PORT%) else ("%LMESH_PY%" -m lmesh serve)
if errorlevel 1 pause
exit /b %errorlevel%

:die
echo 失败：%~1
echo 处理建议：%~2
echo 失败：%~1 >> "%LOG%"
pause
exit /b 1
