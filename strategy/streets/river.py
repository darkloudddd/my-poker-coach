from typing import Dict, Any

from ..utils import format_output, weighted_choice, analyze_range_board_synergy
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


def recommend_river(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    ctx = ensure_range_math_data(features, ctx, "river")
    state = build_postflop_state(features, ctx, "river")
    hydrate_ctx_from_postflop_state(ctx, state)

    add_villain_range_insights(ctx, features, min_board_cards=5, label="River")

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
    pot_bb = features.get("pot_bb", 1.0)

    board_info = ctx.get("board_info", {})
    archetypes = board_info.get("archetypes", [])
    is_monotone = "Monotone" in archetypes

    blocker_info = ctx.get("blocker_info", {})
    has_nut_blocker = blocker_info.get("has_nut_flush_blocker", False)
    has_straight_blocker = blocker_info.get("has_straight_blocker", False)

    reasons = []
    matrix = {"check": 1.0}
    line_state = str(state.get("line_state", "")).lower()
    barrel_spots = {"triple_barrel_opportunity", "river_follow_through_opportunity", "delayed_river_cbet_opportunity"}
    probe_spots = {"probe_after_turn_checkthrough", "river_probe_after_barrel_shutdown", "river_probe_opportunity"}

    add_previous_snapshot_reason(reasons, state.get("previous_snapshot", {}), range_adv, nut_adv)
    add_board_transition_reason(reasons, state.get("board_transition", {}))
    add_line_state_reason(reasons, line_state)

    v_summary = adv_data.get("villain_summary", {})
    v_nuts_freq = sum(v_summary.get(k, 0) for k in ["straight_flush", "quads", "full_house", "flush", "straight", "set"])

    if v_nuts_freq < 0.03 and nut_adv > 1.2:
        reasons.append("對手河牌範圍極度缺乏堅果 (Capped)，極化下注效用最大化。")
    if nut_adv >= 1.2:
        reasons.append(f"具有顯著堅果優勢 ({nut_adv:.2f})。")

    sizing_ratio = 0.75
    size_desc = "標準下注"

    if nut_adv >= 1.4:
        sizing_ratio = 2.0
        size_desc = "雙倍底池下注 (200% Pot)"
    elif nut_adv >= 1.25:
        sizing_ratio = 1.5
        size_desc = "超額下注 (150% Pot)"
    elif nut_adv >= 1.1:
        sizing_ratio = 1.0
        size_desc = "滿池下注 (Pot Bet)"
    elif hand_cat in ["two_pair", "straight", "flush", "set"] and nut_adv < 1.2:
        sizing_ratio = 0.5
        size_desc = "半池下注 (Half Pot)"
    elif hand_cat in ["top_pair", "middle_pair"]:
        sizing_ratio = 0.33
        size_desc = "薄價值下注 (Thin Value)"

    has_initiative = state.get("initiative_owner") == "hero"
    checked_to_hero = state.get("checked_to_hero", False)
    checked_to_hero_assumed = state.get("checked_to_hero_assumed", False)
    can_attack_river = has_initiative or checked_to_hero or line_state in barrel_spots or line_state in probe_spots

    if checked_to_hero_assumed:
        reasons.append("未提供本街對手行動，暫以 IP 被 check 到處理。")

    if state.get("hero_first_to_act") and not has_initiative and not can_attack_river:
        if nut_adv >= 1.25 or hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight"]:
            matrix = {"bet": 0.3, "check": 0.7}
            sizing_ratio = min(sizing_ratio, 0.75)
            reasons.append("缺乏主動權但持有強極化區，可低頻領打爭取最大價值。")
        elif range_adv >= 0.95 and (has_nut_blocker or has_straight_blocker):
            matrix = {"bet": 0.18, "check": 0.82}
            sizing_ratio = min(sizing_ratio, 0.5)
            reasons.append("缺乏主動權時僅保留少量阻擋牌領打。")
        else:
            reasons.append("OOP 且無主動權，河牌預設過牌。")
    else:
        if hand_cat in ["straight_flush", "quads"] or (hand_cat == "full_house" and nut_adv > 1.3):
            matrix = {"bet": 0.95, "check": 0.05}
            reasons.append(f"持有極端堅果 ({hand_cat})，使用 {size_desc}。")
        elif hand_cat in ["full_house", "flush"]:
            matrix = {"bet": 0.85, "check": 0.15}
            reasons.append(f"持有強成牌，進行 {size_desc}。")
        elif hand_cat in ["straight", "set", "two_pair"]:
            if is_monotone:
                matrix = {"check": 0.8, "bet": 0.2}
                reasons.append("單色面板 (Monotone) 對非同花強牌威脅大，採取保守過牌。")
            else:
                matrix = {"bet": 0.7, "check": 0.3}
                reasons.append(f"強成牌進行 {size_desc}。")
        elif hand_cat == "top_pair":
            if is_monotone:
                matrix = {"check": 1.0}
                reasons.append("單色面板對頂對威脅大，過牌控池。")
            else:
                matrix = {"bet": 0.4, "check": 0.6}
                sizing_ratio = 0.33
                reasons.append("頂對尋求薄價值 (Thin Value)，使用小尺寸。")
        elif range_adv >= 0.9 and (has_nut_blocker or has_straight_blocker):
            bluff_ratio = GTOAnalyzer.calculate_bluff_ratio(sizing_ratio)
            matrix = {"bet": bluff_ratio, "check": 1.0 - bluff_ratio}

            if has_nut_blocker:
                reasons.append(f"持有堅果同花阻擋牌，配合 {size_desc} 進行 GTO 平衡詐唬 ({bluff_ratio*100:.0f}%)。")
            else:
                reasons.append(f"持有關鍵順子阻擋牌，配合 {size_desc} 進行 GTO 平衡詐唬 ({bluff_ratio*100:.0f}%)。")
        else:
            reasons.append("牌力不足且無關鍵阻擋牌，採取過牌。")

        if line_state == "delayed_river_cbet_opportunity" and "bet" in matrix:
            matrix = rebalance_bet_check_matrix(matrix, 0.15)
            sizing_ratio = min(sizing_ratio, 1.0)
            reasons.append("延遲到 river 的壓力線需要更保守的 bluff 比例。")
        elif line_state in probe_spots and "bet" in matrix:
            matrix = rebalance_bet_check_matrix(matrix, 0.2)
            sizing_ratio = min(sizing_ratio, 0.75)
            reasons.append("River probe 以較小尺寸與更乾淨的極化區為主。")
        elif checked_to_hero and not has_initiative:
            matrix = rebalance_bet_check_matrix(matrix, 0.2)
            sizing_ratio = min(sizing_ratio, 1.0)
            reasons.append("對手已過牌，但此線屬於延遲施壓而非主動極化，降低裸 bluff 比例。")

    if sizing_ratio == 1.5 and "Overbet" not in reasons[-1]:
        reasons.append("具備極端堅果優勢，使用 Overbet (150%) 進行極致極化施壓。")
    elif sizing_ratio == 1.0 and "Pot Bet" not in reasons[-1]:
        reasons.append("具備堅果優勢，使用滿池下注進行極化施壓。")

    action = weighted_choice(matrix)
    amount = round(pot_bb * sizing_ratio, 1) if action == "bet" else 0
    final_ratio = sizing_ratio if action == "bet" else 0

    size_details = {
        "bet_ratio": sizing_ratio,
        "bet_amount": round(pot_bb * sizing_ratio, 1),
    }

    return format_output(
        "river",
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
    nut_adv = adv_data.get("nut_advantage", 1.0)

    mdf = GTOAnalyzer.calculate_mdf(pot_bb - amount_to_call, amount_to_call)
    reasons = [f"面對河牌下注，MDF 為 {mdf*100:.1f}%。"]

    blocker_info = ctx.get("blocker_info", {})
    has_nut_blkr = blocker_info.get("has_nut_flush_blocker", False)

    hand_cat = ctx.get("effective_hand_category", "")
    if hand_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set", "two_pair"]:
        matrix = {"call": 0.9, "raise": 0.1}
        reasons.append("強牌防守。")
    elif hand_cat == "top_pair":
        matrix = {"call": 0.7, "fold": 0.3}
        reasons.append("頂對作為抓詐牌 (Bluff Catcher) 跟注。")
    elif has_nut_blkr and nut_adv > 0.9:
        matrix = {"call": 0.4, "fold": 0.6}
        reasons.append("持有堅果同花阻擋牌，混合跟注攔截詐唬。")
    else:
        matrix = {"fold": 1.0}
        reasons.append("牌力不足，棄牌。")

    action = weighted_choice(matrix)
    return format_output("river", action, 0.0, 0.0, reasons, ctx, matrix)
