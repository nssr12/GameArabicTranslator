@echo off
REM Build ArabicFontFixer.dll
REM Usage: build.bat  OR  build.bat "C:\path\to\game\Managed"

set GAME_MANAGED=%~1
if "%GAME_MANAGED%"=="" set GAME_MANAGED=C:\Program Files (x86)\Steam\steamapps\common\Flotsam\Flotsam_Data\Managed

set BEPINEX_CORE=%~dp0..\_ bepinex_base\BepInEx\core
set BEPINEX_CORE=%~dp0..\_bepinex_base\BepInEx\core

echo Building ArabicFontFixer.dll ...
echo   Game Managed : %GAME_MANAGED%
echo   BepInEx Core : %BEPINEX_CORE%
echo.

dotnet build ArabicFontFixer.csproj ^
  -p:GAME_MANAGED="%GAME_MANAGED%" ^
  -p:BEPINEX_CORE="%BEPINEX_CORE%" ^
  -c Release ^
  -o ./bin/Release

if %ERRORLEVEL%==0 (
  copy /y bin\Release\ArabicFontFixer.dll ..\_ bepinex_base\BepInEx\plugins\ArabicFontFixer.dll
  copy /y bin\Release\ArabicFontFixer.dll ..\_bepinex_base\BepInEx\plugins\ArabicFontFixer.dll
  echo.
  echo SUCCESS — ArabicFontFixer.dll copied to _bepinex_base
) else (
  echo BUILD FAILED
)
pause
