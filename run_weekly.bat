@echo off
cd /d %~dp0
echo ===== %date% %time% (weekly) ===== >> weekly_log.txt
python weekly_report.py >> weekly_log.txt 2>&1
