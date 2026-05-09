@echo off
setlocal
echo ================================================
echo  Game Arabic Translator - Build Release v1.0
echo ================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH
    pause & exit /b 1
)

:: Install/upgrade PyInstaller
echo [1/4] Installing PyInstaller...
pip install pyinstaller --quiet --upgrade

:: Clean previous build
echo [2/4] Cleaning previous build...
if exist dist\GameArabicTranslator rmdir /s /q dist\GameArabicTranslator
if exist build rmdir /s /q build

:: Build
echo [3/4] Building with PyInstaller...
pyinstaller GameArabicTranslator.spec --noconfirm
if errorlevel 1 (
    echo.
    echo ERROR: Build failed!
    pause & exit /b 1
)

:: Create user data directories next to the exe
echo [4/4] Creating user directories...
mkdir dist\GameArabicTranslator\data\cache 2>nul
mkdir dist\GameArabicTranslator\logs       2>nul

:: Copy config.json and games/configs next to exe (user-accessible)
copy config.json dist\GameArabicTranslator\ >nul
xcopy games\configs dist\GameArabicTranslator\games\configs\ /E /I /Q >nul

echo.
echo ================================================
echo  Build complete!
echo  Output: dist\GameArabicTranslator\
echo ================================================
echo.
pause
