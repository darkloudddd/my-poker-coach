"""strategy package API 聚合入口"""

# 核心策略引擎
from .engine import recommend_action

# GTO 與分析工具
from .gto import GTOAnalyzer, format_output, weighted_choice

# 底池與下注相關計算
from .pot import compute_pot_bb, compute_amount_to_call

# 常用工具與靜態函式
from .utils import (
    analyze_situation,
    effective_hand_category,
    analyze_range_board_synergy,
    calculate_realization_factor,
    calculate_geometric_sizing,
    normalize_hand_code_preflop,
)

# 牌組與範圍
from .ranges import RANGE_ANALYZER, RFI_RANGES, FACING_OPEN, FACING_3BET

# 推理子系統（可選）
from .reasoning import ContextualReasoner, StrengthAnalyzer, ActionRationality, BoardStructure

# 街道策略
from .streets import recommend_preflop, recommend_flop, recommend_turn, recommend_river

__all__ = [
    "recommend_action",
    "GTOAnalyzer",
    "format_output",
    "weighted_choice",
    "compute_pot_bb",
    "compute_amount_to_call",
    "analyze_situation",
    "effective_hand_category",
    "analyze_range_board_synergy",
    "calculate_realization_factor",
    "calculate_geometric_sizing",
    "normalize_hand_code_preflop",
    "RANGE_ANALYZER",
    "RFI_RANGES",
    "FACING_OPEN",
    "FACING_3BET",
    "ContextualReasoner",
    "StrengthAnalyzer",
    "ActionRationality",
    "BoardStructure",
    "recommend_preflop",
    "recommend_flop",
    "recommend_turn",
    "recommend_river",
]
