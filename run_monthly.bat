@echo off
cd /d %~dp0
echo ===== %date% %time% (monthly) ===== >> monthly_log.txt
python monthly_report.py >> monthly_log.txt 2>&1
