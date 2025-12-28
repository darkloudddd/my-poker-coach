from __future__ import annotations

import re
from typing import Dict, List, Any, Tuple, Optional
from core.parser import normalize_action_token, resolve_amount

STREETS = ("preflop", "flop", "turn", "river")



def _iter_street_actions(actions: Dict[str, Any], street: str) -> List[Dict[str, Any]]:
    if not isinstance(actions, dict):
        return []
    items = actions.get(street, [])
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _apply_street_actions(
    actions: Dict[str, Any],
    street: str,
    pot: float,
    contrib: Dict[str, float],
    street_max: float,
    big_blind: float,
) -> Tuple[float, Dict[str, float], float]:
    for action in _iter_street_actions(actions, street):
        player = str(action.get("player", "")).upper()
        act = normalize_action_token(action.get("action", ""))
        amount = resolve_amount(action, pot, big_blind)

        if act in {"", "fold", "check"}:
            continue

        if act == "call":
            required = max(street_max - contrib.get(player, 0.0), 0.0)
            if amount is None:
                amount = required
            elif required > 0 and amount > required:
                amount = required
            contrib[player] = contrib.get(player, 0.0) + amount
            pot += amount
            continue

        if act in {"open", "bet", "raise", "limp"}:
            if amount is None:
                amount = float(big_blind) if act == "limp" else 0.0
            prev = contrib.get(player, 0.0)
            increment = max(amount - prev, 0.0)
            if increment > 0:
                pot += increment
                contrib[player] = prev + increment
            if contrib.get(player, 0.0) > street_max:
                street_max = contrib[player]

    return pot, contrib, street_max


def compute_pot_bb(actions: Dict[str, Any], small_blind: float = 0.5, big_blind: float = 1.0) -> float:
    if not isinstance(actions, dict):
        return 0.0
    has_any = any(actions.get(street) for street in STREETS)
    if not has_any:
        return 0.0

    pot = 0.0
    for street in STREETS:
        contrib: Dict[str, float] = {}
        street_max = 0.0

        if street == "preflop":
            contrib["SB"] = float(small_blind)
            contrib["BB"] = float(big_blind)
            pot += float(small_blind) + float(big_blind)
            street_max = max(float(small_blind), float(big_blind))

        pot, contrib, street_max = _apply_street_actions(
            actions,
            street,
            pot,
            contrib,
            street_max,
            big_blind,
        )

    return round(pot, 2)


def compute_amount_to_call(
    actions: Dict[str, Any],
    street: str,
    hero_position: str,
    small_blind: float = 0.5,
    big_blind: float = 1.0,
) -> float:
    if not actions or not street or not hero_position:
        return 0.0

    street = str(street).lower()
    if street not in STREETS:
        return 0.0

    pot = 0.0
    for current in STREETS:
        contrib: Dict[str, float] = {}
        street_max = 0.0

        if current == "preflop":
            contrib["SB"] = float(small_blind)
            contrib["BB"] = float(big_blind)
            pot += float(small_blind) + float(big_blind)
            street_max = max(float(small_blind), float(big_blind))

        pot, contrib, street_max = _apply_street_actions(
            actions,
            current,
            pot,
            contrib,
            street_max,
            big_blind,
        )

        if current == street:
            hero_key = str(hero_position).upper()
            hero_contrib = contrib.get(hero_key, 0.0)
            amount = max(street_max - hero_contrib, 0.0)
            return round(amount, 2)

    return 0.0
