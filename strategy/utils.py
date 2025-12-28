# strategy/utils.py
from typing import List, Tuple, Dict, Any, Optional

# ==============================================================================
# 1. 橋接 Features (核心數據源)
# ==============================================================================
try:
    # [關鍵修正] 這裡必須明確引入 get_rank_value，因為 range.py 會從這裡 import 它
    from features import (
        RANKS,
        RANK_VALUE,
        analyze_board,
        parse_hand_string,
        canonicalize_hand,
        get_rank_value
    )
except ImportError:
    # Fallback 防止單獨測試報錯
    RANKS = "23456789TJQKA"
    RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}
    def analyze_board(b): return {}
    def parse_hand_string(s): return []
    def canonicalize_hand(s): return s
    def get_rank_value(c): return -1

# [關鍵修正] range.py 依賴這個常數
SUITS = "shdc"

# ==============================================================================
# 2. 橋接 Common (工具函式)
# ==============================================================================
try:
    from .gto import format_output, weighted_choice
    from .eval import calculate_hand_strength
except ImportError:
    import random
    def weighted_choice(d): return list(d.keys())[0] if d else "check"
    def format_output(s, a, amt, ss, r, c, m, math_data=None): return {}
    def calculate_hand_strength(h, b): return ("air", "no_cards")

# ==============================================================================
# 3. Agent 整合工具
# ==============================================================================

def effective_hand_category(hand_category: str, kicker_strength: str) -> str:
    """
    依據 kicker/board 情況，調降過度樂觀的牌力類別。
    """
    cat = (hand_category or "").lower()
    kick = (kicker_strength or "").lower()

    if not cat:
        return cat

    board_only = {
        "board_trips",
        "board_two_pair",
        "board_flush",
        "board_straight",
        "board_full_house",
        "board_quads",
    }

    if cat in {"set", "two_pair", "flush", "straight", "full_house", "quads"} and kick in board_only:
        return "top_pair"

    if cat == "two_pair":
        if kick == "top_and_board":
            return "top_pair"
        if kick == "pair_and_board":
            return "middle_pair"
        if kick == "board_two_pair":
            return "top_pair"

    if cat == "top_pair" and kick.startswith("board_pair_"):
        if "top_kicker" in kick:
            return "middle_pair"
        return "bottom_pair"

    return cat


def analyze_situation(hero_cards: List[str], board_cards: List[str]) -> Dict[str, Any]:
    """整合手牌與公牌資訊，包含高級 Blocker 偵測"""
    category, details = calculate_hand_strength(hero_cards, board_cards)
    board_info = analyze_board(board_cards)

    # 進階 Blocker 偵測
    has_nut_flush_blocker = False
    has_straight_blocker = False
    has_trips_blocker = False
    blocker_details = []
    
    hero_ranks = [c[0].upper() for c in hero_cards]

    # 1. Flush Blocker
    if board_info.get("is_monotone"):
        suits = [c[1].lower() for c in board_cards if c]
        suit_counts = {s: suits.count(s) for s in set(suits)}
        flush_suit = max(suit_counts, key=suit_counts.get)
        for card in hero_cards:
            if card[0].upper() == 'A' and card[1].lower() == flush_suit:
                has_nut_flush_blocker = True
                blocker_details.append(f"持有 {flush_suit} 花色的堅果同花阻擋牌 (Nut Flush Blocker)")
                break

    # 2. Straight Blocker
    key_ranks = board_info.get("straight_key_ranks", [])
    for r in hero_ranks:
        if r in key_ranks:
            has_straight_blocker = True
            blocker_details.append(f"持有關鍵順子阻擋牌 ({r})")
            break

    # 3. Trips/Paired Blocker (Board Pair)
    paired_ranks = board_info.get("paired_ranks", [])
    for r in hero_ranks:
        if r in paired_ranks:
            has_trips_blocker = True
            blocker_details.append(f"持有公牌對子阻擋牌 ({r})，降低對手三條/葫蘆機率")
            break

    return {
        "hand_category": category,
        "effective_hand_category": effective_hand_category(category, details),
        "kicker_strength": details,
        "board_info": board_info,
        "hero_cards": hero_cards,
        "board_cards": board_cards,
        "blocker_info": {
            "has_nut_flush_blocker": has_nut_flush_blocker,
            "has_straight_blocker": has_straight_blocker,
            "has_trips_blocker": has_trips_blocker,
            "details": blocker_details
        }
    }

