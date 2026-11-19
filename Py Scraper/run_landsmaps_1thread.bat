@echo off
chcp 65001 >nul
title NOVA LandsMaps Scraper (1-Thread Safe Mode - All 77 Provinces)
cd /d "%~dp0.."

echo ==============================================================================
echo [NOVA] Starting LandsMaps Real Coordinate Scraper (1-Thread, All 77 Provinces)
echo        - Auto Session Reset (LoginSocial Token Rotation - No 20-request limit)
echo        - Strict Rate Limit: 1 Thread, Delay ^>= 15-16s per request (อิงมาตรฐาน Scraper)
echo        - Auto-saves to data\led_coords_cache.parquet and CSV every 15 deeds
echo        - Press Ctrl+C anytime to pause and resume later
echo ==============================================================================
echo.

set "PY_EXE=python"
if exist ".venv\Scripts\python.exe" (
    set "PY_EXE=.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PY_EXE=%~dp0..\.venv\Scripts\python.exe"
)

"%PY_EXE%" "Py Scraper\enrich_led_landsmaps.py" --limit 0 --workers 1

pause
