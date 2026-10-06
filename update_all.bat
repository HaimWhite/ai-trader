@echo off
cd /d %~dp0
echo ===== update all =====

git check-ignore -q .env
if errorlevel 1 (
  echo [STOP] .env is not listed in .gitignore. Fix that first. Nothing was pushed.
  pause
  exit /b 1
)

echo [1/4] main.py - refresh data
python main.py
if errorlevel 1 goto fail

echo [2/4] backtest.py - recalculate backtest
python backtest.py
if errorlevel 1 goto fail

echo [3/4] advisor.py - weekly setting check
python advisor.py --weekly
if errorlevel 1 goto fail

echo [4/4] upload to GitHub
git add .
git commit -m "update all"
git push

echo.
echo Done. The dashboard updates in 1-2 minutes.
pause
exit /b 0

:fail
echo.
echo [ERROR] A step failed. Nothing was pushed. Check the messages above.
pause
exit /b 1
