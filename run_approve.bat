@echo off
cd /d %~dp0
python advisor.py --poll >> approve_log.txt 2>&1
