"""
公牌結構分析 - 分析牌面的特性和紋理
"""
from typing import List, Dict, Tuple, Set
from collections import Counter

try:
    from core.config import RANK_VALUE
except ImportError:
    RANK_VALUE = {r: i for i, r in enumerate("23456789TJQKA", start=2)}


class BoardStructure:
    """分析公牌本身的特性"""
    
    @staticmethod
    def parse_board(board_cards: List[str]) -> Tuple[List[int], List[str]]:
        """解析公牌為 (排序值列表, 花色列表)"""
        ranks, suits = [], []
        for card in board_cards:
            if not card or len(card) < 2:
                continue
            c = str(card).upper()
            rank_char = c[0]
            if rank_char not in RANK_VALUE:
                continue
            ranks.append(RANK_VALUE[rank_char])
            suits.append(c[1].lower() if len(c) > 1 else "?")
        return ranks, suits
    
    @staticmethod
    def classify_texture(board_cards: List[str]) -> str:
        """
        分類公牌紋理
        返回: "dry" | "wet" | "coordinated"
        """
        ranks, suits = BoardStructure.parse_board(board_cards)
        
        if len(ranks) < 3:
            return "unknown"
        
        # 檢查是否連牌 (coordinated)
        sorted_ranks = sorted(ranks, reverse=True)
        is_connected = False
        for i in range(len(sorted_ranks) - 1):
            if sorted_ranks[i] - sorted_ranks[i + 1] == 1:
                is_connected = True
                break
        
        if is_connected:
            return "coordinated"
        
        # 檢查高牌數量
        high_card_count = sum(1 for r in ranks if r >= 10)
        
        if high_card_count >= 2:
            return "dry"  # 高牌多 = 相對乾
        else:
            return "wet"  # 低牌多 = 濕（易成抽牌）
    
    @staticmethod
    def measure_connectivity(board_cards: List[str]) -> float:
        """
        測量牌面抽牌豐富度 (0.0 - 1.0)
        高連結度 = 易成抽牌、flush draw、straight draw 都可能
        """
        ranks, suits = BoardStructure.parse_board(board_cards)
        
        if len(ranks) < 3:
            return 0.0
        
        # 1. 連牌連續性
        sorted_ranks = sorted(set(ranks), reverse=True)
        gap_score = 0.0
        for i in range(len(sorted_ranks) - 1):
            gap = sorted_ranks[i] - sorted_ranks[i + 1]
            if gap == 1:
                gap_score += 1.0  # 連牌 = 高分
            elif gap == 2:
                gap_score += 0.5  # 單 gap = 中分
        
        gap_score = min(gap_score / 3.0, 1.0)  # 正規化
        
        # 2. Flush 潛力 (同花牌多)
        suit_counts = Counter(suits)
        flush_potential = max(suit_counts.values()) / len(suits) if suits else 0
        
        # 3. 整體連結度分數
        connectivity = (gap_score * 0.6 + flush_potential * 0.4)
        return connectivity
    
    @staticmethod
    def analyze_tiers(board_cards: List[str]) -> Dict[str, List[str]]:
        """
        分類牌力層次
        返回: {"nuts": [...], "strong": [...], "medium": [...], "weak": [...]}
        """
        ranks, suits = BoardStructure.parse_board(board_cards)
        
        if len(ranks) < 3:
            return {"nuts": [], "strong": [], "medium": [], "weak": []}
        
        # 統計排序
        rank_counts = Counter(ranks)
        sorted_ranks = sorted(set(ranks), reverse=True)
        
        tiers = {
            "nuts": [],           # 堅果手（SET、STRAIGHT、FLUSH）
            "strong": [],          # 強手（高對、OV）
            "medium": [],          # 中等手（低對、DRAW）
            "weak": []             # 弱手（高牌）
        }
        
        # 確定最高牌和次高牌
        top_rank = sorted_ranks[0] if sorted_ranks else 0
        second_rank = sorted_ranks[1] if len(sorted_ranks) > 1 else 0
        
        # 基於現在的配置（Flop）分類
        if len(ranks) == 3:
            # 檢查是否有對
            has_pair = any(c >= 2 for c in rank_counts.values())
            
            # Nuts: SET（配對牌）+ 某些連牌
            if has_pair:
                pair_rank = [r for r, c in rank_counts.items() if c == 2][0]
                tiers["nuts"].append(f"SET ({pair_rank})")
            
            # Straight/Flush potential
            if top_rank - second_rank <= 2:  # 連牌
                tiers["nuts"].append("STRAIGHT_POTENTIAL")
            if len(set(suits)) == 1 or all(suit == suits[0] for suit in suits):
                tiers["nuts"].append("FOUR_FLUSH")
            
            # Strong: OV (Ace/King over board)
            if top_rank < 14:  # 公牌沒有 A
                tiers["strong"].append("OVERPAIR_ACE")
            if top_rank < 13 and second_rank < 13:  # 公牌沒有 K
                tiers["strong"].append("OVERPAIR_KING")
            
            tiers["strong"].append(f"TOP_PAIR ({top_rank})")
            tiers["strong"].append(f"SECOND_PAIR ({second_rank})")
            
            # Medium: 低對、DRAW
            tiers["medium"].append("MIDDLE_PAIR")
            tiers["medium"].append("BOTTOM_PAIR")
            tiers["medium"].append("FLUSH_DRAW")
            tiers["medium"].append("STRAIGHT_DRAW")
            
            # Weak: 高牌
            tiers["weak"].append("HIGH_CARD")
        
        return tiers
    
    @staticmethod
    def board_summary(board_cards: List[str]) -> Dict:
        """完整的公牌特性摘要"""
        texture = BoardStructure.classify_texture(board_cards)
        connectivity = BoardStructure.measure_connectivity(board_cards)
        tiers = BoardStructure.analyze_tiers(board_cards)
        ranks, suits = BoardStructure.parse_board(board_cards)
        
        return {
            "cards": board_cards,
            "texture": texture,
            "connectivity": connectivity,
            "tiers": tiers,
            "is_wet": texture in ["wet", "coordinated"],
            "is_dry": texture == "dry",
            "rank_distribution": dict(Counter(ranks)),
            "suit_distribution": dict(Counter(suits)),
        }
