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
REM   All presets run strategy=fibonacci. Legacy donchian YAMLs stay in config/
REM   for reference but are no longer launched; open donchian positions are
REM   adopted by the fib preset with the same magic_number and exit via the
REM   shared Donchian reverse-channel safety exit.
set "FIB_ACC1=config\fib_eurusd.yaml config\fib_usdjpy.yaml config\fib_gbpusd.yaml config\fib_audusd.yaml config\fib_nzdusd.yaml config\fib_usdcad.yaml config\fib_usdchf.yaml config\fib_eurjpy.yaml config\fib_gbpjpy.yaml config\fib_audjpy.yaml config\fib_eurgbp.yaml config\fib_euraud.yaml config\fib_cadjpy.yaml config\fib_chfjpy.yaml config\fib_xauusd.yaml config\fib_xagusd.yaml config\fib_copper_cr.yaml config\fib_cl_oil.yaml config\fib_uk_oil.yaml config\fib_ng.yaml config\fib_xptusd.yaml config\fib_xpdusd.yaml config\fib_btcusd.yaml config\fib_ethusd.yaml config\fib_xrpusd.yaml config\fib_solusd.yaml config\fib_ltcusd.yaml config\fib_adausd.yaml"
set "FIB_ACC2=config\fib_sp500ft_r.yaml config\fib_jpn225ft.yaml config\fib_hk50_r.yaml config\fib_nas100ft.yaml config\fib_dj30ft.yaml config\fib_ger40ft.yaml config\fib_uk100ft.yaml config\fib_aus200ft.yaml config\fib_nvidia.yaml config\fib_nvidia_24h.yaml config\fib_tsla.yaml config\fib_aapl.yaml config\fib_msft.yaml config\fib_googl.yaml config\fib_meta.yaml config\fib_amzn.yaml config\fib_nflx.yaml config\fib_amd.yaml config\fib_intc.yaml config\fib_jpm.yaml config\fib_ba.yaml config\fib_xom.yaml"

start "clau-stock account 1" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 1 %FIB_ACC1%"

start "clau-stock account 2" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 2 %FIB_ACC2%"

start "clau-stock account 3" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 3 config\fib_eurusd_small.yaml"

REM Price-change alerts (independent of trading; binds to account 1's MT5 terminal).
start "clau-stock alerts" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_alerts.py --account 1 config\watchlist.yaml %FIB_ACC1% %FIB_ACC2%"

echo.
echo [start.bat] launched account 1 (28 symbols: FX 14 / metals+energy 8 / crypto 6)
echo [start.bat] launched account 2 (22 symbols: indices 8 / stocks 14)
echo [start.bat] launched account 3 (1 symbol:  EURUSD fib-small, LIVE JPY 20k)
echo [start.bat] launched alerts   (50 symbols + watchlist.yaml extras)
echo Logs: logs\account1.log / logs\account2.log / logs\account3.log / logs\alerts1.log
echo Close the bot windows or press Ctrl+C inside them to stop.
echo.
pause
