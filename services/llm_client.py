import os
import requests
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH)


# ==========================================
# API 設定集中管理：需從環境變數取得，避免硬編碼 key。
# ==========================================

LLM_API_URL = os.getenv("LLM_API_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME")


def call_llm(system_prompt: str, user_message: str, history: List[Dict[str, str]] = None) -> str:
    if not LLM_API_URL or not LLM_API_KEY:
        raise RuntimeError("LLM_API_URL/LLM_API_KEY is not set. Add them to your environment or .env")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }

    # 1. 系統提示詞
    messages = [{"role": "system", "content": system_prompt}]

    # 2. 插入歷史對話
    if history:
        messages.extend(history)

    # 3. 當前用戶訊息
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": LLM_MODEL_NAME,
        "messages": messages,
        "temperature": 0.05, 
        "stream": False 
    }

    try:
        response = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=180)
        response.raise_for_status()
        data = response.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        elif "message" in data:
            return data["message"]["content"]
        else:
            return str(data)
    except Exception as e:
        print(f"[Error] API Call failed: {e}")
        return ""
