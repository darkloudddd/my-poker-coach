import os
import google.generativeai as genai
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# ==========================================
# API 設定集中管理
# ==========================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gemini-1.5-flash")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def call_llm(system_prompt: str, user_message: str, history: List[Dict[str, str]] = None) -> str:
    """
    呼叫 Gemini API 生成回應。
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")

    try:
        # 初始化模型，並帶入系統提示詞
        model = genai.GenerativeModel(
            model_name=LLM_MODEL_NAME,
            system_instruction=system_prompt
        )

        # 轉換歷史紀錄格式為 Gemini 格式 (role: user/model)
        gemini_history = []
        if history:
            for msg in history:
                role = "user" if msg["role"] == "user" else "model"
                gemini_history.append({"role": role, "parts": [msg["content"]]})

        # 啟動對話會話
        chat = model.start_chat(history=gemini_history)

        # 發送訊息
        response = chat.send_message(user_message)
        
        return response.text.strip()

    except Exception as e:
        print(f"[Error] Gemini API Call failed: {e}")
        return f"發生錯誤: {e}"
