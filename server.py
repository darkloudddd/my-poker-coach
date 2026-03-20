# server.py
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os
import signal
import traceback
import asyncio
import uuid
import copy

# 引入現有的 agent 邏輯
import agent
from features.context import parse_poker_situation
from strategy.engine import recommend_action

app = FastAPI(title="Poker Coach API")

# 記憶遊戲狀態與對話歷史
class GameSession:
    def __init__(self):
        self.session_id = str(uuid.uuid4())
        self.current_context = None
        self.internal_strategy_state = None
        self.chat_history = []
        self.last_strategy = None

    def reset(self):
        self.session_id = str(uuid.uuid4())  # Rotate session ID
        self.current_context = None
        self.internal_strategy_state = None
        self.chat_history = [{"role": "assistant", "content": "🧹 記憶已清除，請輸入新牌局。"}]
        self.last_strategy = None

# Global session instance (Simplifying for single user local app)
session = GameSession()

class ChatRequest(BaseModel):
    message: str
    ui_state: Optional[Dict[str, Any]] = None

class ChatResponse(BaseModel):
    advice: str
    game_state: Optional[Dict[str, Any]]
    strategy: Optional[Dict[str, Any]]

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_message = request.message.strip()
    ui_state = request.ui_state
    
    if not user_message and not ui_state:
        raise HTTPException(status_code=400, detail="Empty output")

    # 處理重置指令 (僅支援精確指令)
    if user_message.lower() in ["下一手", "重來", "reset"]:
        session.reset()
        # Return the message from history (or just the same string)
        return ChatResponse(advice="🧹 記憶已清除，請輸入新牌局。", game_state=None, strategy=None)

    # Append to history (user message)
    # If explicit text is empty but we have UI update, we might want to log a system event?
    # But user usually sees "Update Hand" generic text in frontend.
    if user_message:
        session.chat_history.append({"role": "user", "content": user_message})

    # Define synchronous processing function
    def process_chat_logic(user_msg, current_ctx, strategy_state, history, ui_updates):
        try:
            # Phase 0: Enforce UI State Updates (Override memory)
            # This ensures that if user sees cards in UI, backend SEES them too.
            effective_ctx = copy.deepcopy(current_ctx) if current_ctx else {}
            
            if ui_updates:
                # Map frontend keys to backend keys if needed, or assume consistent
                # Frontend sends: { "hero_hole_cards": [...], "board_cards": [...] }
                effective_ctx.update(ui_updates)
                
            # Phase 1: 解析 (Parsing)
            # Pass the ALREADY updated context to parser so LLM sees the new cards as "Previous State"
            new_features = parse_poker_situation(user_msg, effective_ctx)
            
            # Check for Strategy Query
            is_query = new_features.get("is_strategy_query", False)
            
            # Prepare working context
            local_ctx = effective_ctx # Start with what we had + UI
            
            # Always merge new features (excluding special flags if needed, but parser usually returns clean dict + flags)
            local_ctx.update(new_features)
            
            if is_query:
                 # Check if we have minimal required info (e.g., Hero Hand)
                 # Adjust this check based on what recommend_action needs
                 if not local_ctx.get("hero_hand") and not local_ctx.get("hero_hole_cards"):
                     return {
                         "error": "⚠️ 請先提供牌局資訊(至少手牌)，再詢問策略。", 
                         "context": None, 
                         "strategy": None
                     }

            # Phase 2: 策略 (Strategy Calculation)
            # Pass the UPDATED local_ctx
            strategy_input = copy.deepcopy(local_ctx)
            if strategy_state:
                strategy_input["_strategy_state"] = copy.deepcopy(strategy_state)
            strategy_output = recommend_action(strategy_input)

            # Update Context with Math Data from Strategy
            if "context" in strategy_output:
                local_ctx.update(strategy_output["context"])
            local_ctx.pop("_strategy_state", None)
            next_strategy_state = strategy_output.get("strategy_state") if isinstance(strategy_output.get("strategy_state"), dict) else strategy_state

            # Phase 3: 表達 (Agent Advice Generation)
            history_copy = list(history) # Work on copy
            final_advice = agent.generate_coaching_advice(
                user_input=user_msg, 
                game_state=local_ctx, 
                strategy_result=strategy_output, 
                chat_history=history_copy
            )
            public_strategy = copy.deepcopy(strategy_output)
            public_strategy.pop("strategy_state", None)

            return {
                "advice": final_advice.strip(),
                "context": local_ctx,
                "strategy_state": next_strategy_state,
                "strategy": public_strategy
            }
        except ValueError as ve:
             return {"error": f"❌ {str(ve)}"}
        except Exception as e:
             traceback.print_exc()
             return {"error": f"❌ 發生系統錯誤: {str(e)}"}

    # Capture current session ID
    current_sess_id = session.session_id

    try:
        # Run processing in a separate thread to avoid blocking the event loop
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, 
            process_chat_logic, 
            user_message, 
            session.current_context,
            session.internal_strategy_state,
            session.chat_history[:-1], # Exclude the just-added user message
            ui_state # [NEW] Pass UI state
        )

        # Check if session was reset during processing
        if session.session_id != current_sess_id:
            print(f"Session mismatch: {current_sess_id} != {session.session_id}. Discarding result.")
            # Return a special response that frontend can ignore, or error. 
            # Since logic is async, we just don't touch session state.
            return ChatResponse(advice="", game_state=None, strategy=None)

        # Handle Result
        if "error" in result:
             # Remove floating user message or append error?
             # Appending error as assistant message is better
             session.chat_history.append({"role": "assistant", "content": result["error"]})
             return ChatResponse(advice=result["error"], game_state=session.current_context, strategy=None)
        
        # Success: Update Session
        session.current_context = result["context"]
        session.internal_strategy_state = result.get("strategy_state")
        session.last_strategy = result["strategy"]
        
        final_advice = result["advice"]
        session.chat_history.append({"role": "assistant", "content": final_advice})
        
        # Limit History Length
        if len(session.chat_history) > 20:
             session.chat_history = session.chat_history[-20:]

        return ChatResponse(
            advice=final_advice,
            game_state=session.current_context,
            strategy=session.last_strategy
        )

    except Exception as e:
        print(f"System Error in /chat: {e}")
        traceback.print_exc()
        return ChatResponse(
            advice=f"❌ 發生系統錯誤: {str(e)}",
            game_state=session.current_context,
            strategy=None
        )

