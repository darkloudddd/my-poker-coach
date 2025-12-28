@echo off
setlocal
chcp 65001 >nul

echo ==========================================
echo 🃏 My Poker Coach - 一鍵啟動腳本 🚀
echo ==========================================
echo.

:: 1. 安裝套件
echo [1/3] 正在檢查並安裝 Python 套件... 📦
pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 套件安裝失敗，請檢查 Python 是否已安裝。
    pause
    exit /b
)
echo ✅ 套件準備就緒。
echo.

:: 2. 設定環境變數
echo [2/3] 檢查設定檔... ⚙️
if not exist .env (
    echo ⚠️  尚未設定 .env 檔案。
    echo.
    echo 請輸入您的 API Key (例如 sk-xxxx...)，按 Enter 確認：
    set /p API_KEY=
    
    copy .env.example .env >nul
    
    :: 簡單的取代方式 (Append 注意格式，這裡直接覆寫可能比較危險，我們用 append 方式加入 Key)
    :: 為了安全與簡單，我們讀取 example，然後把 KEY 取代掉，或者直接 append。
    :: 這裡採用 Append 方式覆寫 Key
    echo. >> .env
    echo LLM_API_KEY=!API_KEY! >> .env
    
    echo ✅ 設定檔 .env 已建立！
) else (
    echo ✅ 設定檔 .env 已存在，跳過設定。
)
echo.

:: 3. 啟動伺服器與瀏覽器
echo [3/3] 正在啟動系統... 🚀
echo.
echo ⏳ 伺服器啟動中，請稍候...
echo 🌍 網頁將自動開啟：http://localhost:8000

:: 先開瀏覽器 (等個 3 秒讓 server 起跑)
start "" "http://localhost:8000"

:: 啟動 Server
uvicorn server:app --reload

pause
