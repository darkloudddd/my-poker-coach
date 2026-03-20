from __future__ import annotations

from typing import Any, Dict, List, Optional

from features.cards import analyze_board, get_rank_value

_STREET_ORDER = ("preflop", "flop", "turn", "river")
_AGGRESSIVE_ACTIONS = {"open", "bet", "raise"}


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_street_actions(features: Dict[str, Any], street: str) -> List[Dict[str, Any]]:
    actions = features.get("actions", {})
    street_key = str(street or "").lower()

    if isinstance(actions, dict):
        items = actions.get(street_key, [])
        return [item for item in items if isinstance(item, dict)]

    if isinstance(actions, list):
        return [
            item
            for item in actions
            if isinstance(item, dict) and str(item.get("street", "")).lower() == street_key
        ]

    return []


def get_last_action_by_player(features: Dict[str, Any], street: str, player: str) -> str:
    player_key = str(player or "").upper()
    if not player_key:
        return ""

    last_action = ""
    for item in get_street_actions(features, street):
        if str(item.get("player", "")).upper() != player_key:
            continue
        action = str(item.get("action", "")).lower()
        if action:
            last_action = action
    return last_action


def get_last_aggressor_player(features: Dict[str, Any], street: str) -> str:
    last_player = ""
    for item in get_street_actions(features, street):
        action = str(item.get("action", "")).lower()
        if action in _AGGRESSIVE_ACTIONS:
            player = str(item.get("player", "")).upper()
            if player:
                last_player = player
    return last_player


def get_previous_street(street: str) -> Optional[str]:
    street_key = str(street or "").lower()
    try:
        idx = _STREET_ORDER.index(street_key)
    except ValueError:
        return None
    if idx <= 0:
        return None
    return _STREET_ORDER[idx - 1]


def get_previous_snapshot(ctx: Dict[str, Any], street: str) -> Dict[str, Any]:
    previous_street = get_previous_street(street)
    snapshots = ctx.get("street_snapshots", {})
    if not previous_street or not isinstance(snapshots, dict):
        return {}
    snapshot = snapshots.get(previous_street)
    return snapshot if isinstance(snapshot, dict) else {}


def _infer_initiative_owner(
    features: Dict[str, Any],
    ctx: Dict[str, Any],
    street: str,
    hero_pos: str,
    villain_pos: str,
) -> str:
    street_key = str(street or "").lower()
    hero_key = str(hero_pos or "").upper()
    villain_key = str(villain_pos or "").upper()

    if street_key == "flop":
        tag = str(ctx.get("preflop_aggressor", "")).lower()
        return tag if tag in {"hero", "villain"} else ""

    previous_street = get_previous_street(street_key)
    if not previous_street:
        return ""

    last_aggressor = get_last_aggressor_player(features, previous_street)
    if last_aggressor == hero_key:
        return "hero"
    if last_aggressor == villain_key:
        return "villain"
    return ""


def get_cached_advantage_data(ctx: Dict[str, Any]) -> Dict[str, Any]:
    adv_data = ctx.get("advantage_data")
    if isinstance(adv_data, dict) and adv_data:
        return adv_data

    math_data = ctx.get("math_data", {})
    if not isinstance(math_data, dict):
        return {"range_advantage": 1.0, "realized_range_advantage": 1.0, "nut_advantage": 1.0}

    return {
        "range_advantage": _coerce_float(math_data.get("range_advantage"), 1.0),
        "realized_range_advantage": _coerce_float(
            math_data.get("realized_range_advantage", math_data.get("range_advantage")),
            _coerce_float(math_data.get("range_advantage"), 1.0),
        ),
        "nut_advantage": _coerce_float(math_data.get("nut_advantage"), 1.0),
        "hero_score": _coerce_float(math_data.get("hero_score"), 0.0),
        "villain_score": _coerce_float(math_data.get("villain_score"), 0.0),
        "hero_rf": _coerce_float(math_data.get("hero_rf"), 1.0),
        "villain_rf": _coerce_float(math_data.get("villain_rf"), 1.0),
        "hero_summary": math_data.get("hero_range_summary", {}) if isinstance(math_data.get("hero_range_summary"), dict) else {},
        "villain_summary": math_data.get("villain_range_summary", {}) if isinstance(math_data.get("villain_range_summary"), dict) else {},
    }


