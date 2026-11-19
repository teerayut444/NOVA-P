@echo off
setlocal
chcp 65001 > nul
title Merge Monthly CSV & Generate Parquet

cd /d "%~dp0"

echo ======================================================================
echo   All Asset NPA: Merge Monthly CSV & Parquet Generator
echo ======================================================================
echo.

set "PYTHON_EXE="

rem 1. Check local virtual environment (.venv)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

rem 2. Check Python Launcher (py)
if not defined PYTHON_EXE (
    py -c "import sys" >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=py"
    )
)

rem 3. Check python command (verify it actually executes code)
if not defined PYTHON_EXE (
    python -c "import sys" >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=python"
    )
)

rem 4. Search user and system Python installation folders directly
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%D\python.exe" (
            "%%D\python.exe" -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%D\python.exe"
        )
    )
)
if not defined PYTHON_EXE (
    for /d %%D in ("%ProgramFiles%\Python*") do (
        if exist "%%D\python.exe" (
            "%%D\python.exe" -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%D\python.exe"
        )
    )
)
if not defined PYTHON_EXE (
    for /d %%D in ("C:\Python*") do (
        if exist "%%D\python.exe" (
            "%%D\python.exe" -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%D\python.exe"
        )
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] Python not found or not working.
    echo Please install Python and ensure "Add Python to PATH" is selected during installation.
    echo.
    pause
    exit /b 1
)

echo [Environment] Using: %PYTHON_EXE%
if exist "%~dp0merge_csv_monthly.py" (
    echo [Executing]   %~dp0merge_csv_monthly.py
    echo.
    "%PYTHON_EXE%" "%~dp0merge_csv_monthly.py"
) else (
    echo [Executing]   Py Scraper\merge_csv_monthly.py
    echo.
    "%PYTHON_EXE%" "Py Scraper\merge_csv_monthly.py"
)

echo.
echo ======================================================================
echo กระบวนการทำงานเสร็จสิ้นแล้ว
echo ======================================================================
pause
