"""
牌力分析 - 基於具體牌面分析範圍的牌力層次分佈
"""
from typing import List, Dict, Optional, Any
from strategy.eval.hand_eval import calculate_hand_strength
from strategy.reasoning.board_structure import BoardStructure

try:
    from core.config import RANK_VALUE
except ImportError:
    RANK_VALUE = {r: i for i, r in enumerate("23456789TJQKA", start=2)}


class StrengthAnalyzer:
    """分析範圍的牌力分佈"""

    @staticmethod
    def _coerce_hole_cards(hand_repr: Any) -> Optional[List[str]]:
        if isinstance(hand_repr, (tuple, list)) and len(hand_repr) == 2:
            cards = [str(c) for c in hand_repr]
            if all(len(card) >= 2 for card in cards):
                return cards

        text = str(hand_repr or "").strip()
        if len(text) == 4:
            c1, c2 = text[:2], text[2:4]
            if c1[0].upper() in RANK_VALUE and c2[0].upper() in RANK_VALUE:
                return [c1, c2]
        return None
    
    @staticmethod
    def evaluate_hand_on_board(
        hand_code: Any,
        board_cards: List[str]
    ) -> str:
        """
        評估特定手牌在特定牌面上的牌力類別
        返回: "nuts" | "strong" | "medium" | "weak" | "blocked"
        """
        try:
            hole = StrengthAnalyzer._coerce_hole_cards(hand_code)
            if hole is None:
                # 解析 generic hand code，如 AKo / AKs / AA
                text = str(hand_code or "")
                if len(text) < 2:
                    return "weak"

                rank1, rank2 = text[0], text[1]
                if len(text) >= 3 and text.endswith("s"):
                    hole = [f"{rank1}h", f"{rank2}h"]
                elif len(text) >= 3 and text.endswith("o"):
                    hole = [f"{rank1}s", f"{rank2}h"]
                else:
                    hole = [f"{rank1}s", f"{rank2}h"]

            if len(hole) != 2:
                return "weak"

            category, details = calculate_hand_strength(hole, board_cards)
            
            # 對應到牌力層級
            strength_mapping = {
                "straight_flush": "nuts",
                "quads": "nuts",
                "full_house": "nuts",
                "flush": "nuts",
                "straight": "nuts",
                "set": "nuts",
                "two_pair": "strong",
                "top_pair": "strong",
                "overpair": "strong",
                "middle_pair": "medium",
                "bottom_pair": "weak",
                "draw": "medium",
                "air": "weak",
            }
             
            return strength_mapping.get(category, "weak")
        
        except Exception as e:
            return "weak"
    
    @staticmethod
    def analyze_range_distribution(
        range_dict: Dict[Any, float],
        board_cards: List[str]
    ) -> Dict:
        """
        給定範圍，分析在特定牌面上的牌力分佈
        
        返回:
        {
            "nuts_pct": 0.15,
            "strong_pct": 0.35,
            "medium_pct": 0.40,
            "weak_pct": 0.10,
            "breakdown": {
                "nuts": {"total_weight": 0.15, "hands": ["AA", "KK", ...]},
                ...
            }
        }
        """
        distribution = {
            "nuts_pct": 0.0,
            "strong_pct": 0.0,
            "medium_pct": 0.0,
            "weak_pct": 0.0,
            "breakdown": {
                "nuts": {"total_weight": 0.0, "hands": [], "count": 0},
                "strong": {"total_weight": 0.0, "hands": [], "count": 0},
                "medium": {"total_weight": 0.0, "hands": [], "count": 0},
                "weak": {"total_weight": 0.0, "hands": [], "count": 0},
            }
        }
        
        total_weight = 0.0
        
        for hand_code, weight in range_dict.items():
            strength = StrengthAnalyzer.evaluate_hand_on_board(
                hand_code, board_cards
            )
            
            distribution[f"{strength}_pct"] += weight
            distribution["breakdown"][strength]["total_weight"] += weight
            distribution["breakdown"][strength]["hands"].append(hand_code)
            distribution["breakdown"][strength]["count"] += 1
            
            total_weight += weight
        
        # 正規化為百分比
        if total_weight > 0:
            for key in ["nuts_pct", "strong_pct", "medium_pct", "weak_pct"]:
                distribution[key] = distribution[key] / total_weight
        
        # 排序每個強度層的手牌
        for strength in distribution["breakdown"]:
            breakdown = distribution["breakdown"][strength]
            # 按權重降序排列
            hands_with_weight = [
                (h, range_dict.get(h, 0)) for h in breakdown["hands"]
            ]
            hands_with_weight.sort(key=lambda x: x[1], reverse=True)
            breakdown["hands"] = [h for h, _ in hands_with_weight[:5]]  # 取前5
        
        return distribution
    
    @staticmethod
    def compare_ranges_at_board(
        hero_range: Dict[Any, float],
        villain_range: Dict[Any, float],
        board_cards: List[str]
    ) -> Dict:
        """
        在特定牌面上比較雙方範圍的相對牌力
        
        返回:
        {
            "hero_dist": {...},
            "villain_dist": {...},
            "range_advantage": 0.25,  # hero - villain 的強手百分比
            "who_leads": "Hero",  # 誰在這個牌面領先
            "polarization_diff": 0.1,  # 分化程度差異
        }
        """
        hero_dist = StrengthAnalyzer.analyze_range_distribution(
            hero_range, board_cards
        )
        villain_dist = StrengthAnalyzer.analyze_range_distribution(
            villain_range, board_cards
        )
        
        # 計算牌力領先度
        hero_strong = hero_dist["nuts_pct"] + hero_dist["strong_pct"]
        villain_strong = villain_dist["nuts_pct"] + villain_dist["strong_pct"]
        range_advantage = hero_strong - villain_strong
        
        # 分化程度（強手 - 弱手的差異）
        hero_polarization = hero_strong - villain_dist["weak_pct"]
        villain_polarization = villain_strong - hero_dist["weak_pct"]
        polarization_diff = hero_polarization - villain_polarization
        
        return {
            "hero_dist": hero_dist,
            "villain_dist": villain_dist,
            "range_advantage": range_advantage,
            "who_leads": "Hero" if range_advantage > 0 else "Villain",
            "lead_margin": abs(range_advantage),
            "polarization_diff": polarization_diff,
            "board_summary": BoardStructure.board_summary(board_cards)
        }


