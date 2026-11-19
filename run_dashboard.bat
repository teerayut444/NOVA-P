@echo off
setlocal
title NOVA Dashboard Launcher

cd /d "%~dp0"

echo ======================================================================
echo   NOVA NPA Intelligence Dashboard (14 Sources)
echo   LED / SAM / BAM / Chayo555 / GHB / KBANK / KTB / SCB / GSB /
echo   DDproperty / Livinginsider / NaYoo / ZmyHome / Baania
echo ======================================================================
echo.

set "PYTHON_EXE="

rem 1. Check local virtual environment (.venv)
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
)

rem 2. Check Python Launcher (py) - standard on Windows
if not defined PYTHON_EXE (
    py -c "import sys" >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=py"
    )
)

rem 3. Check python command (verify it actually executes code, avoiding WindowsApps store shortcut)
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

echo [Launch] Checking dependencies...
"%PYTHON_EXE%" -c "import streamlit" >nul 2>nul
if %errorlevel% neq 0 (
    echo [Info] Installing dependencies from requirements.txt...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
)

echo [Launch] Starting Streamlit Dashboard...
echo [Python] %PYTHON_EXE%
echo [Local]  http://localhost:8501
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4"') do (
    for /f "tokens=* delims= " %%B in ("%%A") do echo [Network] http://%%B:8501
)
echo.
echo [Tip] If other PCs cannot connect, allow port 8501 in Windows Firewall (run once as Admin):
echo       netsh advfirewall firewall add rule name="NOVA Dashboard 8501" dir=in action=allow protocol=TCP localport=8501 profile=domain,private
echo.

"%PYTHON_EXE%" -m streamlit run app.py --server.headless=false --server.maxUploadSize=500 --browser.gatherUsageStats=false

if %errorlevel% neq 0 (
    echo.
    echo [Warning] Streamlit exited or encountered an error.
    echo [Info] Retrying with dependency verification...
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    echo.
    echo [Launch] Retrying Streamlit Dashboard...
    "%PYTHON_EXE%" -m streamlit run app.py --server.headless=false --server.maxUploadSize=500 --browser.gatherUsageStats=false
)

echo.
pause
