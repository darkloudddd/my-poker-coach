#!/bin/bash

echo "=========================================="
echo "🃏 My Poker Coach - 一鍵啟動腳本 🚀"
echo "=========================================="
echo ""

# 檢查 Python 指令
PYTHON_CMD="python"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ 找不到 python 或 python3，請安裝 Python。"
    exit 1
fi

echo "ℹ️  使用系統 Python: $PYTHON_CMD"

# 1. 虛擬環境設定
echo "[1/3] 檢查並設定虛擬環境 (.venv)... 🛠️"
if [ ! -d ".venv" ]; then
    echo "ℹ️  正在建立虛擬環境..."
    $PYTHON_CMD -m venv .venv
    if [ $? -ne 0 ]; then
        echo "❌ 建立虛擬環境失敗。"
        exit 1
    fi
    echo "✅ 虛擬環境建立完成。"
fi

# 設定使用虛擬環境的 Python
VENV_PYTHON="./.venv/bin/python"

# 2. 安裝套件 (使用虛擬環境)
echo "[2/3] 正在虛擬環境中檢查並安裝套件... 📦"
"$VENV_PYTHON" -m pip install -r requirements.txt > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ 套件安裝失敗，請檢查 Python/Pip 是否已安裝。"
    exit 1
fi
echo "✅ 套件準備就緒。"
echo ""

# 2. 設定環境變數
echo "[3/4] 檢查設定檔... ⚙️"
if [ ! -f .env ]; then
    echo "⚠️  尚未設定 .env 檔案。"
    echo ""
    read -p "請輸入您的 API Key (例如 sk-xxxx...)，按 Enter 確認：" API_KEY
    
    cp .env.example .env
    
    # Append the key to the file (simple approach) or replace
    # We will use sed to replace the placeholder if it exists, or append.
    # To be safe and simple: Append allows overwriting previous duplicate keys in some env parsers, 
    # but let's just append a clear line.
    echo "" >> .env
    echo "LLM_API_KEY=$API_KEY" >> .env
    
    echo "✅ 設定檔 .env 已建立！"
else
    echo "✅ 設定檔 .env 已存在，跳過設定。"
fi
echo ""

# 3. 啟動伺服器與瀏覽器
echo "[4/4] 正在啟動系統... 🚀"
echo ""

# 尋找可用 Port
SERVER_PORT=$("$VENV_PYTHON" find_port.py)

if [ "$SERVER_PORT" == "None" ] || [ -z "$SERVER_PORT" ]; then
    echo "❌ 找不到可用的 Port (8000-8010 皆被佔用)。"
    echo "請關閉其他使用中的程式後再試。"
    exit 1
fi

echo "⏳ 伺服器啟動中 (Port: $SERVER_PORT)..."
echo "🌍 網頁將自動開啟：http://localhost:$SERVER_PORT"

# Open browser based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://localhost:$SERVER_PORT"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open "http://localhost:$SERVER_PORT" 2>/dev/null || echo "請手動開啟瀏覽器: http://localhost:$SERVER_PORT"
fi

# Start Server
"$VENV_PYTHON" -u -m uvicorn server:app --reload --port "$SERVER_PORT"
