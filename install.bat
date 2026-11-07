@echo off
setlocal
cd /d "%~dp0"
title Installing Callout
echo Installing Callout...
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto nopython
%PY% --version >nul 2>nul || goto nopython
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto oldpython

if not exist ".venv\Scripts\python.exe" (
    echo Creating a private Python environment for Callout...
    %PY% -m venv .venv
    if errorlevel 1 goto failed
)

echo Installing packages. This can take a minute or two...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto failed

if not exist "config.toml" ".venv\Scripts\python.exe" -m callout init

echo.
echo ============================================================
echo   Done. Next: set up TWS (README step 4), then double-click
echo   start.bat
echo ============================================================
pause
exit /b 0

:nopython
echo Python isn't installed, or it wasn't added to PATH.
echo Install it from https://www.python.org/downloads/
echo and tick "Add python.exe to PATH" on the installer's first screen.
pause
exit /b 1

:oldpython
echo Your Python is too old. Callout needs Python 3.11 or newer.
echo Get the latest from https://www.python.org/downloads/
pause
exit /b 1

:failed
echo.
echo Something went wrong above. Take a screenshot of this window if you need help.
pause
exit /b 1
