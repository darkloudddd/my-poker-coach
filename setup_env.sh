#!/bin/bash
if [ -f .env ]; then
    echo ".env 檔案已經存在囉！ ⚠️"
else
    cp .env.example .env
    echo "設定檔 .env 建立成功！ ✨"
    echo "請記得打開 .env 填入您的 API Key 喔！ 🔑"
fi
