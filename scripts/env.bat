@echo off
rem 工具链与缓存位置：所有脚本先加载它（call scripts\env.bat），只设置环境变量和 PATH。
chcp 65001 >nul
for %%I in ("%~dp0..") do set "LMESH_ROOT=%%~fI"
set "PYTHONUTF8=1"

rem Python（uv）：下载缓存、解释器、工具都放在项目内
set "UV_CACHE_DIR=%LMESH_ROOT%\.toolchain\cache\uv"
set "UV_PYTHON_INSTALL_DIR=%LMESH_ROOT%\.toolchain\runtime\python"
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_TOOL_DIR=%LMESH_ROOT%\.toolchain\uv-tools"
rem start 脚本安装 uv 时装到项目内
set "UV_INSTALL_DIR=%LMESH_ROOT%\.toolchain\bin"
if exist "%LMESH_ROOT%\.toolchain\bin" set "PATH=%LMESH_ROOT%\.toolchain\bin;%PATH%"

rem Node（只用于构建前端）：运行时与缓存放在项目内；pnpm store 写在 frontend\.npmrc
set "npm_config_cache=%LMESH_ROOT%\.toolchain\cache\npm"
set "COREPACK_HOME=%LMESH_ROOT%\.toolchain\cache\corepack"
rem 端到端测试的浏览器（Playwright）也放在项目内
set "PLAYWRIGHT_BROWSERS_PATH=%LMESH_ROOT%\.toolchain\cache\ms-playwright"
if exist "%LMESH_ROOT%\.toolchain\runtime\node\node.exe" set "PATH=%LMESH_ROOT%\.toolchain\runtime\node;%PATH%"
