# core/config.py
"""
全域設定檔：定義撲克基礎常數與參數
"""

# 撲克基礎
RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}  # 2=2, ..., A=14

# 位置順序 (6-Max)
POSITION_ORDER = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

# GTO 權重設定 (用於 Range Score 計算)
# 這裡集中管理，以後想調整 Bot 個性改這裡即可
RANGE_WEIGHTS = {
    "nut": 4.0,      # 堅果牌
    "strong": 2.0,   # 強成牌
    "medium": 1.0,   # 中等成牌
    "weak": 0.35,    # 弱成牌 (抓雞/過牌)
    "strong_draw": 0.8, # 強聽牌
    "weak_draw": 0.2,   # 弱聽牌
    "air": 0.15,        # 空氣牌 (負分項通常在邏輯中處理，這裡給個基礎值)
}

# 調整閾值
ADVANTAGE_THRESHOLD_AGGRESSIVE = 1.25 # 優勢大於此值 -> 解鎖詐唬
ADVANTAGE_THRESHOLD_DEFENSIVE = 0.8   # 優勢小於此值 -> 保守