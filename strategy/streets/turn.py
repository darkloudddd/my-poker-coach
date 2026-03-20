from typing import Dict, Any

from ..utils import (
    format_output,
    weighted_choice,
    analyze_range_board_synergy,
    calculate_geometric_sizing,
)
from ..ranges.range_context import ensure_range_math_data
from ..gto import GTOAnalyzer
from .postflop_utils import (
    add_board_transition_reason,
    add_line_state_reason,
    add_previous_snapshot_reason,
    add_villain_range_insights,
    build_postflop_state,
    get_cached_advantage_data,
    hydrate_ctx_from_postflop_state,
    rebalance_bet_check_matrix,
)


def recommend_turn(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ensure_range_math_data(features, ctx, "turn")
    state = build_postflop_state(features, ctx, "turn")
    hydrate_ctx_from_postflop_state(ctx, state)

    add_villain_range_insights(ctx, features, min_board_cards=4, label="Turn")

    board_info = ctx.get("board_info", {})
    hero_pos = state["hero_pos"]
    villain_pos = state["villain_pos"]
    ctx["hero_synergy"] = analyze_range_board_synergy(hero_pos, board_info)
    ctx["villain_synergy"] = analyze_range_board_synergy(villain_pos, board_info)

    adv_data = get_cached_advantage_data(ctx)
    ctx["advantage_data"] = adv_data

    if state["facing_bet"]:
        return _handle_facing_bet(features, ctx, adv_data, hero_pos, villain_pos)

    return _handle_open_action(features, ctx, adv_data, state)


def _handle_open_action(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], state: Dict[str, Any]):
    hand_cat = ctx.get("effective_hand_category", "")
    nut_adv = adv_data.get("nut_advantage", 1.0)
    range_adv = adv_data.get("range_advantage", 1.0)
    transition = state.get("board_transition", {})
    has_scare = transition.get("has_scare", False)
    pot_bb = features.get("pot_bb", 1.0)
    is_3bet_pot = features.get("is_3bet_pot", False)

    board_info = ctx.get("board_info", {})
    archetypes = board_info.get("archetypes", [])
    is_wet = "Connected-Wet" in archetypes or board_info.get("connectedness_score", 0) >= 60
    is_monotone = "Monotone" in archetypes

    blocker_info = ctx.get("blocker_info", {})
    has_nut_blocker = blocker_info.get("has_nut_flush_blocker", False)
    has_straight_blocker = blocker_info.get("has_straight_blocker", False)
    has_trips_blocker = blocker_info.get("has_trips_blocker", False)

    reasons = []
    matrix = {"check": 1.0}
    sizing_ratio = 0.75
    line_state = str(state.get("line_state", "")).lower()
    barrel_spots = {"double_barrel_opportunity", "delayed_cbet_opportunity"}
    probe_spots = {"probe_after_missed_cbet", "probe_after_flop_barrel_check", "turn_probe_opportunity"}

    add_previous_snapshot_reason(reasons, state.get("previous_snapshot", {}), range_adv, nut_adv)
    add_board_transition_reason(reasons, transition)
    add_line_state_reason(reasons, line_state)

    v_summary = adv_data.get("villain_summary", {})
    v_nuts_freq = sum(v_summary.get(k, 0) for k in ["straight_flush", "quads", "full_house", "flush", "straight", "set"])
    v_draw_freq = v_summary.get("draw", 0) + v_summary.get("weak_draw", 0)
    v_air_freq = v_summary.get("air", 0)

    if v_nuts_freq < 0.05 and nut_adv > 1.2:
        reasons.append("偵測到對手範圍缺乏堅果 (Nuts < 5%)，屬於 Capped Range。")
    if v_draw_freq > 0.25:
        reasons.append(f"對手範圍含有高比例聽牌 ({v_draw_freq*100:.0f}%)，需注意保護或價值下注。")
    if v_air_freq > 0.4:
        reasons.append(f"對手範圍含有大量空氣牌 ({v_air_freq*100:.0f}%)。")

    has_initiative = state.get("initiative_owner") == "hero"
    checked_to_hero = state.get("checked_to_hero", False)
    checked_to_hero_assumed = state.get("checked_to_hero_assumed", False)
    can_attack_turn = has_initiative or checked_to_hero or line_state in barrel_spots or line_state in probe_spots

    if checked_to_hero_assumed:
        reasons.append("未提供本街對手行動，暫以 IP 被 check 到處理。")

    if can_attack_turn:
        should_barrel = False

        if nut_adv >= 1.1 or hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set"]:
            if is_monotone and hand_cat not in ["flush", "full_house", "quads", "straight_flush"]:
                matrix = {"bet": 0.3, "check": 0.7}
                reasons.append("單色面板 (Monotone) 對非同花強牌威脅極大，建議高頻過牌控池。")
            else:
                matrix = {"bet": 0.75, "check": 0.25}
                reasons.append("具有優勢，持續下注 (Double Barrel)。")
            should_barrel = True
        elif (has_scare or has_nut_blocker or has_straight_blocker) and range_adv >= 0.9:
            if is_wet and not (has_nut_blocker or has_straight_blocker):
                matrix = {"bet": 0.2, "check": 0.8}
                reasons.append("面板極度濕潤且無關鍵阻擋牌，減少轉牌詐唬頻率。")
            else:
                matrix = {"bet": 0.55, "check": 0.45}
                if has_nut_blocker:
                    reasons.append("持有堅果同花阻擋牌 (Nut Blocker)，進行平衡詐唬。")
                elif has_straight_blocker:
                    reasons.append("持有關鍵順子阻擋牌，減少對手強牌組合，適合進行第二發詐唬。")
                else:
                    reasons.append("轉牌驚悚牌有利於進攻方範圍，進行持續詐唬。")
            should_barrel = True
        elif "draw" in hand_cat and range_adv > 1.05:
            matrix = {"bet": 0.4, "check": 0.6}
            reasons.append("強聽牌進行第二發半詐唬。")
            should_barrel = True

        if should_barrel:
            spr = ctx.get("spr", 15.0)
            size_reason = "標準轉牌價值/詐唬下注。"

            if is_monotone:
                sizing_ratio = 0.33
                size_reason = "單色面板 (Monotone)，使用小注 (33%) 進行剝削與控池。"
            elif nut_adv >= 1.15 and 1.5 <= spr <= 6.0:
                sizing_ratio = calculate_geometric_sizing(spr, 2)
                size_reason = f"轉牌具備顯著堅果優勢 ({nut_adv:.2f}) 且 SPR ({spr:.1f}) 適中，採用幾何尺寸規劃兩街全壓。"
            elif nut_adv >= 1.3 and not has_scare:
                sizing_ratio = 1.25
                size_reason = "極端堅果優勢且轉牌為空白牌，使用超額下注施加最大極化壓力。"
            elif nut_adv >= 1.2 or has_scare or board_info.get("connectedness_score", 0) >= 60:
                sizing_ratio = 0.75
                size_reason = "面板動態或需保護優勢，使用 75% 標準大注。"
            elif is_3bet_pot and spr > 4.0:
                sizing_ratio = 0.33
                size_reason = "3-Bet 底池且 SPR 深，使用小注控制底池並保持頻率。"

            reasons.append(size_reason)

        if line_state == "delayed_cbet_opportunity" and "bet" in matrix:
            matrix = rebalance_bet_check_matrix(matrix, 0.12)
            sizing_ratio = min(sizing_ratio, 0.75)
            reasons.append("延遲 C-Bet 頻率通常低於標準第二發，尺寸也更收斂。")
        elif line_state in probe_spots and "bet" in matrix:
            matrix = rebalance_bet_check_matrix(matrix, 0.18)
            sizing_ratio = min(sizing_ratio, 0.66)
            reasons.append("Probe 節點以中小尺寸與較保守頻率施壓。")
        elif checked_to_hero and not has_initiative:
            matrix = rebalance_bet_check_matrix(matrix, 0.15)
            sizing_ratio = min(sizing_ratio, 0.75)
            reasons.append("對手先過牌但主動權不在 Hero，轉牌更多採用延遲 C-Bet / Probe。")
    else:
        if nut_adv >= 1.3:
            matrix = {"bet": 0.25, "check": 0.75}
            reasons.append("堅果優勢劇增，考慮領打 (Donk)。")
            sizing_ratio = 0.33
        elif has_trips_blocker and range_adv > 1.1:
            matrix = {"bet": 0.2, "check": 0.8}
            reasons.append("持有公牌對子阻擋牌，輕微領打試探。")
            sizing_ratio = 0.25
        else:
            reasons.append("OOP 且無主動權，預設過牌。")

    action = weighted_choice(matrix)
    amount = round(pot_bb * sizing_ratio, 1) if action == "bet" else 0
    final_ratio = sizing_ratio if action == "bet" else 0

    size_details = {
        "bet_ratio": sizing_ratio,
        "bet_amount": round(pot_bb * sizing_ratio, 1),
    }

    return format_output(
        "turn",
        action,
        final_ratio,
        amount,
        reasons,
        ctx,
        matrix,
        size_details=size_details,
    )


