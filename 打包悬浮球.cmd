@echo off
setlocal
cd /d "%~dp0"

if not exist ".build-venv\Scripts\python.exe" (
  echo Build environment not found.
  echo Create it with: python -m venv .build-venv
  pause
  exit /b 1
)

".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "打包.spec"
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo Build complete: dist\CC Switch 悬浮球.exe
pause
