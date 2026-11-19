@echo off
rem Sets up (or updates) your Callout relay on Cloudflare. Double-click it; see README.md in this folder.
cd /d "%~dp0"
title Callout relay setup

where node >nul 2>nul
if errorlevel 1 goto nonode

echo Installing the relay's tools. The first time takes a minute...
call npm install --no-audit --no-fund --loglevel=error
if errorlevel 1 goto failed

echo.
echo Checking your Cloudflare sign-in...
call npx wrangler whoami 2>nul | findstr /i /c:"logged in" >nul
if errorlevel 1 goto login
goto deploy

:login
echo Your browser will open. Click Allow so this computer can publish the relay.
call npx wrangler login
if errorlevel 1 goto failed

:deploy
echo.
echo Publishing the relay...
call npx wrangler deploy
if errorlevel 1 goto failed
echo.
echo ============================================================
echo   Done. Copy the https://...workers.dev address above into
echo   Callout: Settings, Phone, Advanced: relay address.
echo ============================================================
pause
exit /b 0

:nonode
echo Node.js isn't installed. Installing it now: Windows will ask for permission.
winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
echo.
echo When it finishes, close this window and double-click deploy.bat again.
pause
exit /b 1

:failed
echo.
echo Something went wrong. Read the messages above, then double-click deploy.bat to try again.
pause
exit /b 1
