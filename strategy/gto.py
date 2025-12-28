# strategy/gto.py
from typing import Dict, Any, List, Tuple, Optional
from core.config import RANGE_WEIGHTS, ADVANTAGE_THRESHOLD_AGGRESSIVE, ADVANTAGE_THRESHOLD_DEFENSIVE
import random

class GTOAnalyzer:
    """
    負責所有與 Range 優勢、分數計算相關的數學邏輯。
    """
    
    @staticmethod
    def calculate_range_score(range_summary: Dict[str, float]) -> float:
        """根據 Range 分佈計算一個綜合戰力分數"""
        if not range_summary: return 0.0
        
        total = float(range_summary.get("total_active_combos", 0.0))
        if total <= 1e-9: return 0.0

        # 提取各類別佔比
        def _get_ratio(key): return float(range_summary.get(key, 0.0)) / total
        
        nut = _get_ratio("nut_made_hands")
        strong = _get_ratio("strong_made_hands")
        medium = _get_ratio("medium_made_hands")
        weak = _get_ratio("weak_made_hands")
        s_draw = _get_ratio("strong_draws")
        w_draw = _get_ratio("weak_draws")
        air = _get_ratio("air")

        score = 0.0
        score += nut * RANGE_WEIGHTS["nut"]
        score += strong * RANGE_WEIGHTS["strong"]
        score += medium * RANGE_WEIGHTS["medium"]
        score += weak * RANGE_WEIGHTS["weak"]
        score += s_draw * RANGE_WEIGHTS["strong_draw"]
        score += w_draw * RANGE_WEIGHTS["weak_draw"]
        score -= air * RANGE_WEIGHTS["air"] # 空氣牌扣分

        return max(0.0, score)

    @staticmethod
    def calculate_advantage_ratio(hero_summary: Dict, villain_summary: Dict) -> float:
        h_score = GTOAnalyzer.calculate_range_score(hero_summary)
        v_score = GTOAnalyzer.calculate_range_score(villain_summary)
        
        eps = 1e-6
        ratio = h_score / (v_score + eps)
        # 限制範圍避免極端值
        return max(0.4, min(2.5, ratio))

    @staticmethod
    def apply_advantage_adjustment(
        base_matrix: Dict[str, float], 
        adv_ratio: float, 
        is_ip: bool,
        street: str
    ) -> Tuple[Dict[str, float], List[str]]:
        """
        全域 GTO 調整層：根據優勢比率調整頻率
        這是原本重複寫在 flop/turn/river 的邏輯
        """
        new_matrix = base_matrix.copy()
        reasons = []
        
        # 1. 顯著優勢調整 (Aggressive)
        threshold = ADVANTAGE_THRESHOLD_AGGRESSIVE
        # River 的標準可以稍微高一點
        if street == "river": threshold += 0.05 

        if adv_ratio > threshold and is_ip:
            if "bet" not in new_matrix:
                # 本來是 Check，解鎖詐唬
                new_matrix["bet"] = 0.35
                new_matrix["check"] = 0.65
                reasons.append(f"Range Advantage ({adv_ratio:.2f}) -> Unlock GTO Bluff.")
            else:
                # 本來有 Bet，增加頻率
                boost = 0.2
                current_bet = new_matrix["bet"]
                new_bet = min(0.95, current_bet + boost)
                new_matrix["bet"] = new_bet
                if "check" in new_matrix: new_matrix["check"] = 1.0 - new_bet
                reasons.append(f"Range Advantage ({adv_ratio:.2f}) -> Frequency Boost (+{boost*100}%).")

        # 2. 劣勢調整 (Defensive)
        elif adv_ratio < ADVANTAGE_THRESHOLD_DEFENSIVE:
            if "bet" in new_matrix and new_matrix["bet"] > 0.3:
                reduce = 0.2
                new_bet = max(0.05, new_matrix["bet"] - reduce)
                new_matrix["bet"] = new_bet
                if "check" in new_matrix: new_matrix["check"] = 1.0 - new_bet
                reasons.append(f"Range Disadvantage ({adv_ratio:.2f}) -> Frequency Reduce.")

        return new_matrix, reasons

    @staticmethod
    def calculate_mdf(pot: float, bet: float) -> float:
        """
        Minimum Defense Frequency.
        MDF = Pot / (Pot + Bet)
        """
        if pot + bet <= 0:
            return 1.0
        return pot / (pot + bet)

    @staticmethod
    def calculate_bluff_ratio(bet_ratio: float) -> float:
        """
        GTO Bluff Ratio for a given bet size (as ratio of pot).
        Alpha = Size / (1 + Size)
        Bluff Ratio in betting range = Alpha / (1 + Alpha)
        Wait, standard GTO: 
        Opponent needs Alpha equity to call.
        We should have Alpha proportion of bluffs in our range if opponent is indifferent.
        Example 1 pot: Alpha = 0.5. We need 1 bluff for 2 value (33% bluff in range).
        Formula: Bluff_in_range = bet_ratio / (1 + 2 * bet_ratio)
        Actually common shortcut: 
        1/3 pot -> 20% bluff
        1/2 pot -> 25%
        3/4 pot -> 30%
        1 pot -> 33% 
        Formula for bluffs in betting range: B = ratio / (1 + 2*ratio)
        """
        if bet_ratio <= 0:
            return 0.0
        return bet_ratio / (1 + 2 * bet_ratio)

