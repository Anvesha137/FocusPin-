@echo off
setlocal
cd /d "%~dp0"
echo Running FocusPin V2 storage, recurrence, statistics and sound tests...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m unittest discover -s tests -v
) else (
  py -3 -m unittest discover -s tests -v
)
pause
