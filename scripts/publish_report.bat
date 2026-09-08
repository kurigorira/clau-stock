@echo off
REM Regenerate the monthly report and publish it, for Task Scheduler.
REM
REM Writes reports\monthly.md and docs\index.html from live MT5 history, then
REM commits and pushes ONLY if the figures actually changed - a scheduled run
REM on a quiet day should not leave an empty commit behind.
REM
REM Register it to run daily after the US close (JST 06:30 = shortly after
REM 21:00 UTC):
REM   schtasks /Create /TN "clau-stock publish report" ^
REM     /TR "C:\Users\user\clau-stock\scripts\publish_report.bat" /SC DAILY /ST 06:30
REM
REM The MT5 terminals must be running and logged in - the trading bots keep
REM them open. Accounts that cannot be reached are reported in the page as
REM "not reported" rather than failing the whole run.

cd /d "%~dp0.."
if not exist "logs" mkdir logs

echo [publish_report] started %date% %time% >> logs\publish_report.log

if not exist ".venv\Scripts\activate.bat" (
    echo [publish_report] .venv not found >> logs\publish_report.log
    exit /b 1
)
call .venv\Scripts\activate.bat

REM ==== 1. Regenerate both artefacts from live account history ====
python -u scripts\monthly_report.py --markdown --html >> logs\publish_report.log 2>&1
if errorlevel 1 (
    echo [publish_report] report generation failed, nothing published >> logs\publish_report.log
    exit /b 1
)

REM ==== 2. Publish only when something changed ====
git diff --quiet -- reports/monthly.md docs/index.html
if not errorlevel 1 (
    echo [publish_report] no change, nothing to commit >> logs\publish_report.log
    echo [publish_report] finished %date% %time% >> logs\publish_report.log
    exit /b 0
)

git add reports/monthly.md docs/index.html >> logs\publish_report.log 2>&1
git commit -m "monthly report %date%" >> logs\publish_report.log 2>&1
if errorlevel 1 (
    echo [publish_report] commit failed >> logs\publish_report.log
    exit /b 1
)

REM Push with a few retries: a scheduled run should survive a flaky network.
setlocal
set "TRIES=0"
:push
git push >> logs\publish_report.log 2>&1
if not errorlevel 1 goto pushed
set /a TRIES+=1
if %TRIES% GEQ 4 (
    echo [publish_report] push failed after %TRIES% attempts - the commit is >> logs\publish_report.log
    echo [publish_report] local, so the next run will carry it up >> logs\publish_report.log
    endlocal
    exit /b 1
)
timeout /t 10 /nobreak >nul
goto push
:pushed
endlocal

echo [publish_report] published >> logs\publish_report.log
echo [publish_report] finished %date% %time% >> logs\publish_report.log
exit /b 0
