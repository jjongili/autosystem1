\xEF\xBB\xBF@echo off
chcp 65001 >nul
cd /d "%~dp0"
python client.py
pause
