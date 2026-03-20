"""
Context / situation parsing extracted from agent.py
"""
from __future__ import annotations

import copy
import json
import re
import traceback
from typing import Dict, Any, List, Set, Tuple, Union

from .cards import parse_hand_string, normalize_card_input
from .schema import validate_parser_snapshot
from core.parser import (
    normalize_action_token,
    resolve_amount,
    action_has_amount,
    coerce_amount,
)
from services.prompts import EXTRACTOR_SYSTEM_PROMPT
from strategy.pot import compute_pot_bb, compute_amount_to_call


# ==========================================
# 解析輔助函式
# ==========================================

_STREETS = ("preflop", "flop", "turn", "river")
_POSITION_CANONICAL_MAP = {
    "utg": "UTG",
    "utg1": "UTG+1",
    "utg+1": "UTG+1",
    "mp": "MP",
    "lj": "LJ",
    "hj": "HJ",
    "co": "CO",
    "btn": "BTN",
    "button": "BTN",
    "buttun": "BTN",
    "botton": "BTN",
    "dealer": "BTN",
    "按鈕": "BTN",
    "莊位": "BTN",
    "庄位": "BTN",
    "sb": "SB",
    "smallblind": "SB",
    "小盲": "SB",
    "bb": "BB",
    "bigblind": "BB",
    "大盲": "BB",
}
_POSITION_TOKEN_RE = re.compile(
    r"utg\+1|utg1|utg|mp|lj|hj|co|btn|button|buttun|botton|dealer|"
    r"sb|small\s*blind|bb|big\s*blind|按鈕|莊位|庄位|小盲|大盲",
    re.IGNORECASE,
)
_CARD_TOKEN_RE = re.compile(r"(10|[2-9TJQKA])([shdc])", re.IGNORECASE)
_ACTION_TOKEN_RE = re.compile(
    r"open|raise|3bet|3-bet|4bet|4-bet|bet|cbet|c-bet|call|check|fold|limp|jam|shove|all-?in|"
    r"下注|打|加注|跟注|過牌|棄牌|蓋牌",
    re.IGNORECASE,
)
_PLAYER_ACTION_RE = re.compile(
    rf"(?P<player>hero|villain|opponent|我|對手|他|{_POSITION_TOKEN_RE.pattern})\s*"
    rf"(?:(?:在|is)\s*(?:{_POSITION_TOKEN_RE.pattern})\s*)?"
    rf"(?P<action>{_ACTION_TOKEN_RE.pattern})"
    rf"(?P<rest>.*?)(?=(?:hero|villain|opponent|我|對手|他|{_POSITION_TOKEN_RE.pattern})\s*"
    rf"(?:{_ACTION_TOKEN_RE.pattern})|$)",
    re.IGNORECASE,
)
_STREET_PATTERNS = {
    "preflop": re.compile(r"\bpreflop\b|翻前|翻牌前", re.IGNORECASE),
    "flop": re.compile(r"\bflop\b|翻牌", re.IGNORECASE),
    "turn": re.compile(r"\bturn\b|轉牌", re.IGNORECASE),
    "river": re.compile(r"\briver\b|河牌", re.IGNORECASE),
}
_QUERY_HINTS = ("怎麼", "為什麼", "是否", "可不可以", "可以", "該不該", "應該", "建議", "strategy", "line")


def _empty_actions() -> Dict[str, List[Dict[str, Any]]]:
    return {street: [] for street in _STREETS}


def _normalize_position_token(token: Any) -> str:
    if token is None:
        return ""
    clean = re.sub(r"[\s\-_]+", "", str(token).strip().lower())
    return _POSITION_CANONICAL_MAP.get(clean, "")


def _normalize_card_token(rank_text: str, suit_text: str) -> str:
    rank = str(rank_text).upper()
    if rank == "10":
        rank = "T"
    suit = str(suit_text).lower()
    return f"{rank}{suit}"


def _find_card_tokens(text: Any) -> List[str]:
    if not text:
        return []
    return [_normalize_card_token(match.group(1), match.group(2)) for match in _CARD_TOKEN_RE.finditer(str(text))]


def _detect_street(text: Any) -> str:
    if not text:
        return ""
    raw = str(text)
    for street, pattern in _STREET_PATTERNS.items():
        if pattern.search(raw):
            return street
    return ""


def _normalize_player_token(token: Any, hero_pos: str, villain_pos: str) -> str:
    raw = str(token or "").strip()
    raw_lower = raw.lower()
    if raw_lower in {"hero", "我"}:
        return "HERO"
    if raw_lower in {"villain", "opponent", "對手", "他"}:
        return "VILLAIN"
    return _normalize_position_token(raw)


def _extract_positions_from_text(text: str) -> Tuple[str, str]:
    hero_pos = ""
    villain_pos = ""

    matchup = re.search(
        rf"(?P<hero>{_POSITION_TOKEN_RE.pattern})\s*(?:vs\.?|v\.?|對上|對到|對)\s*(?P<villain>{_POSITION_TOKEN_RE.pattern})",
        text,
        re.IGNORECASE,
    )
    if matchup:
        hero_pos = _normalize_position_token(matchup.group("hero")) or hero_pos
        villain_pos = _normalize_position_token(matchup.group("villain")) or villain_pos

    hero_patterns = (
        rf"(?:hero|hero\s+is|我在|我是|我的位置)\s*[:：]?\s*(?P<pos>{_POSITION_TOKEN_RE.pattern})",
    )
    villain_patterns = (
        rf"(?:villain|opponent|對手|對手在|對手是)\s*[:：]?\s*(?P<pos>{_POSITION_TOKEN_RE.pattern})",
    )

    for pattern in hero_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            hero_pos = _normalize_position_token(match.group("pos")) or hero_pos
            break

    for pattern in villain_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            villain_pos = _normalize_position_token(match.group("pos")) or villain_pos
            break

    return hero_pos, villain_pos


