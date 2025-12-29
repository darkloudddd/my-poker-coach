@echo off
setlocal
chcp 65001 >nul

echo ==========================================
echo 🃏 My Poker Coach - 一鍵啟動腳本 🚀
echo ==========================================
echo.

:: 檢查 Python 指令
set PYTHON_CMD=python
where python >nul 2>&1
if %errorlevel% neq 0 (
    where python3 >nul 2>&1
    if %errorlevel% neq 0 (
        where py >nul 2>&1
        if %errorlevel% neq 0 (
            echo ❌ 找不到 python, python3 或 py 指令，請安裝 Python。
            pause
            exit /b
        ) else (
            set PYTHON_CMD=py
        )
    ) else (
        set PYTHON_CMD=python3
    )
)

echo ℹ️  使用系統 Python: %PYTHON_CMD%

:: 1. 虛擬環境設定
echo [1/3] 檢查並設定虛擬環境 (.venv)... 🛠️
if not exist .venv (
    echo ℹ️  正在建立虛擬環境...
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo ❌ 建立虛擬環境失敗。
        pause
        exit /b
    )
    echo ✅ 虛擬環境建立完成。
)

:: 設定使用虛擬環境的 Python
set VENV_PYTHON=.venv\Scripts\python.exe

:: 2. 安裝套件 (使用虛擬環境)
echo [2/3] 正在虛擬環境中檢查並安裝套件... 📦
"%VENV_PYTHON%" -m pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 套件安裝失敗。
    pause
    exit /b
)
echo ✅ 套件準備就緒。
echo.

:: 2. 設定環境變數
echo [3/4] 檢查設定檔... ⚙️
if not exist .env (
    echo ⚠️  尚未設定 .env 檔案。
    echo.
    echo 請輸入您的 API Key (例如 sk-xxxx...)，按 Enter 確認：
    set /p API_KEY=
    
    copy .env.example .env >nul
    
    :: 簡單的取代方式
    echo. >> .env
    echo LLM_API_KEY=!API_KEY! >> .env
    
    echo ✅ 設定檔 .env 已建立！
) else (
    echo ✅ 設定檔 .env 已存在，跳過設定。
)
echo.

:: 3. 啟動伺服器與瀏覽器
echo [4/4] 正在啟動系統... 🚀
echo.

:: 尋找可用 Port
for /f "delims=" %%i in ('"%VENV_PYTHON%" find_port.py') do set SERVER_PORT=%%i

if "%SERVER_PORT%"=="None" (
    echo ❌ 找不到可用的 Port (8000-8010 皆被佔用)。
    echo 請關閉其他使用中的程式後再試。
    pause
    exit /b
)

echo ⏳ 伺服器啟動中 (Port: %SERVER_PORT%)，請稍候...
echo 🌍 網頁將自動開啟：http://localhost:%SERVER_PORT%

:: 伺服器將在啟動後自動開啟瀏覽器

:: 啟動 Server (使用虛擬環境)
"%VENV_PYTHON%" -m uvicorn server:app --reload --port %SERVER_PORT%

pause
