#!/bin/bash
echo "正在啟動撲克教練... 🚀"
echo "請等到出現 \"Uvicorn running on...\" 字樣"
echo "然後打開瀏覽器輸入: http://localhost:8000"
echo ""
uvicorn server:app --reload