def rebalance_bet_check_matrix(matrix: Dict[str, float], bet_discount: float) -> Dict[str, float]:
    if "bet" not in matrix or bet_discount <= 0:
        return dict(matrix)

    adjusted = {key: float(value) for key, value in matrix.items()}
    current_bet = max(adjusted.get("bet", 0.0), 0.0)
    new_bet = max(0.05, current_bet - bet_discount)
    delta = current_bet - new_bet

    adjusted["bet"] = new_bet
    adjusted["check"] = max(adjusted.get("check", 0.0) + delta, 0.0)

    total = sum(max(value, 0.0) for value in adjusted.values())
    if total <= 0:
        return {"check": 1.0}

    return {key: max(value, 0.0) / total for key, value in adjusted.items()}


def add_previous_snapshot_reason(
    reasons: List[str],
    previous_snapshot: Dict[str, Any],
    current_range_adv: float,
    current_nut_adv: float,
) -> None:
    if not isinstance(previous_snapshot, dict) or not previous_snapshot:
        return

    previous_street = str(previous_snapshot.get("street", "前一街")).lower()
    prev_range_adv = _coerce_float(previous_snapshot.get("range_advantage"), current_range_adv)
    prev_nut_adv = _coerce_float(previous_snapshot.get("nut_advantage"), current_nut_adv)

    range_delta = current_range_adv - prev_range_adv
    nut_delta = current_nut_adv - prev_nut_adv

    if range_delta >= 0.15:
        reasons.append(f"相較 {previous_street}，這張牌更有利於 Hero 範圍延續施壓。")
    elif range_delta <= -0.15:
        reasons.append(f"相較 {previous_street}，Hero 的範圍優勢收窄，需降低裸壓力頻率。")

    if nut_delta >= 0.2:
        reasons.append(f"相較 {previous_street}，Hero 的堅果優勢提升。")
    elif nut_delta <= -0.2:
        reasons.append(f"相較 {previous_street}，對手保留更多極強牌，避免過度極化。")


def _extract_new_board_card(previous_board_cards: List[str], current_board_cards: List[str]) -> str:
    prev_cards = list(previous_board_cards or [])
    curr_cards = list(current_board_cards or [])
    if len(curr_cards) <= len(prev_cards):
        return ""
    if curr_cards[: len(prev_cards)] == prev_cards:
        return str(curr_cards[-1])
    return str(curr_cards[-1])


def build_board_transition(previous_snapshot: Dict[str, Any], current_board_cards: List[str]) -> Dict[str, Any]:
    prev_board_cards = list(previous_snapshot.get("board_cards", [])) if isinstance(previous_snapshot, dict) else []
    curr_board_cards = list(current_board_cards or [])
    if not prev_board_cards and len(curr_board_cards) in {4, 5}:
        prev_board_cards = curr_board_cards[:-1]
    new_card = _extract_new_board_card(prev_board_cards, curr_board_cards)

    if not prev_board_cards or not curr_board_cards or len(curr_board_cards) <= len(prev_board_cards):
        return {
            "new_card": new_card,
            "previous_board_cards": prev_board_cards,
            "current_board_cards": curr_board_cards,
            "has_scare": False,
            "scare_score": 0.0,
            "scare_tags": [],
        }

    previous_info = analyze_board(prev_board_cards)
    current_info = analyze_board(curr_board_cards)

    prev_high = int(previous_info.get("high_card_rank", 0) or 0)
    curr_high = int(current_info.get("high_card_rank", 0) or 0)
    new_rank = get_rank_value(new_card)

    prev_suit_max = max(previous_info.get("suit_counts", {}).values()) if previous_info.get("suit_counts") else 0
    curr_suit_max = max(current_info.get("suit_counts", {}).values()) if current_info.get("suit_counts") else 0
    prev_conn = float(previous_info.get("connectedness_score", 0) or 0)
    curr_conn = float(current_info.get("connectedness_score", 0) or 0)
    prev_draw_density = float(previous_info.get("draw_density", 0) or 0)
    curr_draw_density = float(current_info.get("draw_density", 0) or 0)

    is_overcard = new_rank > prev_high > 0
    is_broadway_overcard = is_overcard and new_rank >= 12
    turns_ace_high = new_rank == 14 and prev_high < 14
    completes_flush = curr_suit_max >= 3 and curr_suit_max > prev_suit_max
    straight_pressure = curr_conn >= 60 and curr_conn > prev_conn
    pairs_board = len(current_info.get("paired_ranks", [])) > len(previous_info.get("paired_ranks", []))
    becomes_more_dynamic = (
        bool(current_info.get("is_dynamic"))
        and not bool(previous_info.get("is_dynamic"))
    ) or curr_draw_density > prev_draw_density + 1

    scare_score = 0.0
    scare_tags: List[str] = []

    if is_overcard:
        scare_score += 1.0
        scare_tags.append("overcard")
    if is_broadway_overcard:
        scare_score += 0.5
        scare_tags.append("broadway")
    if turns_ace_high:
        scare_score += 0.5
        scare_tags.append("ace")
    if completes_flush:
        scare_score += 1.5
        scare_tags.append("flush")
    if straight_pressure:
        scare_score += 1.25
        scare_tags.append("straight")
    if pairs_board:
        scare_score += 0.75
        scare_tags.append("paired")
    if becomes_more_dynamic:
        scare_score += 0.5
        scare_tags.append("dynamic")

    has_scare = scare_score >= 1.25 or completes_flush or straight_pressure or turns_ace_high

    return {
        "new_card": new_card,
        "new_rank": new_rank,
        "previous_board_cards": prev_board_cards,
        "current_board_cards": curr_board_cards,
        "previous_high_card_rank": prev_high,
        "current_high_card_rank": curr_high,
        "is_overcard_to_previous": is_overcard,
        "is_broadway_overcard": is_broadway_overcard,
        "turns_ace_high": turns_ace_high,
        "completes_flush": completes_flush,
        "increases_straight_pressure": straight_pressure,
        "pairs_board": pairs_board,
        "becomes_more_dynamic": becomes_more_dynamic,
        "connectedness_delta": round(curr_conn - prev_conn, 2),
        "draw_density_delta": round(curr_draw_density - prev_draw_density, 2),
        "scare_score": round(scare_score, 2),
        "has_scare": has_scare,
        "scare_tags": scare_tags,
    }