class ActionRationality:
    """判斷對手行動是否合理"""
    
    @staticmethod
    def get_reasonable_actions(
        villain_dist: Dict,
        board_struct: Dict,
        is_ip: bool,
        street: str,
        background: Optional[Dict] = None
    ) -> Dict[str, float]:
        """
        根據牌力分佈和牌面特性，決定合理的行動
        
        返回:
        {
            "check_likelihood": 0.35,      # 過牌的合理程度
            "bet_likelihood": 0.50,        # 下注的合理程度
            "raise_likelihood": 0.15,      # 加注的合理程度
        }
        """
        # 基礎：根據牌力分佈
        villain_nuts = villain_dist["nuts_pct"]
        villain_strong = villain_dist["strong_pct"]
        villain_weak = villain_dist["weak_pct"]
        
        # 初始倾向
        if villain_nuts > 0.3:
            # 堅果多 → 傾向下注/加注
            check_like = 0.1
            bet_like = 0.6
            raise_like = 0.3
        elif villain_strong > 0.4:
            # 強手多 → 經常下注
            check_like = 0.25
            bet_like = 0.60
            raise_like = 0.15
        elif villain_weak > 0.5:
            # 弱手多 → 傾向過牌
            check_like = 0.70
            bet_like = 0.20
            raise_like = 0.10
        else:
            # 無法判斷 → 平衡
            check_like = 0.40
            bet_like = 0.45
            raise_like = 0.15
        
        # 根據牌面特性調整
        if board_struct["is_wet"]:
            # 濕牌 → 更可能下注流暢牌面
            bet_like += 0.10
            check_like -= 0.05
        else:
            # 乾牌 → 更可能過牌等待發展
            check_like += 0.05
            bet_like -= 0.05
        
        # 根據位置調整
        if is_ip:
            # IP → 更激進
            bet_like += 0.10
            check_like -= 0.05
        else:
            # OOP → 更保守
            check_like += 0.05
            bet_like -= 0.05
        
        # 正規化
        total = check_like + bet_like + raise_like
        return {
            "check": check_like / total,
            "bet": bet_like / total,
            "raise": raise_like / total,
        }
    
    @staticmethod
    def action_surprise_factor(
        actual_action: str,
        reasonable_actions: Dict[str, float]
    ) -> float:
        """
        計算實際行動與預期行動的'驚訝度'（0.0 - 1.0）
        0.0 = 完全合理
        1.0 = 非常意外
        """
        if actual_action not in reasonable_actions:
            return 0.5  # 未知行動
        
        likelihood = reasonable_actions[actual_action]
        surprise = 1.0 - likelihood
        return surprise
