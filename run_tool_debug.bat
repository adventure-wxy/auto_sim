@echo off
setlocal
cd /d "%~dp0"

set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PY%" (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PY=python"
  ) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
      set "PY=py"
    )
  )
)

if not defined PY (
  echo Python was not found.
  pause
  exit /b 1
)

echo Using Python: %PY%
echo Working directory: %CD%
echo.
"%PY%" "%~dp0abaqus_shock_tool.py"
echo.
echo Exit code: %errorlevel%
pause
