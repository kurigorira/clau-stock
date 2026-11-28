@echo off
REM Alert settings app: edit config\watchlist.yaml in the browser.
REM Saving takes effect in the running alerts on their next poll -
REM nothing to restart. Close this window to stop the app.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [alert_settings] .venv not found - run the setup in README first
    pause
    exit /b 1
)
".venv\Scripts\python.exe" scripts\alert_settings.py %*
pause
