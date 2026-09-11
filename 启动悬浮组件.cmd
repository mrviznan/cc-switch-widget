@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0dist\CC Switch 悬浮球.exe" (
  start "" "%~dp0dist\CC Switch 悬浮球.exe"
  exit /b
)

if exist "%ProgramFiles%\Python310\pythonw.exe" (
  "%ProgramFiles%\Python310\pythonw.exe" "%~dp0widget.py"
  exit /b
)

if exist "%LocalAppData%\Programs\Python\Python310\pythonw.exe" (
  "%LocalAppData%\Programs\Python\Python310\pythonw.exe" "%~dp0widget.py"
  exit /b
)

where pyw >nul 2>nul
if not errorlevel 1 (
  pyw -3 "%~dp0widget.py"
  exit /b
)

where pythonw >nul 2>nul
if not errorlevel 1 (
  pythonw "%~dp0widget.py"
  exit /b
)

echo Python 3 with Tkinter was not found.
echo Install Python 3 and make sure pythonw.exe is available on PATH.
pause
