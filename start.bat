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
REM   Fleet selected by the 6-month backtest (scripts/backtest_all.py):
REM   each preset runs whichever strategy (donchian/fibonacci) won on its
REM   own data; symbols where both lost are not launched. Crypto is BTC-only
REM   by design. The 20 non-tech stock presets are UNTESTED - dump+backtest
REM   them before trusting the results. Symbols whose Vantage names failed
REM   to dump (GOOGL/AMZN/INTC/BA/XOM/UK-OIL/NG/XPT/XPD/index futures) stay
REM   out of the fleet until their symbol: fields are fixed.
set "FIB_ACC1=config\fib_gbpusd.yaml config\fib_usdchf.yaml config\fib_usdcad.yaml config\fib_xauusd.yaml config\fib_btcusd.yaml config\fib_ng_cr.yaml config\fib_xaueur.yaml config\fib_cocoa_cr.yaml config\fib_coffee_cr.yaml"
set "FIB_ACC2=config\fib_jpn225ft.yaml config\fib_amd.yaml config\fib_msft.yaml config\fib_nflx.yaml config\fib_nvidia.yaml config\fib_meta.yaml config\fib_jnj.yaml config\fib_unh.yaml config\fib_ko.yaml config\fib_pep.yaml config\fib_mcd.yaml config\fib_cost.yaml config\fib_hd.yaml config\fib_nke.yaml config\fib_bac.yaml config\fib_meta_24h.yaml config\fib_goog_24h.yaml config\fib_orcl.yaml config\fib_toyota.yaml config\fib_mo.yaml config\fib_alibaba.yaml config\fib_bmw.yaml config\fib_azn.yaml"

start "clau-stock account 1" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 1 %FIB_ACC1%"

start "clau-stock account 2" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 2 %FIB_ACC2%"

REM Account 3 (LIVE JPY 20k) bot is PAUSED by the 12-month review decision:
REM EURUSD-small trained at PF 0.32 over the year. The terminal still opens
REM for manual position management; uncomment to resume automated entries.
REM start "clau-stock account 3" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 3 config\fib_eurusd_small.yaml"

REM Price-change alerts (independent of trading; binds to account 1's MT5 terminal).
start "clau-stock alerts" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_alerts.py --account 1 config\watchlist.yaml %FIB_ACC1% %FIB_ACC2%"

echo.
echo [start.bat] launched account 1 (9 symbols:  FX 3 / gold 2 / energy 1 / softs 2 / BTC)
echo [start.bat] launched account 2 (23 symbols: JPN225 + stocks + 24H CFDs, all review-picked)
echo [start.bat] account 3 (LIVE) bot is PAUSED - terminal opens for manual management only
echo [start.bat] launched alerts   (32 symbols + watchlist.yaml extras)
echo Logs: logs\account1.log / logs\account2.log / logs\account3.log / logs\alerts1.log
echo Close the bot windows or press Ctrl+C inside them to stop.
echo.
pause
