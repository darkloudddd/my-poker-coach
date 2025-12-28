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

def recommend_flop(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ensure_range_math_data(features, ctx, "flop")
    villain_action = features.get("villain_action", "check").lower()
    
    # Analyze Positional Synergy
    board_info = ctx.get("board_info", {})
    hero_pos = features.get("hero_pos", "")
    villain_pos = features.get("villain_pos", "")
    ctx["hero_synergy"] = analyze_range_board_synergy(hero_pos, board_info)
    ctx["villain_synergy"] = analyze_range_board_synergy(villain_pos, board_info)
    
    amount_to_call = features.get("amount_to_call", 0)
    hero_is_ip = features.get("hero_is_ip", False)
    
    # 1. 獲取動態範圍優勢 (考慮行動歷史後的 Capping)
    adv_data = get_dynamic_advantage(features, ctx)
    ctx["advantage_data"] = adv_data
    
    # 判斷進攻權 (誰是最後一個 Raise 的人)
    # 簡化: Preflop 之後，如果 Villain Check，Hero (IP) 有進攻權
    if villain_action in ["bet", "raise"] or amount_to_call > 0:
        return _handle_facing_bet(features, ctx, adv_data, hero_pos, villain_pos)
        
    has_initiative = not (features.get("hero_is_ip", False) and villain_action == "check")
    if features.get("hero_is_ip", False) and villain_action == "check":
        has_initiative = True
    elif not features.get("hero_is_ip", False) and villain_action == "check":
        has_initiative = False
        
    return _handle_open_action(features, ctx, adv_data, has_initiative, hero_pos, villain_pos)

def _handle_open_action(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], has_initiative: bool, hero_pos: str, villain_pos: str):
    # Archetype heuristics & Advanced Metrics
    board_info = ctx.get("board_info", {})
    hand_cat = ctx.get("effective_hand_category", "")
    nut_adv = adv_data.get("nut_advantage", 1.0)
    range_adv = adv_data.get("range_advantage", 1.0)
    pot_bb = features.get("pot_bb", 1.0)
    spr = ctx.get("spr", 15.0)
    
    archetypes = board_info.get("archetypes", [])
    is_a_high_dry = "A-High Dry" in archetypes
    is_monotone = "Monotone" in archetypes
    is_3bet_pot = features.get("is_3bet_pot", False)

    reasons = []
    matrix = {"check": 1.0}

    # [Range Data Integration]
    v_summary = adv_data.get("villain_summary", {})
    v_nuts_freq = sum(v_summary.get(k, 0) for k in ["straight_flush", "quads", "full_house", "flush", "straight", "set"])
    
    if v_nuts_freq < 0.035 and range_adv > 1.1:
        reasons.append("對手範圍隱含封頂 (Capped)，缺乏強牌組合。")
    
    # 2. 核心啟發式：多尺寸下注 (Multi-Sizing)
    sizing_ratio = 0.33 # Default Small (33%)
    size_reason = "基於面板與優勢的標準下注。"

    # A. 幾何下注啟發式 (Geometric Sizing)
    if nut_adv >= 1.2 and 2.5 <= spr <= 8.0:
        sizing_ratio = calculate_geometric_sizing(spr, 3) 
        size_reason = f"具備顯著堅果優勢 ({nut_adv}) 且 SPR ({spr}) 適中，採用幾何尺寸規劃三街全壓。"
        
    # [High Priority] B. Range Bet (33%): Range Advantage OR Dry Board
    # 修正: 只要有顯著 Range Advantage (>= 1.15) 或 面板乾燥，優先採取 33%
    elif (range_adv >= 1.15 and not is_monotone) or (not board_info.get("is_dynamic") and board_info.get("connectedness_score", 0) < 50):
        sizing_ratio = 0.33
        reason_tag = "顯著範圍優勢" if range_adv >= 1.15 else "乾燥靜態面板"
        size_reason = f"具備{reason_tag}，優先使用 33% 小尺寸下注 (Range Bet / Dry Board C-Bet)。"
        
    # C. 常規大注 (75%): 動態/濕潤面板 (且無顯著 Range Advantage 時)
    elif board_info.get("is_dynamic") or board_info.get("connectedness_score", 0) >= 60:
        sizing_ratio = 0.75
        size_reason = "動態濕潤面板 (且缺乏範圍優勢)，大注保護權益並獲取價值。"
        
    # D. 低 SPR 強制 (100%): 
    elif spr < 2.0:
        sizing_ratio = 1.0
        size_reason = "低 SPR，直接進入承諾尺寸。"
    
    reasons.append(size_reason)

    hero_synergy = ctx.get("hero_synergy", 0)
    villain_synergy = ctx.get("villain_synergy", 0)
    villain_pos = features.get("villain_pos", "BB")
    
    if has_initiative:
        # [位置-範圍交互] 如果對手位置對此面板有極強契合度
        if villain_synergy >= 30 and range_adv < 1.2:
            matrix = {"bet": 0.35, "check": 0.65}
            reasons.append(f"此面板非常契合對手 ({villain_pos}) 的範圍優勢區，建議轉入高頻過牌以保護權益。")
        elif is_a_high_dry and range_adv >= 1.0:
            matrix = {"bet": 0.9, "check": 0.1}
            reasons.append("A-High Dry 面板非常有利於進攻方範圍，建議極高頻小尺寸 C-Bet。")
        elif is_monotone:
            matrix = {"bet": 0.4, "check": 0.6}
            reasons.append("單色面板 (Monotone) 對雙方範圍都極具威脅，建議較保守且極化的 C-Bet。")
        elif range_adv >= 1.2:
            matrix = {"bet": 0.8, "check": 0.2}
            reasons.append("具有顯著範圍優勢，進行高頻持續下注。")
        elif nut_adv >= 1.25 and not is_3bet_pot:
            matrix = {"bet": 0.6, "check": 0.4}
            reasons.append("具有極大堅果優勢，採取極化大尺寸下注。")
        elif hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set", "two_pair", "top_pair"]:
            matrix = {"bet": 0.7, "check": 0.3}
            reasons.append("強成牌價值下注。")
        elif "draw" in hand_cat:
            matrix = {"bet": 0.5, "check": 0.5}
            reasons.append("聽牌半詐唬。")
    else:
        if nut_adv >= 1.3:
            matrix = {"bet": 0.25, "check": 0.75}
            sizing_ratio = 0.33
            reasons.append("具有極端堅果優勢 (Donk Potential)，進行小尺寸領打。")
        else:
            reasons.append("身為防守方，預設採取過牌。")
            
    action = weighted_choice(matrix)
    
    # [Fix] 計算 Bet Amount 即使 Action 是 Check，供前端顯示 "若下注，建議尺寸"
    bet_amount = round(sizing_ratio * pot_bb, 2)
    size_details = {
        "bet_ratio": sizing_ratio,
        "bet_amount": bet_amount
    }

    return format_output(
        "flop", 
        action, 
        sizing_ratio if action == "bet" else 0,
        bet_amount if action == "bet" else 0,
        reasons,
        ctx,
        matrix,
        size_details=size_details # Pass extra info
    )

