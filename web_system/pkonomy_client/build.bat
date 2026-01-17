@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ========================================
echo Pkonomy Client Build
echo ========================================
echo.

REM Create venv if not exists
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate venv
call venv\Scripts\activate

REM Install dependencies
echo Installing dependencies...
pip install PyQt6 requests websocket-client pyinstaller -q

REM Build
echo.
echo Building EXE...
python -m PyInstaller --clean client.spec

echo.
echo ========================================
echo Build Complete!
echo Output: dist\PkonomyClient.exe
echo ========================================
pause

