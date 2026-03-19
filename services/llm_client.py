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

# 模型列表（優先順序）- 當額度用完時自動切換
MODELS_TO_TRY = [
    'gemini-2.0-flash',
    'gemini-1.5-pro',
    'gemini-1.5-flash',
    'gemini-flash-latest'
]

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", MODELS_TO_TRY[0])
CURRENT_MODEL_INDEX = 0  # 追蹤當前使用的模型

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def call_llm(system_prompt: str, user_message: str, history: List[Dict[str, str]] = None) -> str:
    """
    呼叫 Gemini API 生成回應。
    支援模型 fallback 機制 - 當一個模型額度用完時自動切換到下一個。
    """
    global CURRENT_MODEL_INDEX
    
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")

    # 嘗試列表中的所有模型
    for attempt, model_name in enumerate(MODELS_TO_TRY[CURRENT_MODEL_INDEX:], start=CURRENT_MODEL_INDEX):
        try:
            # 初始化模型，並帶入系統提示詞
            model = genai.GenerativeModel(
                model_name=model_name,
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
            
            # 如果成功，更新當前模型索引
            CURRENT_MODEL_INDEX = attempt
            print(f"[Info] Using model: {model_name}")
            return response.text.strip()

        except Exception as e:
            error_msg = str(e).lower()
            print(f"[Warning] Model {model_name} failed: {e}")
            
            # 如果是配額限制錯誤或最後一個模型，繼續嘗試下一個
            if attempt < len(MODELS_TO_TRY) - 1:
                print(f"[Info] Trying next model in list...")
                continue
            else:
                # 所有模型都失敗了
                print(f"[Error] All models have failed.")
                return f"發生錯誤: 所有模型都無法使用 - {e}"
    
    return "發生錯誤: 無法連線到任何模型"
