@echo off
if "%1"=="" goto usage
if "%2"=="" goto usage
python "%~dp0tools\publish_translation.py" %1 %2
pause
exit /b

:usage
echo Usage: publish_translation.bat [GameId] [Version]
echo Example: publish_translation.bat Grounded2 0.2
pause
