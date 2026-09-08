@echo off
REM Fleet launcher for the current account layout:
REM   account 1 (demo) - macd base US-stock fleet        config\us_fleet\*.yaml
REM   account 2 (demo) - macd + stoch 80/20 fleet        config\us_fleet_a2\*.yaml
REM   account 4 (demo) - bollrci mean-reversion fleet    config\us_fleet_a4\*.yaml
REM   account 3 (LIVE) - manual management ONLY: the terminal opens, no bot.
REM   any other MT5_PATH_<n> - terminal opens, no bot (manual accounts).
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
REM Suffixes 1-9 cover every account; unset ones are skipped, so a new
REM account needs only its MT5_PATH_<n> line in .env - nothing to edit here.
for %%n in (1 2 3 4 5 6 7 8 9) do set "MT5_PATH_%%n="
for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
    for %%n in (1 2 3 4 5 6 7 8 9) do (
        if /I "%%a"=="MT5_PATH_%%n" set "MT5_PATH_%%n=%%~b"
    )
)
REM The three bot accounts must be present; the rest are optional.
for %%n in (1 2 4) do (
    call :require_path %%n || exit /b 1
)

REM ==== 2. Launch one terminal per configured account ====
REM Each MT5_PATH_<n> is started AT MOST ONCE, and a path shared by two
REM suffixes is opened a single time. MT5 gives one install one instance, but
REM a /portable shortcut does not dedupe - starting it repeatedly piles up
REM windows. Nothing is scanned: only what .env names is opened.
set "LAUNCHED_PATHS="
for %%n in (1 2 3 4 5 6 7 8 9) do call :launch_terminal %%n

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

REM Account 3 (LIVE) and any other account stay bot-free by design - their
REM terminals open above for manual position management only. Do not add a
REM run_live line for one without a fresh OOS pass.

REM Price-change alerts (independent of trading; binds to account 1's terminal).
REM run_alerts.py expands the glob, so the alert list tracks the live fleet.
start "clau-stock alerts" cmd /k "call .venv\Scripts\activate.bat && python -u scripts\run_alerts.py --account 1 config\watchlist.yaml config\us_fleet\*.yaml"

echo.
echo [start.bat] launched account 1 bot (macd base, 100 US stocks)
echo [start.bat] launched account 2 bot (macd + stoch 80/20, same 100 symbols - A/B vs account 1)
echo [start.bat] launched account 4 bot (bollrci mean reversion, same 100 symbols)
echo [start.bat] other accounts: terminal only, MANUAL management - no bot
echo [start.bat] launched alerts (watchlist.yaml extras + the account-1 fleet)
echo Logs: logs\account1.log / logs\account2.log / logs\account4.log / logs\alerts1.log
echo Close a bot window or press Ctrl+C inside it to stop that account.
echo.
pause
exit /b 0

:launch_terminal
call set "p=%%MT5_PATH_%1%%"
if not defined p exit /b 0
if not exist "%p%" (
    echo [start.bat] WARNING: MT5_PATH_%1 not found on disk: %p%
    exit /b 0
)
REM already opened under another suffix? two accounts cannot share a terminal
REM anyway, so opening it twice would only stack windows.
echo "%LAUNCHED_PATHS%"| findstr /i /c:"[%p%]" >nul
if not errorlevel 1 (
    echo [start.bat] account-%1 shares an already-opened terminal: %p%
    exit /b 0
)
set "LAUNCHED_PATHS=%LAUNCHED_PATHS%[%p%]"
echo [start.bat] launching account-%1 terminal: %p%
start "" "%p%"
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