def _extract_hero_cards_from_text(text: str) -> List[str]:
    patterns = (
        r"(?:手牌|hero\s*cards?|my\s*hand|我拿到|我有|持有)\s*[:：]?\s*(?P<cards>[^\n,;，。]+)",
        r"(?:hero|我)\s*[:：]?\s*(?P<cards>(?:\s*(?:10|[2-9TJQKA])[shdc]){2,})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        cards = _find_card_tokens(match.group("cards"))
        if len(cards) >= 2:
            return cards[:2]
    return []


def _extract_action_amount(rest: str, action: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    raw = str(rest or "")

    explicit_amount = None
    amount_match = re.search(r"(\d+(?:\.\d+)?)\s*bb", raw, re.IGNORECASE)
    if amount_match:
        explicit_amount = coerce_amount(amount_match.group(1))
    elif action == "raise":
        to_match = re.search(r"\bto\s*(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
        if to_match:
            explicit_amount = coerce_amount(to_match.group(1))
    elif action in {"open", "bet", "limp"}:
        number_match = re.search(r"(\d+(?:\.\d+)?)", raw)
        if number_match:
            explicit_amount = coerce_amount(number_match.group(1))

    if explicit_amount is not None and explicit_amount > 0:
        payload["amount"] = explicit_amount
        return payload

    ratio_match = re.search(
        r"(\d+(?:\.\d+)?\s*%\s*(?:pot|池)?|\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:pot|池)?|半池|半 pot|half pot|七成半|七成|全池|滿池)",
        raw,
        re.IGNORECASE,
    )
    if ratio_match:
        payload["amount_ratio"] = ratio_match.group(1).strip()
        return payload

    if re.search(r"all-?in|jam|shove", raw, re.IGNORECASE):
        payload["is_all_in"] = True
    return payload


def _extract_actions_from_segment(
    segment: str,
    street: str,
    hero_pos: str,
    villain_pos: str,
) -> List[Dict[str, Any]]:
    extracted: List[Dict[str, Any]] = []
    for match in _PLAYER_ACTION_RE.finditer(segment):
        player = _normalize_player_token(match.group("player"), hero_pos, villain_pos)
        action = normalize_action_token(match.group("action"))
        if not player or not action:
            continue
        entry: Dict[str, Any] = {
            "player": player,
            "action": action,
        }
        entry.update(_extract_action_amount(match.group("rest"), action))
        extracted.append(entry)
    return extracted


def _extract_rule_based_update(user_input: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
    text = str(user_input or "")
    segments = [seg.strip() for seg in re.split(r"[\n,;，。]+", text) if seg.strip()]

    hero_pos, villain_pos = _extract_positions_from_text(text)
    action_hero_pos = hero_pos or str(current_state.get("hero_position", "") or "")
    action_villain_pos = villain_pos or str(current_state.get("villain_position", "") or "")
    hero_cards = _extract_hero_cards_from_text(text)

    working_board = list(current_state.get("board_cards", []) or [])
    board_updated = False
    actions = _empty_actions()
    action_streets: Set[str] = set()
    clear_action_streets: Set[str] = set()
    mentioned_streets: List[str] = []
    current_street = "preflop"

    board_label_match = re.search(r"(?:board|board cards|公牌)\s*[:：]?\s*(?P<cards>[^\n;，。]+)", text, re.IGNORECASE)
    if board_label_match:
        board_cards = _find_card_tokens(board_label_match.group("cards"))
        if 3 <= len(board_cards) <= 5:
            working_board = board_cards[:5]
            board_updated = True

    for segment in segments:
        explicit_street = _detect_street(segment)
        if explicit_street:
            current_street = explicit_street
            mentioned_streets.append(explicit_street)

            street_cards = _find_card_tokens(segment)
            if explicit_street == "flop" and len(street_cards) >= 3:
                working_board = street_cards[:3]
                board_updated = True
            elif explicit_street == "turn" and street_cards:
                base = working_board[:3] or list(current_state.get("board_cards", []) or [])[:3]
                working_board = base + [street_cards[0]]
                board_updated = True
            elif explicit_street == "river" and street_cards:
                base = working_board[:4] or list(current_state.get("board_cards", []) or [])[:4]
                working_board = base + [street_cards[0]]
                board_updated = True

        extracted_actions = _extract_actions_from_segment(segment, current_street, action_hero_pos, action_villain_pos)
        if extracted_actions:
            actions[current_street].extend(extracted_actions)
            action_streets.add(current_street)

    if actions.get("preflop"):
        clear_action_streets.update(_STREETS)

    explicit_seen_players = {
        str(item.get("player", "")).upper()
        for street in _STREETS
        for item in actions.get(street, [])
        if isinstance(item, dict) and str(item.get("player", "")).upper() not in {"HERO", "VILLAIN"}
    }
    if hero_pos and not villain_pos:
        others = explicit_seen_players - {str(hero_pos).upper()}
        if len(others) == 1:
            villain_pos = next(iter(others))
    if villain_pos and not hero_pos:
        others = explicit_seen_players - {str(villain_pos).upper()}
        if len(others) == 1:
            hero_pos = next(iter(others))

    resolved_hero = str(hero_pos or current_state.get("hero_position", "") or "").upper()
    resolved_villain = str(villain_pos or current_state.get("villain_position", "") or "").upper()
    for street in _STREETS:
        for item in actions.get(street, []):
            if not isinstance(item, dict):
                continue
            player = str(item.get("player", "")).upper()
            if player == "HERO" and resolved_hero:
                item["player"] = resolved_hero
            elif player == "VILLAIN" and resolved_villain:
                item["player"] = resolved_villain

    final_street = mentioned_streets[-1] if mentioned_streets else ""
    if not final_street and len(working_board) in {3, 4, 5}:
        final_street = {3: "flop", 4: "turn", 5: "river"}[len(working_board)]

    if final_street and final_street not in action_streets and final_street != "preflop":
        clear_action_streets.add(final_street)

    parsed: Dict[str, Any] = {
        "hero_position": hero_pos,
        "villain_position": villain_pos,
        "hero_hole_cards": hero_cards[:2] if len(hero_cards) >= 2 else hero_cards,
        "board_cards": working_board if board_updated else [],
        "street": final_street,
        "actions": actions,
        "_action_streets": action_streets,
        "_clear_action_streets": clear_action_streets,
        "_mentioned_streets": set(mentioned_streets),
    }

    has_new_info = bool(hero_pos or villain_pos or hero_cards or board_updated or mentioned_streets or any(actions[street] for street in _STREETS))
    parsed["_has_new_info"] = has_new_info
    return parsed


def _merge_partial_parse(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    merged = copy.deepcopy(base or {})
    source = update or {}

    for key in ("hero_position", "villain_position", "hero_hole_cards", "board_cards", "street", "hero_stack_bb", "villain_stack_bb"):
        value = source.get(key)
        if value in (None, "", []):
            continue
        merged[key] = copy.deepcopy(value)

    for key in ("is_strategy_query", "error", "missing_fields", "meta", "blinds", "hand_ended", "showdown"):
        if key in source:
            merged[key] = copy.deepcopy(source.get(key))

    if "players" in source and isinstance(source.get("players"), dict):
        merged_players = merged.get("players") if isinstance(merged.get("players"), dict) else {}
        for role in ("hero", "villain"):
            info = source["players"].get(role)
            if not isinstance(info, dict):
                continue
            existing = merged_players.get(role) if isinstance(merged_players.get(role), dict) else {}
            next_info = copy.deepcopy(existing)
            for key, value in info.items():
                if value in (None, "", []):
                    continue
                next_info[key] = copy.deepcopy(value)
            merged_players[role] = next_info
        merged["players"] = merged_players

    if "board" in source and isinstance(source.get("board"), dict):
        merged_board = merged.get("board") if isinstance(merged.get("board"), dict) else {}
        next_board = copy.deepcopy(merged_board)
        for key, value in source["board"].items():
            if value in (None, "", []):
                continue
            next_board[key] = copy.deepcopy(value)
        merged["board"] = next_board

    if isinstance(source.get("actions"), dict):
        action_streets = source.get("_action_streets")
        clear_action_streets = source.get("_clear_action_streets")
        has_action_payload = any(
            isinstance(source["actions"].get(street), list) and source["actions"].get(street)
            for street in _STREETS
        )

        should_override_actions = bool(has_action_payload)
        if isinstance(action_streets, set) and action_streets:
            should_override_actions = True
        if isinstance(clear_action_streets, set) and clear_action_streets:
            should_override_actions = True

        if not should_override_actions:
            return merged

        merged_actions = _empty_actions()
        base_actions = merged.get("actions", {})
        if isinstance(base_actions, dict):
            for street in _STREETS:
                if isinstance(base_actions.get(street), list):
                    merged_actions[street] = copy.deepcopy(base_actions.get(street, []))

        if isinstance(action_streets, set) or isinstance(clear_action_streets, set):
            action_streets = set(action_streets or set())
            clear_action_streets = set(clear_action_streets or set())
            for street in clear_action_streets:
                if street in merged_actions:
                    merged_actions[street] = []
            for street in action_streets:
                if street in merged_actions:
                    merged_actions[street] = copy.deepcopy(source["actions"].get(street, []))
            if has_action_payload and not action_streets:
                for street in _STREETS:
                    if isinstance(source["actions"].get(street), list) and source["actions"].get(street):
                        merged_actions[street] = copy.deepcopy(source["actions"].get(street, []))
        else:
            for street in _STREETS:
                if street in source["actions"] and isinstance(source["actions"].get(street), list):
                    merged_actions[street] = copy.deepcopy(source["actions"].get(street, []))

        merged["actions"] = merged_actions
    elif isinstance(source.get("actions"), list):
        merged["actions"] = copy.deepcopy(source.get("actions", []))

    return merged


def _build_prompt_snapshot(state: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    allowed_keys = (
        "hero_position",
        "villain_position",
        "hero_hole_cards",
        "board_cards",
        "street",
        "hero_stack_bb",
        "villain_stack_bb",
        "pot_bb",
        "actions",
        "villain_action",
        "is_3bet_pot",
        "line_state",
    )
    snapshot = {}
    for key in allowed_keys:
        value = state.get(key)
        if key == "actions" and isinstance(value, dict) and not _actions_has_data(value):
            continue
        if value in (None, "", [], {}):
            continue
        snapshot[key] = copy.deepcopy(value)
    return snapshot


def _build_rule_hint_snapshot(rule_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(rule_data, dict):
        return {}
    hint = {}
    for key in ("hero_position", "villain_position", "hero_hole_cards", "board_cards", "street", "actions"):
        value = rule_data.get(key)
        if key == "actions" and isinstance(value, dict) and not _actions_has_data(value):
            continue
        if value in (None, "", [], {}):
            continue
        hint[key] = copy.deepcopy(value)
    return hint


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").replace("```json", "").replace("```", "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
    except json.JSONDecodeError:
        pass

    lines = text.splitlines()
    for line in lines:
        line = line.strip()
        if not line.startswith("{") or not line.endswith("}"):
            continue
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return {}


def _normalize_llm_snapshot(raw_data: Dict[str, Any], current_state: Dict[str, Any]) -> Dict[str, Any]:
    data = copy.deepcopy(raw_data or {})
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    players = data.get("players") if isinstance(data.get("players"), dict) else {}
    hero_info = players.get("hero") if isinstance(players.get("hero"), dict) else {}
    villain_info = players.get("villain") if isinstance(players.get("villain"), dict) else {}
    board = data.get("board") if isinstance(data.get("board"), dict) else {}

    hero_pos = hero_info.get("position") or data.get("hero_position") or current_state.get("hero_position")
    villain_pos = villain_info.get("position") or data.get("villain_position") or current_state.get("villain_position")
    raw_actions = data.get("actions", {})
    normalized_actions = _normalize_actions_from_model(raw_actions, hero_pos or "", villain_pos or "")

    normalized = {
        "is_strategy_query": bool(data.get("is_strategy_query", False)),
        "is_new_hand": data.get("is_new_hand"),
        "hero_position": hero_info.get("position") or data.get("hero_position"),
        "villain_position": villain_info.get("position") or data.get("villain_position"),
        "hero_hole_cards": hero_info.get("cards") or data.get("hero_hole_cards") or [],
        "board_cards": board.get("cards") or data.get("board_cards") or [],
        "street": data.get("street"),
        "hero_stack_bb": hero_info.get("stack_bb") if hero_info.get("stack_bb") is not None else data.get("hero_stack_bb"),
        "villain_stack_bb": villain_info.get("stack_bb") if villain_info.get("stack_bb") is not None else data.get("villain_stack_bb"),
        "pot_bb": data.get("pot_bb"),
        "actions": normalized_actions,
        "blinds": data.get("blinds") if isinstance(data.get("blinds"), dict) else {"sb": 0.5, "bb": 1.0},
        "missing_fields": data.get("missing_fields") or meta.get("missing_fields") or [],
        "assumptions": data.get("assumptions") or meta.get("assumptions") or [],
        "confidence": data.get("confidence") if data.get("confidence") is not None else meta.get("confidence"),
    }

    validated = validate_parser_snapshot(normalized)
    if hasattr(validated, "model_dump"):
        return validated.model_dump()
    return validated.dict()


def _merge_llm_snapshot(base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    source = copy.deepcopy(update or {})
    if source.get("is_new_hand"):
        base = {}
    merged = copy.deepcopy(base or {})

    for key in (
        "hero_position",
        "villain_position",
        "hero_hole_cards",
        "board_cards",
        "street",
        "hero_stack_bb",
        "villain_stack_bb",
        "pot_bb",
        "blinds",
        "confidence",
    ):
        value = source.get(key)
        if value in (None, "", [], {}):
            continue
        merged[key] = copy.deepcopy(value)

    if "is_strategy_query" in source:
        merged["is_strategy_query"] = bool(source.get("is_strategy_query", False))
    if "is_new_hand" in source:
        merged["is_new_hand"] = source.get("is_new_hand")
    if "missing_fields" in source:
        merged["missing_fields"] = copy.deepcopy(source.get("missing_fields") or [])
    if "assumptions" in source:
        merged["assumptions"] = copy.deepcopy(source.get("assumptions") or [])

    actions = source.get("actions")
    if isinstance(actions, dict) and _actions_has_data(actions):
        merged["actions"] = copy.deepcopy(actions)

    return merged


def _has_complete_rule_parse(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    hero_pos = data.get("hero_position")
    villain_pos = data.get("villain_position")
    hero_cards = normalize_card_input(data.get("hero_hole_cards", []))
    board_cards = normalize_card_input(data.get("board_cards", []))
    street = str(data.get("street", "")).lower()
    actions = data.get("actions", {})

    if not hero_pos or not villain_pos:
        return False
    if len(hero_cards) != 2:
        return False
    if len(board_cards) not in {0, 3, 4, 5}:
        return False
    if street not in {"preflop", "flop", "turn", "river"}:
        return False
    return _actions_has_data(actions)


def _has_meaningful_hand_update(data: Dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("hero_position") or data.get("villain_position"):
        return True
    if len(normalize_card_input(data.get("hero_hole_cards", []))) == 2:
        return True
    if len(normalize_card_input(data.get("board_cards", []))) in {3, 4, 5}:
        return True
    if str(data.get("street", "")).lower() in {"preflop", "flop", "turn", "river"}:
        return True
    return _actions_has_data(data.get("actions", {}))


def _looks_like_strategy_query(user_input: str, current_state: Dict[str, Any], rule_data: Dict[str, Any]) -> bool:
    if not current_state:
        return False
    if rule_data.get("_has_new_info"):
        return False
    text = str(user_input or "").strip().lower()
    if not text:
        return False
    if "?" in text or "？" in text:
        return True
    return any(hint in text for hint in _QUERY_HINTS)




def _classify_position_matchup(hero_pos: str, villain_pos: str, is_3bet: bool = False):
    """
    簡單的位置判斷邏輯。
    """
    pos_order = {"SB": 0, "BB": 1, "UTG": 2, "UTG+1": 3, "MP": 4, "LJ": 4, "HJ": 5, "CO": 6, "BTN": 7}
    h_val = pos_order.get(hero_pos.upper(), 4)
    v_val = pos_order.get(villain_pos.upper(), 4)

    # 判斷 IP/OOP
    hero_is_ip = False
    if h_val > v_val:
        hero_is_ip = True
    if hero_pos.upper() == "SB":
        hero_is_ip = False
    if hero_pos.upper() == "BTN":
        hero_is_ip = True

    # 特殊：BB vs SB, BB is IP
    if hero_pos.upper() == "BB" and villain_pos.upper() == "SB":
        hero_is_ip = True

    return "IP" if hero_is_ip else "OOP", hero_is_ip


def _actions_has_data(actions: Dict[str, Any]) -> bool:
    if not isinstance(actions, dict):
        return False
    return any(actions.get(street) for street in ("preflop", "flop", "turn", "river"))


def _count_actions(actions: Dict[str, Any]) -> int:
    if not isinstance(actions, dict):
        return 0
    total = 0
    for street in ("preflop", "flop", "turn", "river"):
        items = actions.get(street, [])
        if isinstance(items, list):
            total += len(items)
    return total





def _count_amount_fields(actions: Any) -> int:
    if isinstance(actions, dict):
        total = 0
        for street in ("preflop", "flop", "turn", "river"):
            total += _count_amount_fields(actions.get(street, []))
        return total
    if isinstance(actions, list):
        return sum(1 for action in actions if action_has_amount(action))
    return 0

_CORE_ACTIONS = {"open", "raise", "bet", "call", "limp"}

def _count_core_actions(items: Any) -> int:
    if not isinstance(items, list):
        return 0
    total = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).lower()
        if action in _CORE_ACTIONS:
            total += 1
    return total



def _validate_constraints(data: Dict[str, Any]) -> List[str]:
    """
    驗證牌局是否符合系統限制條件
    返回錯誤訊息列表，空列表表示驗證通過
    """
    errors = []
    
    # 1. 檢查是否為單挑 (heads-up) - 只能有 Hero 和 Villain 兩位玩家
    hero_pos = data.get("hero_position")
    villain_pos = data.get("villain_position")
    
    if not hero_pos or not villain_pos:
        return errors  # 如果連位置都沒有，會在後續的 missing_fields 處理
    
    # 檢查 actions 中是否有第三位玩家參與
    actions = data.get("actions", {})
    if isinstance(actions, dict):
        players_seen = set()
        for street in ("preflop", "flop", "turn", "river"):
            items = actions.get(street, [])
            if isinstance(items, list):
                for action in items:
                    if isinstance(action, dict):
                        player = str(action.get("player", "")).upper()
                        if player:
                            players_seen.add(player)
        
        # 移除 Hero 和 Villain 後，不應該有其他玩家
        hero_key = str(hero_pos).upper()
        villain_key = str(villain_pos).upper()
        other_players = players_seen - {hero_key, villain_key}
        
        # [MODIFIED] 進階檢查：如果其他玩家只是 Fold，則不視為違反 Heads-Up
        active_other_players = set()
        for player in other_players:
            is_active = False
            # 檢查該玩家是否只有 fold / post blind 行動
            for street in ("preflop", "flop", "turn", "river"):
                for action in actions.get(street, []):
                    if isinstance(action, dict):
                        p_name = str(action.get("player", "")).upper()
                        act_type = str(action.get("action", "")).lower()
                        if p_name == player:
                            # 只要有非 fold 且非 post blind (通常 post 不會明確寫 action="post", 而是隱含)
                            # 但我們這裡只看 "action" 欄位。若 user input 是 "sb fold", action="fold"。
                            # 若是 "sb calls", action="call" -> is_active = True
                            if act_type not in {"fold", "check"}: 
                                # Check 其實通常也不會出現在 preflop open 之前的 fold 玩家身上
                                # 但為了保險，如果是 check，代表他還在牌局中，也算 active
                                is_active = True
            if is_active:
                active_other_players.add(player)

        if len(active_other_players) > 0:
            errors.append(f"⚠️ 本系統僅支援單挑底池 (Heads-Up)，但偵測到其他活躍玩家: {', '.join(active_other_players)}")
    
    # 2. 檢查是否有完整的 preflop 行動歷史
    preflop_actions = actions.get("preflop", [])
    if not isinstance(preflop_actions, list) or len(preflop_actions) == 0:
        errors.append("⚠️ 缺少 Preflop 行動歷史，請提供完整的手牌經過")
    else:
        # 檢查 preflop 是否有核心行動 (open/raise/call/limp)
        has_core_action = False
        for action in preflop_actions:
            if isinstance(action, dict):
                act = str(action.get("action", "")).lower()
                if act in {"open", "raise", "bet", "call", "limp"}:
                    has_core_action = True
                    break
        
        if not has_core_action:
            errors.append("⚠️ Preflop 行動不完整，請提供開池/加注/跟注等完整行動")
    
    # 3. 檢查是否為決策點 (不能是已經攤牌的手牌)
    # 判斷依據：River 之後不應該還有雙方都 all-in 或已經 showdown 的情況
    street = data.get("street", "").lower()
    
    # 如果有明確的 "已結束" 標記
    if data.get("hand_ended") or data.get("showdown"):
        errors.append("⚠️ 請提供尚未做決策的牌局，不接受已攤牌的手牌分析")
    
    # 4. (可選) 提醒遊戲類型
    # 雖然我們無法從輸入強制驗證是否為 6-max cash，但可以在 prompt 中要求
    # 這裡不做強制檢查，但可以記錄提示
    
    return errors


def _infer_villain_action(actions: Dict[str, Any], street: str, villain_pos: str) -> str:
    if not isinstance(actions, dict) or not street:
        return ""
    items = actions.get(street, [])
    if not isinstance(items, list):
        return ""
    villain_key = str(villain_pos or "").upper()
    last_villain_action = ""
    for item in items:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).lower()
        player = str(item.get("player", "")).upper()
        if action and player == villain_key:
            last_villain_action = action
    return last_villain_action


def _normalize_actions(raw_actions: Any, hero_pos: str, villain_pos: str) -> Dict[str, List[Dict[str, Any]]]:
    streets = ("preflop", "flop", "turn", "river")
    normalized = {street: [] for street in streets}

    if isinstance(raw_actions, dict):
        for street in streets:
            if isinstance(raw_actions.get(street), list):
                normalized[street] = raw_actions.get(street)
            elif isinstance(raw_actions.get(f"{street}_actions"), list):
                normalized[street] = raw_actions.get(f"{street}_actions")
    elif isinstance(raw_actions, list):
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            street = str(item.get("street", "")).lower()
            if street in normalized:
                normalized[street].append(item)

    hero_key = (hero_pos or "").upper()
    villain_key = (villain_pos or "").upper()

    for street, items in normalized.items():
        clean_items = []
        for action in items:
            if not isinstance(action, dict):
                continue
            entry = action.copy()
            player = str(entry.get("player", "")).strip()
            player_lower = player.lower()
            if player_lower in {"hero", "me", "i", "我"}:
                player = hero_key or player
            elif player_lower in {"villain", "opponent", "v", "對手", "他"}:
                player = villain_key or player
            if player:
                entry["player"] = player.upper()
            normalized_action = normalize_action_token(str(entry.get("action", "")))
            if normalized_action:
                entry["action"] = normalized_action
            clean_items.append(entry)
        normalized[street] = clean_items

    return normalized


def _normalize_actions_from_model(raw_actions: Any, hero_pos: str, villain_pos: str) -> Dict[str, List[Dict[str, Any]]]:
    if isinstance(raw_actions, list):
        actions = {street: [] for street in ("preflop", "flop", "turn", "river")}
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            street = str(item.get("street", "")).lower()
            if street not in actions:
                continue
            player = str(item.get("player", "")).strip()
            if not player:
                continue
            player_lower = player.lower()
            if player_lower in {"hero", "me", "i", "我"}:
                player = (hero_pos or player).upper()
            elif player_lower in {"villain", "opponent", "v", "對手", "他"}:
                player = (villain_pos or player).upper()
            else:
                player = player.upper()
            action = normalize_action_token(str(item.get("action", "")))
            if not action:
                continue
            entry = {"player": player, "action": action}
            for key in ("order", "amount", "amount_to", "to", "size", "amount_ratio", "pot_ratio", "ratio", "amount_pct", "size_pct", "is_all_in"):
                if key in item:
                    entry[key] = item.get(key)
            actions[street].append(entry)
        return actions
    return _normalize_actions(raw_actions, hero_pos, villain_pos)


# ==========================================
# 主要解析流程
# ==========================================


def parse_poker_situation(user_input: str, current_state: Dict[str, Any] = None) -> Dict[str, Any]:
    print("正在更新牌局資訊...")

    def _print_missing(fields: list[str]) -> None:
        if fields:
            print(f"需要補充: {', '.join(map(str, fields))}")
        else:
            print("需要補充")

    def _coerce_float(value: Any):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        raw = str(value).strip().lower().replace("bb", "")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    current_state = current_state or {}
    rule_data = _extract_rule_based_update(user_input, current_state)

    if _looks_like_strategy_query(user_input, current_state, rule_data):
        preserved = copy.deepcopy(current_state)
        preserved["is_strategy_query"] = True
        return preserved

    state_prompt = ""
    prev_snapshot = _build_prompt_snapshot(current_state)
    if prev_snapshot:
        state_prompt = f"【上一手狀態】: {json.dumps(prev_snapshot, ensure_ascii=False)}\n"

    rule_hint_prompt = ""
    rule_hint = _build_rule_hint_snapshot(rule_data)
    if rule_hint:
        rule_hint_prompt = f"【規則式輔助線索】: {json.dumps(rule_hint, ensure_ascii=False)}\n"

    data = None
    try:
        rule_merged = _merge_partial_parse(current_state, rule_data)
        try:
            from services.llm_client import call_llm

            user_message = (
                f"{state_prompt}"
                f"{rule_hint_prompt}"
                f"【用戶新指令】: {user_input}\n"
                "請輸出完整目前牌局 JSON snapshot。"
            )
            json_str = call_llm(
                EXTRACTOR_SYSTEM_PROMPT,
                user_message,
                response_mime_type="application/json",
            )
            llm_payload = _extract_json_object(json_str)
            if not llm_payload:
                print("解析失敗，LLM 回傳了什麼？")
                print(json_str)
                raise ValueError("無法解析 LLM 回應 (JSON 格式錯誤 或 為空)")
            data = _normalize_llm_snapshot(llm_payload, current_state)
            data = _merge_llm_snapshot(current_state, data)
            if data.get("is_strategy_query") and _has_meaningful_hand_update(data):
                data["is_strategy_query"] = False
        except Exception as exc:
            if _has_complete_rule_parse(rule_merged):
                data = rule_merged
            else:
                if isinstance(exc, ValueError):
                    raise
                raise ValueError(f"LLM 解析失敗: {exc}")

        missing_fields = data.get("missing_fields") or []
        if missing_fields:
            # Filter out missing fields that can be inferred (specifically 'call' amounts)
            # The LLM might flag "actions.preflop.call.amount" as missing, but our logic computes it.
            real_missing = []
            for field in missing_fields:
                f_str = str(field).lower()
                # If it's a Call or Check action, we don't need the amount typically
                if "call.amount" in f_str or "check.amount" in f_str:
                    continue
                # [NEW] Ignore stack missing fields, we will default them to 100bb
                if "stack_bb" in f_str:
                    continue
                # Derived fields are computed by backend; parser does not need them.
                if f_str in {"pot_bb", "amount_to_call", "spr"}:
                    continue
                
                real_missing.append(field)
            
            # [FIX] Double check if "amount" is missing but "ratio" is present in data
            # LLM might flag amount as missing even if it extracted pot_ratio
            final_missing = []
            for field in real_missing:
                # 1. Check if we have this data in current_state (existing logic)
                state_key = field
                if field == "hero.cards" or field == "hero_hole_cards": state_key = "hero_hole_cards"
                elif field == "board.cards" or field == "board_cards": state_key = "board_cards"
                elif field == "hero.stack_bb" or field == "hero_stack_bb": state_key = "hero_stack_bb"
                elif field == "villain.stack_bb" or field == "villain_stack_bb": state_key = "villain_stack_bb"
                elif field == "hero.position" or field == "hero_position": state_key = "hero_position"
                elif field == "villain.position" or field == "villain_position": state_key = "villain_position"
                
                val = data.get(state_key)
                if val is not None and val != [] and val != "":
                    continue

                # 2. [NEW] Check for Ratio/Pct if amount is missing
                if "amount" in str(field).lower():
                    # Try to find the action object in data
                    # Field format might be "actions.flop.amount" or "actions.flop.0.amount"
                    parts = str(field).split('.')
                    if len(parts) >= 2 and parts[0] == "actions":
                        street_key = parts[1]
                        # We just check ALL actions in that street for any ratio presence
                        actions_data = data.get("actions", {})
                        if isinstance(actions_data, dict):
                            street_actions = actions_data.get(street_key, [])
                            if isinstance(street_actions, list):
                                has_ratio = False
                                for act in street_actions:
                                    if isinstance(act, dict):
                                        # Check common ratio keys
                                        if any(k in act for k in ["pot_ratio", "amount_ratio", "size_ratio", "ratio", "amount_pct", "size_pct"]):
                                            has_ratio = True
                                            break
                                if has_ratio:
                                    continue # Skip this missing field
                        elif isinstance(actions_data, list):
                            # Fallback for list-style actions (flat list)
                            # We search entire list for ratio keys if we can't determine street easily
                            has_ratio = False
                            for act in actions_data:
                                if isinstance(act, dict):
                                    # Optional: check if act['street'] matches street_key if present
                                    if any(k in act for k in ["pot_ratio", "amount_ratio", "size_ratio", "ratio", "amount_pct", "size_pct"]):
                                        has_ratio = True
                                        break
                            if has_ratio:
                                continue
                
                final_missing.append(field)

                if final_missing:
                    raise ValueError(f"資訊不足，請補充: {', '.join(map(str, final_missing))}")

        required_fields = [
            "hero_position",
            "villain_position",
            "hero_hole_cards",
            # "hero_stack_bb",    # defaulting to 100
            # "villain_stack_bb", # defaulting to 100
            "board_cards",
            "street",
            "actions",
        ]

        if data.get("is_strategy_query", False):
            if current_state:
                preserved = current_state.copy()
                preserved["is_strategy_query"] = True
                return preserved
            raise ValueError("無法執行策略查詢：缺少當前牌局狀態 (Current State Missing)")

        hero_pos = data.get("hero_position")
        villain_pos = data.get("villain_position")
        
        # Stacks: 0 is valid, so check for None explicitly
        hero_stack = data.get("hero_stack_bb")
        # [NEW] Default to 100bb if not specified
        if hero_stack is None: hero_stack = 100.0

        villain_stack = data.get("villain_stack_bb")
        # [NEW] Default to 100bb if not specified
        if villain_stack is None: villain_stack = 100.0

        hero_cards = data.get("hero_hole_cards") or []
        board_cards = data.get("board_cards") or []

        hero_cards = normalize_card_input(hero_cards)
        board_cards = normalize_card_input(board_cards)

        board_len = len(board_cards)
        street_map = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
        derived_street = street_map.get(board_len)
        street = data.get("street") or derived_street
        if derived_street:
            street = derived_street

        raw_actions = data.get("actions", [])
        actions = _normalize_actions_from_model(raw_actions, hero_pos or "", villain_pos or "")

        hero_stack = _coerce_float(hero_stack)
        villain_stack = _coerce_float(villain_stack)

        stacks = {}
        if hero_pos:
            stacks[str(hero_pos).upper()] = hero_stack
        if villain_pos:
            stacks[str(villain_pos).upper()] = villain_stack

        # Track current/remaining stacks for correct SPR calc
        current_stacks = {k: v for k, v in stacks.items()}

        def _resolve_amounts_and_stacks():
            pot = 0.0
            total_contrib = {key: 0.0 for key in stacks}

            for street_name in ("preflop", "flop", "turn", "river"):
                street_contrib = {}
                street_max = 0.0

                if street_name == "preflop":
                    if "SB" in stacks:
                        amt = 0.5
                        street_contrib["SB"] = amt
                        total_contrib["SB"] = total_contrib.get("SB", 0.0) + amt
                        pot += amt
                        current_stacks["SB"] = max(stacks["SB"] - total_contrib["SB"], 0.0)
                        street_max = max(street_max, amt)
                    if "BB" in stacks:
                         amt = 1.0
                         street_contrib["BB"] = amt
                         total_contrib["BB"] = total_contrib.get("BB", 0.0) + amt
                         pot += amt
                         current_stacks["BB"] = max(stacks["BB"] - total_contrib["BB"], 0.0)
                         street_max = max(street_max, amt)

                for item in actions.get(street_name, []):
                    if not isinstance(item, dict):
                        continue
                    player = str(item.get("player", "")).upper()
                    act = str(item.get("action", "")).lower()
                    if not player or act in {"", "fold", "check"}:
                        continue
                    
                    # Try to resolve amount
                    amount = resolve_amount(item, pot, 1.0)
                    
                    # [FIX]: Handle All-in without explicit amount
                    if amount is None and act in {"open", "bet", "raise", "limp"} and item.get("is_all_in") and player in stacks:
                        remaining = stacks[player] - total_contrib.get(player, 0.0)
                        amount = street_contrib.get(player, 0.0) + max(remaining, 0.0)
                        item["amount"] = round(amount, 2) # Inject back into item

                    # [FIX]: If still None but we have ratio (e.g. "full pot"), resolve_amount should have handled it IF pot > 0.
                    # But resolve_amount logic depends on parser.py
                    # Here we re-check if amount is None but we have ratio
                    if amount is None and act in {"open", "bet", "raise", "limp"}:
                         # Check for manual ratio calc if parser didn't catch it
                         # (parser needs `amount_ratio` key)
                         pass

                    if act == "call":
                        required = max(street_max - street_contrib.get(player, 0.0), 0.0)
                        # All-in call checks
                        can_pay = stacks.get(player, 9999) - total_contrib.get(player, 0.0)
                        actual_call = min(required, can_pay)
                        
                        if amount is None:
                            amount = actual_call
                        elif amount > required: # Cap at required
                            amount = required # Simplify
                        
                        street_contrib[player] = street_contrib.get(player, 0.0) + amount
                        total_contrib[player] = total_contrib.get(player, 0.0) + amount
                        pot += amount
                        if player in current_stacks:
                            current_stacks[player] = max(stacks[player] - total_contrib[player], 0.0)
                        continue

                    if act in {"open", "bet", "raise", "limp"}:
                        if amount is None:
                            amount = 1.0 if act == "limp" else 0.0
                        
                        # Verify we don't bet more than stack
                        can_pay = stacks.get(player, 99999) - total_contrib.get(player, 0.0) # total remaining
                        prev_street_bet = street_contrib.get(player, 0.0)
                        # amount implies 'raise to' or 'bet total'.
                        # Increment needed = amount - prev_street_bet
                        increment_needed = amount - prev_street_bet
                        if increment_needed > can_pay:
                             # Cap to all-in
                             amount = prev_street_bet + can_pay
                             item["amount"] = round(amount, 2)

                        prev = street_contrib.get(player, 0.0)
                        increment = max(amount - prev, 0.0)
                        if increment > 0:
                            pot += increment
                            street_contrib[player] = prev + increment
                            total_contrib[player] = total_contrib.get(player, 0.0) + increment
                            if player in current_stacks:
                                current_stacks[player] = max(stacks[player] - total_contrib[player], 0.0)
                        
                        if street_contrib.get(player, 0.0) > street_max:
                            street_max = street_contrib[player]

        _resolve_amounts_and_stacks()

        action_missing = []
        for street_name in ("preflop", "flop", "turn", "river"):
            for item in actions.get(street_name, []):
                if not isinstance(item, dict):
                    continue
                act = str(item.get("action", "")).lower()
                if act in {"open", "raise", "bet", "limp"} and not action_has_amount(item):
                    label = f"actions.{street_name}.{act}_amount"
                    if label not in action_missing:
                        action_missing.append(label)

        missing = []
        if not hero_pos:
            missing.append("hero_position")
        if not villain_pos:
            missing.append("villain_position")
        if not hero_cards or len(hero_cards) != 2:
            missing.append("hero_hole_cards")
        if hero_stack is None:
            missing.append("hero_stack_bb")
        if villain_stack is None:
            missing.append("villain_stack_bb")
        if board_len not in (0, 3, 4, 5):
            missing.append("board_cards")
        if not street:
            missing.append("street")
        if not _actions_has_data(actions):
            missing.append("actions")
        if action_missing:
            missing.extend(action_missing)

        if missing:
            raise ValueError(f"缺少必要欄位: {', '.join(missing)}")

        data["hero_position"] = hero_pos
        data["villain_position"] = villain_pos
        data["hero_stack_bb"] = hero_stack
        data["villain_stack_bb"] = villain_stack
        data["hero_hole_cards"] = hero_cards
        data["board_cards"] = board_cards
        data["street"] = street
        data["actions"] = actions

        pos_matchup, hero_is_ip = _classify_position_matchup(hero_pos, villain_pos, data.get("is_3bet_pot", False))
        data["hero_is_ip"] = hero_is_ip
        data["position_matchup"] = pos_matchup

        preflop_raises = 0
        for item in actions.get("preflop", []):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "")).lower()
            if action in {"open", "raise"}:
                preflop_raises += 1
        if preflop_raises >= 2:
            data["is_3bet_pot"] = True
        elif preflop_raises == 1:
            data["is_3bet_pot"] = False

        blinds = data.get("blinds") if isinstance(data.get("blinds"), dict) else {}
        sb = _coerce_float(blinds.get("sb", 0.5)) or 0.5
        bb = _coerce_float(blinds.get("bb", 1.0)) or 1.0

        data["pot_bb"] = compute_pot_bb(actions, sb, bb)
        data["amount_to_call"] = compute_amount_to_call(actions, street, hero_pos, sb, bb)

        if street in ("flop", "turn", "river"):
            street_actions = actions.get(street, [])
            if isinstance(street_actions, list) and street_actions:
                inferred = _infer_villain_action(actions, street, villain_pos)
                data["villain_action"] = inferred or ""
            else:
                data["villain_action"] = ""

        pot_raw = data.get("pot_bb")
        stack_raw = data.get("hero_stack_bb")
        data["pot_bb"] = float(pot_raw) if pot_raw is not None else 0.0
        data["hero_stack_bb"] = float(stack_raw) if stack_raw is not None else 100.0
        if data["pot_bb"] > 0:
            # Use current effective stack for SPR
            eff_stack = current_stacks.get(str(hero_pos).upper(), 0.0) if hero_pos else 0.0
            data["spr"] = eff_stack / data["pot_bb"]
            # Update returned stack to reflect current state
            data["hero_stack_bb"] = eff_stack
            if villain_pos:
                data["villain_stack_bb"] = current_stacks.get(str(villain_pos).upper(), 0.0)
        else:
            data["spr"] = 100.0

        # ==========================================
        # 驗證系統限制條件
        # ==========================================
        validation_errors = _validate_constraints(data)
        if validation_errors:
            err_msg = "\\n".join(validation_errors)
            print(f"Validation Error: {err_msg}")
            raise ValueError(f"牌局不符合系統限制:\\n{err_msg}")

        for key in ("_action_streets", "_clear_action_streets", "_mentioned_streets", "_has_new_info"):
            data.pop(key, None)

        return data

    except ValueError:
        raise
    except Exception as e:
        print(f"數據處理錯誤 (Phase 1): {e}")
        traceback.print_exc()
        raise ValueError(f"系統發生未預期錯誤: {str(e)}")
