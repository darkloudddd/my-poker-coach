# agent.py
import sys
import traceback
from typing import Dict, Any, List

# 引入核心模組
try:
    import features  # 這是 features.py 模組
    from strategy.engine import recommend_action
    from services.prompts import COACH_SYSTEM_PROMPT
    from services.llm_client import call_llm
except ImportError as e:
    print(f"❌ 模組載入失敗: {e}")
    sys.exit(1)

# ==========================================
# 1. 第一階段：感知 (Perception)
# ==========================================

parse_poker_situation = features.parse_poker_situation


def _sanitize_coach_output(text: str) -> str:
    return text or ""


# ==========================================
# 3. 第三階段：表達 (Expression)
# ==========================================

def generate_coaching_advice(user_input: str, game_state: Dict[str, Any], strategy_result: Dict[str, Any], chat_history: List[Dict[str, str]]) -> str:
    print("💬 正在生成教練建議...")

    # --- 1. 基礎資訊提取 ---
    # 從 strategy context 提取手牌資訊，若無則顯示未知
    ctx = strategy_result.get("context", {})
    hand_cat = ctx.get('hand_category', '未知牌型')
    if ctx.get('kicker_strength'):
        hand_cat += f" ({ctx['kicker_strength']})"
    
    # 判斷位置
    is_ip = bool(game_state.get("hero_is_ip", False))
    pos_text = "有位置 (IP)" if is_ip else "無位置 (OOP)"
    
    # 判斷對手動作
    villain_act = game_state.get("villain_action", "check")
    
    # SPR / Pot / Odds
    math_data = strategy_result.get("math_data", {}) or {}
    spr = float(math_data.get("spr", game_state.get("spr", 0.0)) or 0.0)
    pot_bb = float(game_state.get("pot_bb", 0.0) or 0.0)
    current_pot = float(math_data.get("current_pot", 0.0) or 0.0)
    pot_display = current_pot if current_pot > 0 else pot_bb
    amount_call = float(math_data.get("amount_to_call", game_state.get("amount_to_call", 0.0)) or 0.0)
    pot_odds = float(math_data.get("pot_odds", ctx.get("pot_odds", game_state.get("pot_odds", 0.0))) or 0.0)
    pot_text = f"{pot_display:.2f} bb" if pot_display > 0 else "未知"
    unknown_call = amount_call <= 0 and str(villain_act).lower() in {"bet", "raise"}
    amount_text = f"{amount_call:.2f} bb" if amount_call > 0 else ("未知" if unknown_call else "0")
    if amount_call > 0:
        pot_odds_text = f"{pot_odds*100:.0f}%" if pot_odds > 0 else "未知"
    else:
        pot_odds_text = "未知" if unknown_call else "—"
    if unknown_call:
        act_desc = "對手下注 (尺寸未知)"
    else:
        act_desc = f"對手下注 ({amount_call:.2f}bb)" if amount_call > 0 else f"對手 {villain_act}"

    # --- 2. 策略矩陣與尺寸 ---
    # [修改] 從新的 strategy output 結構讀取
    matrix = strategy_result.get('strategy_matrix', {})
    strategy_str = ", ".join([f"{k.upper()} {v*100:.0f}%" for k, v in matrix.items() if v > 0.01])
    
    raw_amount = strategy_result.get("amount", 0.0)
    amount = float(raw_amount) if raw_amount is not None else 0.0
    street = strategy_result.get("street", game_state.get("street", "unknown"))
    
    # 產生尺寸描述
    action_name = str(strategy_result.get("recommended_action", "")).lower()
    if amount == 0:
        if action_name == "raise":
            size_display_text = "Raise (尺寸未知)"
        elif action_name == "bet":
            size_display_text = "Bet (尺寸未知)"
        elif action_name == "call":
            size_display_text = "Call (尺寸未知)"
        else:
            size_display_text = "不適用"
    else:
        # 計算相對於底池的比例 (簡單估算)
        pot_raw = game_state.get("pot_bb", 0.0)
        pot = float(pot_raw) if pot_raw is not None else 0.0
        pct = (amount / pot) * 100 if pot > 0 else 0
        if action_name == "raise":
            size_display_text = f"Raise to {amount:.1f} bb"
        elif action_name == "call":
            size_display_text = f"Call {amount:.1f} bb"
        else:
            size_display_text = f"{amount:.1f} BB ({pct:.0f}% Pot)"

    size_details = strategy_result.get("size_details", {}) or {}
    bet_ratio = size_details.get("bet_ratio")
    bet_amount = size_details.get("bet_amount")
    if bet_ratio and action_name == "check":
        if bet_amount and bet_amount > 0:
            bet_hint = f"{bet_amount:.1f} BB ({bet_ratio*100:.0f}% Pot)"
        else:
            bet_hint = f"{bet_ratio*100:.0f}% Pot"
        size_display_text = f"{size_display_text} | 可下注尺寸: {bet_hint}"

    # --- 3. 解析數學優勢數據 (Math Data) ---
    # [關鍵修改] 這裡要讀取新的 engine 算出來的 adv_ratio
    adv_ratio = ctx.get("adv_ratio", 0.0)
    
    math_section = "無詳細範圍數據"
    if adv_ratio > 0:
        if adv_ratio > 1.2: adv_label = "Hero 顯著優勢 (Aggressive)"
        elif adv_ratio < 0.8: adv_label = "Villain 顯著優勢 (Defensive)"
        else: adv_label = "勢均力敵 (Neutral)"
        
        math_section = f"""
    - 優勢比率 (Advantage Ratio): {adv_ratio:.2f} (Base: 1.0)
    - 優勢判斷: {adv_label}
    """
    
    # 若有更細的範圍摘要 (Optional)
    if "math_data" in ctx:
        hero_score = ctx["math_data"].get("hero_score", 0)
        if hero_score > 0:
             math_section += f" - 原始範圍評分 (Hero): {hero_score:.2f}"

    # --- 4. 構建 Context (User Message) ---
    context = f"""
    【📊 當前牌局快照 (JSON Data)】
    1. 狀態: {game_state.get('hero_position')} vs {game_state.get('villain_position')}, {pos_text}
    2. 底池: {pot_text}
    3. SPR: {spr:.2f}
    4. 手牌: {game_state.get('hero_hole_cards')} ({hand_cat})
    5. 公牌: {game_state.get('board_cards')}
    6. 對手行動: {act_desc}
    7. 需跟注: {amount_text}
    8. 底池賠率: {pot_odds_text}
    9. 範圍數據 (Range Analysis): {math_section}


    【🤖 Solver 運算結果】
    - 建議行動: {strategy_result.get('action_desc', 'Unknown')}
    - 混合策略頻率: {strategy_str}
    - 建議尺寸: {size_display_text}
    - 系統判定理由: {strategy_result.get('reasoning', ['無'])}
    
    【用戶問題】: "{user_input}"
    """
    
    # --- 5. 呼叫 LLM ---
    raw_advice = call_llm(COACH_SYSTEM_PROMPT, context, history=chat_history)
    return _sanitize_coach_output(raw_advice)

