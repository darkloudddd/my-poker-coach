"""
Card parsing / canonicalization utilities shared across strategy layers.
Extracted from features.py to reduce that file's responsibilities.
"""
from __future__ import annotations
from typing import List, Tuple, Optional, Dict, Any, Union
import re

try:
    from core.config import RANKS, RANK_VALUE, SUITS
except ImportError:
    # Fallback 防止單獨測試時報錯
    RANKS = "23456789TJQKA"
    SUITS = "shdc"
    RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}

def get_rank_value(card: str) -> int:
    if not card: return -1
    return RANK_VALUE.get(card[0].upper(), -1)

def parse_card(card: str) -> Tuple[Optional[str], Optional[str]]:
    """
    將 'Ks' -> ('K', 's')
    驗證是否合法，不合法回傳 (None, None)
    """
    if not card or len(card) != 2:
        return None, None
    rank = card[0].upper()
    suit = card[1].lower()
    if rank not in RANKS or suit not in SUITS:
        return None, None
    return rank, suit

def parse_hand_string(hand_str: str) -> List[str]:
    """ 把 'KhTh' 轉成 ['Kh', 'Th'] """
    if not hand_str: return []
    # 移除雜訊
    clean_str = hand_str.replace(" ", "").replace(",", "")
    if len(clean_str) % 2 != 0: return []
    return [clean_str[i:i+2] for i in range(0, len(clean_str), 2)]

def normalize_card_input(cards_data: Union[str, List[str]]) -> List[str]:
    """統一處理手牌/公牌解析，支援字串或列表輸入。"""
    if not cards_data:
        return []
    if isinstance(cards_data, str):
        return parse_hand_string(cards_data)
    if isinstance(cards_data, list):
        result = []
        for item in cards_data:
            result.extend(parse_hand_string(item))
        return result
    return []

# --- 手牌標準化 (從原 features.py 移出) ---
_HAND_RE_PAIR = re.compile(r"^[2-9TJQKA]{2}$")      # 如 "99", "TT"
_HAND_RE_SUFFIX = re.compile(r"^[2-9TJQKA]{2}[so]$") # 如 "AKs", "AKo"

def canonicalize_hand(code: str) -> str:
    """
    統一手牌代碼格式，供 Range 查表使用。
    輸入範例: "AhKh", "Ah Kh", "AKs", "A Ks", "9s9h"
    輸出範例: "AKs", "AKo", "99"
    """
    if not code: return ""
    
    # 1. 清理字串
    c = str(code).strip().replace(" ", "").replace(",", "").replace("OFF", "o").replace("off", "o")
    
    # 2. 如果已經是標準格式 (如 "AKs", "99")，直接回傳
    c_upper = c.upper()  # 字尾 s/o 暫時大寫，後面轉回小寫
    if _HAND_RE_PAIR.match(c_upper) and c_upper[0] == c_upper[1]:
        return c_upper # "99"
    if _HAND_RE_SUFFIX.match(c_upper):
        return c_upper[:-1] + c_upper[-1].lower() # "AKS" -> "AKs"

    # 3. 處理具體手牌 (如 "AhKh")
    if len(c) == 4:
        r1, s1 = c[0].upper(), c[1].lower()
        r2, s2 = c[2].upper(), c[3].lower()
        
        # 驗證是否為合法撲克牌
        if r1 not in RANKS or r2 not in RANKS: return code
        
        # 排序：大牌在前
        if RANK_VALUE[r1] < RANK_VALUE[r2]:
            r1, r2 = r2, r1
            s1, s2 = s2, s1
            
        if r1 == r2:
            return f"{r1}{r2}" # Pair -> "99"
        elif s1 == s2:
            return f"{r1}{r2}s" # Suited -> "AKs"
        else:
            return f"{r1}{r2}o" # Offsuit -> "AKo"
            
    return code # 無法解析則原樣回傳

