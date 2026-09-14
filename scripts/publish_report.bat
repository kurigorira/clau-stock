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
REM     /TR "C:\Users\user\clau-stock\scripts\publish_report.bat" ^
REM     /SC DAILY /ST 06:30 /IT /F
REM
REM /IT matters: the task must run in the logged-on session. The MT5
REM terminals only exist there, and git push needs that user's credentials.
REM It pushes the CURRENT branch, which must be the one GitHub Pages serves
REM or the site will not change.
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

REM ==== 0. Refuse to run on a repository mid-operation ====
REM An unfinished merge or rebase makes every later step fail in a way that
REM reads like a different problem. Name it once, with the way out.
if exist ".git\rebase-merge" goto :needs_hands
if exist ".git\rebase-apply" goto :needs_hands
if exist ".git\MERGE_HEAD" goto :needs_hands
git ls-files -u | findstr . >nul
if not errorlevel 1 goto :needs_hands

REM ==== 1. Catch up with the remote ====
REM The page can also be edited from GitHub's web UI, which leaves this clone
REM behind; committing on top of that could only fail to push. Rebase while
REM the tree is still clean, so there is nothing to conflict with.
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
echo [publish_report] branch: %BRANCH% >> logs\publish_report.log
git pull --rebase >> logs\publish_report.log 2>&1
if errorlevel 1 (
    echo [publish_report] git pull --rebase failed - publishing nothing >> logs\publish_report.log
    exit /b 1
)

REM ==== 2. Regenerate both artefacts from live account history ====
python -u scripts\monthly_report.py --markdown --html >> logs\publish_report.log 2>&1
if errorlevel 1 (
    echo [publish_report] report generation failed, nothing published >> logs\publish_report.log
    exit /b 1
)

REM ==== 3. Publish only when something changed ====
git diff --quiet -- reports/monthly.md docs/index.html
if not errorlevel 1 (
    echo [publish_report] no change, nothing to commit >> logs\publish_report.log
    echo [publish_report] finished %date% %time% >> logs\publish_report.log
    exit /b 0
)

REM remember where we were, so a commit that cannot be pushed can be undone
for /f %%h in ('git rev-parse HEAD') do set "BEFORE=%%h"
git add reports/monthly.md docs/index.html >> logs\publish_report.log 2>&1
git commit -m "monthly report %date%" >> logs\publish_report.log 2>&1
if errorlevel 1 (
    echo [publish_report] commit failed >> logs\publish_report.log
    exit /b 1
)

REM Push with a few retries: a scheduled run should survive a flaky network.
set "TRIES=0"
:push
git push >> logs\publish_report.log 2>&1
if not errorlevel 1 goto :pushed
set /a TRIES+=1
if %TRIES% GEQ 4 goto :push_failed
timeout /t 10 /nobreak >nul
goto push

:pushed
echo [publish_report] published >> logs\publish_report.log
echo [publish_report] finished %date% %time% >> logs\publish_report.log
exit /b 0

:push_failed
REM Undo our own commit rather than leave it behind. Both files are fully
REM regenerated every run, so a commit that cannot be pushed is worth
REM nothing - and keeping it would make the next run's rebase conflict on
REM the very same lines, every day, until someone stepped in.
for /f %%h in ('git rev-parse HEAD~1') do set "PARENT=%%h"
if "%PARENT%"=="%BEFORE%" (
    git reset --hard %BEFORE% >> logs\publish_report.log 2>&1
    echo [publish_report] push failed after %TRIES% attempts - local commit >> logs\publish_report.log
    echo [publish_report] rolled back; the next run regenerates from the remote >> logs\publish_report.log
) else (
    echo [publish_report] push failed after %TRIES% attempts and HEAD moved >> logs\publish_report.log
    echo [publish_report] unexpectedly - left alone for a human to look at >> logs\publish_report.log
)
exit /b 1

:needs_hands
echo [publish_report] unfinished merge/rebase or unresolved conflicts - >> logs\publish_report.log
echo [publish_report] publishing nothing. To recover, in the repo: >> logs\publish_report.log
echo [publish_report]   git rebase --abort    (or: git merge --abort) >> logs\publish_report.log
echo [publish_report]   git fetch origin >> logs\publish_report.log
echo [publish_report]   git log --oneline @{u}..HEAD >> logs\publish_report.log
echo [publish_report] If only "monthly report" commits are listed they are >> logs\publish_report.log
echo [publish_report] regenerated output, so git reset --hard @{u} is safe. >> logs\publish_report.log
exit /b 1