# ==========================================
# 4. 互動對話模式
# ==========================================

def start_chat_mode():
    print("\n" + "="*80)
    print("🃏 AI GTO 撲克教練")
    print("--------------------------------------------------")
    print("適用於6-max現金桌牌局")
    print("輸入「下一手」或「重來」可清除記憶")
    print("輸入「exit」或「quit」可結束對話")
    print("⚠️  注意: 輸入盡量完整，包含完整行動線、牌的花色等等，較能給出正確建議!!!")
    print("="*80)

    current_context = None
    chat_history = []      # Chat Memory (列表)

    while True:
        try:
            user_input = input("\n請輸入: ").strip()
            
            if user_input.lower() in ["exit", "quit"]:
                print("👋 下次見！")
                break
            
            if not user_input: continue
            
            # 重置邏輯 (同時清空兩種記憶)
            if user_input in ["下一手", "重來", "reset"]:
                current_context = None
                chat_history = [] 
                print("🧹 記憶已清除，請輸入新牌局。")
                continue
            
            if "下一手" in user_input and len(user_input) > 5:
                current_context = None
                chat_history = []
                print("🧹 (偵測到新牌局，記憶已清除)")

            # Phase 1: 解析 (不帶 Chat History，保持乾淨)
            new_features = parse_poker_situation(user_input, current_context)
            if not new_features: continue
            
            # 如果是純提問 (is_strategy_query=True)，new_features 可能就是舊的 context，或者有標記
            is_query = new_features.get("is_strategy_query", False)
            if not is_query:
                current_context = new_features
            else:
                # 如果是提問，使用舊的 context，但確保不為空
                if current_context is None:
                    print("⚠️ 請先提供牌局資訊，再詢問策略。")
                    continue
            
            # Phase 2: 策略 (純邏輯 - 呼叫新的 Engine)
            # engine.recommend_action 會回傳包含 math_data 的完整結果
            strategy_output = recommend_action(current_context)
            
            # [重要] 更新 context 中的數學數據，讓下一輪對話知道優勢狀態
            # Engine 會把 range math 存在 strategy_output["context"]
            if "context" in strategy_output:
                current_context.update(strategy_output["context"])
            
            # Phase 3: 表達 (帶 Chat History，保持連貫)
            final_advice = generate_coaching_advice(user_input, current_context, strategy_output, chat_history)
            
            print("\n" + "-"*30)
            print(final_advice.strip())
            print("-"*30)
            
            # 更新對話歷史
            chat_history.append({"role": "user", "content": user_input})
            chat_history.append({"role": "assistant", "content": final_advice})
            
            # 限制歷史長度 (避免 Token 爆炸)
            if len(chat_history) > 6:
                chat_history = chat_history[-6:]

        except KeyboardInterrupt:
            print("\n👋 強制結束。")
            break
        except Exception as e:
            print(f"\n❌ 錯誤: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    start_chat_mode()
