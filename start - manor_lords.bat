@echo off
title Manor Lords - Arabic Translator
cd /d "%~dp0"

echo ================================================================
echo   Manor Lords - Arabic Translator Launcher
echo ================================================================
echo.
echo IMPORTANT: Manor Lords must NOT be running yet.
echo            If it is, close it first.
echo.
echo This will:
echo   1. Start translation proxy (Ollama backend)
echo   2. Start watcher (auto-translates new text)
echo   3. Launch Manor Lords with hook DLLs pre-injected
echo.
echo Steam must be running in background for DRM.
echo.
pause

echo.
echo [1/3] Starting proxy server...
start "Manor Lords Proxy" cmd /k C:\Python314\python.exe tools\start_proxy.py --game "Manor Lords"

timeout /t 4 /nobreak >nul 2>&1

echo [2/3] Starting watcher...
start "Manor Lords Watcher" cmd /k C:\Python314\python.exe tools\unreal_hook_watcher.py

timeout /t 2 /nobreak >nul 2>&1

echo [3/3] Launching Manor Lords with hook DLLs pre-injected...
echo.
C:\Python314\python.exe tools\launch_unreal_game.py --game "Manor Lords"

echo.
echo ================================================================
echo Done! Manor Lords should be starting now with translations.
echo ================================================================
echo.
pause
