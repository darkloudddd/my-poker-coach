from typing import List, Dict, Any, Tuple
from .range import RANGE_ANALYZER, get_preflop_range
from strategy.reasoning.contextual_reasoner import ContextualReasoner

# 已移除舊系統切換，永遠使用 ContextualReasoner (新系統)
DEBUG_RANGE_FILTERING = False

_FOUR_BET_AGGRESSOR_RANGE = {
    "AA": 1.0,
    "KK": 1.0,
    "QQ": 1.0,
    "JJ": 0.75,
    "AKs": 1.0,
    "AKo": 0.8,
    "AQs": 0.4,
}

_FOUR_BET_CALLER_RANGE = {
    "AA": 1.0,
    "KK": 1.0,
    "QQ": 0.85,
    "JJ": 0.65,
    "TT": 0.35,
    "AKs": 0.8,
    "AQs": 0.45,
}

_PREMIUM_HANDS = {"AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs"}


def _flatten(range_data: Dict[str, Any]) -> Dict[str, float]:
    """將複雜的 Preflop Range 格式扁平化為 Dict[str, float]"""
    if not range_data: return {}
    flattened = {}
    for hand, data in range_data.items():
        if isinstance(data, dict):
            # 取最大頻率 (例如 {"raise": 0.8, "call": 0.2} -> 1.0)
            flattened[hand] = sum(data.values())
        else:
            flattened[hand] = float(data)
    return flattened


def _extract_action_subset(range_data: Dict[str, Any], allowed_actions: List[str]) -> Dict[str, float]:
    if not range_data:
        return {}
    subset: Dict[str, float] = {}
    allowed = {a.lower() for a in allowed_actions}
    for hand, data in range_data.items():
        if isinstance(data, dict):
            weight = 0.0
            for action_name, action_weight in data.items():
                if str(action_name).lower() in allowed:
                    weight += float(action_weight)
            if weight > 0:
                subset[hand] = weight
        elif "all" in allowed:
            subset[hand] = float(data)
    return subset


def _proxy_open_position(pos: str) -> str:
    pos_key = str(pos or "").upper()
    if pos_key in {"BTN", "SB", "CO", "HJ", "MP", "UTG", "UTG+1", "LJ"}:
        return pos_key
    if pos_key == "BB":
        return "BTN"
    return "BTN"


def _build_capped_range(
    base_range: Dict[str, float],
    premium_cap: float,
    default_cap: float,
) -> Dict[str, float]:
    capped: Dict[str, float] = {}
    for hand, weight in base_range.items():
        limit = premium_cap if hand in _PREMIUM_HANDS else default_cap
        clipped = min(float(weight), limit)
        if clipped > 0:
            capped[hand] = clipped
    return capped


def _iter_preflop_actions(actions: Any) -> List[Dict[str, Any]]:
    if isinstance(actions, dict):
        items = actions.get("preflop", [])
        return [a for a in items if isinstance(a, dict)]
    if isinstance(actions, list):
        return [a for a in actions if isinstance(a, dict) and str(a.get("street", "")).lower() == "preflop"]
    return []


def _get_street_board(board_cards: List[str], street: str) -> List[str]:
    street_key = str(street or "").lower()
    if street_key == "flop":
        return board_cards[:3]
    if street_key == "turn":
        return board_cards[:4]
    if street_key == "river":
        return board_cards[:5]
    return []


def _flatten_postflop_actions(actions: Any) -> List[Dict[str, Any]]:
    flat_actions: List[Dict[str, Any]] = []
    if isinstance(actions, dict):
        for street_key in ["preflop", "flop", "turn", "river"]:
            street_acts = actions.get(street_key, [])
            if not isinstance(street_acts, list):
                continue
            for item in street_acts:
                if not isinstance(item, dict):
                    continue
                normalized = dict(item)
                normalized["street"] = str(normalized.get("street", street_key)).lower()
                flat_actions.append(normalized)
        return flat_actions

    if isinstance(actions, list):
        for item in actions:
            if isinstance(item, dict):
                flat_actions.append(dict(item))
    return flat_actions


