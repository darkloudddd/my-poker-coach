# strategy/ranges/range_insights.py
"""
範圍洞察工具：整合縮減後的對手範圍信息，
用於決策和推理展示。
"""

from typing import Dict, Tuple, List, Any


class RangeInsights:
    """
    根據縮減後的範圍生成可讀的洞察信息。
    """

    @staticmethod
    def analyze_villain_range(
        villain_combo_range: Dict[Tuple[str, str], float],
        board_cards: List[str],
        actions_taken: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        分析對手縮減後的範圍，生成洞察和推理。

        Return:
            {
                "most_likely_hands": ["JJ", "TT", "98s", ...],
                "nut_frequency": 0.15,  # 堅果牌比例
                "bluff_frequency": 0.05,
                "draw_frequency": 0.25,
                "range_strength": "Moderate",
                "key_insight": "對手可能拿著 top pair 或 draw",
                "blocking_considerations": {...}
            }
        """
        from ..utils import calculate_hand_strength, effective_hand_category

        if not villain_combo_range:
            return {
                "most_likely_hands": [],
                "nut_frequency": 0.0,
                "bluff_frequency": 0.0,
                "draw_frequency": 0.0,
                "range_strength": "Unknown",
                "key_insight": "無法確定對手範圍",
            }

        # 1. 統計各類別的權重
        category_weights: Dict[str, float] = {}
        hand_weights: Dict[str, float] = {}  # 追蹤手牌代碼以便展示

        for combo, weight in villain_combo_range.items():
            if weight <= 0:
                continue

            hands = [f"{c[0]}{c[1]}" for c in combo]
            cat, details = calculate_hand_strength(hands, board_cards)
            eff_cat = effective_hand_category(cat, details)

            category_weights[eff_cat] = category_weights.get(eff_cat, 0) + weight

            # 簡化為手牌代碼（便於展示）
            # 例如: ('As', '8h') -> 'A8o' 或 ('As', 'Ks') -> 'AKs'
            rank1, suit1 = hands[0][0], hands[0][1]
            rank2, suit2 = hands[1][0], hands[1][1]
            
            # 排序 rank (高到低)
            if "23456789TJQKA".index(rank1) > "23456789TJQKA".index(rank2):
                high_rank, low_rank = rank1, rank2
            else:
                high_rank, low_rank = rank2, rank1
            
            # 判斷同花/異花
            if suit1 == suit2:
                hand_code = f"{high_rank}{low_rank}s"
            else:
                hand_code = f"{high_rank}{low_rank}o"
            
            hand_weights[hand_code] = hand_weights.get(hand_code, 0) + weight

        total_weight = sum(villain_combo_range.values())
        if total_weight == 0:
            total_weight = 1.0

        # 2. 計算類別頻率
        nut_categories = [
            "straight_flush", "quads", "full_house", "flush", "straight", "set"
        ]
        value_categories = ["two_pair", "top_pair"]
        draw_categories = ["draw", "strong_draw", "weak_draw"]
        bluff_categories = ["air", "weak_pair"]

        nut_freq = sum(category_weights.get(c, 0) for c in nut_categories) / total_weight
        value_freq = sum(category_weights.get(c, 0) for c in value_categories) / total_weight
        draw_freq = sum(category_weights.get(c, 0) for c in draw_categories) / total_weight
        bluff_freq = sum(category_weights.get(c, 0) for c in bluff_categories) / total_weight

        # 3. 排序得出最可能的手牌
        most_likely = sorted(
            hand_weights.items(), key=lambda x: x[1], reverse=True
        )[:5]
        most_likely_hands = [h[0] for h in most_likely]

        # 4. 判斷範圍強度
        if nut_freq > 0.3:
            range_strength = "Very Strong (Nuts Heavy)"
        elif value_freq + nut_freq > 0.5:
            range_strength = "Strong"
        elif draw_freq + bluff_freq > 0.4:
            range_strength = "Weak/Draw-Heavy"
        else:
            range_strength = "Moderate"

        # 5. 生成洞察文字
        insight = RangeInsights._generate_insight_text(
            nut_freq, value_freq, draw_freq, bluff_freq,
            most_likely_hands, actions_taken
        )

        return {
            "most_likely_hands": most_likely_hands,
            "nut_frequency": round(nut_freq, 3),
            "value_frequency": round(value_freq, 3),
            "draw_frequency": round(draw_freq, 3),
            "bluff_frequency": round(bluff_freq, 3),
            "range_strength": range_strength,
            "key_insight": insight,
            "category_breakdown": {k: round(v / total_weight, 3) for k, v in category_weights.items()},
        }

    @staticmethod
    def _generate_insight_text(
        nut_freq: float,
        value_freq: float,
        draw_freq: float,
        bluff_freq: float,
        likely_hands: List[str],
        actions: List[Dict[str, Any]]
    ) -> str:
        """根據範圍統計生成易讀的洞察文字"""
        parts = []

        # 根據頻率分析
        if nut_freq > 0.25:
            parts.append("對手範圍中堅果牌非常多 🥜")
        elif value_freq + nut_freq > 0.5:
            parts.append("對手傾向於 value 牌")
        
        if draw_freq > 0.3:
            parts.append("大量抽牌")
        
        if bluff_freq > 0.2:
            parts.append("可能有詐唬成分")

        # 根據最可能的牌
        if likely_hands:
            parts.append(f"最可能：{', '.join(likely_hands)}")

        # 根據行動歷史
        if actions:
            last_action = actions[-1].get("action", "").lower() if actions else ""
            if last_action == "check":
                parts.append("對手過牌 → 可能不自信")
            elif last_action == "bet":
                parts.append("對手主動下注 → 可能 Value 牌為主")
            elif last_action == "raise":
                parts.append("對手加注 → 非常強")

        return " | ".join(parts) if parts else "無法確定對手意圖"
