@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
rem 透网 LucidMesh 一键运行（Windows）
rem 用法：start.bat [--check] [--setup [--defaults]] [--reinstall] [--port 端口]
cd /d "%~dp0"
call scripts\env.bat
if not exist logs mkdir logs
set "LOG=logs\start.log"
echo ==== %date% %time% start.bat %* ==== >> "%LOG%"

set CHECK=0
set SETUP=0
set DEFAULTS=0
set REINSTALL=0
set PORT=
:parse
if "%~1"=="" goto parsed
if /i "%~1"=="--check" set CHECK=1& shift & goto parse
if /i "%~1"=="--setup" set SETUP=1& shift & goto parse
if /i "%~1"=="--defaults" set DEFAULTS=1& shift & goto parse
if /i "%~1"=="--reinstall" set REINSTALL=1& shift & goto parse
if /i "%~1"=="--port" set "PORT=%~2"& shift & shift & goto parse
echo 未知参数：%~1
exit /b 2
:parsed

echo [1/6] 检查 uv ……
where uv >nul 2>nul
where uv >nul 2>nul
if errorlevel 1 (
  set /p ANS=没有找到 uv（Python 包管理器），现在安装吗？[Y/n]
  if /i "!ANS!"=="n" call :die "需要 uv" "安装 uv 后重新运行 start.bat" & exit /b 1
  if not exist "%UV_INSTALL_DIR%" mkdir "%UV_INSTALL_DIR%"
  set "UV_NO_MODIFY_PATH=1"
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%UV_INSTALL_DIR%;%PATH%"
  where uv >nul 2>nul || (call :die "uv 安装失败" "检查网络，或参考 https://docs.astral.sh/uv/ 手动安装" & exit /b 1)
)
for /f "delims=" %%v in ('uv --version') do echo       %%v

echo [2/6] 准备 Python 环境与依赖 ……
if "%REINSTALL%"=="1" (
  if exist .venv rmdir /s /q .venv
  if exist frontend\node_modules rmdir /s /q frontend\node_modules
)
set OFFLINE=
if exist .toolchain\offline set OFFLINE=--offline
uv sync --frozen %OFFLINE% >> "%LOG%" 2>&1 || (call :die "依赖安装失败" "检查网络或镜像源（UV_INDEX_URL），然后用 --reinstall 重试" & exit /b 1)

echo [3/6] 准备 Web 界面 ……
uv run --no-project python scripts\build_frontend.py --check >nul 2>nul
if errorlevel 1 (
  uv run --no-project python scripts\ensure_node.py || (call :die "Node 准备失败" "检查网络，或设置 LMESH_NODE_MIRROR 指定镜像" & exit /b 1)
  uv run --no-project python scripts\build_frontend.py || (call :die "前端构建失败" "用 --reinstall 重试；仍失败时查看上面的 pnpm 输出" & exit /b 1)
) else (
  echo       已是最新
)

echo [4/6] 检查配置 ……
if "%SETUP%"=="1" if exist config\config.toml (
  for /f "delims=" %%t in ('powershell -NoProfile -c "Get-Date -Format yyyyMMddHHmmss"') do set "STAMP=%%t"
  move /y config\config.toml "config\config.toml.bak-!STAMP!" >nul
  echo       原配置已备份为 config\config.toml.bak-!STAMP!
)
if "%SETUP%"=="1" if "%DEFAULTS%"=="1" (
  uv run lmesh setup --defaults || (call :die "配置失败" "检查环境变量中的配置值" & exit /b 1)
)
if exist config\config.toml (echo       已配置) else (echo       尚未配置：启动后在浏览器中完成向导)

echo [5/6] 检查数据库 ……
if exist config\config.toml (
  uv run lmesh db upgrade || (call :die "数据库升级失败" "检查 config\config.toml 中的 [database] url" & exit /b 1)
) else (
  echo       配置完成后自动初始化
)

if "%CHECK%"=="1" (
  echo [6/6] 检查完成（--check，不启动）
  uv run lmesh status
  exit /b 0
)

echo [6/6] 启动 ……
if defined PORT (uv run lmesh serve --port %PORT%) else (uv run lmesh serve)
if errorlevel 1 pause
exit /b %errorlevel%

:die
echo 失败：%~1
echo 处理建议：%~2
echo 详细记录见 %LOG%
echo 失败：%~1 >> "%LOG%"
pause
exit /b 1
