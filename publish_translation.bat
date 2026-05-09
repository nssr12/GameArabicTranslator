@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul

:: ════════════════════════════════════════════════════════
::  publish_translation.bat
::  ينشر ملفات الترجمة على GitHub ويحدث manifest.json
::
::  الاستخدام:
::    publish_translation.bat Grounded2 0.2
:: ════════════════════════════════════════════════════════

set GAME_ID=%1
set VERSION=%2
set REPO=nssr12/GameArabicTranslator

if "%GAME_ID%"=="" (
    echo.
    echo  الاستخدام: publish_translation.bat ^<GameId^> ^<Version^>
    echo  مثال:     publish_translation.bat Grounded2 0.2
    pause
    exit /b 1
)
if "%VERSION%"=="" (
    echo.
    echo  الاستخدام: publish_translation.bat ^<GameId^> ^<Version^>
    echo  مثال:     publish_translation.bat Grounded2 0.2
    pause
    exit /b 1
)

set TAG=translation-%GAME_ID%-v%VERSION%
set READY_DIR=%~dp0mods\%GAME_ID%\ready

echo.
echo === نشر ترجمة: %GAME_ID% v%VERSION% ===
echo.

:: ── 1. تحقق من وجود مجلد ready ──────────────────────────
if not exist "%READY_DIR%" (
    echo [خطأ] المجلد غير موجود: %READY_DIR%
    echo شغّل "مزامنة التعديل" من صفحة Cache أولاً.
    pause
    exit /b 1
)

:: ── 2. تحقق من وجود الملفات ──────────────────────────────
set PAK=%READY_DIR%\Paks_legacy_P.pak
set UCAS=%READY_DIR%\Paks_legacy_P.ucas
set UTOC=%READY_DIR%\Paks_legacy_P.utoc

if not exist "%PAK%"  ( echo [خطأ] ملف .pak غير موجود  & pause & exit /b 1 )
if not exist "%UCAS%" ( echo [خطأ] ملف .ucas غير موجود & pause & exit /b 1 )
if not exist "%UTOC%" ( echo [خطأ] ملف .utoc غير موجود & pause & exit /b 1 )

echo الملفات جاهزة للرفع:
echo   %PAK%
echo   %UCAS%
echo   %UTOC%
echo.

:: ── 3. احذف الـ Release القديم إن وجد ───────────────────
gh release view %TAG% --repo %REPO% > nul 2>&1
if %errorlevel%==0 (
    echo الـ Release %TAG% موجود مسبقاً — سيتم الحذف وإعادة الإنشاء...
    gh release delete %TAG% --repo %REPO% --yes --cleanup-tag
    timeout /t 3 /nobreak > nul
)

:: ── 4. أنشئ GitHub Release وارفع الملفات ────────────────
echo جاري إنشاء Release %TAG% ورفع الملفات...
gh release create %TAG% ^
    --repo %REPO% ^
    --title "%GAME_ID% Arabic Translation v%VERSION%" ^
    --notes "ترجمة عربية لـ %GAME_ID% — الإصدار %VERSION%" ^
    "%PAK%" "%UCAS%" "%UTOC%"

if %errorlevel% neq 0 (
    echo [خطأ] فشل رفع الملفات على GitHub
    pause
    exit /b 1
)
echo تم الرفع بنجاح.
echo.

:: ── 5. احسب الأحجام وحدّث manifest.json ─────────────────
echo جاري تحديث manifest.json...
python "%~dp0tools\update_manifest.py" "%GAME_ID%" "%VERSION%" "%READY_DIR%"

if %errorlevel% neq 0 (
    echo [خطأ] فشل تحديث manifest.json
    pause
    exit /b 1
)

:: ── 6. Git commit + push ──────────────────────────────────
echo جاري رفع manifest.json على GitHub...
git -C "%~dp0" add manifest.json
git -C "%~dp0" commit -m "Update manifest: %GAME_ID% v%VERSION%"
git -C "%~dp0" push origin main

echo.
echo === اكتمل النشر ===
echo رابط الـ Release: https://github.com/%REPO%/releases/tag/%TAG%
echo المستخدمون سيرون زر التحميل عند فتح التطبيق تلقائياً.
echo.
pause
