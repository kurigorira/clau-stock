@echo off
REM Twice-daily status email: balances, today's PnL, open positions, strategy
REM breakdown, and unprotected-position warnings across accounts 1/2/3/4.
REM Register with Task Scheduler (see README "Daily status email"):
REM   schtasks /Create /TN "clau-stock daily report AM" /TR "C:\path\to\clau-stock\scripts\daily_report.bat" /SC DAILY /ST 06:00
REM   schtasks /Create /TN "clau-stock daily report PM" /TR "C:\path\to\clau-stock\scripts\daily_report.bat" /SC DAILY /ST 21:00
REM Requires the relevant MT5 terminal(s) to be running and logged in
REM (they normally are - the trading bots keep them open).

cd /d "%~dp0.."
if not exist "logs" mkdir logs
call .venv\Scripts\activate.bat
echo [daily_report] started %date% %time% >> logs\daily_report.log
python -u scripts\daily_report.py >> logs\daily_report.log 2>&1
echo [daily_report] finished %date% %time% >> logs\daily_report.log
