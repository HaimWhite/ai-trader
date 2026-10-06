@echo off
cd /d %~dp0
echo ===== %date% %time% (advisor) ===== >> advisor_log.txt
python advisor.py >> advisor_log.txt 2>&1
