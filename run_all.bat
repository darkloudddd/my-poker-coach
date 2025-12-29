@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ==========================================
echo *** My Poker Coach - Launcher *** 
echo ==========================================
echo.

:: Check Python
set PYTHON_CMD=python
where python >nul 2>&1
if errorlevel 1 (
    set PYTHON_CMD=python3
)

echo Using Python command: %PYTHON_CMD%
echo.

:: 1. Setup Venv
echo [*] 1. Checking virtual environment...
if not exist .venv (
    echo   Creating .venv...
    %PYTHON_CMD% -m venv .venv
) else (
    echo   .venv already exists.
)

:: 2. Install Dependencies
echo.
echo [+] 2. Installing dependencies...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
    echo   [ERROR] Install failed.
    pause
    exit /b
)
echo [OK] Dependencies ready!

:: 3. Setup .env
echo.
echo [*] 3. Checking configuration...
set NEED_SETUP=0

if not exist .env (
    set NEED_SETUP=1
) else (
    findstr "sk-placeholder" .env >nul
    if not errorlevel 1 (
        echo   [!] Found placeholder configuration.
        set NEED_SETUP=1
    )
)

if "!NEED_SETUP!"=="1" (
    echo.
    if not exist .env echo   [!] .env not found.
    
    set /p API_KEY="Please enter your API Key (e.g. sk-...), then press Enter: "

    echo   Creating .env...
    copy .env.example .env >nul
    echo. >> .env
    echo LLM_API_KEY=!API_KEY!>> .env
    
    echo   [OK] .env created with your Key.
) else (
    echo   Configuration found.
)

:: 4. Start Server
echo.
echo [^>^>] 4. Starting Server...
echo.

:: Run server.py directly
.venv\Scripts\python.exe server.py

:: Check Python Exit Code
if errorlevel 1 (
    echo.
    echo [!] Server crashed or exited with error.
    pause
) else (
    echo.
    echo [OK] Server shutdown gracefully.
)