def _role_for_player(player: str, hero_pos: str, villain_pos: str) -> str:
    player_key = str(player or "").upper()
    if player_key == str(hero_pos or "").upper():
        return "hero"
    if player_key == str(villain_pos or "").upper():
        return "villain"
    return ""


def summarize_street_sequence(
    features: Dict[str, Any],
    street: str,
    hero_pos: str,
    villain_pos: str,
    hero_is_ip: bool,
) -> Dict[str, Any]:
    actions = get_street_actions(features, street)
    summary: Dict[str, Any] = {
        "street": str(street or "").lower(),
        "actions": [],
        "first_action_role": "",
        "first_action": "",
        "last_action_role": "",
        "last_action": "",
        "first_aggressor_role": "",
        "first_aggressive_action": "",
        "last_aggressor_role": "",
        "last_aggressive_action": "",
        "hero_checked": False,
        "villain_checked": False,
        "hero_called": False,
        "villain_called": False,
        "hero_bet": False,
        "villain_bet": False,
        "hero_raised": False,
        "villain_raised": False,
        "hero_folded": False,
        "villain_folded": False,
        "hero_aggressive": False,
        "villain_aggressive": False,
        "check_through": False,
        "hero_check_back": False,
        "villain_check_back": False,
        "hero_bet_called": False,
        "villain_bet_called": False,
        "hero_bet_raised": False,
        "villain_bet_raised": False,
    }

    for item in actions:
        role = _role_for_player(item.get("player", ""), hero_pos, villain_pos)
        action = str(item.get("action", "")).lower()
        if role not in {"hero", "villain"} or not action:
            continue

        summary["actions"].append({"role": role, "action": action})
        if not summary["first_action_role"]:
            summary["first_action_role"] = role
            summary["first_action"] = action
        summary["last_action_role"] = role
        summary["last_action"] = action

        if action == "check":
            summary[f"{role}_checked"] = True
        elif action == "call":
            summary[f"{role}_called"] = True
        elif action == "bet":
            summary[f"{role}_bet"] = True
        elif action == "raise":
            summary[f"{role}_raised"] = True
        elif action == "fold":
            summary[f"{role}_folded"] = True

        if action in _AGGRESSIVE_ACTIONS:
            summary[f"{role}_aggressive"] = True
            if action in {"bet", "open"}:
                summary[f"{role}_bet"] = True
            if action == "raise":
                summary[f"{role}_raised"] = True
            if not summary["first_aggressor_role"]:
                summary["first_aggressor_role"] = role
                summary["first_aggressive_action"] = action
            summary["last_aggressor_role"] = role
            summary["last_aggressive_action"] = action

    summary["check_through"] = (
        not summary["first_aggressor_role"]
        and summary["hero_checked"]
        and summary["villain_checked"]
    )
    summary["hero_check_back"] = bool(hero_is_ip and summary["check_through"] and summary["hero_checked"])
    summary["villain_check_back"] = bool((not hero_is_ip) and summary["check_through"] and summary["villain_checked"])
    summary["hero_bet_called"] = bool(summary["first_aggressor_role"] == "hero" and summary["villain_called"] and not summary["villain_raised"])
    summary["villain_bet_called"] = bool(summary["first_aggressor_role"] == "villain" and summary["hero_called"] and not summary["hero_raised"])
    summary["hero_bet_raised"] = bool(summary["first_aggressor_role"] == "hero" and summary["villain_raised"])
    summary["villain_bet_raised"] = bool(summary["first_aggressor_role"] == "villain" and summary["hero_raised"])
    return summary


