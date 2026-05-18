@echo off
REM Tri-account launcher.
REM Reads MT5_PATH_1 / MT5_PATH_2 / MT5_PATH_3 from .env, launches all three MT5
REM terminals, then spawns three Python processes (one per account) in
REM separate windows.

cd /d "%~dp0"

REM ==== 1. Read MT5 paths from .env ====
if not exist ".env" (
    echo [start.bat] .env not found
    pause
    exit /b 1
)
set "MT5_PATH_1="
set "MT5_PATH_2="
set "MT5_PATH_3="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /I "%%a"=="MT5_PATH_1" set "MT5_PATH_1=%%~b"
    if /I "%%a"=="MT5_PATH_2" set "MT5_PATH_2=%%~b"
    if /I "%%a"=="MT5_PATH_3" set "MT5_PATH_3=%%~b"
)
if not defined MT5_PATH_1 (
    echo [start.bat] MT5_PATH_1 not set in .env
    pause
    exit /b 1
)
if not defined MT5_PATH_2 (
    echo [start.bat] MT5_PATH_2 not set in .env
    pause
    exit /b 1
)
if not defined MT5_PATH_3 (
    echo [start.bat] MT5_PATH_3 not set in .env
    pause
    exit /b 1
)
if not exist "%MT5_PATH_1%" (
    echo [start.bat] MT5_PATH_1 not found on disk: %MT5_PATH_1%
    pause
    exit /b 1
)
if not exist "%MT5_PATH_2%" (
    echo [start.bat] MT5_PATH_2 not found on disk: %MT5_PATH_2%
    pause
    exit /b 1
)
if not exist "%MT5_PATH_3%" (
    echo [start.bat] MT5_PATH_3 not found on disk: %MT5_PATH_3%
    pause
    exit /b 1
)

REM ==== 2. Launch all three MT5 terminals (re-launching is safe; MT5 dedupes per data folder) ====
echo [start.bat] launching account-1 terminal: %MT5_PATH_1%
start "" "%MT5_PATH_1%"
echo [start.bat] launching account-2 terminal: %MT5_PATH_2%
start "" "%MT5_PATH_2%"
echo [start.bat] launching account-3 terminal: %MT5_PATH_3%
start "" "%MT5_PATH_3%"
echo [start.bat] waiting 30 seconds for all terminals to load and auto-login...
timeout /t 30 /nobreak >nul

REM ==== 3. Verify venv ====
if not exist ".venv\Scripts\activate.bat" (
    echo [start.bat] .venv not found.
    echo Run: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM ==== 4. Spawn 3 bot processes, one per account ====
REM   python -u forces unbuffered stdout/stderr so log lines appear in the cmd
REM   window immediately rather than waiting for the buffer to fill.
start "clau-stock account 1" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 1 config\example.yaml config\eurusd.yaml config\usdjpy.yaml config\xauusd.yaml config\xagusd.yaml config\copper.yaml config\cloil.yaml"

start "clau-stock account 2" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 2 config\nvidia.yaml config\nvidia_24h.yaml config\jpn225ft.yaml config\hk50.yaml config\sp500ft.yaml"

start "clau-stock account 3" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 3 config\eurusd_small.yaml"

echo.
echo [start.bat] launched account 1 (7 symbols: BTC/EUR/USDJPY/XAU/XAG/Copper/CL-OIL)
echo [start.bat] launched account 2 (5 symbols: NVIDIA/NVIDIA.24H/JPN225/HK50/SP500)
echo [start.bat] launched account 3 (1 symbol:  EURUSD-small, LIVE JPY 20k)
echo Logs: logs\account1.log / logs\account2.log / logs\account3.log
echo Close the bot windows or press Ctrl+C inside them to stop.
echo.
pause
