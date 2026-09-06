@echo off
REM Monthly fleet review: rescans the ENTIRE broker catalog (fleet included)
REM over 12 months of H1 data with spread-aware slippage, and emails the
REM report to NOTIFY_TO. Register with Task Scheduler (see README):
REM   schtasks /Create /TN "clau-stock monthly review" ^
REM     /TR "C:\path\to\clau-stock\scripts\review_fleet.bat" ^
REM     /SC MONTHLY /MO FIRST /D WED /ST 20:00
REM Requires the account-1 MT5 terminal to be running and logged in
REM (it normally is - the trading bot keeps it open).

cd /d "%~dp0.."
if not exist "logs" mkdir logs
call .venv\Scripts\activate.bat
echo [review_fleet] started %date% %time% >> logs\review.log
python -u scripts\screen_symbols.py --account 1 --months 12 --groups "*" --include-existing --email >> logs\review.log 2>&1
echo [review_fleet] finished %date% %time% >> logs\review.log
