@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Callout isn't installed yet. Double-click install.bat first.
    pause
    exit /b 1
)

title Callout connection check
".venv\Scripts\python.exe" -m callout check
pause