def _build_postflop_action_sequence(
    actions: Any,
    hero_pos: str,
    villain_pos: str,
    hero_is_ip: bool,
) -> List[Dict[str, Any]]:
    sequence = []
    for act in _flatten_postflop_actions(actions):
        street = str(act.get("street", "")).lower()
        action = str(act.get("action", "")).lower()
        player = str(act.get("player", "")).upper()

        if street not in {"flop", "turn", "river"}:
            continue
        if action not in {"check", "bet", "raise", "call"}:
            continue
        if player == str(hero_pos).upper():
            sequence.append({
                "actor": "hero",
                "street": street,
                "action": action,
                "pos": str(hero_pos).upper(),
                "is_ip": bool(hero_is_ip),
            })
        elif player == str(villain_pos).upper():
            sequence.append({
                "actor": "villain",
                "street": street,
                "action": action,
                "pos": str(villain_pos).upper(),
                "is_ip": not bool(hero_is_ip),
            })
    return sequence


def _apply_actor_action_filter(
    actor_range: Dict[Tuple[str, str], float],
    opponent_range: Dict[Tuple[str, str], float],
    action_info: Dict[str, Any],
    board_cards: List[str],
    background: Dict[str, Any],
) -> Dict[Tuple[str, str], float]:
    street = action_info.get("street", "flop")
    street_cards = _get_street_board(board_cards, street)
    if not street_cards:
        return actor_range

    reasoner = ContextualReasoner()
    result = reasoner.reason_street(
        villain_range=actor_range,
        hero_range=opponent_range,
        board_cards=street_cards,
        next_action=action_info.get("action", "check"),
        street=street.upper(),
        is_ip=bool(action_info.get("is_ip", False)),
        villain_pos=action_info.get("pos", ""),
        background=background,
    )
    return result.get("new_range", actor_range)


def _extract_raise_chain(preflop_actions: List[Dict[str, Any]]) -> List[str]:
    chain = []
    for item in preflop_actions:
        action = str(item.get("action", "")).lower()
        if action in {"open", "raise", "bet"}:
            player = str(item.get("player", "")).upper()
            if player:
                chain.append(player)
    return chain


