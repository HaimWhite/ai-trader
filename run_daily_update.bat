@echo off
cd /d %~dp0
echo ===== %date% %time% (daily update) ===== >> update_log.txt
git check-ignore -q .env
if errorlevel 1 (
  echo [STOP] .env is not in .gitignore. Nothing was pushed. >> update_log.txt
  exit /b 1
)
python main.py >> update_log.txt 2>&1
python backtest.py >> update_log.txt 2>&1
git add . >> update_log.txt 2>&1
git commit -m "daily update" >> update_log.txt 2>&1
git push >> update_log.txt 2>&1
