@echo off
cd /d %~dp0
echo ===== %date% %time% (report) ===== >> run_log.txt
python main.py --report >> run_log.txt 2>&1
