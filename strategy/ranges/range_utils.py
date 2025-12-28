from typing import List, Dict, Any
from .range import RANGE_ANALYZER, get_preflop_range

def _flatten(range_data: Dict[str, Any]) -> Dict[str, float]:
    """將複雜的 Preflop Range 格式扁平化為 Dict[str, float]"""
    if not range_data: return {}
    flattened = {}
    for hand, data in range_data.items():
        if isinstance(data, dict):
            # 取最大頻率 (例如 {"raise": 0.8, "call": 0.2} -> 1.0)
            flattened[hand] = sum(data.values())
        else:
            flattened[hand] = float(data)
    return flattened

def apply_action_history_to_ranges(features: Dict[str, Any], board_cards: List[str]):
    """
    根據行動歷史過濾 Hero 與 Villain 的範圍。
    進化版本：起始即使用 1326 Combo 級別追蹤。
    """
    hero_pos = features.get("hero_pos", features.get("hero_position", "BTN"))
    villain_pos = features.get("villain_pos", features.get("villain_position", "BB"))
    actions = features.get("actions", [])
    hero_hole_cards = features.get("hero_cards", []) # Hero 的具體手牌作為已知死牌
    
    # 初始死牌 (公牌 + Hero 手牌)
    dead_set = set(board_cards) | set(hero_hole_cards)
    
    # 1. 分析 Preflop 結構以決定初始範圍
    # [FIX] 區分加注底池 (Raised Pot) 與 跛入底池 (Limped Pot)
    preflop_acts = []
    if isinstance(actions, dict):
        preflop_acts = actions.get("preflop", [])
    elif isinstance(actions, list):
        preflop_acts = [a for a in actions if a.get("street") == "preflop"]
        
    has_raise = any(str(a.get("action", "")).lower() in ["open", "raise"] for a in preflop_acts)
    
    if has_raise:
        # 加注底池：假設 Hero RFI (或被動), Villain Call (或 RFI)
        # 這裡簡化假設 Hero 是主要視角，若 Hero 沒 Open 則可能邏輯需反轉，但暫維持原樣
        h_pre_weighted = _flatten(get_preflop_range("RFI", hero_pos))
        
        # 對於防守方 (Villain)
        v_preflop_data = get_preflop_range("facing_open", villain_pos, hero_pos)
        v_call_range = {}
        for hand, acts in v_preflop_data.items():
            if "call" in acts:
                v_call_range[hand] = acts["call"]
        v_pre_weighted = _flatten(v_call_range)
    else:
        # 跛入/過牌底池 (Limped Pot)：雙方範圍極寬且封頂 (Capped)
        # 模擬 Top 60% 範圍，並移除頂端 5% 強牌 (AA-TT, AK, AQs)
        # 這裡直接調用寬範圍 (RFI UTG 類似 Top 15%, BTN 50%) - 我們用 BTN 範圍作為基底並放寬
        base_range = _flatten(get_preflop_range("RFI", "BTN")) 
        
        # 移除強牌 (Capping)
        capped_range = {}
        premium = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}
        for hand, w in base_range.items():
            if hand not in premium:
                capped_range[hand] = 0.8 # 稍微降低權重表示不確定性
        
        h_pre_weighted = capped_range
        v_pre_weighted = capped_range.copy()

    hero_range = RANGE_ANALYZER.convert_weighted_range_to_combos(h_pre_weighted, dead_set)
    villain_range = RANGE_ANALYZER.convert_weighted_range_to_combos(v_pre_weighted, dead_set)

    # 2. 依次對各街行動進行過濾 (Range Capping)
    from features import analyze_board
    
    # [FIX] actions is a Dict {street: [list_of_actions]}, we need to flatten it chronologically
    flat_actions = []
    if isinstance(actions, dict):
        for street_key in ["preflop", "flop", "turn", "river"]:
             street_acts = actions.get(street_key, [])
             if isinstance(street_acts, list):
                 for item in street_acts:
                     # Ensure item has street info attached if missing
                     if isinstance(item, dict):
                         if "street" not in item:
                             item["street"] = street_key
                         flat_actions.append(item)
    elif isinstance(actions, list):
        flat_actions = actions

    for act in flat_actions:
        if not isinstance(act, dict):
            continue
        street = act.get("street", "").lower()
        p = act.get("player", "").upper()
        a = act.get("action", "").lower()
        
        # 獲取當時街的公牌
        if street == "flop":
            current_board = board_cards[:3]
        elif street == "turn":
            current_board = board_cards[:4]
        else:
            current_board = board_cards
            
        current_board_info = analyze_board(current_board) if current_board else {}
            
        if p == "HERO":
            hero_range = RANGE_ANALYZER.filter_range_by_action(hero_range, a, street, current_board, current_board_info)
        else:
            villain_range = RANGE_ANALYZER.filter_range_by_action(villain_range, a, street, current_board, current_board_info)
            
    return hero_range, villain_range

def get_dynamic_advantage(features: Dict[str, Any], ctx: Dict[str, Any]):
    """
    獲取動態 Advantage 數據。
    """
    board_cards = features.get("board_cards", [])
    if not board_cards:
        return {"range_advantage": 1.0, "nut_advantage": 1.0}
        
    hero_range, villain_range = apply_action_history_to_ranges(features, board_cards)
    return RANGE_ANALYZER.calculate_advantage(hero_range, villain_range, board_cards, features, ctx)
