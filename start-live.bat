@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Callout isn't installed yet. Double-click install.bat first.
    pause
    exit /b 1
)

echo ============================================================
echo   LIVE TRADING: REAL MONEY
echo   Orders you confirm go to your real Interactive Brokers account.
echo   config.toml must also say trading_mode = "live" and port = 7496.
echo ============================================================
echo.
set "ANSWER="
set /p "ANSWER=Type LIVE (in capitals) and press Enter to continue: "
if not "%ANSWER%"=="LIVE" (
    echo Cancelled. Nothing was started.
    pause
    exit /b 1
)
title Callout - LIVE
".venv\Scripts\python.exe" -m callout run --live
pause
