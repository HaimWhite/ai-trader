@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== 1/4 scheduler re-register =====
python register_tasks.py --fix-tasks
echo.
echo ===== 2/4 one scout round (no apply) =====
python codeeater.py --scout --force
echo.
echo ===== 3/4 status check =====
python check_codeeater.py
echo.
echo ===== 4/4 dashboard upload =====
git add data index.html
git commit -m "codeeater check"
git push
echo.
echo Done. Dashboard updates in 1-2 min (Ctrl+F5).
pause
