@echo off
cd /d %~dp0
echo ===== %date% %time% (monitor) ===== >> monitor_log.txt
python -u monitor.py >> monitor_log.txt 2>&1
