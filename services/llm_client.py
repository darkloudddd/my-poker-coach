import json
import os
from typing import Any, List, Dict
from pathlib import Path
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH)

# ==========================================
# API 設定集中管理
# ==========================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 模型列表（優先順序）- 當額度用完時自動切換
DEFAULT_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
]

LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", DEFAULT_FALLBACK_MODELS[0]).strip()
CURRENT_MODEL_INDEX = 0  # 追蹤當前使用的模型


def _get_genai_components():
    from google import genai
    from google.genai import types

    return genai, types


def _build_history_contents(types_module, history: List[Dict[str, str]] | None):
    contents = []
    if not history:
        return contents

    for msg in history:
        if not isinstance(msg, dict):
            continue
        role = "user" if str(msg.get("role", "")).lower() == "user" else "model"
        text = str(msg.get("content", "") or "").strip()
        if not text:
            continue
        contents.append(
            types_module.Content(
                role=role,
                parts=[types_module.Part.from_text(text=text)],
            )
        )
    return contents


def _build_models_to_try() -> List[str]:
    ordered = []
    if LLM_MODEL_NAME:
        ordered.append(LLM_MODEL_NAME)
    ordered.extend(DEFAULT_FALLBACK_MODELS)

    deduped = []
    seen = set()
    for name in ordered:
        model_name = str(name or "").strip()
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        deduped.append(model_name)
    return deduped


def _response_to_text(response: Any) -> str:
    text = str(getattr(response, "text", "") or "").strip()
    if text:
        return text

    parsed = getattr(response, "parsed", None)
    if parsed is None:
        return ""
    if hasattr(parsed, "model_dump_json"):
        return parsed.model_dump_json()
    if hasattr(parsed, "json"):
        return parsed.json()
    try:
        return json.dumps(parsed, ensure_ascii=False)
    except TypeError:
        return str(parsed).strip()


def call_llm(
    system_prompt: str,
    user_message: str,
    history: List[Dict[str, str]] = None,
    response_mime_type: str | None = None,
) -> str:
    """
    呼叫 Gemini API 生成回應。
    支援模型 fallback 機制 - 當一個模型額度用完時自動切換到下一個。
    """
    global CURRENT_MODEL_INDEX
    
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it to your .env file.")
    genai, types_module = _get_genai_components()
    history_contents = _build_history_contents(types_module, history)
    user_text = str(user_message or "").strip()
    config_kwargs = {"system_instruction": str(system_prompt or "")}
    if response_mime_type:
        config_kwargs["response_mime_type"] = response_mime_type
    config = types_module.GenerateContentConfig(**config_kwargs)
    models_to_try = _build_models_to_try()

    # 嘗試列表中的所有模型
    for attempt, model_name in enumerate(models_to_try[CURRENT_MODEL_INDEX:], start=CURRENT_MODEL_INDEX):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            chat = client.chats.create(
                model=model_name,
                config=config,
                history=history_contents,
            )
            response = chat.send_message(user_text)
            response_text = _response_to_text(response)
            if not response_text:
                raise RuntimeError(f"Model {model_name} returned an empty response.")
            
            # 如果成功，更新當前模型索引
            CURRENT_MODEL_INDEX = attempt
            print(f"[Info] Using model: {model_name}")
            return response_text

        except Exception as e:
            print(f"[Warning] Model {model_name} failed: {e}")
            
            # 如果是配額限制錯誤或最後一個模型，繼續嘗試下一個
            if attempt < len(models_to_try) - 1:
                print(f"[Info] Trying next model in list...")
                continue
            else:
                # 所有模型都失敗了
                print(f"[Error] All models have failed.")
                return f"發生錯誤: 所有模型都無法使用 - {e}"
    
    return "發生錯誤: 無法連線到任何模型"