def _build_limped_ranges(
    hero_pos: str,
    villain_pos: str,
    preflop_actions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    # 跛入/過牌底池：limper 偏 capped，checker 可保留更多完整寬範圍。
    limper = ""
    checker = ""
    for item in preflop_actions:
        action = str(item.get("action", "")).lower()
        player = str(item.get("player", "")).upper()
        if action in {"call", "limp"} and not limper:
            limper = player
        elif action == "check" and player and player != limper:
            checker = player

    if not limper:
        limper = str(hero_pos).upper()
    if not checker:
        checker = str(villain_pos).upper() if limper == str(hero_pos).upper() else str(hero_pos).upper()

    limper_base = _flatten(get_preflop_range("RFI", _proxy_open_position(limper)))
    checker_base = _flatten(get_preflop_range("RFI", _proxy_open_position(checker)))

    limper_range = _build_capped_range(limper_base, premium_cap=0.2, default_cap=0.85)
    checker_range = _build_capped_range(checker_base, premium_cap=0.7, default_cap=1.0)

    if limper == str(hero_pos).upper():
        return {"hero": limper_range, "villain": checker_range}
    return {"hero": checker_range, "villain": limper_range}


def _infer_preflop_seed_ranges(
    hero_pos: str,
    villain_pos: str,
    preflop_actions: List[Dict[str, Any]],
) -> Dict[str, Dict[str, float]]:
    raise_chain = _extract_raise_chain(preflop_actions)

    if not raise_chain:
        return _build_limped_ranges(hero_pos, villain_pos, preflop_actions)

    if len(raise_chain) == 1:
        opener = raise_chain[0]
        if opener == hero_pos:
            return {
                "hero": _flatten(get_preflop_range("RFI", hero_pos)),
                "villain": _extract_action_subset(
                    get_preflop_range("facing_open", villain_pos, hero_pos),
                    ["call"],
                ),
            }
        return {
            "hero": _extract_action_subset(
                get_preflop_range("facing_open", hero_pos, villain_pos),
                ["call"],
            ),
            "villain": _flatten(get_preflop_range("RFI", villain_pos)),
        }

    if len(raise_chain) == 2:
        opener = raise_chain[0]
        threebettor = raise_chain[1]
        if threebettor == hero_pos:
            return {
                "hero": _extract_action_subset(
                    get_preflop_range("facing_open", hero_pos, villain_pos),
                    ["raise"],
                ),
                "villain": _extract_action_subset(
                    get_preflop_range("facing_3bet", villain_pos, hero_pos),
                    ["call"],
                ),
            }
        return {
            "hero": _extract_action_subset(
                get_preflop_range("facing_3bet", hero_pos, villain_pos),
                ["call"],
            ),
            "villain": _extract_action_subset(
                get_preflop_range("facing_open", villain_pos, hero_pos),
                ["raise"],
            ),
        }

    if len(raise_chain) == 3:
        fourbettor = raise_chain[-1]
        if fourbettor == hero_pos:
            hero_4bet = _extract_action_subset(
                get_preflop_range("facing_3bet", hero_pos, villain_pos),
                ["raise"],
            )
            return {
                "hero": hero_4bet or _FOUR_BET_AGGRESSOR_RANGE.copy(),
                "villain": _FOUR_BET_CALLER_RANGE.copy(),
            }
        villain_4bet = _extract_action_subset(
            get_preflop_range("facing_3bet", villain_pos, hero_pos),
            ["raise"],
        )
        return {
            "hero": _FOUR_BET_CALLER_RANGE.copy(),
            "villain": villain_4bet or _FOUR_BET_AGGRESSOR_RANGE.copy(),
        }

    last_aggressor = raise_chain[-1]
    if last_aggressor == hero_pos:
        return {"hero": _FOUR_BET_AGGRESSOR_RANGE.copy(), "villain": _FOUR_BET_CALLER_RANGE.copy()}
    return {"hero": _FOUR_BET_CALLER_RANGE.copy(), "villain": _FOUR_BET_AGGRESSOR_RANGE.copy()}

def apply_action_history_to_ranges(features: Dict[str, Any], board_cards: List[str]):
    """
    根據行動歷史過濾 Hero 與 Villain 的範圍。
    進化版本：起始即使用 1326 Combo 級別追蹤。
    """
    hero_pos = features.get("hero_pos", features.get("hero_position", "BTN"))
    villain_pos = features.get("villain_pos", features.get("villain_position", "BB"))
    actions = features.get("actions", [])
    hero_hole_cards = features.get("hero_cards", features.get("hero_hole_cards", [])) # Hero 的具體手牌作為已知死牌
    
    # 初始死牌 (公牌 + Hero 手牌)
    dead_set = set(board_cards) | set(hero_hole_cards)
    
    # 1. 分析 Preflop 結構以決定初始範圍
    preflop_acts = _iter_preflop_actions(actions)
    seed_ranges = _infer_preflop_seed_ranges(hero_pos, villain_pos, preflop_acts)
    h_pre_weighted = seed_ranges.get("hero", {})
    v_pre_weighted = seed_ranges.get("villain", {})

    hero_range = RANGE_ANALYZER.convert_weighted_range_to_combos(h_pre_weighted, dead_set)
    villain_range = RANGE_ANALYZER.convert_weighted_range_to_combos(v_pre_weighted, dead_set)

    hero_is_ip = features.get("hero_is_ip", True)
    postflop_sequence = _build_postflop_action_sequence(actions, hero_pos, villain_pos, hero_is_ip)

    if postflop_sequence and board_cards:
        previous_street = ""
        street_action_index = 0

        for action_info in postflop_sequence:
            street = action_info.get("street", "flop")
            if street != previous_street:
                street_action_index = 0
                previous_street = street
            street_action_index += 1

            background = {
                "actor": action_info.get("actor"),
                "street": street,
                "street_action_index": street_action_index,
            }

            if action_info.get("actor") == "hero":
                hero_range = _apply_actor_action_filter(
                    hero_range,
                    villain_range,
                    action_info,
                    board_cards,
                    background,
                )
                filtered_range = hero_range
            else:
                villain_range = _apply_actor_action_filter(
                    villain_range,
                    hero_range,
                    action_info,
                    board_cards,
                    background,
                )
                filtered_range = villain_range

            if DEBUG_RANGE_FILTERING:
                print(
                    f"[{street.upper()}] {action_info.get('actor', '').upper()} {action_info.get('action', '').upper()} "
                    f"- Size: {sum(filtered_range.values()):.0f} combos"
                )

    return hero_range, villain_range

def get_dynamic_advantage(features: Dict[str, Any], ctx: Dict[str, Any]):
    """
    獲取動態 Advantage 數據。
    """
    board_cards = features.get("board_cards", [])
    if not board_cards:
        return {"range_advantage": 1.0, "nut_advantage": 1.0}
        
    hero_range, villain_range = apply_action_history_to_ranges(features, board_cards)
    return RANGE_ANALYZER.calculate_advantage(hero_range, villain_range, board_cards, features, ctx)
