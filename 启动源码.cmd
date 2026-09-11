@echo off
setlocal
cd /d "%~dp0"

if exist "%ProgramFiles%\Python310\pythonw.exe" (
  start "" "%ProgramFiles%\Python310\pythonw.exe" "%~dp0widget.py"
  exit /b
)

echo Python 3.10 with Tkinter was not found.
pause
