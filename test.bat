@echo off
chcp 65001 >nul
rem 透网 LucidMesh 一键测试（Windows）：test.bat [--unit^|--cli^|--api^|--docs^|--roundtrip^|--frontend^|--e2e] [--changed [REF]] [-n N^|--serial] [--max-workers N] [--live --base-url URL --token TOKEN]
cd /d "%~dp0"
call scripts\env.bat
uv sync --frozen -q || (echo 依赖安装失败：先运行 start.bat --check & pause & exit /b 1)
uv run python scripts\run_tests.py %*
if errorlevel 1 (pause & exit /b 1)
