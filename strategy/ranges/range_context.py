# strategy/range_context.py
from __future__ import annotations
from typing import Dict, Any, Tuple
import traceback

from .range import RANGE_ANALYZER  # 單例：避免重複生成 1326 combos

_RA = RANGE_ANALYZER


def _normalize_aggressor_tag(tag: str) -> str:
    """
    將舊版標記 (hero_open/hero_3bet/hero_4bet) 正規化為 'hero'/'villain'。
    """
    if not tag:
        return ""
    if isinstance(tag, str):
        lower = tag.lower()
        if lower.startswith("hero"):
            return "hero"
        if lower.startswith("villain"):
            return "villain"
    return str(tag)


def _get_sample_combos(combo_range: Dict[Tuple[str, str], float], board_cards: list = None, limit_per_cat=2) -> str:
    if not combo_range: return ""
    sorted_combos = sorted(combo_range.keys(), key=lambda x: combo_range[x], reverse=True)
    if not board_cards:
        return ", ".join([f"{c[0]}{c[1]}" for c in sorted_combos[:8]])
        
    try:
        import sys
        sys.path.append("c:\_src\python\計算理論專題\my_poker_coach")
        from strategy.eval import calculate_hand_strength
        from strategy.utils import effective_hand_category
    except Exception as e:
        return ", ".join([f"{c[0]}{c[1]}" for c in sorted_combos[:8]])
        
    cat_hands = {}
    board_set = set(board_cards)
    for c in sorted_combos:
        if c[0] in board_set or c[1] in board_set: continue
        try:
            cat, details = calculate_hand_strength(list(c), board_cards)
            eff = effective_hand_category(cat, details)
            if eff not in cat_hands: cat_hands[eff] = []
            if len(cat_hands[eff]) < limit_per_cat:
                cat_hands[eff].append(f"{c[0]}{c[1]}")
        except:
            pass
            
    return " | ".join([f"{cat}: {','.join(h)}" for cat, h in cat_hands.items() if cat != 'air'])


def ensure_range_math_data(features: Dict[str, Any], ctx: Dict[str, Any], street: str) -> Dict[str, Any]:
    """
    確保 ctx 中包含 'math_data'。
    整合了：
    1. 基礎數學：Pot Odds, SPR, Current Pot (修正下注後底池計算)
    2. 進階 GTO：Range Advantage, Score (保留你的範圍分析邏輯)
    """
    
    # 1. 初始化與基礎數學運算 (每次呼叫都更新，計算量小)
    math_data = ctx.get("math_data")
    if not isinstance(math_data, dict):
        math_data = {}

    try:
        # A. 提取基礎數據
        base_pot = float(features.get("pot_bb", 0.0))
        stack = float(features.get("hero_stack_bb", 100.0))
        amount_to_call = float(features.get("amount_to_call", 0.0))
        
        # B. 計算當前實際底池 (Current Pot)
        # 這裡的 base_pot 已包含目前街道的所有下注
        current_pot = base_pot
            
        # C. 計算底池賠率 (Pot Odds) -> Call / (Current Pot + Call)
        pot_odds = 0.0
        if amount_to_call > 0:
            final_pot_after_call = current_pot + amount_to_call
            pot_odds = amount_to_call / final_pot_after_call

        # D. 計算 SPR (Stack-to-Pot Ratio)
        spr = 999.0
        if current_pot > 0:
            spr = stack / current_pot

        # E. 先更新基礎數學到 math_data
        math_data.update({
            "base_pot": base_pot,
            "current_pot": current_pot, # 這是修正後的底池
            "amount_to_call": amount_to_call,
            "pot_odds": pot_odds,
            "spr": spr,
        })
        
        # 確保 ctx 外層也有 spr 供舊邏輯讀取
        ctx["spr"] = spr

    except Exception as e:
        print(f"⚠️ Basic Math Error: {e}")

    # 2. 進階 GTO 範圍運算 (緩存邏輯)
    # 如果已經算過該條街的 Range 數據，就直接回傳
    if math_data.get("street") == street and math_data.get("hero_range_summary"):
        ctx["math_data"] = math_data
        return ctx

    try:
        # 3. 獲取動態範圍 (考慮行動歷史後的 Capping)
        from .range_utils import apply_action_history_to_ranges
        board_cards = features.get("board_cards", [])
        hero_combo_range, villain_combo_range = apply_action_history_to_ranges(features, board_cards)

        # 4. 計算 Postflop 範圍分布 (使用 Combo 模式)
        hero_summary = _RA.get_postflop_range_summary(hero_combo_range, board_cards)
        villain_summary = _RA.get_postflop_range_summary(villain_combo_range, board_cards)

        # 5. 計算優勢分數 (利用已進化的 calculate_advantage)
        adv_res = _RA.calculate_advantage(hero_combo_range, villain_combo_range, board_cards, features, ctx)

        # 6. 更新 GTO 數據到 math_data
        hero_pos = str(features.get("hero_pos", features.get("hero_position", "BTN"))).upper()
        villain_pos = str(features.get("villain_pos", features.get("villain_position", "BB"))).upper()
        model = "3BP" if features.get("is_3bet_pot") else "SRP"

        math_data.update({
            "street": street,
            "hero_range_summary": hero_summary,
            "villain_range_summary": villain_summary,
            "hero_score": adv_res.get("hero_score", 0),
            "villain_score": adv_res.get("villain_score", 0),
            "range_advantage": adv_res.get("range_advantage", 1.0),
            "realized_range_advantage": adv_res.get("realized_range_advantage", 1.0),
            "nut_advantage": adv_res.get("nut_advantage", 1.0),
            "hero_rf": adv_res.get("hero_rf", 1.0),
            "villain_rf": adv_res.get("villain_rf", 1.0),
            "ratio": adv_res.get("realized_range_advantage", 1.0), # Fallback for old ratio field
            "hero_combos_sample": _get_sample_combos(hero_combo_range, board_cards),
            "villain_combos_sample": _get_sample_combos(villain_combo_range, board_cards),
            "note": f"Model: {model}, H:{hero_pos} vs V:{villain_pos} (Exact Combo + Realized Adv)"
        })
        
    except Exception as e:
        traceback.print_exc()
        print(f"⚠️ Range Context Error: {e}")
        math_data.update({"street": street, "ratio": 1.0, "error": str(e)})

    ctx["math_data"] = math_data
    return ctx
