from typing import Dict, Any, List, Optional
import random
from ..utils import format_output, weighted_choice, effective_hand_category, analyze_range_board_synergy
from ..ranges.range_utils import get_dynamic_advantage
from ..ranges.range_context import ensure_range_math_data
from ..gto import GTOAnalyzer

def recommend_river(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ensure_range_math_data(features, ctx, "river")
    villain_action = features.get("villain_action", "check").lower()
    amount_to_call = features.get("amount_to_call", 0)
    
    # Analyze Positional Synergy
    board_info = ctx.get("board_info", {})
    hero_pos = features.get("hero_pos", "")
    villain_pos = features.get("villain_pos", "")
    ctx["hero_synergy"] = analyze_range_board_synergy(hero_pos, board_info)
    ctx["villain_synergy"] = analyze_range_board_synergy(villain_pos, board_info)
    
    # 1. 獲取動態優勢 (包含 Range Capping)
    adv_data = get_dynamic_advantage(features, ctx)
    ctx["advantage_data"] = adv_data
    
    if villain_action in ["bet", "raise"] or amount_to_call > 0:
        return _handle_facing_bet(features, ctx, adv_data, hero_pos, villain_pos)
        
    return _handle_open_action(features, ctx, adv_data, hero_pos, villain_pos)

def _handle_open_action(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], hero_pos: str, villain_pos: str):
    hand_cat = ctx.get("effective_hand_category", "")
    nut_adv = adv_data.get("nut_advantage", 1.0)
    range_adv = adv_data.get("range_advantage", 1.0)
    pot_bb = features.get("pot_bb", 1.0)
    
    # Archetype heuristics & Advanced Metrics
    board_info = ctx.get("board_info", {})
    archetypes = board_info.get("archetypes", [])
    is_monotone = "Monotone" in archetypes
    is_static = board_info.get("static_vs_dynamic") == "static"
    is_trips = "Trips-Board" in archetypes
    
    # Blocker Info
    blocker_info = ctx.get("blocker_info", {})
    has_nut_blocker = blocker_info.get("has_nut_flush_blocker", False)
    has_straight_blocker = blocker_info.get("has_straight_blocker", False)
    
    reasons = []
    matrix = {"check": 1.0}
    size_strategy = "medium" # Default
    
    # [Range Data Integration]
    v_summary = adv_data.get("villain_summary", {})
    v_nuts_freq = sum(v_summary.get(k, 0) for k in ["straight_flush", "quads", "full_house", "flush", "straight", "set"])
    
    if v_nuts_freq < 0.03 and nut_adv > 1.2:
        reasons.append("對手河牌範圍極度缺乏堅果 (Capped)，極化下注效用最大化。")
    
    if nut_adv >= 1.2:
        reasons.append(f"具有顯著堅果優勢 ({nut_adv:.2f})。")
        
    # --- Decision Tree ---
    
    # --- Decision Tree ---
    
    # 0. Determine Optimal Sizing First
    # 優先決定下注尺寸 (Sizing)，再決定頻率
    sizing_ratio = 0.75 # Default
    size_desc = "標準下注"
    
    if nut_adv >= 1.4:
        sizing_ratio = 2.0
        size_desc = "雙倍底池下注 (200% Pot)"
    elif nut_adv >= 1.2:
        sizing_ratio = 1.5
        size_desc = "超額下注 (150% Pot)"
    elif nut_adv >= 1.2:
        sizing_ratio = 1.0
        size_desc = "滿池下注 (Pot Bet)"
    # [NEW] 50% for Medium-Strong
    elif hand_cat in ["two_pair", "straight", "flush", "set"] and nut_adv < 1.2:
        sizing_ratio = 0.5
        size_desc = "半池下注 (Half Pot)"
    elif hand_cat in ["top_pair", "middle_pair"]:
        sizing_ratio = 0.33
        size_desc = "薄價值下注 (Thin Value)"

    # 1. Absolute Nuts (Polarized)
    if hand_cat in ["straight_flush", "quads"] or (hand_cat == "full_house" and nut_adv > 1.3):
        matrix = {"bet": 0.95, "check": 0.05}
        reasons.append(f"持有極端堅果 ({hand_cat})，使用 {size_desc}。")
        
    # 2. Strong Made Hands (Value)
    elif hand_cat in ["full_house", "flush"]:
        matrix = {"bet": 0.85, "check": 0.15}
        reasons.append(f"持有強成牌，進行 {size_desc}。")
        
    elif hand_cat in ["straight", "set", "two_pair"]:
        if is_monotone:
            matrix = {"check": 0.8, "bet": 0.2}
            reasons.append("單色面板 (Monotone) 對非同花強牌威脅大，採取保守過牌。")
        else:
            matrix = {"bet": 0.7, "check": 0.3}
            reasons.append(f"強成牌進行 {size_desc}。")
            
    # 3. Marginal Value (Thin Value)
    elif hand_cat == "top_pair":
        if is_monotone:
            matrix = {"check": 1.0}
            reasons.append("單色面板對頂對威脅大，過牌控池。")
        else:
            matrix = {"bet": 0.4, "check": 0.6}
            # 強制切換為小注
            sizing_ratio = 0.33 
            reasons.append("頂對尋求薄價值 (Thin Value)，使用小尺寸。")
            
    # 4. GTO Bluffs with Blockers
    elif range_adv >= 0.9 and (has_nut_blocker or has_straight_blocker):
        # Dynamically calculate bluff ratio based on CHOSEN sizing
        bluff_ratio = GTOAnalyzer.calculate_bluff_ratio(sizing_ratio)
        matrix = {"bet": bluff_ratio, "check": 1.0 - bluff_ratio}
        
        if has_nut_blocker:
            reasons.append(f"持有堅果同花阻擋牌，配合 {size_desc} 進行 GTO 平衡詐唬 ({bluff_ratio*100:.0f}%)。")
        else:
            reasons.append(f"持有關鍵順子阻擋牌，配合 {size_desc} 進行 GTO 平衡詐唬 ({bluff_ratio*100:.0f}%)。")
    else:
        reasons.append("牌力不足且無關鍵阻擋牌，採取過牌。")
        
    # Finalize
    if sizing_ratio == 1.5 and "Overbet" not in reasons[-1]:
         reasons.append("具備極端堅果優勢，使用 Overbet (150%) 進行極致極化施壓。")
    elif sizing_ratio == 1.0 and "Pot Bet" not in reasons[-1]:
         reasons.append("具備堅果優勢，使用買入尺 (Pot Size) 進行極化下注。")
        
    action = weighted_choice(matrix)
    amount = round(pot_bb * sizing_ratio, 1) if action == "bet" else 0
    final_ratio = sizing_ratio if action == "bet" else 0

    size_details = {
        "bet_ratio": sizing_ratio,
        "bet_amount": round(pot_bb * sizing_ratio, 1)
    }

    return format_output(
        "river", 
        action, 
        final_ratio,
        amount,
        reasons,
        ctx,
        matrix,
        size_details=size_details
    )

