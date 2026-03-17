import sys
import os
from pathlib import Path

# 將根目錄加入 path
sys.path.append(str(Path(__file__).resolve().parents[0]))

from services.llm_client import call_llm

def test_gemini():
    print("🚀 正在測試 Gemini 整合...")
    
    system_prompt = "你是一個專業的撲克教練。請用繁體中文回答。"
    user_message = "你好，請簡短自我介紹並告訴我你現在使用的模型名稱（如果你知道的話）。"
    history = [
        {"role": "user", "content": "準備好了嗎？"},
        {"role": "assistant", "content": "是的，我準備好了。"}
    ]
    
    try:
        response = call_llm(system_prompt, user_message, history)
        print("\n🤖 Gemini 回應：")
        print("-" * 30)
        print(response)
        print("-" * 30)
        
        if response and "錯誤" not in response:
            print("\n✅ 測試成功！")
        else:
            print("\n❌ 測試失敗或回應中包含錯誤訊息。")
            
    except Exception as e:
        print(f"\n❌ 測試過程中發生異常：{e}")

if __name__ == "__main__":
    # 檢查 .env 是否有 API Key
    from dotenv import load_dotenv
    load_dotenv()
    if os.getenv("GEMINI_API_KEY") == "YOUR_GEMINI_API_KEY_HERE" or not os.getenv("GEMINI_API_KEY"):
        print("⚠️ 警告：請先在 .env 檔案中填寫正確的 GEMINI_API_KEY。")
    else:
        test_gemini()