def analyze_range_board_synergy(pos: str, board_info: Dict[str, Any]) -> int:
    """
    評估特定位置的原始範圍與公牌結構的契合度 (Synergy Score)。
    正分表示利於該位置，負分表示不利。
    """
    if not pos or not board_info: return 0
    
    pos = pos.upper()
    high_rank = board_info.get("high_card_rank", 0)
    conn_score = board_info.get("connectedness_score", 0)
    archetypes = board_info.get("archetypes", [])
    
    # 位置類別定義
    tight_ranges = ["UTG", "HJ", "EP", "MP"]
    offensive_ranges = ["UTG", "HJ", "CO", "BTN"] # 開牌方通常具備高牌優勢
    defender_pos = "BB"
    
    synergy = 0
    
    # 1. Broadway Synergy (對開牌方/進攻方有利)
    if "Broadway-Dry" in archetypes or "A-High Dry" in archetypes:
        if pos in offensive_ranges: synergy += 30
        elif pos == defender_pos: synergy -= 20
        
    # 2. Low-Connected Synergy (寬手/Defender 優勢)
    if high_rank <= 9 and conn_score >= 60:
        if pos == defender_pos: synergy += 40
        elif pos in tight_ranges: synergy -= 30
        
    # 3. Paired/Trips Boards (Defender 優勢)
    if "Low-Paired" in archetypes or "Trips-Board" in archetypes:
        if pos == defender_pos: synergy += 20
        elif pos in tight_ranges: synergy -= 10

    # 4. Wheel & Connected (BTN/SB/BB 優勢)
    if "Wheel-Board" in archetypes or ("Connected" in archetypes and high_rank <= 7):
        if pos in ["BTN", "SB", "BB"]: synergy += 25
        
    return synergy

def calculate_realization_factor(pos: str, is_ip: bool, board_info: Dict[str, Any], spr: float) -> float:
    """
    計算權益實現係數 (R-Factor)。
    1.0 表示理論實現，> 1.0 表示超額實現 (通常為 IP)，< 1.0 表示實現不足 (通常為 OOP)。
    """
    if not pos: return 1.0
    
    # 基礎實現率
    r_factor = 1.0
    
    # 1. 位置影響 (IP 具備資訊優勢與最後行動權)
    if is_ip:
        r_factor += 0.15 # IP Bonus
    else:
        r_factor -= 0.10 # OOP Penalty
        
    # 2. 面板影響
    is_dynamic = board_info.get("is_dynamic", False)
    conn_score = board_info.get("connectedness_score", 0)
    if is_dynamic or conn_score >= 60:
        if is_ip:
            r_factor += 0.05 # IP 在動態面板更容易施壓
        else:
            r_factor -= 0.05 # OOP 在動態面板更容易被施壓
            
    # 3. SPR 影響 (SPR 越小，權益實現越接近 100%)
    if spr < 2.0:
        convergence = max(0.0, min(1.0, (2.0 - spr) / 2.0))
        r_factor = r_factor * (1.0 - convergence) + (1.0 * convergence)
    elif spr > 15.0:
        if is_ip: r_factor += 0.05
        else: r_factor -= 0.05
        
    return round(r_factor, 3)

def calculate_geometric_sizing(spr: float, streets_remaining: int) -> float:
    """
    計算幾何下注尺寸 (Geometric Sizing)。
    公式: B = (1 + SPR)^(1/n) - 1
    其中 B 是下注額佔當前底池的比例，n 是剩餘街道數。
    """
    if spr <= 0 or streets_remaining <= 0:
        return 0.75 # Default to large
        
    try:
        # B = (1 + SPR)^(1/n) - 1
        sizing = (1 + spr)**(1.0 / streets_remaining) - 1
        return round(float(sizing), 3)
    except:
        return 0.75

def normalize_hand_code_preflop(hand_str: Any) -> str:
    """Preflop 依賴此函式"""
    if isinstance(hand_str, list): hand_str = "".join(hand_str)
    return canonicalize_hand(hand_str)
