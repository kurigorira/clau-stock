@echo off
REM One-click launcher for the BTC trading bot.
REM Prerequisite: MT5 terminal is already running and logged in to the
REM account configured in .env.

cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" (
    echo [start.bat] .venv not found.
    echo Run: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

if not exist "config\example.yaml" (
    echo [start.bat] config\example.yaml not found.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

title clau-stock live (BTCUSD)
echo [start.bat] launching bot. Press Ctrl+C to stop.
echo.
python scripts\run_live.py config\example.yaml

echo.
echo [start.bat] bot exited. Window stays open so you can read any error above.
pause
