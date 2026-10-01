@echo off
cd /d %~dp0
python main.py
git add data
git commit -m "update data"
git push
pause
