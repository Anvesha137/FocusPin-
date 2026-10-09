@echo off
setlocal
cd /d "%~dp0"
title FocusPin - Build Windows EXE
if not exist ".venv\Scripts\python.exe" (
  echo First run START_FOCUSPIN.bat to install the app dependencies.
  pause
  exit /b 1
)
echo Installing PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :error
echo Building one-file executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name FocusPin --icon "assets\focuspin.ico" --add-data "assets\focuspin.ico;assets" focuspin.py
if errorlevel 1 goto :error
echo.
echo Done! Your app is here: %~dp0dist\FocusPin.exe
pause
exit /b 0
:error
echo Build failed. Review the error messages above.
pause
exit /b 1
