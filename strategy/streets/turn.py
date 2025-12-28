from typing import Dict, Any, List, Optional
import random
from ..utils import (
    format_output, 
    weighted_choice, 
    effective_hand_category, 
    analyze_range_board_synergy,
    calculate_geometric_sizing
)
from ..ranges.range_utils import get_dynamic_advantage
from ..ranges.range_context import ensure_range_math_data
from ..gto import GTOAnalyzer

def recommend_turn(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ensure_range_math_data(features, ctx, "turn")
    villain_action = features.get("villain_action", "check").lower()
    amount_to_call = features.get("amount_to_call", 0)
    hero_is_ip = features.get("hero_is_ip", False)
    
    # Analyze Positional Synergy
    board_info = ctx.get("board_info", {})
    hero_pos = features.get("hero_pos", "")
    villain_pos = features.get("villain_pos", "")
    ctx["hero_synergy"] = analyze_range_board_synergy(hero_pos, board_info)
    ctx["villain_synergy"] = analyze_range_board_synergy(villain_pos, board_info)
    
    # 1. 獲取動態範圍優勢 (考慮行動歷史後的 Capping)
    adv_data = get_dynamic_advantage(features, ctx)
    ctx["advantage_data"] = adv_data
    
    if villain_action == "check":
        has_initiative = hero_is_ip
    else:
        has_initiative = False
        
    if villain_action in ["bet", "raise"] or amount_to_call > 0:
        return _handle_facing_bet(features, ctx, adv_data, hero_pos, villain_pos)
        
    return _handle_open_action(features, ctx, adv_data, has_initiative, hero_pos, villain_pos)

def _handle_open_action(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], has_initiative: bool, hero_pos: str, villain_pos: str):
    hand_cat = ctx.get("effective_hand_category", "")
    nut_adv = adv_data.get("nut_advantage", 1.0)
    range_adv = adv_data.get("range_advantage", 1.0)
    has_scare = ctx.get("has_turn_scare", False)
    pot_bb = features.get("pot_bb", 1.0)
    is_3bet_pot = features.get("is_3bet_pot", False)
    
    # Archetype heuristics & Advanced Metrics
    board_info = ctx.get("board_info", {})
    archetypes = board_info.get("archetypes", [])
    is_wet = "Connected-Wet" in archetypes or board_info.get("connectedness_score", 0) >= 60
    is_monotone = "Monotone" in archetypes
    is_ragged = "Ragged" in archetypes
    
    # Blocker Info
    blocker_info = ctx.get("blocker_info", {})
    has_nut_blocker = blocker_info.get("has_nut_flush_blocker", False)
    has_straight_blocker = blocker_info.get("has_straight_blocker", False)
    has_trips_blocker = blocker_info.get("has_trips_blocker", False)
    
    reasons = []
    matrix = {"check": 1.0}
    sizing_ratio = 0.75 # Default
    
    if has_initiative:
        should_barrel = False
        
        # 1. Standard Value & Nut Advantage
        if nut_adv >= 1.1 or hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set"]:
            if is_monotone and hand_cat not in ["flush", "full_house", "quads", "straight_flush"]:
                matrix = {"bet": 0.3, "check": 0.7}
                reasons.append("單色面板 (Monotone) 對非同花強牌威脅極大，建議高頻過牌控池。")
            else:
                matrix = {"bet": 0.75, "check": 0.25}
                reasons.append("具有優勢，持續下注 (Double Barrel)。")
            should_barrel = True
            
        # 2. GTO Bluffs: Scare Card or Nut/Straight Blocker
        elif (has_scare or has_nut_blocker or has_straight_blocker) and range_adv >= 0.9:
            if is_wet and not (has_nut_blocker or has_straight_blocker):
                matrix = {"bet": 0.2, "check": 0.8}
                reasons.append("面板極度濕潤且無關鍵阻擋牌，減少轉牌詐唬頻率。")
            else:
                matrix = {"bet": 0.55, "check": 0.45}
                if has_nut_blocker:
                    reasons.append("持有堅果同花阻擋牌 (Nut Blocker)，進行平衡詐唬。")
                elif has_straight_blocker:
                    reasons.append("持有關鍵順子阻擋牌，減少對手強牌組合，適合進行第二發詐唬。")
                else:
                    reasons.append("轉牌驚悚牌有利於進攻方範圍，進行持續詐唬。")
            should_barrel = True
            
        elif "draw" in hand_cat and range_adv > 1.05:
            matrix = {"bet": 0.4, "check": 0.6}
            reasons.append("強聽牌進行第二發半詐唬。")
            should_barrel = True
            
        # 3. Sizing Adjustment (Multi-Sizing)
        if should_barrel:
            spr = ctx.get("spr", 15.0)
            size_reason = "標準轉牌價值/詐唬下注。"

            # A. 單色面板 (Monotone) [High Priority]
            if is_monotone:
                sizing_ratio = 0.33
                size_reason = "單色面板 (Monotone)，使用小注 (33%) 進行剝削與控池。"

            # B. 幾何下注啟發式 (Geometric Sizing)
            elif nut_adv >= 1.2 and 1.5 <= spr <= 6.0:
                sizing_ratio = calculate_geometric_sizing(spr, 2) # 剩餘 2 街
                size_reason = f"轉牌具備顯著堅果優勢 ({nut_adv:.2f}) 且 SPR ({spr:.1f}) 適中，採用幾何尺寸規劃兩街全壓。"

            # C. 超額下注 (Overbet 125%)
            elif nut_adv >= 1.5 and not has_scare:
                sizing_ratio = 1.25
                size_reason = "極端堅果優勢且轉牌為空白牌，使用超額下注施加最大極化壓力。"

            # D. 常規大注 (75%)
            elif nut_adv >= 1.2 or has_scare or board_info.get("connectedness_score", 0) >= 60:
                sizing_ratio = 0.75
                size_reason = "面板動態或需保護優勢，使用 75% 標準大注。"

            # E. 小注 (33%)
            elif is_3bet_pot and spr > 4.0:
                sizing_ratio = 0.33
                size_reason = "3-Bet 底池且 SPR 深，使用小注控制底池並保持頻率。"

            reasons.append(size_reason)
            
    else:
        # OOP Check-back protection...
        if nut_adv >= 1.3:
            matrix = {"bet": 0.25, "check": 0.75}
            reasons.append("堅果優勢劇增，考慮領打 (Donk)。")
            sizing_ratio = 0.33
        elif has_trips_blocker and range_adv > 1.1:
            matrix = {"bet": 0.2, "check": 0.8}
            reasons.append("持有公牌對子阻擋牌，輕微領打試探。")
            sizing_ratio = 0.25
        else:
            reasons.append("OOP 標準過牌。")
            
    action = weighted_choice(matrix)
    amount = round(pot_bb * sizing_ratio, 1) if action == "bet" else 0
    final_ratio = sizing_ratio if action == "bet" else 0

    size_details = {
        "bet_ratio": sizing_ratio,
        "bet_amount": round(pot_bb * sizing_ratio, 1)
    }

    return format_output(
        "turn", 
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
    
    mdf = GTOAnalyzer.calculate_mdf(pot_bb - amount_to_call, amount_to_call)
    reasons = [f"面對轉牌下注，MDF 為 {mdf*100:.1f}%。"]
    
    # 簡易防守邏輯
    hand_cat = ctx.get("effective_hand_category", "")
    if hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set", "two_pair", "top_pair"]:
        matrix = {"call": 0.8, "raise": 0.1, "fold": 0.1}
        reasons.append("強牌傾向跟注或加注。")
    elif "draw" in hand_cat:
        if ctx.get("hero_synergy", 0) >= 30:
            matrix = {"call": 0.6, "raise": 0.4}
            reasons.append("強聽牌 (Strong Draw) 適合進行過牌加注 (Check-Raise) 半詐唬，平衡堅果範圍。")
        else:
            matrix = {"call": 0.8, "fold": 0.2}
            reasons.append("一般聽牌根據賠率跟注。")
    else:
        matrix = {"fold": 1.0}
        reasons.append("牌力不足，棄牌。")
        
    action = weighted_choice(matrix)
    return format_output("turn", action, 0.0, 0.0, reasons, ctx, matrix)