# Global variable for server control
server_instance = None

@app.post("/reset")
async def reset():
    session.reset()
    return {"status": "success", "message": "Game session reset"}

@app.post("/shutdown")
async def shutdown():
    """
    接收關閉指令，結束伺服器進程。
    """
    global server_instance
    print("🛑 Server received shutdown command...")
    
    if server_instance:
        # Graceful shutdown for Uvicorn (Exit code 0)
        server_instance.should_exit = True
    else:
        # Fallback if running via uvicorn command line directly (Exit code 1 usually)
        import threading
        def kill_server():
            print("🛑 Server shutting down (KILL)...")
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Timer(1.0, kill_server).start()
    
    return {"status": "success", "message": "Server is shutting down..."}

@app.get("/state")
async def get_state():
    """
    Retrieve current game session state for restoration.
    """
    return {
        "chat_history": session.chat_history,
        "game_state": session.current_context,
        "strategy": session.last_strategy
    }

# 掛載靜態檔案 (前端)
if not os.path.exists("static"):
    os.makedirs("static")

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import webbrowser
    from find_port import find_free_port
    
    port = find_free_port(8000, 8020)
    if not port:
        print("❌ Error: Could not find a free port between 8000 and 8020.")
        exit(1)
        
    print(f"🚀 Starting server on port {port}...")
    print(f"🚀 Opening browser at http://localhost:{port}...")
    
    webbrowser.open(f"http://localhost:{port}")
    
    # Run Uvicorn via Server object for control
    config = uvicorn.Config(app, host="0.0.0.0", port=port, loop="asyncio")
    server_instance = uvicorn.Server(config)
    server_instance.run()
