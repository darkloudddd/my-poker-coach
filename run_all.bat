@echo off
setlocal
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
.venv\Scripts\python.exe -m pip install -r requirements.txt >nul 2>&1
if errorlevel 1 (
    echo   [ERROR] Install failed.
    pause
    exit /b
)
echo [OK] Dependencies ready!

:: 3. Setup .env
echo.
echo [*] 3. Checking configuration...
if not exist .env (
    echo   Creating .env from example...
    copy .env.example .env >nul
    echo. >> .env
    echo LLM_API_KEY=sk-placeholder >> .env
    echo   [WARNING] Please edit .env later to add your real API Key.
) else (
    echo   Configuration found.
)

:: 4. Start Server
echo.
echo [>>] 4. Starting Server on Port 8000...
echo [o] Opening browser...
start http://localhost:8000

.venv\Scripts\python.exe -u -m uvicorn server:app --reload --port 8000

pause