def classify_decision_line(
    ctx: Dict[str, Any],
    state: Dict[str, Any],
    current_sequence: Dict[str, Any],
    previous_sequence: Dict[str, Any],
    second_previous_sequence: Dict[str, Any],
) -> str:
    street = str(state.get("street", "")).lower()
    preflop_aggressor = str(ctx.get("preflop_aggressor", "")).lower()
    previous_snapshot = state.get("previous_snapshot", {})
    previous_line = str(previous_snapshot.get("line_state", "")).lower()
    facing_bet = bool(state.get("facing_bet", False))
    hero_has_acted = bool(state.get("hero_has_acted", False))
    checked_to_hero = bool(state.get("checked_to_hero", False))
    hero_first_to_act = bool(state.get("hero_first_to_act", False))

    if street == "flop":
        if facing_bet:
            if hero_has_acted and current_sequence.get("hero_bet_raised"):
                return "facing_raise_after_hero_bet"
            if preflop_aggressor == "hero":
                return "facing_donk_bet"
            return "facing_flop_bet"
        if preflop_aggressor == "hero" and (checked_to_hero or hero_first_to_act):
            return "cbet_opportunity"
        if checked_to_hero:
            return "stab_opportunity"
        if hero_first_to_act:
            return "defender_check_decision"
        return "flop_open_decision"

    if street == "turn":
        if facing_bet:
            if hero_has_acted and current_sequence.get("hero_bet_raised"):
                if previous_line == "double_barrel_opportunity":
                    return "facing_raise_after_double_barrel"
                if previous_line == "delayed_cbet_opportunity":
                    return "facing_raise_after_delayed_cbet"
                return "facing_raise_after_turn_bet"
            if previous_sequence.get("check_through") and preflop_aggressor == "hero":
                return "facing_probe_after_missed_cbet"
            if previous_sequence.get("villain_bet_called"):
                return "facing_second_barrel"
            if previous_sequence.get("hero_bet_called"):
                return "facing_turn_donk_after_flop_cbet"
            return "facing_turn_bet"

        if previous_sequence.get("hero_bet_called") and preflop_aggressor == "hero":
            return "double_barrel_opportunity"
        if previous_sequence.get("check_through") and preflop_aggressor == "hero":
            return "delayed_cbet_opportunity"
        if previous_sequence.get("check_through") and preflop_aggressor == "villain":
            return "probe_after_missed_cbet"
        if previous_sequence.get("villain_bet_called") and checked_to_hero:
            return "probe_after_flop_barrel_check"
        if checked_to_hero:
            return "turn_probe_opportunity"
        if hero_first_to_act:
            return "oop_turn_decision"
        return "turn_open_decision"

    if street == "river":
        if facing_bet:
            if hero_has_acted and current_sequence.get("hero_bet_raised"):
                if previous_line == "triple_barrel_opportunity":
                    return "facing_raise_after_triple_barrel"
                return "facing_raise_after_river_bet"
            if previous_sequence.get("villain_bet_called"):
                return "facing_river_barrel"
            return "facing_river_bet"

        if previous_sequence.get("hero_bet_called"):
            if (
                second_previous_sequence.get("hero_bet_called")
                and preflop_aggressor == "hero"
            ):
                return "triple_barrel_opportunity"
            if previous_line in {
                "double_barrel_opportunity",
                "delayed_cbet_opportunity",
                "turn_probe_opportunity",
            }:
                return "triple_barrel_opportunity"
            return "river_follow_through_opportunity"
        if previous_sequence.get("check_through") and preflop_aggressor == "hero":
            return "delayed_river_cbet_opportunity"
        if previous_sequence.get("check_through") and preflop_aggressor == "villain":
            return "probe_after_turn_checkthrough"
        if previous_sequence.get("villain_bet_called") and checked_to_hero:
            return "river_probe_after_barrel_shutdown"
        if checked_to_hero:
            return "river_probe_opportunity"
        if hero_first_to_act:
            return "oop_river_decision"
        return "river_open_decision"

    return ""