def _handle_facing_bet(features: Dict[str, Any], ctx: Dict[str, Any], adv_data: Dict[str, Any], hero_pos: str, villain_pos: str):
    pot_bb = features.get("pot_bb", 1.0)
    amount_to_call = features.get("amount_to_call", 0)

    mdf = GTOAnalyzer.calculate_mdf(pot_bb - amount_to_call, amount_to_call)
    reasons = [f"面對轉牌下注，MDF 為 {mdf*100:.1f}%。"]

    hand_cat = ctx.get("effective_hand_category", "")
    if hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set", "two_pair", "top_pair"]:
        matrix = {"call": 0.8, "raise": 0.1, "fold": 0.1}
        reasons.append("強牌傾向跟注或加注。")
    elif "draw" in hand_cat:
        if ctx.get("hero_synergy", 0) >= 30:
            matrix = {"call": 0.6, "raise": 0.4}
            reasons.append("強聽牌 (Strong Draw) 適合進行過牌加注 (Check-Raise) 半詐唬，平衡堅果範圍。")
        else:
            matrix = {"call": 0.8, "fold": 0.2}
            reasons.append("一般聽牌根據賠率跟注。")
    else:
        matrix = {"fold": 1.0}
        reasons.append("牌力不足，棄牌。")

    action = weighted_choice(matrix)
    return format_output("turn", action, 0.0, 0.0, reasons, ctx, matrix)
