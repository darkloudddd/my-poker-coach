# server.py
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import traceback

# 引入現有的 agent 邏輯
import agent
from features.context import parse_poker_situation
from strategy.engine import recommend_action

app = FastAPI(title="Poker Coach API")

# 記憶遊戲狀態與對話歷史
class GameSession:
    def __init__(self):
        self.current_context = None
        self.chat_history = []

    def reset(self):
        self.current_context = None
        self.chat_history = []

# Global session instance (Simplifying for single user local app)
session = GameSession()

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    advice: str
    game_state: Optional[Dict[str, Any]]
    strategy: Optional[Dict[str, Any]]

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_message = request.message.strip()
    
    if not user_message:
        raise HTTPException(status_code=400, detail="Empty message")

    # 處理重置指令
    # 處理重置指令 (僅支援精確指令)
    if user_message.lower() in ["下一手", "重來", "reset"]:
        session.reset()
        return ChatResponse(advice="🧹 記憶已清除，請輸入新牌局。", game_state=None, strategy=None)

    # Append to history (user message)
    session.chat_history.append({"role": "user", "content": user_message})

    try:
        # Phase 1: 解析 (Parsing)
        # 這裡會拋出 ValueError 如果解析失敗或驗證不過
        new_features = parse_poker_situation(user_message, session.current_context)
        
        # 檢查是否為策略查詢 (Strategy Query) - 暫時不支援純查詢，邏輯上會要求有 Context
        is_query = new_features.get("is_strategy_query", False)
        
        # 更新 Context
        if not is_query:
            if session.current_context:
                # 合併新舊資訊 (簡單覆蓋)
                session.current_context.update(new_features)
            else:
                session.current_context = new_features
        else:
            if session.current_context is None:
                 return ChatResponse(advice="⚠️ 請先提供牌局資訊，再詢問策略。", game_state=None, strategy=None)

        # Phase 2: 策略 (Strategy Calculation)
        strategy_output = recommend_action(session.current_context)
        
        # 更新 context 中的數學數據 (例如 pot odds, SPR 等 由 strategy 計算出的)
        if "context" in strategy_output:
            if session.current_context:
                session.current_context.update(strategy_output["context"])
        
        # Phase 3: 表達 (Agent Advice Generation)
        final_advice = agent.generate_coaching_advice(
            user_input=user_message, 
            game_state=session.current_context, 
            strategy_result=strategy_output, 
            chat_history=session.chat_history
        )
        
        # Append Assistant Response to history
        session.chat_history.append({"role": "assistant", "content": final_advice})
        
        # Limit History Length
        if len(session.chat_history) > 20:
            session.chat_history = session.chat_history[-20:]

        return ChatResponse(
            advice=final_advice.strip(),
            game_state=session.current_context,
            strategy=strategy_output
        )

    except ValueError as ve:
        # 捕捉解析或驗證的預期錯誤，回傳給前端顯示
        error_msg = f"❌ {str(ve)}"
        print(f"Validation/Parsing Error: {ve}")
        return ChatResponse(
            advice=error_msg,
            game_state=session.current_context,
            strategy=None
        )

    except Exception as e:
        print(f"System Error in /chat: {e}")
        traceback.print_exc()
        return ChatResponse(
            advice=f"❌ 發生系統錯誤: {str(e)}",
            game_state=session.current_context,
            strategy=None
        )

@app.post("/reset")
async def reset():
    session.reset()
    return {"status": "success", "message": "Game session reset"}

# 掛載靜態檔案 (前端)
if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
