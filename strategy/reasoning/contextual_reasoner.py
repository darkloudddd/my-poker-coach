"""
街道-特定的推理引擎 - 基於牌面+牌力+歷史的統一推理系統
"""
from typing import List, Dict, Optional, Any
from strategy.reasoning.board_structure import BoardStructure
from strategy.reasoning.strength_analyzer import (
    StrengthAnalyzer, ActionRationality
)


class ContextualReasoner:
    """
    街道推理主類
    每一街都基於：
    1. 牌面特性（連結度、紋理）
    2. 範圍牌力分佈（對手在這個牌面有什麼）
    3. 相對優勢（我 vs 對手）
    4. 前一街背景（發生了什麼）
    5. 實際行動 vs 合理行動
    """
    
    def __init__(self):
        self.board_struct = None
        self.ranges_comparison = None
        self.action_rationality = None
        self.filtering_trace = []  # 追蹤所有過濾步驟
    
    def reason_street(
        self,
        street: str,  # "flop" | "turn" | "river"
        hero_range: Dict[Any, float],
        villain_range: Dict[Any, float],
        board_cards: List[str],
        next_action: str,  # "check" | "bet" | "call" | "raise"
        is_ip: bool,
        villain_pos: str,
        background: Optional[Dict] = None
    ) -> Dict:
        """
        完整的街道推理流程
        
        返回:
        {
            "new_range": {...},  # 過濾後的範圍
            "reasoning": {
                "board_structure": {...},
                "ranges_comparison": {...},
                "action_rationality_summary": {...},
                "plain_english": "...",  # 可讀的推理
                "filtering_adjustment": 0.75,  # 過濾強度
            }
        }
        """
        street_key = str(street).lower()
        
        # 1. 分析牌面特性
        self.board_struct = BoardStructure.board_summary(board_cards)
        
        # 2. 分析雙方牌力
        self.ranges_comparison = StrengthAnalyzer.compare_ranges_at_board(
            hero_range, villain_range, board_cards
        )
        
        # 3. 決定合理的行動
        reasonable_actions = ActionRationality.get_reasonable_actions(
            self.ranges_comparison["villain_dist"],
            self.board_struct,
            is_ip,
            street_key,
            background
        )
        
        # 4. 計算驚訝度
        surprise = ActionRationality.action_surprise_factor(
            next_action, reasonable_actions
        )
        
        # 5. 基於驚訝度和連結度，決定過濾強度
        filtering_adjustment = self._calculate_filtering_adjustment(
            surprise,
            self.board_struct["connectivity"],
            self.ranges_comparison["who_leads"],
            is_ip,
            street_key
        )
        
        # 6. 過濾範圍
        new_range = self._filter_range(
            villain_range,
            next_action,
            filtering_adjustment,
            self.board_struct,
            self.ranges_comparison
        )
        
        # 7. 生成推理摘要
        reasoning = self._generate_reasoning(
            street,
            next_action,
            surprise,
            reasonable_actions,
            filtering_adjustment,
            background
        )
        
        return {
            "new_range": new_range,
            "reasoning": reasoning,
            "board_struct": self.board_struct,
            "ranges_comparison": self.ranges_comparison,
            "action_rationality": reasonable_actions,
            "surprise_factor": surprise,
        }
    
    def _calculate_filtering_adjustment(
        self,
        surprise: float,
        connectivity: float,
        who_leads: str,
        is_ip: bool,
        street: str
    ) -> float:
        """
        決定過濾強度的乘數（0.5 - 1.0）
        
        較低的值 = 更激進的過濾（範圍縮減幅度更大）
        較高的值 = 更溫和的過濾（範圍保留更多）
        """
        # 基礎：驚訝度越高、過濾越強（乘數越低）
        if surprise > 0.7:
            surprise_factor = 0.5   # 非常意外 → 激進過濾
        elif surprise > 0.4:
            surprise_factor = 0.7   # 有點意外
        elif surprise > 0.1:
            surprise_factor = 0.85  # 稍微意外
        else:
            surprise_factor = 1.0   # 很合理 → 溫和過濾
        
        # 連結度修飾：
        # 高連結度牌面 → 行動信息密度高 → 更激進過濾
        # 低連結度牌面 → 行動信息密度低 → 更溫和過濾
        connectivity_factor = 0.9 - (connectivity * 0.3)  # range: 0.6 - 0.9
        
        # 領先修飾：
        if who_leads == "Hero":
            lead_factor = 1.0  # 我領先，行動信息更明確 → 不修改
        else:
            lead_factor = 0.9  # 對手領先，有更多選擇 → 溫和一些
        
        # 位置修飾：
        position_factor = 1.0 if is_ip else 0.95  # OOP slightly better filtering
        
        # 街道修飾：
        street_factor = {
            "flop": 0.95,      # Flop 信息多但選項仍多 → 稍微激進
            "turn": 0.90,      # Turn 新牌，信息精準 → 激進
            "river": 0.80,     # River 最後，行動很重要 → 非常激進
        }.get(street, 0.95)
        
        # 整合（相乘）
        adjustment = surprise_factor * connectivity_factor * lead_factor * position_factor * street_factor
        
        # 限制範圍
        adjustment = max(0.55, min(1.0, adjustment))
        
        return adjustment
    
    def _filter_range(
        self,
        villain_range: Dict[Any, float],
        action: str,
        adjustment: float,
        board_struct: Dict,
        ranges_comparison: Dict
    ) -> Dict[Any, float]:
        """
        基於行動和過濾強度，實際過濾範圍
        
        villain_range 可為 hand-code 或 combo-key 的權重字典。
        """
        new_range = {}
        
        # 首先計算所有手的新權重
        for hand_code, original_weight in villain_range.items():
            # 評估這隻手在這個牌面的牌力
            strength = StrengthAnalyzer.evaluate_hand_on_board(
                hand_code, board_struct["cards"]
            )
            
            # 根據行動和牌力決定倍數（0.05 - 1.5）
            multiplier = self._get_action_multiplier(strength, action)
            
            # 應用 adjustment（過濾強度）
            # adjustment < 1.0 表示更激進的過濾
            # 例如：adjustment=0.6 表示只保留60%的倍數
            adjusted_multiplier = multiplier * adjustment
            
            # 應用到權重（不是正規化後的百分比，直接使用原始權重）
            new_weight = original_weight * adjusted_multiplier
             
            # Combo 模式下常見權重為 0.3~1.0，門檻不能太高，否則中弱牌會被整片抹掉。
            if new_weight > 0.05:
                new_range[hand_code] = new_weight
        
        return new_range
    
    def _get_action_multiplier(self, strength: str, action: str) -> float:
        """
        根據手牌強度和行動，決定權重倍數（0.1 - 1.0）
        """
        multipliers = {
            "check": {
                "nuts": 0.15,    # Nuts check 很不尋常
                "strong": 0.40,  # 強手 check 不尋常
                "medium": 0.85,  # 中等手 check 合理
                "weak": 1.0,     # 弱手 check 完全正常
            },
            "bet": {
                "nuts": 1.0,     # Nuts bet 完全正常
                "strong": 0.95,  # 強手 bet 很正常
                "medium": 0.65,  # 中等手 bet 可能是 semi-bluff
                "weak": 0.20,    # 弱手 bet 很罕見
            },
            "raise": {
                "nuts": 1.0,
                "strong": 0.55,
                "medium": 0.10,
                "weak": 0.02,
            },
            "call": {
                "nuts": 0.25,
                "strong": 0.35,
                "medium": 0.90,
                "weak": 0.70,
            }
        }
        
        return multipliers.get(action, {}).get(strength, 1.0)
    
    def _generate_reasoning(
        self,
        street: str,
        action: str,
        surprise: float,
        reasonable_actions: Dict[str, float],
        adjustment: float,
        background: Optional[Dict] = None
    ) -> Dict:
        """
        生成可讀的推理說明
        """
        surprise_level = (
            "非常驚訝" if surprise > 0.7 else
            "有點驚訝" if surprise > 0.4 else
            "很合理" if surprise > 0.1 else
            "非常合理"
        )
        
        texture = self.board_struct["texture"]
        connectivity = self.board_struct["connectivity"]
        who_leads = self.ranges_comparison["who_leads"]
        villain_dist = self.ranges_comparison["villain_dist"]
        
        # 構造說明
        plain_english = (
            f"{street.upper()}: {self.board_struct['cards']} | "
            f"牌面: {texture} | 連結度: {connectivity:.2f}\n"
            f"對手範圍: {villain_dist['nuts_pct']:.1%} nuts, "
            f"{villain_dist['strong_pct']:.1%} strong, "
            f"{villain_dist['weak_pct']:.1%} weak\n"
            f"誰領先: {who_leads}\n"
            f"對手 {action}: {surprise_level} "
            f"(期望: check {reasonable_actions['check']:.1%}, "
            f"bet {reasonable_actions['bet']:.1%})\n"
            f"過濾強度: {adjustment:.2f}x "
            f"{'(激進)' if adjustment < 0.7 else '(溫和)' if adjustment > 0.9 else '(標準)'}"
        )
        
        return {
            "board_texture": texture,
            "connectivity": connectivity,
            "villain_distribution": {
                "nuts": f"{villain_dist['nuts_pct']:.1%}",
                "strong": f"{villain_dist['strong_pct']:.1%}",
                "medium": f"{villain_dist['medium_pct']:.1%}",
                "weak": f"{villain_dist['weak_pct']:.1%}",
            },
            "who_leads": who_leads,
            "surprise_level": surprise_level,
            "expected_actions": reasonable_actions,
            "actual_action": action,
            "filtering_strength": adjustment,
            "plain_english": plain_english,
            "background": background or {}
        }
