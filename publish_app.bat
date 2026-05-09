@echo off
if "%1"=="" goto usage
python "%~dp0tools\publish_app.py" %1
pause
exit /b

:usage
echo Usage: publish_app.bat [Version]
echo Example: publish_app.bat 1.1
pause