def categorize_board_type(analysis: Dict[str, Any]) -> List[str]:
    """
    將分析結果轉化為語義化的標籤 (Archetypes)。
    """
    tags = []
    is_monotone = analysis.get("is_monotone", False)
    is_paired = analysis.get("is_paired", False)
    is_connected = analysis.get("is_connected", False)
    high_rank = analysis.get("high_card_rank", 0)
    suit_counts = analysis.get("suit_counts", {})
    max_suit = max(suit_counts.values()) if suit_counts else 0
    
    # 1. A-High Dry (GTO 經典場景: 高頻小注)
    if high_rank == 14 and not is_monotone and not is_connected and not is_paired:
        tags.append("A-High Dry")
        
    # 2. Monotone & Two-Tone
    if is_monotone:
        tags.append("Monotone")
    elif max_suit == 2:
        tags.append("Two-Tone")
    else:
        tags.append("Rainbow")
        
    # 3. Paired Boards / Multi-Pair
    ranks_char = analysis.get("ranks_char", [])
    pair_counts = {r: ranks_char.count(r) for r in set(ranks_char)}
    trips = [r for r, count in pair_counts.items() if count == 3]
    pairs = [r for r, count in pair_counts.items() if count == 2]

    if trips:
        tags.append("Trips-Board")
    elif len(pairs) >= 2:
        tags.append("Double-Paired")
    elif len(pairs) == 1:
        if RANK_VALUE.get(pairs[0], 0) >= 10:
            tags.append("High-Paired")
        else:
            tags.append("Low-Paired")
            
    # 4. Connectedness & Wheel
    if is_connected:
        if analysis.get("connectedness_score", 0) >= 80:
            tags.append("Highly-Connected")
        tags.append("Connected")
        
    ranks_val = analysis.get("ranks_val", [])
    if set([14, 2, 3]).issubset(set(ranks_val)) or set([2, 3, 4]).issubset(set(ranks_val)):
        tags.append("Wheel-Board")

    # 5. Broadway Dry
    if 11 <= high_rank <= 13 and not is_monotone and not is_connected and not is_paired:
        tags.append("Broadway-Dry")

    # 6. Ragged (低牌且不連張)
    if high_rank <= 9 and not is_connected and not is_paired and not is_monotone:
        tags.append("Ragged")

    return tags

def analyze_board(board_cards: List[str]) -> Dict[str, Any]:
    """
    進化的公共牌分析。包含連張分、聽牌密度與動態性評估。
    """
    if not board_cards:
        return {"danger_level": "safe", "is_monotone": False, "is_paired": False, "archetypes": []}

    ranks_char = [c[0].upper() for c in board_cards if c]
    suits = [c[1].lower() for c in board_cards if c]
    ranks_val = sorted(list(set([RANK_VALUE.get(r, 0) for r in ranks_char])), reverse=True)
    
    # 1. 顏色分析 (Monotone, Two-Tone, Rainbow)
    suit_counts = {s: suits.count(s) for s in set(suits)}
    max_suit = max(suit_counts.values()) if suit_counts else 0
    is_monotone = (max_suit >= 3)
    
    # 2. 公對面分析
    paired_ranks = [r for r in set(ranks_char) if ranks_char.count(r) >= 2]
    is_paired = len(paired_ranks) > 0
    
    # 3. 連張分 (Connectedness Score) 與 聽牌密度
    conn_score = 0
    draw_density = 0
    is_connected = False
    straight_key_ranks = []
    
    if len(ranks_val) >= 2:
        for start_val in range(2, 11): 
            window = set(range(start_val, start_val + 5))
            intersection = window.intersection(set(ranks_val))
            hit_count = len(intersection)
            
            if hit_count >= 3:
                is_connected = True
                span = max(intersection) - min(intersection)
                if hit_count >= 4:
                    score = 90
                elif span == 2: # No gap (e.g., 9-10-11)
                    score = 80
                elif span == 3: # 1 gap (e.g., 9-10-12)
                    score = 60
                else: # 2 gaps (e.g., 9-11-13)
                    score = 40
                
                conn_score = max(conn_score, score)
                draw_density += (2 if hit_count == 3 else 5) # 權重估算
                missing = window - intersection
                for m in missing:
                    r_char = [k for k, v in RANK_VALUE.items() if v == m]
                    if r_char and r_char[0] not in straight_key_ranks:
                        straight_key_ranks.append(r_char[0])
            elif hit_count == 2:
                # 判斷是相連還是有 Gap
                span = max(intersection) - min(intersection)
                if span <= 4:
                    conn_score = max(conn_score, 40 if span <= 2 else 20)
                    draw_density += 1

    # 4. 動態 vs 靜態 (Static vs Dynamic)
    # 越濕潤、越連張，面板越動態
    dynamic_val = conn_score * 0.5 + (max_suit - 1) * 20
    is_dynamic = dynamic_val >= 50
    
    # 危險度評級
    danger = "safe"
    if is_monotone or (is_connected and max_suit >= 2):
        danger = "wet"
    elif is_paired or is_dynamic:
        danger = "dynamic"
        
    analysis = {
        "is_monotone": is_monotone,
        "is_paired": is_paired,
        "paired_ranks": paired_ranks,
        "is_connected": is_connected,
        "connectedness_score": conn_score,
        "draw_density": draw_density,
        "is_dynamic": is_dynamic,
        "static_vs_dynamic": "dynamic" if is_dynamic else "static",
        "straight_key_ranks": straight_key_ranks,
        "high_card_rank": ranks_val[0] if ranks_val else 0,
        "danger_level": danger,
        "board_cards": board_cards,
        "suit_counts": suit_counts,
        "ranks_char": ranks_char,
        "ranks_val": ranks_val
    }
    
    # 注入語義標籤
    analysis["archetypes"] = categorize_board_type(analysis)
    return analysis