def hydrate_ctx_from_postflop_state(ctx: Dict[str, Any], state: Dict[str, Any]) -> None:
    if ctx is None or not isinstance(state, dict):
        return

    ctx["villain_action"] = state.get("villain_action", "")
    ctx["initiative_owner"] = state.get("initiative_owner", "")
    ctx["checked_to_hero"] = bool(state.get("checked_to_hero", False))
    ctx["hero_first_to_act"] = bool(state.get("hero_first_to_act", False))
    ctx["board_transition"] = state.get("board_transition", {})
    ctx["line_state"] = state.get("line_state", "")
    ctx["previous_street_sequence"] = state.get("previous_street_sequence", {})
    ctx["current_street_sequence"] = state.get("current_street_sequence", {})

    if str(state.get("street", "")).lower() == "turn":
        ctx["has_turn_scare"] = bool(state.get("board_transition", {}).get("has_scare", False))


def add_board_transition_reason(reasons: List[str], transition: Dict[str, Any]) -> None:
    if not isinstance(transition, dict) or not transition:
        return

    new_card = transition.get("new_card")
    if not new_card:
        return

    tags = transition.get("scare_tags", [])
    if transition.get("has_scare"):
        fragments = []
        if "ace" in tags:
            fragments.append("A 高張")
        elif "broadway" in tags:
            fragments.append("Broadway 高張")
        elif "overcard" in tags:
            fragments.append("高張")
        if "flush" in tags:
            fragments.append("同花完成壓力")
        if "straight" in tags:
            fragments.append("順子完成壓力")
        if "paired" in tags:
            fragments.append("公牌成對")
        if "dynamic" in tags and "同花完成壓力" not in fragments and "順子完成壓力" not in fragments:
            fragments.append("面板轉向動態")

        if fragments:
            reasons.append(f"{new_card} 帶來 {' / '.join(fragments)}，屬於高壓轉牌/河牌。")
    elif transition.get("becomes_more_dynamic"):
        reasons.append(f"{new_card} 讓面板比前一街更動態。")


def add_line_state_reason(reasons: List[str], line_state: str) -> None:
    label = str(line_state or "").lower()
    if not label:
        return

    reason_map = {
        "cbet_opportunity": "此節點是標準 C-Bet 機會。",
        "stab_opportunity": "對手在 flop 放棄主動權，這是 stab 節點。",
        "double_barrel_opportunity": "前一街已成功延續壓力，這是標準第二發節點。",
        "delayed_cbet_opportunity": "前一街錯過 C-Bet，這是延遲持續下注節點。",
        "probe_after_missed_cbet": "進攻方前一街放棄 C-Bet，這是 turn probe 節點。",
        "probe_after_flop_barrel_check": "對手 flop 下注後在 turn 減速，這是 probe 節點。",
        "triple_barrel_opportunity": "前兩街壓力已建立，這是第三發極化節點。",
        "river_follow_through_opportunity": "前一街價值/壓力線成功延續，river 可考慮跟進。",
        "delayed_river_cbet_opportunity": "前兩街未主動下注，river 屬於延遲壓力節點。",
        "probe_after_turn_checkthrough": "雙方 turn 都未主動出手，river 是 probe 節點。",
        "river_probe_after_barrel_shutdown": "對手 turn 施壓後在 river 降速，這是 probe 節點。",
    }
    reason = reason_map.get(label)
    if reason:
        reasons.append(reason)


