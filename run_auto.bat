@echo off
cd /d %~dp0
echo ===== %date% %time% ===== >> run_log.txt
python main.py >> run_log.txt 2>&1
git add data >> run_log.txt 2>&1
git commit -m "auto update" >> run_log.txt 2>&1
git push >> run_log.txt 2>&1
