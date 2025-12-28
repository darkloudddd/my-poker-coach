#!/bin/bash

echo "=========================================="
echo "🃏 My Poker Coach - 一鍵啟動腳本 🚀"
echo "=========================================="
echo ""

# 1. 安裝套件
echo "[1/3] 正在檢查並安裝 Python 套件... 📦"
pip install -r requirements.txt > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ 套件安裝失敗，請檢查 Python/Pip 是否已安裝。"
    exit 1
fi
echo "✅ 套件準備就緒。"
echo ""

# 2. 設定環境變數
echo "[2/3] 檢查設定檔... ⚙️"
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
echo "[3/3] 正在啟動系統... 🚀"
echo ""
echo "⏳ 伺服器啟動中..."
echo "🌍 網頁將自動開啟：http://localhost:8000"

# Open browser based on OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "http://localhost:8000"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    xdg-open "http://localhost:8000" 2>/dev/null || echo "請手動開啟瀏覽器: http://localhost:8000"
fi

# Start Server
uvicorn server:app --reload
