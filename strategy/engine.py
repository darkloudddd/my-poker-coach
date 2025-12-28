# strategy/engine.py
from typing import Dict, Any, Optional
import traceback

# 1. 引入核心配置
from core.config import RANKS, SUITS

# 2. 引入共用模組 (GTO 分析器、輸出格式化)
from .gto import GTOAnalyzer, format_output, weighted_choice

# 3. 引入具體策略規則 (邏輯層)
from .streets.preflop import recommend_preflop
from .streets.flop import recommend_flop
from .streets.turn import recommend_turn
from .streets.river import recommend_river

# 4. 引入工具 (用於計算具體牌力，如 "top_pair")
# 雖然我們重構了 features，但 utils 裡的 analyze_situation 
# 負責把 cards + board 轉成 "hand_category"，這部分保留在 utils 很好
from .utils import analyze_situation 

# 5. [關鍵連接] 引入 Range Context
# 這是連接 range.py 資料庫的橋樑
from .ranges.range_context import ensure_range_math_data

def recommend_action(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    策略總入口：負責基礎分析，然後將控制權轉交給對應的街道模組。
    """
    try:
        street = features.get("street", "preflop").lower()
        
        # 1. 基礎牌力分析 (Hand Strength)
        # 使用 utils 裡的 analyze_situation (已包含牌力計算)
        ctx = analyze_situation(
            features.get("hero_hole_cards", []),
            features.get("board_cards", [])
        )
        
        # 2. 數學參數注入 (SPR & Pot Odds)
        pot_bb = features.get("pot_bb", 1.0)
        amount_to_call = features.get("amount_to_call", 0.0)
        stack = features.get("hero_stack_bb", 100.0)
        
        # 計算 SPR
        if pot_bb > 0:
            ctx["spr"] = round(stack / pot_bb, 2)
        else:
            ctx["spr"] = 10.0
            
        # 計算 Pot Odds
        total_pot_after_call = pot_bb + amount_to_call
        if total_pot_after_call > 0 and amount_to_call > 0:
            ctx["pot_odds"] = round(amount_to_call / total_pot_after_call, 2)
        else:
            ctx["pot_odds"] = 0.0

        # 3. 路由分發 (Routing) - 直接交給各街道模組處理
        if street == "preflop":
            return recommend_preflop(features, ctx)
        elif street == "flop":
            return recommend_flop(features, ctx)
        elif street == "turn":
            return recommend_turn(features, ctx)
        elif street == "river":
            return recommend_river(features, ctx)
        else:
            return _error_fallback(f"Unknown street: {street}", ctx)

    except Exception as e:
        traceback.print_exc()
        return _error_fallback(str(e), features)

def _error_fallback(msg: str, ctx: Dict) -> Dict:
    """發生例外時的保底策略"""
    return {
        "street": ctx.get("street", "unknown"),
        "recommended_action": "fold", 
        "amount": 0.0,
        "action_desc": "FOLD (Error)",
        "suggestion": "FOLD 100%",
        "stats": "",
        "reasons": [f"Strategy Engine Error: {msg}"],
        "reasoning": [f"Strategy Engine Error: {msg}"],
        "strategy_matrix": {"fold": 1.0},
        "context": ctx
    }
