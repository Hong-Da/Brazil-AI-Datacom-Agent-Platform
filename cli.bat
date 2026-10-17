@echo off
chcp 65001 >nul
rem 透网 LucidMesh 命令行包装（Windows）：在任意目录调用 cli.bat ^<参数^>，等同于 lmesh ^<参数^>
setlocal
call "%~dp0scripts\env.bat"
uv run --project "%~dp0." --frozen -q lmesh %*
exit /b %errorlevel%
