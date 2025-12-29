# strategy/range_context.py
from __future__ import annotations
from typing import Dict, Any, Tuple
import traceback

from .range import RANGE_ANALYZER  # 單例：避免重複生成 1326 combos
from ..gto import DecisionMaker

_RA = RANGE_ANALYZER
_DM = DecisionMaker()

# 位置順序只用於 fallback（ctx 沒給 preflop 資訊時才用）
_POS_ORDER = {"UTG": 0, "HJ": 1, "CO": 2, "BTN": 3, "SB": 4, "BB": 5}


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


def _get_sample_combos(combo_range: Dict[Tuple[str, str], float], limit=8) -> str:
    """從範圍中取樣出代表性手牌 (轉換為字串列表)"""
    if not combo_range: return ""
    # 修正：依照權重 (Weight) 由高到低排序，取出最可能的對手手牌
    # x 是 key (combo tuple)，combo_range[x] 是 weight
    hands = sorted(combo_range.keys(), key=lambda x: combo_range[x], reverse=True)[:limit]
    return ", ".join([f"{c[0]}{c[1]}" for c in hands])


def _infer_model(features, ctx):
    # 直接讀取 features，不要自己再算一遍
    if features.get("is_3bet_pot"): return "3BP"
    return "SRP"


def _infer_roles(features: Dict[str, Any], ctx: Dict[str, Any], model: str) -> Tuple[str, str, list]:
    """
    回傳 (opener, threebettor_or_none, assumptions)

    opener / threebettor_or_none 的值：
      - 'hero' / 'villain'
      - threebettor_or_none 在 SRP 會是 'none'
    """
    assumptions = []
    aggressor = _normalize_aggressor_tag((ctx or {}).get("preflop_aggressor"))  # 'hero' / 'villain' / None

    if model == "SRP":
        # SRP：aggressor == opener（最後一次加注就是 open）
        if aggressor in ("hero", "villain"):
            assumptions.append("SRP：使用 ctx.preflop_aggressor 決定 opener（不再用位置順序猜）")
            return aggressor, "none", assumptions

        # fallback：用位置順序猜（盡量少用）
        hero_pos = features.get("hero_position", "BTN")
        villain_pos = features.get("villain_position", "BB")
        hero_first = _POS_ORDER.get(hero_pos, 999) < _POS_ORDER.get(villain_pos, 999)
        opener = "villain" if hero_first else "hero"
        assumptions.append("SRP fallback：ctx 未提供 preflop_aggressor，使用位置順序近似推斷 opener")
        return opener, "none", assumptions

    # 3BP：aggressor == 3-bettor（最後一次加注是 3bet）
    if aggressor in ("hero", "villain"):
        threebettor = aggressor
        opener = "villain" if threebettor == "hero" else "hero"
        assumptions.append("3BP：使用 ctx.preflop_aggressor 決定 3-bettor/opener（不再用位置順序猜）")
        return opener, threebettor, assumptions

    # fallback：用位置順序猜誰是 opener，另一方當作 3bettor（不可靠但比完全不能算好）
    hero_pos = features.get("hero_position", "BTN")
    villain_pos = features.get("villain_position", "BB")
    hero_first = _POS_ORDER.get(hero_pos, 999) < _POS_ORDER.get(villain_pos, 999)
    opener = "villain" if hero_first else "hero"
    threebettor = "hero" if opener == "villain" else "villain"
    assumptions.append("3BP fallback：ctx 未提供 preflop_aggressor，使用位置順序近似推斷 opener/3-bettor")
    return opener, threebettor, assumptions


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
            "realized_range_advantage": adv_res.get("realized_range_advantage", 1.0),
            "nut_advantage": adv_res.get("nut_advantage", 1.0),
            "ratio": adv_res.get("realized_range_advantage", 1.0), # Fallback for old ratio field
            "hero_combos_sample": _get_sample_combos(hero_combo_range),
            "villain_combos_sample": _get_sample_combos(villain_combo_range),
            "note": f"Model: {model}, H:{hero_pos} vs V:{villain_pos} (Exact Combo + Realized Adv)"
        })
        
    except Exception as e:
        traceback.print_exc()
        print(f"⚠️ Range Context Error: {e}")
        math_data.update({"street": street, "ratio": 1.0, "error": str(e)})

    ctx["math_data"] = math_data
    return ctx
