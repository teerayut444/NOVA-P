@echo off
setlocal
chcp 65001 > nul
title Monthly Parallel All Asset NPA Scrapers Launcher
cd /d "%~dp0.."

echo ==============================================================================================================
echo Starting Monthly Parallel Scrapers (14 Sources)...
echo [ LED / SAM / BAM / Chayo555 / GHB / KBANK / KTB / SCB / GSB /
echo   DDproperty / Livinginsider / NaYoo / ZmyHome / Baania ]
echo ==============================================================================================================
echo.

set "PY_EXE="
if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
    py -c "import sys" >nul 2>nul
    if %errorlevel% equ 0 (
        set "PY_EXE=py"
    ) else (
        set "PY_EXE=python"
    )
)

echo [Environment] Using: %PY_EXE%
"%PY_EXE%" "Py Scraper\run_parallel_monthly.py" %*

echo.
echo ==========================================================================
echo Scrape processes completed. Press any key to exit...
echo ==========================================================================
pause > nul
