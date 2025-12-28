# strategy/preflop.py
from typing import Dict, Any, Optional, List
import random
import re

from ..ranges import range as ranges
from ..utils import normalize_hand_code_preflop, format_output, weighted_choice

_FACING_4BET_RAISE = {"AA", "KK", "QQ", "AKs", "AKo"}
_FACING_4BET_CALL = {"JJ", "AQs"}

def _coerce_amount(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().lower().replace("bb", "")
    match = re.search(r"(\d+(?:\.\d+)?)", raw)
    if match:
        return float(match.group(1))
    return None

def _extract_preflop_raises(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    raise_actions = []
    for item in actions or []:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action", "")).lower()
        if action not in {"open", "raise", "bet"}:
            continue
        player = str(item.get("player", "")).upper()
        amount = _coerce_amount(item.get("amount"))
        raise_actions.append({"player": player, "amount": amount, "action": action})
    return raise_actions

# --- Sizing Helpers ---

def _get_rfi_size(hero_pos: str) -> float:
    pos = hero_pos.upper()
    if pos == "SB":
        return 3.0
    if pos == "BTN":
        return 2.5
    return 2.3

def _get_3bet_size(open_size: float, is_ip: bool) -> float:
    # IP: 3x, OOP: 4x
    multiplier = 3.0 if is_ip else 4.0
    return max(open_size * multiplier, 0.0)

def _get_4bet_size(last_raise: float, is_ip: bool) -> float:
    # IP: 2.2x-2.4x, OOP: 2.7x-3x (Simpler heuristic: 2.3x IP, 2.7x OOP)
    multiplier = 2.3 if is_ip else 2.7
    return max(last_raise * multiplier, 0.0)

# --- Core Logic ---

def recommend_preflop(features: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    # 1. Parsing
    hero_cards = features.get("hero_hole_cards", [])
    hand_code = normalize_hand_code_preflop(hero_cards)
    hero_pos = str(features.get("hero_position", "BTN")).upper()
    villain_pos = str(features.get("villain_position", "UTG")).upper()

    math_data = ctx.get("math_data", {})
    amount_to_call = float(features.get("amount_to_call", 0.0) or 0.0)
    
    # Position logic
    # Default simplistic HU detection: BTN is IP, BB is OOP (except SB vs BB)
    hero_is_ip = features.get("hero_is_ip")
    if hero_is_ip is None:
        hero_is_ip = (hero_pos == "BTN") or (hero_pos == "BB" and villain_pos == "SB") # BB is IP vs SB

    # [Fix] Handle actions as List (Standard) or Dict (Legacy)
    raw_actions = features.get("actions", [])
    if isinstance(raw_actions, dict):
         preflop_actions = raw_actions.get("preflop", [])
    else:
         preflop_actions = [a for a in raw_actions if isinstance(a, dict) and a.get("street") == "preflop"]
    raise_actions = _extract_preflop_raises(preflop_actions)
    raise_count = len(raise_actions)
    
    # 2. Extract Raise Info
    # Only consider the LAST raise for sizing reference
    last_raise_item = raise_actions[-1] if raise_actions else {}
    last_raise_player = last_raise_item.get("player", "")
    last_raise_amt = last_raise_item.get("amount")

    # If amount is unknown, assume defaults
    if last_raise_amt is None:
        last_raise_amt = 3.0 if raise_count > 0 else 1.0

    # 3. Detect Scenario (Heads-Up Focused + Expanded)
    # RFI: No raises, little to call (blinds)
    is_rfi_spot = (raise_count == 0)

    # ISO Spot: Openers (limpers) > 0 but No Raises
    # Count limps explicitly
    actual_limps = 0
    for act in preflop_actions:
        if act.get("action") in ("call", "limp"):
            actual_limps += 1
            
    # Heuristic: If there are calls, it's an ISO spot (unless we are BB checking)
    is_iso_spot = is_rfi_spot and (actual_limps > 0)
    
    # Special case: BB facing limps -> "Check" or "ISO Raise" strategy.
    # Note: If SB completes, it is a 'call'. So actual_limps > 0 handles checking SB limp too.
    if hero_pos == "BB" and is_iso_spot and amount_to_call == 0.0:
        # BB Option: Limpers exist, we have option
        pass

    # Facing Open: 1 Raise, Opener is Villain
    facing_open = (raise_count == 1) and (last_raise_player != hero_pos)
    
    # Facing 3-Bet: 2 Raises, Last was Villain (meaning Hero opened -> Villain 3bet)
    facing_3bet = (raise_count == 2) and (last_raise_player != hero_pos)

    # Cold 4-Bet: 2 Raises, BUT Hero NOT the Opener
    # e.g. UTG Open, CO 3-bet, Hero BTN acts.
    # raise_count=2, last_player != Hero. Check if Hero was the first raiser?
    is_cold_4bet_spot = False
    if raise_count == 2 and last_raise_player != hero_pos:
        # Check first raiser
        first_raiser = raise_actions[0].get("player", "")
        if first_raiser != hero_pos:
            is_cold_4bet_spot = True
            facing_3bet = False # Override facing_3bet flag

    # Facing 4-Bet+: 3+ Raises
    facing_4bet_plus = (raise_count >= 3) and (last_raise_player != hero_pos)

    # 4. Strategy Execution
    
    # --- A. RFI / ISO ---
    if is_rfi_spot or is_iso_spot:
        # Use ISO/RFI logic
        # For ISO, size up: 3bb + 1bb/limper + 1bb OOP
        range_key = "iso" if is_iso_spot else "RFI"
        rfi_range = ranges.get_preflop_range(range_key, hero_pos)
        
        if hand_code in rfi_range:
            prob = rfi_range[hand_code]
            if weighted_choice({"raise": prob, "fold": 1-prob}) == "raise":
                size = _get_rfi_size(hero_pos)
                if is_iso_spot:
                    # ISO Sizing
                    # Base 3bb + 1bb per limp. If OOP +1bb.
                    base_iso = 3.0 + max(1, actual_limps) # +1bb per limp (min 1)
                    if not hero_is_ip: base_iso += 1.0
                    size = base_iso

                action_label = "ISO Raise" if is_iso_spot else "RFI"
                _mark_preflop_context(ctx, features, "raise")
                return format_output(
                    "preflop", "raise", 0.0, size,
                    [f"{action_label} ({hero_pos}), Size: {size}bb"],
                    ctx, {"raise": prob}, math_data=math_data
                )
        
        # Fold/Check
        if amount_to_call <= 0:
             return format_output(
                "preflop", "check", 0.0, 0.0,
                ["Check Option"], ctx, {"check": 1.0}, math_data=math_data
            )

        _mark_preflop_context(ctx, features, "fold")
        return format_output(
            "preflop", "fold", 0.0, 0.0,
            ["Fold (Not in Range)"],
            ctx, {"fold": 1.0}, math_data=math_data
        )

    # --- B. Cold 4-Bet ---
    if is_cold_4bet_spot:
        hero_range_table = ranges.get_preflop_range("cold_4bet", hero_pos)
        if hand_code in hero_range_table:
             # Cold 4-Bet Logic: Usually strict value
             size = _get_4bet_size(last_raise_amt, hero_is_ip)
             _mark_preflop_context(ctx, features, "raise")
             return format_output(
                "preflop", "raise", 0.0, size,
                [f"Cold 4-Bet! (Strong Range only). Size: {size:.1f}bb"],
                ctx, {"raise": 1.0}, math_data=math_data
            )
        # Fold
        return format_output(
            "preflop", "fold", 0.0, 0.0,
            ["Fold vs 3-Bet Cold"], ctx, {"fold": 1.0}, math_data=math_data
        )

    # --- C. Facing Open ---
    if facing_open:
        # Lookup range: Facing Open
        # range keys are typically "facing_open"
        hero_range_table = ranges.get_preflop_range("facing_open", hero_pos, villain_pos)
        # Table format: {hand: {'raise': 0.x, 'call': 0.y}}
        
        if hand_code in hero_range_table:
            action_probs = hero_range_table[hand_code]
            chosen = weighted_choice(action_probs)
            
            _mark_preflop_context(ctx, features, chosen)
            
            if chosen == "raise":
                size = _get_3bet_size(last_raise_amt, hero_is_ip)
                return format_output(
                    "preflop", "raise", 0.0, size,
                    [f"3-Bet vs Open ({'IP' if hero_is_ip else 'OOP'}). Size: {size:.1f}bb"],
                    ctx, action_probs, math_data=math_data
                )
            elif chosen == "call":
                return format_output(
                    "preflop", "call", 0.0, amount_to_call,
                    ["Flat Call vs Open"],
                    ctx, action_probs, math_data=math_data
                )
        
        # Fold
        _mark_preflop_context(ctx, features, "fold")
        return format_output(
            "preflop", "fold", 0.0, 0.0,
            ["Fold vs Open"], ctx, {"fold": 1.0}, math_data=math_data
        )

    # --- C. Facing 3-Bet ---
    if facing_3bet:
        hero_range_table = ranges.get_preflop_range("facing_3bet", hero_pos, villain_pos)
        
        if hand_code in hero_range_table:
            action_probs = hero_range_table[hand_code]
            chosen = weighted_choice(action_probs)
            # In facing_3bet range, 'raise' Usually means 4-Bet
            
            _mark_preflop_context(ctx, features, chosen)

            if chosen == "raise": # 4-Bet
                size = _get_4bet_size(last_raise_amt, hero_is_ip)
                return format_output(
                    "preflop", "raise", 0.0, size,
                    [f"4-Bet vs 3-Bet. Size: {size:.1f}bb"],
                    ctx, action_probs, math_data=math_data
                )
            elif chosen == "call":
                return format_output(
                    "preflop", "call", 0.0, amount_to_call,
                    ["Defend Call vs 3-Bet"],
                    ctx, action_probs, math_data=math_data
                )
        
        # Fold (Overfold check?)
        # For now, standard fold logic
        return format_output(
            "preflop", "fold", 0.0, 0.0,
            ["Fold vs 3-Bet"], ctx, {"fold": 1.0}, math_data=math_data
        )

    # --- D. Facing 4-Bet+ (Fallback) ---
    if facing_4bet_plus:
        # Fallback simplistic hardcoded logic 
        # (Since we don't have deep range tables for 5bet+)
        is_jam_territory = (amount_to_call > 20) or (features.get("hero_stack_bb", 100) < 40)
        
        if hand_code in _FACING_4BET_RAISE:
            # All-in usually at this depth
            return format_output(
                "preflop", "raise", 0.0, 9999.0, # All-in signal
                ["5-Bet / Jam Value (KK+, AK)"],
                ctx, {"raise": 1.0}, math_data=math_data
            )
        if hand_code in _FACING_4BET_CALL and not is_jam_territory:
             return format_output(
                "preflop", "call", 0.0, amount_to_call,
                ["Call 4-Bet"],
                ctx, {"call": 1.0}, math_data=math_data
            )

        return format_output(
            "preflop", "fold", 0.0, 0.0,
            ["Fold vs 4-Bet+"], ctx, {"fold": 1.0}, math_data=math_data
        )

    # Fallback default
    return format_output(
        "preflop", "fold", 0.0, 0.0,
        ["Unspecified Scenario -> Fold"], ctx, {"fold": 1.0}, math_data=math_data
    )

def _mark_preflop_context(ctx: Dict[str, Any], features: Dict[str, Any], decided_action: str) -> None:
    if ctx is None:
        return
    if decided_action == "raise":
        ctx["preflop_aggressor"] = "hero"
    elif decided_action == "call":
        ctx["preflop_aggressor"] = "villain"
