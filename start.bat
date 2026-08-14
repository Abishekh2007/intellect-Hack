@echo off
REM ===========================================================
REM  DataPilot AI - one-click launcher (Windows)
REM
REM  Double-click this file. It installs anything missing, starts
REM  the API and the web app, and opens your browser.
REM
REM  Options:  start.bat reset    wipe chat history + demo data
REM ===========================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title DataPilot AI

echo.
echo   DataPilot AI
echo   ============
echo.

REM ---------- optional: reset demo state ----------
if /i "%~1"=="reset" (
  echo   Resetting demo data...
  if exist "backend\data\*.db"  del /q "backend\data\*.db"
  if exist "backend\db\*.db"    del /q "backend\db\*.db"
  echo   Done - the database will be re-seeded on the next start.
  echo.
)

REM ---------- prerequisites ----------
where python >nul 2>&1
if errorlevel 1 (
  echo   [X] Python not found.
  echo       Install Python 3.11+ from https://python.org and tick
  echo       "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b 1
)

set "PKG="
where bun >nul 2>&1
if not errorlevel 1 set "PKG=bun"
if "!PKG!"=="" (
  where npm >nul 2>&1
  if not errorlevel 1 set "PKG=npm"
)
if "!PKG!"=="" (
  echo   [X] Neither Bun nor Node.js found.
  echo       Install Node.js LTS from https://nodejs.org then run this again.
  echo.
  pause
  exit /b 1
)

REM ---------- backend deps (virtual env, created once) ----------
if not exist "backend\.venv\Scripts\python.exe" (
  echo   [1/4] Creating Python environment ^(first run only, ~1 min^)...
  python -m venv "backend\.venv"
  if errorlevel 1 (
    echo   [X] Could not create the virtual environment.
    pause
    exit /b 1
  )
  echo         Installing backend packages...
  "backend\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  "backend\.venv\Scripts\python.exe" -m pip install --quiet -r "backend\requirements.txt"
  if errorlevel 1 (
    echo   [X] Backend packages failed to install. Scroll up for the reason.
    pause
    exit /b 1
  )
) else (
  echo   [1/4] Python environment ready.
)

REM ---------- frontend deps ----------
if not exist "frontend\node_modules" (
  echo   [2/4] Installing frontend packages ^(first run only, ~2 min^)...
  pushd frontend
  call !PKG! install
  popd
  if errorlevel 1 (
    echo   [X] Frontend packages failed to install.
    pause
    exit /b 1
  )
) else (
  echo   [2/4] Frontend packages ready.
)

REM ---------- .env ----------
if not exist "backend\.env" (
  if exist "backend\.env.example" (
    copy /y "backend\.env.example" "backend\.env" >nul
    echo         Created backend\.env - add an API key there for full AI mode.
    echo         Without one the app still works using the offline engine.
  )
)

REM ---------- launch ----------
echo   [3/4] Starting API on http://localhost:8000 ...
start "DataPilot API" cmd /k ""%~dp0backend\.venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir "%~dp0backend""

echo   [4/4] Starting web app on http://localhost:8080 ...
start "DataPilot Web" cmd /k "cd /d "%~dp0frontend" && !PKG! run dev"

REM ---------- wait for the API, then open the browser ----------
echo.
echo   Waiting for the app to come up...
set "READY="
for /l %%i in (1,1,45) do (
  if not defined READY (
    timeout /t 1 /nobreak >nul
    curl -s -o nul http://127.0.0.1:8080/ >nul 2>&1
    if not errorlevel 1 set "READY=1"
  )
)

start "" http://localhost:8080

echo.
if defined READY (
  echo   Ready. DataPilot is open in your browser.
) else (
  echo   Still starting - give it a few more seconds, then open
  echo   http://localhost:8080 yourself.
)
echo.
echo     App   http://localhost:8080
echo     API   http://localhost:8000
echo     Docs  http://localhost:8000/docs
echo.
echo   Two other windows are now running the API and the web app.
echo   Close them to stop DataPilot.
echo.
pause
