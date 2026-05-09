@echo off
REM One-click launcher for the BTC trading bot.
REM 1. Launches MT5 terminal if it's not already running.
REM 2. Activates the venv.
REM 3. Runs the live trader.

cd /d "%~dp0"

REM ====== 1. Ensure MT5 terminal is running ======
tasklist /FI "IMAGENAME eq terminal64.exe" 2>NUL | find /I "terminal64.exe" >NUL
if not errorlevel 1 goto :mt5_running

echo [start.bat] MT5 terminal not running. Locating terminal64.exe...

REM Try MT5_PATH from .env first.
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if /I "%%a"=="MT5_PATH" set "MT5_PATH_FROM_ENV=%%~b"
    )
)

set "MT5_EXE="
if defined MT5_PATH_FROM_ENV if exist "%MT5_PATH_FROM_ENV%" set "MT5_EXE=%MT5_PATH_FROM_ENV%"
if not defined MT5_EXE if exist "C:\Program Files\Vantage MetaTrader 5\terminal64.exe" set "MT5_EXE=C:\Program Files\Vantage MetaTrader 5\terminal64.exe"
if not defined MT5_EXE if exist "C:\Program Files (x86)\Vantage MetaTrader 5\terminal64.exe" set "MT5_EXE=C:\Program Files (x86)\Vantage MetaTrader 5\terminal64.exe"
if not defined MT5_EXE if exist "C:\Program Files\Vantage International MT5\terminal64.exe" set "MT5_EXE=C:\Program Files\Vantage International MT5\terminal64.exe"
if not defined MT5_EXE if exist "C:\Program Files\MetaTrader 5\terminal64.exe" set "MT5_EXE=C:\Program Files\MetaTrader 5\terminal64.exe"
if not defined MT5_EXE if exist "C:\Program Files (x86)\MetaTrader 5\terminal64.exe" set "MT5_EXE=C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
if not defined MT5_EXE if exist "%LOCALAPPDATA%\Programs\Vantage MetaTrader 5\terminal64.exe" set "MT5_EXE=%LOCALAPPDATA%\Programs\Vantage MetaTrader 5\terminal64.exe"

if not defined MT5_EXE (
    echo [start.bat] Could not find terminal64.exe in common locations.
    echo.
    echo Add this line to .env with the actual path on your machine:
    echo     MT5_PATH=C:\full\path\to\terminal64.exe
    echo.
    pause
    exit /b 1
)

echo [start.bat] launching: %MT5_EXE%
start "" "%MT5_EXE%"
echo [start.bat] waiting 10 seconds for MT5 to load and auto-login...
timeout /t 10 /nobreak >nul
goto :mt5_done

:mt5_running
echo [start.bat] MT5 terminal already running.

:mt5_done

REM ====== 2. Activate venv ======
if not exist ".venv\Scripts\activate.bat" (
    echo [start.bat] .venv not found.
    echo Run: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

REM ====== 3. Run the bot ======
title clau-stock live (BTCUSD)
echo [start.bat] launching bot. Press Ctrl+C to stop.
echo.
python scripts\run_live.py config\example.yaml

echo.
echo [start.bat] bot exited. Window stays open so you can read any error above.
pause