def weighted_choice(action_probs: Dict[str, float]) -> str:
    """根據機率字典選擇動作"""
    actions = list(action_probs.keys())
    # probs = list(action_probs.values())
    # [Mod] 用戶希望 "建議行動" 固定為最高頻率者，而非隨機抽樣
    # return random.choices(actions, weights=probs, k=1)[0]
    if not action_probs: return "check"
    return max(action_probs, key=action_probs.get)


class DecisionMaker:
    """
    Backward-compatible wrapper around GTOAnalyzer for callers expecting this name.
    """
    def calculate_range_score(self, s: Dict[str, float]) -> float:
        return GTOAnalyzer.calculate_range_score(s)

    def analyze_advantage(self, hero_stats: Dict[str, float], villain_stats: Dict[str, float]) -> float:
        return GTOAnalyzer.calculate_advantage_ratio(hero_stats, villain_stats)

def format_output(
    street: str,
    action: str,
    sizing_ratio: float,
    amount: Optional[float],
    reasons: List[str],
    ctx: Dict[str, Any],
    matrix: Dict[str, float],
    size_details: Optional[Dict[str, float]] = None,
    math_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    統一輸出格式，包含詳細的 'suggestion' (機率字串) 與 'stats' (數學數據)
    """
    # 數值正規化，避免 None/字串導致後續比較出錯
    try:
        amount_val = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        amount_val = 0.0
    try:
        sizing_val = float(sizing_ratio) if sizing_ratio is not None else 0.0
    except (TypeError, ValueError):
        sizing_val = 0.0

    # 1. 數據初始化
    if math_data is None:
        math_data = ctx.get("math_data", {})

    adv_ratio = float(math_data.get("ratio", math_data.get("adv_ratio", 0.0)))
    
    # 2. 生成建議字串 (Suggestion String)
    # 範例: "RAISE 4.2bb (40%) / CALL (60%)"
    suggestion_str = action.upper()
    if matrix:
        prob_parts = []
        sorted_probs = sorted(matrix.items(), key=lambda x: x[1], reverse=True)
        
        for act, p in sorted_probs:
            if p > 0.01:
                act_title = act.title()
                # 如果是當前選中的動作，且有具體金額，顯示金額
                if act.lower() == action.lower():
                    if amount_val > 0:
                        if act.lower() == "raise":
                            act_title += f" to {amount_val:.1f}bb"
                        elif act.lower() != "check":
                            act_title += f" {amount_val:.1f}bb"
                    elif sizing_val > 0 and act.lower() != "check":
                        act_title += f" {sizing_val*100:.0f}%"
                prob_parts.append(f"{act_title} {int(p*100)}%")
        
        if prob_parts:
            suggestion_str = " / ".join(prob_parts)

    # 3. 生成情境數據字串 (Stats String)
    # 範例: "底池 6.0bb (4.5+1.5) / SPR 17.5 / 賠率 20%"
    stats_parts = []
    
    curr_pot = float(math_data.get("current_pot", 0.0))
    base_pot = float(math_data.get("base_pot", 0.0))
    to_call = float(math_data.get("amount_to_call", 0.0))
    
    # 顯示底池細節
    if to_call > 0 and curr_pot >= base_pot + to_call:
        stats_parts.append(f"底池 {curr_pot:.1f}bb ({base_pot} + {to_call})")
    else:
        display_pot = curr_pot if curr_pot > 0 else float(ctx.get("pot_bb", 0))
        stats_parts.append(f"底池 {display_pot:.1f}bb")

    # 顯示 SPR
    spr_val = float(math_data.get("spr", ctx.get("spr", 0.0)))
    stats_parts.append(f"SPR {spr_val:.1f}")

    # 顯示賠率
    if to_call > 0:
        odds = float(math_data.get("pot_odds", ctx.get("pot_odds", 0.0)))
        if odds > 0:
            odds_ratio = (1 / odds) - 1
            stats_parts.append(f"需跟注 {to_call:.1f}bb")
            stats_parts.append(f"賠率 {odds*100:.1f}% (1:{odds_ratio:.1f})")

    stats_str = " / ".join(stats_parts)
    hand_cat = ctx.get("hand_category", "NA")
    kicker = ctx.get("kicker_strength", "NA")

    action_desc = action.upper()
    if amount_val > 0:
        if action.lower() == "raise":
            action_desc = f"RAISE to {amount_val:.1f}bb"
        else:
            action_desc = f"{action.upper()} {amount_val:.1f}bb"

    # 4. 戰略視覺指標 (Strategic Radar)
    board_info = ctx.get("board_info", {})
    danger = board_info.get("danger_level", "safe").upper()
    danger_icons = {"SAFE": "🟢 SAFE", "DRY": "🟢 DRY", "DYNAMIC": "🟡 DYNAMIC", "WET": "🔴 WET", "DANGEROUS": "💀 DANGEROUS"}
    danger_meter = danger_icons.get(danger, f"⚪ {danger}")
    
    h_syn = ctx.get("hero_synergy", 0)
    v_syn = ctx.get("villain_synergy", 0)
    synergy_str = f"Hero {'+' if h_syn>=0 else ''}{h_syn} / Villain {'+' if v_syn>=0 else ''}{v_syn}"
    
    adv_data = ctx.get("advantage_data", {})
    r_adv = adv_data.get("range_advantage", 1.0)
    real_adv = adv_data.get("realized_range_advantage", r_adv)
    n_adv = adv_data.get("nut_advantage", 1.0)
    
    h_rf = adv_data.get("hero_rf", 1.0)
    v_rf = adv_data.get("villain_rf", 1.0)
    
    adv_summary = f"Range: {r_adv:.2f} | Realized: {real_adv:.2f} | Nut: {n_adv:.2f}"
    rf_balance = f"Realization: H {h_rf:.2f} / V {v_rf:.2f}"

    # 5. 構建返回物件
    res: Dict[str, Any] = {
        "street": street,
        "recommended_action": action,
        "action_desc": action_desc,
        "amount": amount_val,
        "sizing_ratio": sizing_val,
        "strategy_matrix": matrix,
        "reasons": reasons,
        "reasoning": reasons,  # 兼容舊欄位
        "suggestion": suggestion_str,
        "stats": stats_str,
        "hand_info": f"{hand_cat} ({kicker})",
        "strategic_radar": {
            "danger_meter": danger_meter,
            "synergy_balance": synergy_str,
            "advantage_summary": adv_summary,
            "realization_balance": rf_balance
        },
        "math_data": math_data or {},
        "context": {
             "hand_category": hand_cat,
             "kicker_strength": kicker,
             "spr": spr_val,
             "adv_ratio": adv_ratio,
             "advantage_data": adv_data
        }
    }
    if size_details: res["size_details"] = size_details
    return res
