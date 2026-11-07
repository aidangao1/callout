@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Callout isn't installed yet. Double-click install.bat first.
    pause
    exit /b 1
)

title Callout
echo Opening Callout. Keep this window open: closing it closes Callout.
echo If something goes wrong, the error shows up here.
".venv\Scripts\python.exe" -m callout app %*
if errorlevel 1 pause
