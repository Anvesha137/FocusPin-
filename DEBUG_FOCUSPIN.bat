@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo First run START_FOCUSPIN.bat to install FocusPin.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "focuspin.py"
if errorlevel 1 echo FocusPin exited with an error. See messages above.
pause
