@echo off
cd /d "%~dp0"
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
    py -c "import sys" >nul 2>nul
    if %errorlevel% equ 0 (
        set "PYTHON_EXE=py"
    ) else (
        python -c "import sys" >nul 2>nul
        if %errorlevel% equ 0 (
            set "PYTHON_EXE=python"
        )
    )
)
if not defined PYTHON_EXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
        if exist "%%D\python.exe" (
            "%%D\python.exe" -c "import sys" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%D\python.exe"
        )
    )
)
if not defined PYTHON_EXE (
    echo [ERROR] Python not found.
    pause
    exit /b 1
)
"%PYTHON_EXE%" build_exe.py
pause
