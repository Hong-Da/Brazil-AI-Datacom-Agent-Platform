@echo off
rem LucidMesh command line for the offline package: lmesh.bat <command> ..., e.g. lmesh.bat status, lmesh.bat setup
rem start.bat calls it with --env-only to set the environment only (no chcp then: it would make the caller misread lines).
if /i not "%~1"=="--env-only" (
  setlocal
  chcp 65001 >nul
)
for %%I in ("%~dp0.") do set "LMESH_ROOT=%%~fI"
set "LMESH_PY=%LMESH_ROOT%\runtime\python\python.exe"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PYTHONPATH="
set "PYTHONHOME="
rem 临时文件放在程序目录内
set "TMP=%LMESH_ROOT%\tmp\os"
set "TEMP=%LMESH_ROOT%\tmp\os"
if not exist "%TMP%" mkdir "%TMP%"
if /i "%~1"=="--env-only" exit /b 0
"%LMESH_PY%" -m lmesh %*
exit /b %errorlevel%