def _handle_facing_bet(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], hero_pos: str, villain_pos: str):
    # 再利用 GTO 分析器進行 MDF 判斷
    pot_bb = features.get("pot_bb", 1.0)
    amount_to_call = features.get("amount_to_call", 0)
    range_adv = adv_data.get("range_advantage", 1.0)
    
    mdf = GTOAnalyzer.calculate_mdf(pot_bb - amount_to_call, amount_to_call)
    reasons = [f"面對此下注，MDF 為 {mdf*100:.1f}%.", f"Hero 範圍優勢: {range_adv:.2f}"]
    
    hand_cat = ctx.get("effective_hand_category", "")
    hero_synergy = ctx.get("hero_synergy", 0)
    
    # 基礎防守邏輯
    if hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "top_pair"]:
        matrix = {"call": 0.85, "raise": 0.1, "fold": 0.05}
        reasons.append("強牌防守。")
    elif "draw" in hand_cat:
        if hero_synergy >= 30:
            matrix = {"call": 0.6, "raise": 0.4}
            reasons.append("此面板非常契合您的防守範圍，建議增加過牌-加注 (Check-Raise) 頻率進行半詐唬。")
        else:
            matrix = {"call": 0.8, "raise": 0.2}
            reasons.append("持有聽牌，混合跟注與平衡加注。")
            
    elif hand_cat in ["set", "two_pair"]:
        if hero_synergy >= 30:
            matrix = {"call": 0.3, "raise": 0.7}
            reasons.append("在有利於您的面板上持強成牌，進行高頻加注獲取價值。")
        else:
            matrix = {"call": 0.6, "raise": 0.4}
            reasons.append("強牌防守。")
    else:
         if mdf > 0.8:
             matrix = {"call": 0.9, "fold": 0.1}
             reasons.append(f"面對極小下注 (MDF={mdf*100:.0f}%)，根據賠率必須大幅放寬防守範圍。")
         else:
             matrix = {"fold": 1.0}
             reasons.append("牌力不足，棄牌。")
             
    action = weighted_choice(matrix)
    
    # [Fix] 計算 Bet Amount 即使 Action 是 Check (雖然 Facing Bet 通常只有 Raise/Call/Fold)
    # 但為了防呆仍保留結構
    bet_amount = 0.0 # Facing Bet 不為主動下注
    size_details = {
        "bet_ratio": 0.0,
        "bet_amount": 0.0
    }
    
    return format_output("flop", action, 0.0, 0.0, reasons, ctx, matrix, size_details=size_details)
