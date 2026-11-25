@echo off
cd /d %~dp0
echo ===== %date% %time% (codeeater) ===== >> codeeater_log.txt
python codeeater.py >> codeeater_log.txt 2>&1
git add data >> codeeater_log.txt 2>&1
git commit -m "codeeater weekly" >> codeeater_log.txt 2>&1
git push >> codeeater_log.txt 2>&1
