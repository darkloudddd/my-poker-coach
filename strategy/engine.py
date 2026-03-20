# strategy/engine.py
from typing import Dict, Any, Optional
import traceback
import copy

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

PRIVATE_STATE_KEY = "_strategy_state"
_STATEFUL_CTX_KEYS = {
    "preflop_aggressor",
    "villain_action",
    "initiative_owner",
    "checked_to_hero",
    "hero_first_to_act",
    "line_state",
    "board_transition",
    "has_turn_scare",
    "street_snapshots",
    "last_snapshot",
    "villain_range_insights",
    "hero_synergy",
    "villain_synergy",
    "math_data",
    "advantage_data",
}


def _normalize_strategy_features(features: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(features or {})

    hero_pos = normalized.get("hero_position") or normalized.get("hero_pos")
    villain_pos = normalized.get("villain_position") or normalized.get("villain_pos")
    hero_cards = normalized.get("hero_hole_cards") or normalized.get("hero_cards") or []

    if hero_pos:
        normalized["hero_position"] = str(hero_pos).upper()
        normalized["hero_pos"] = normalized["hero_position"]
    if villain_pos:
        normalized["villain_position"] = str(villain_pos).upper()
        normalized["villain_pos"] = normalized["villain_position"]

    normalized["hero_hole_cards"] = hero_cards
    normalized["hero_cards"] = hero_cards
    return normalized


def _extract_public_carryover(features: Dict[str, Any]) -> Dict[str, Any]:
    carried = {}
    for key in _STATEFUL_CTX_KEYS:
        value = features.get(key)
        if value is not None:
            carried[key] = copy.deepcopy(value)
    return carried


def _infer_preflop_aggressor_from_actions(features: Dict[str, Any]) -> str:
    actions = features.get("actions", {})
    hero_pos = str(features.get("hero_position") or features.get("hero_pos") or "").upper()
    villain_pos = str(features.get("villain_position") or features.get("villain_pos") or "").upper()

    preflop_actions = []
    if isinstance(actions, dict):
        items = actions.get("preflop", [])
        if isinstance(items, list):
            preflop_actions = items
    elif isinstance(actions, list):
        preflop_actions = [
            item for item in actions
            if isinstance(item, dict) and str(item.get("street", "")).lower() == "preflop"
        ]

    last_raiser = ""
    for item in preflop_actions:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).lower()
        if action not in {"open", "raise", "bet"}:
            continue
        player = str(item.get("player", "")).upper()
        if player:
            last_raiser = player

    if last_raiser == hero_pos:
        return "hero"
    if last_raiser == villain_pos:
        return "villain"
    return ""


def _build_ctx(features: Dict[str, Any]) -> Dict[str, Any]:
    previous_state = features.get(PRIVATE_STATE_KEY)
    previous_ctx = {}
    if isinstance(previous_state, dict):
        previous_ctx = previous_state.get("ctx") if isinstance(previous_state.get("ctx"), dict) else {}

    ctx = {}
    ctx.update(_extract_public_carryover(features))
    if previous_ctx:
        ctx.update(copy.deepcopy(previous_ctx))

    ctx.update(analyze_situation(
        features.get("hero_hole_cards", []),
        features.get("board_cards", [])
    ))

    ctx["hero_position"] = features.get("hero_position")
    ctx["villain_position"] = features.get("villain_position")
    if not ctx.get("preflop_aggressor"):
        inferred_aggressor = _infer_preflop_aggressor_from_actions(features)
        if inferred_aggressor:
            ctx["preflop_aggressor"] = inferred_aggressor
    return ctx

def recommend_action(features: Dict[str, Any]) -> Dict[str, Any]:
    """
    策略總入口：負責基礎分析，然後將控制權轉交給對應的街道模組。
    """
    try:
        features = _normalize_strategy_features(features)
        street = features.get("street", "preflop").lower()
        ctx = _build_ctx(features)
        
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

        # 3. Routing - 直接交給各街道模組處理
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
    public_ctx = dict(ctx or {})
    public_ctx.pop(PRIVATE_STATE_KEY, None)
    return {
        "street": public_ctx.get("street", "unknown"),
        "recommended_action": "fold", 
        "amount": 0.0,
        "action_desc": "FOLD (Error)",
        "suggestion": "FOLD 100%",
        "stats": "",
        "reasons": [f"Strategy Engine Error: {msg}"],
        "reasoning": [f"Strategy Engine Error: {msg}"],
        "strategy_matrix": {"fold": 1.0},
        "context": public_ctx,
        "strategy_state": ctx.get(PRIVATE_STATE_KEY) if isinstance(ctx.get(PRIVATE_STATE_KEY), dict) else None,
    }
