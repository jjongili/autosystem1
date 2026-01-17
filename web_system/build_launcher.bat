@echo off
chcp 65001 > nul
echo ========================================
echo    Local Launcher EXE Build
echo ========================================
echo.

pip install pyinstaller flask flask-cors

pyinstaller --onefile --console --name local_launcher local_launcher.py

echo.
echo ========================================
echo    Build Complete!
echo    dist\local_launcher.exe
echo ========================================
pause
