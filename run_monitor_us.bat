@echo off
cd /d %~dp0
echo ===== %date% %time% (monitor_us) ===== >> monitor_log.txt
python -u monitor_us.py >> monitor_log.txt 2>&1