def _handle_facing_bet(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], hero_pos: str, villain_pos: str):
    # 再利用 GTO 分析器進行 MDF 判斷
    pot_bb = features.get("pot_bb", 1.0)
    amount_to_call = features.get("amount_to_call", 0)
    nut_adv = adv_data.get("nut_advantage", 1.0)
    
    mdf = GTOAnalyzer.calculate_mdf(pot_bb - amount_to_call, amount_to_call)
    reasons = [f"面對河牌下注，MDF 為 {mdf*100:.1f}%。"]
    
    # 阻擋牌防守邏輯 (Bluff Catcher)
    blocker_info = ctx.get("blocker_info", {})
    has_nut_blkr = blocker_info.get("has_nut_flush_blocker", False)
    
    hand_cat = ctx.get("effective_hand_category", "")
    if hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set", "two_pair"]:
        matrix = {"call": 0.9, "raise": 0.1}
        reasons.append("強牌防守。")
    elif hand_cat == "top_pair":
        matrix = {"call": 0.7, "fold": 0.3}
        reasons.append("頂對作為抓詐牌 (Bluff Catcher) 跟注。")
    elif has_nut_blkr and nut_adv > 0.9:
        matrix = {"call": 0.4, "fold": 0.6}
        reasons.append("持有堅果同花阻擋牌，混合跟注攔截詐唬。")
    else:
        matrix = {"fold": 1.0}
        reasons.append("牌力不足，棄牌。")
        
    action = weighted_choice(matrix)
    return format_output("river", action, 0.0, 0.0, reasons, ctx, matrix)
