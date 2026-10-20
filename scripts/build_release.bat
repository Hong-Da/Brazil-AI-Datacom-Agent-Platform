@echo off
chcp 65001 >nul
rem 生成发布包到 dist\<版本>\（Windows：离线包 zip 与安装程序 exe）
rem 用法：scripts\build_release.bat [版本号] [--targets win-zip,win-exe] [--skip-frontend]
setlocal
cd /d "%~dp0.."
call scripts\env.bat
uv run --no-project python scripts\build_release.py %*
exit /b %errorlevel%