def add_villain_range_insights(
    ctx: Dict[str, Any],
    features: Dict[str, Any],
    min_board_cards: int,
    label: str = "",
) -> None:
    try:
        from ..ranges.range_insights import RangeInsights
        from ..ranges.range_utils import apply_action_history_to_ranges

        board_cards = features.get("board_cards", [])
        if not board_cards or len(board_cards) < min_board_cards:
            return

        _, villain_range = apply_action_history_to_ranges(features, board_cards)
        villain_insights = RangeInsights.analyze_villain_range(
            villain_range,
            board_cards,
            features.get("actions", {}),
        )
        ctx["villain_range_insights"] = villain_insights

        reasoning = ctx.get("reasoning")
        if not reasoning:
            ctx["reasoning"] = []
        elif not isinstance(reasoning, list):
            ctx["reasoning"] = [str(reasoning)]

        insight_text = villain_insights.get("key_insight", "")
        if insight_text:
            prefix = f"對手範圍({label})分析" if label else "對手範圍分析"
            ctx["reasoning"].append(f"{prefix}: {insight_text}")

        likely_hands = villain_insights.get("most_likely_hands", [])
        if likely_hands:
            ctx["reasoning"].append(f"最可能的牌: {', '.join(likely_hands)}")
    except Exception:
        pass


def build_postflop_state(features: Dict[str, Any], ctx: Dict[str, Any], street: str) -> Dict[str, Any]:
    street_key = str(street or "").lower()
    hero_pos = str(features.get("hero_position") or features.get("hero_pos") or ctx.get("hero_position") or "").upper()
    villain_pos = str(features.get("villain_position") or features.get("villain_pos") or ctx.get("villain_position") or "").upper()
    hero_is_ip = bool(features.get("hero_is_ip", False))
    street_actions = get_street_actions(features, street_key)
    villain_action = get_last_action_by_player(features, street_key, villain_pos)
    if not villain_action:
        villain_action = str(features.get("villain_action", "") or "").lower().strip()

    hero_action = get_last_action_by_player(features, street_key, hero_pos)
    amount_to_call = _coerce_float(features.get("amount_to_call"), 0.0)
    villain_has_acted = bool(villain_action)
    hero_has_acted = bool(hero_action)

    assumed_checked_to_hero = (
        hero_is_ip
        and not street_actions
        and not villain_has_acted
        and not hero_has_acted
        and amount_to_call <= 0
    )
    checked_to_hero = amount_to_call <= 0 and (villain_action == "check" or assumed_checked_to_hero)
    hero_first_to_act = (not hero_is_ip) and not street_actions
    initiative_owner = _infer_initiative_owner(features, ctx, street_key, hero_pos, villain_pos)
    previous_snapshot = get_previous_snapshot(ctx, street_key)
    board_transition = build_board_transition(previous_snapshot, features.get("board_cards", []))
    current_street_sequence = summarize_street_sequence(features, street_key, hero_pos, villain_pos, hero_is_ip)
    previous_street = get_previous_street(street_key)
    previous_street_sequence = (
        summarize_street_sequence(features, previous_street, hero_pos, villain_pos, hero_is_ip)
        if previous_street in {"flop", "turn", "river"}
        else {}
    )
    second_previous_street = get_previous_street(previous_street) if previous_street else None
    second_previous_street_sequence = (
        summarize_street_sequence(features, second_previous_street, hero_pos, villain_pos, hero_is_ip)
        if second_previous_street in {"flop", "turn", "river"}
        else {}
    )
    line_state = classify_decision_line(ctx, {
        "street": street_key,
        "facing_bet": amount_to_call > 0 or villain_action in {"bet", "raise"},
        "hero_has_acted": hero_has_acted,
        "checked_to_hero": checked_to_hero,
        "hero_first_to_act": hero_first_to_act,
        "previous_snapshot": previous_snapshot,
    }, current_street_sequence, previous_street_sequence, second_previous_street_sequence)

    return {
        "street": street_key,
        "hero_pos": hero_pos,
        "villain_pos": villain_pos,
        "hero_is_ip": hero_is_ip,
        "street_actions": street_actions,
        "hero_action": hero_action,
        "villain_action": villain_action,
        "villain_has_acted": villain_has_acted,
        "hero_has_acted": hero_has_acted,
        "amount_to_call": amount_to_call,
        "facing_bet": amount_to_call > 0 or villain_action in {"bet", "raise"},
        "checked_to_hero": checked_to_hero,
        "checked_to_hero_assumed": assumed_checked_to_hero,
        "hero_first_to_act": hero_first_to_act,
        "initiative_owner": initiative_owner,
        "previous_snapshot": previous_snapshot,
        "previous_street_sequence": previous_street_sequence,
        "second_previous_street_sequence": second_previous_street_sequence,
        "current_street_sequence": current_street_sequence,
        "line_state": line_state,
        "board_transition": board_transition,
    }
