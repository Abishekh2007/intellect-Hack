@echo off
REM Build DataPilot.exe from tools/launcher.py.
REM
REM Run this once; the resulting exe is what everyone else double-clicks.
REM Requires PyInstaller:  python -m pip install pyinstaller
setlocal
cd /d "%~dp0.."

echo.
echo   Building DataPilot.exe ...
echo.

python -m PyInstaller --noconfirm --onefile --console ^
  --name DataPilot ^
  --distpath . ^
  --workpath "tools\build" ^
  --specpath "tools" ^
  "tools\launcher.py"

if errorlevel 1 (
  echo.
  echo   Build failed. Install PyInstaller first:
  echo       python -m pip install pyinstaller
  echo.
  pause
  exit /b 1
)

REM PyInstaller's intermediates are not worth keeping.
if exist "tools\build" rmdir /s /q "tools\build"

echo.
echo   Done - DataPilot.exe is in the project root.
echo.
pause
