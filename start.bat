@echo off
title Game Arabic Translator v1.0
echo.
echo ========================================
echo    Game Arabic Translator v1.0
echo ========================================
echo.
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo Error: Python not found or script error.
    echo Make sure Python 3.10+ is installed.
    pause
)
