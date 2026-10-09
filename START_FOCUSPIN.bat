@echo off
setlocal
cd /d "%~dp0"
title FocusPin - Setup and Launch

if not exist ".venv\Scripts\python.exe" (
  echo [1/2] Creating FocusPin's private Python environment...
  where py >nul 2>nul
  if not errorlevel 1 (
    py -3 -m venv .venv
  ) else (
    where python >nul 2>nul
    if errorlevel 1 (
      echo Python not found. Please install Python 3.11 or later from:
      echo https://www.python.org/downloads/windows/
      echo Then rerun this file.
      pause
      exit /b 1
    )
    python -m venv .venv
  )
  if errorlevel 1 goto :error
)

".venv\Scripts\python.exe" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
  echo [2/2] Installing the desktop UI dependency [internet required once]...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)

echo Launching FocusPin...
start "FocusPin" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0focuspin.py"
exit /b 0

:error
echo.
echo Setup failed. The error is shown above.
pause
exit /b 1
