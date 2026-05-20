@echo off
setlocal
cd /d "%~dp0"

set "APP=%~dp0abaqus_shock_tool.py"
if not exist "%APP%" (
  echo Could not find "%APP%".
  pause
  exit /b 1
)

set "PYTHON_EXE="
set "PYTHONW_EXE="

set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "CODEX_PYW=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"
if exist "%CODEX_PY%" set "PYTHON_EXE=%CODEX_PY%"
if exist "%CODEX_PYW%" set "PYTHONW_EXE=%CODEX_PYW%"

where python >nul 2>nul
if %errorlevel%==0 if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('where python') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
  )
)

where pythonw >nul 2>nul
if %errorlevel%==0 if not defined PYTHONW_EXE (
  for /f "delims=" %%P in ('where pythonw') do (
    if not defined PYTHONW_EXE set "PYTHONW_EXE=%%P"
  )
)

if defined PYTHON_EXE (
  "%PYTHON_EXE%" "%APP%"
  if errorlevel 1 (
    echo.
    echo The tool failed to start. Error code: %errorlevel%
    pause
  )
  exit /b %errorlevel%
)

if defined PYTHONW_EXE (
  start "" "%PYTHONW_EXE%" "%APP%"
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  py "%APP%"
  if errorlevel 1 (
    echo.
    echo The tool failed to start. Error code: %errorlevel%
    pause
  )
  exit /b %errorlevel%
)

if exist "%CODEX_PY%" (
  "%CODEX_PY%" "%APP%"
  if errorlevel 1 (
    echo.
    echo The tool failed to start. Error code: %errorlevel%
    pause
  )
  exit /b %errorlevel%
)
echo Python was not found in PATH.
echo Install Python 3 with Tkinter, or run abaqus_shock_tool.py with a known Python executable.
pause
