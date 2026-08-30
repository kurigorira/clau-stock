@echo off
REM Fleet launcher for the current account layout:
REM   account 1 (demo) - macd base US-stock fleet        config\us_fleet\*.yaml
REM   account 2 (demo) - macd + stoch 80/20 fleet        config\us_fleet_a2\*.yaml
REM   account 4 (demo) - bollrci mean-reversion fleet    config\us_fleet_a4\*.yaml
REM   account 3 (LIVE) - manual management ONLY: the terminal opens, no bot.
REM
REM Accounts 1 vs 2 are a live A/B: identical 100 spread-selected symbols,
REM the only difference is the stoch 80/20 gate (OOS test +467 vs +276).
REM Account 4 runs the OOS-validated bollrci book (train-selected thr=60,
REM test +502, 56% win rate) - expect it to win in ranges and lose in trends,
REM the opposite timing of accounts 1/2. That is by design, not a fault.
REM
REM The us_fleet* YAMLs are machine-generated with live spread data
REM (scripts\gen_us_fleet.py) and are NOT in the repo. Generate them before
REM the first launch; this script refuses to start a bot whose fleet dir is
REM missing rather than silently launching nothing.

cd /d "%~dp0"

REM ==== 1. Read MT5 terminal paths from .env ====
if not exist ".env" (
    echo [start.bat] .env not found
    pause
    exit /b 1
)
set "MT5_PATH_1="
set "MT5_PATH_2="
set "MT5_PATH_3="
set "MT5_PATH_4="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    if /I "%%a"=="MT5_PATH_1" set "MT5_PATH_1=%%~b"
    if /I "%%a"=="MT5_PATH_2" set "MT5_PATH_2=%%~b"
    if /I "%%a"=="MT5_PATH_3" set "MT5_PATH_3=%%~b"
    if /I "%%a"=="MT5_PATH_4" set "MT5_PATH_4=%%~b"
)
for %%n in (1 2 4) do (
    call :require_path %%n || exit /b 1
)

REM ==== 2. Launch the bot terminals (re-launching is safe; MT5 dedupes per folder) ====
echo [start.bat] launching account-1 terminal: %MT5_PATH_1%
start "" "%MT5_PATH_1%"
echo [start.bat] launching account-2 terminal: %MT5_PATH_2%
start "" "%MT5_PATH_2%"
echo [start.bat] launching account-4 terminal: %MT5_PATH_4%
start "" "%MT5_PATH_4%"
if defined MT5_PATH_3 (
    if exist "%MT5_PATH_3%" (
        echo [start.bat] launching account-3 LIVE terminal for manual management: %MT5_PATH_3%
        start "" "%MT5_PATH_3%"
    ) else (
        echo [start.bat] WARNING: MT5_PATH_3 not found on disk: %MT5_PATH_3%
        echo [start.bat] the LIVE terminal will not open - fix MT5_PATH_3 in .env
    )
) else (
    echo [start.bat] NOTE: MT5_PATH_3 not set - LIVE terminal will not open
)
echo [start.bat] waiting 30 seconds for the terminals to load and auto-login...
timeout /t 30 /nobreak >nul

REM ==== 3. Verify venv ====
if not exist ".venv\Scripts\activate.bat" (
    echo [start.bat] .venv not found.
    echo Run: python -m venv .venv ^&^& .venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM ==== 4. Verify the generated fleet dirs exist ====
call :require_fleet "config\us_fleet" || exit /b 1
call :require_fleet "config\us_fleet_a2" || exit /b 1
call :require_fleet "config\us_fleet_a4" || exit /b 1

REM ==== 5. Spawn the bots, one window per account ====
REM python -u forces unbuffered stdout so log lines appear immediately.
REM run_live.py expands the *.yaml glob itself (cmd/PowerShell do not).
start "clau-stock account 1 (macd)" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 1 config\us_fleet\*.yaml"

start "clau-stock account 2 (macd+stoch)" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 2 config\us_fleet_a2\*.yaml"

start "clau-stock account 4 (bollrci)" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_live.py --account 4 config\us_fleet_a4\*.yaml"

REM Account 3 (LIVE JPY 20k) stays bot-free by the 12-month review decision
REM (EURUSD-small trained at PF 0.32). Its terminal opens above for manual
REM position management only. Do not add a run_live line for it without a
REM fresh OOS pass.

REM Price-change alerts (independent of trading; binds to account 1's terminal).
REM run_alerts.py expands the glob, so the alert list tracks the live fleet.
start "clau-stock alerts" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_alerts.py --account 1 config\watchlist.yaml config\us_fleet\*.yaml"

echo.
echo [start.bat] launched account 1 bot (macd base, 100 US stocks)
echo [start.bat] launched account 2 bot (macd + stoch 80/20, same 100 symbols - A/B vs account 1)
echo [start.bat] launched account 4 bot (bollrci mean reversion, same 100 symbols)
echo [start.bat] account 3 LIVE terminal opened for MANUAL management only - no bot
echo [start.bat] launched alerts (watchlist.yaml extras + the account-1 fleet)
echo Logs: logs\account1.log / logs\account2.log / logs\account4.log / logs\alerts1.log
echo Close a bot window or press Ctrl+C inside it to stop that account.
echo.
pause
exit /b 0

:require_path
setlocal
call set "p=%%MT5_PATH_%1%%"
if not defined p (
    echo [start.bat] MT5_PATH_%1 not set in .env
    pause
    endlocal
    exit /b 1
)
if not exist "%p%" (
    echo [start.bat] MT5_PATH_%1 not found on disk: %p%
    pause
    endlocal
    exit /b 1
)
endlocal
exit /b 0

:require_fleet
if not exist "%~1\*.yaml" (
    echo [start.bat] %~1 has no YAMLs - generate the fleet first with
    echo     scripts\gen_us_fleet.py  (see README "US fleet" section^)
    pause
    exit /b 1
)
exit /b 0
