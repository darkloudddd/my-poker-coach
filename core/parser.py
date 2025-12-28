"""
Core parsing logic for text, numbers, and poker actions.
Consolidates logic previously in features/context.py and strategy/pot.py.
"""
from typing import Any, Optional, Dict
import re

# ==============================================================================
# Constants & Maps
# ==============================================================================

ZH_NUM_MAP = {
    "零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, 
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

_AMOUNT_KEYS = (
    "amount", "amount_to", "to", "size", 
    "amount_ratio", "pot_ratio", "ratio", 
    "amount_pct", "size_pct"
)

# ==============================================================================
# Number & Ratio Parsing
# ==============================================================================

def parse_zh_number(text: Any) -> Optional[int]:
    """Parse Chinese number (e.g. '二十五') to int."""
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    raw = raw.replace("兩", "二")
    if raw == "十":
        return 10
    if "十" in raw:
        parts = raw.split("十", 1)
        tens = 1 if parts[0] == "" else ZH_NUM_MAP.get(parts[0])
        if tens is None:
            return None
        ones = ZH_NUM_MAP.get(parts[1], 0) if parts[1] else 0
        if ones is None:
            return None
        return tens * 10 + ones
    if len(raw) == 1:
        return ZH_NUM_MAP.get(raw)
    return None

def extract_ratio(value: Any) -> Optional[float]:
    """Extract ratio/percentage from string (e.g. '50%', 'half pot', '1/3')."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return None
    text = str(value).strip().lower()
    if not text:
        return None


    # Try specific Chinese fractional pattens first (e.g. 7成半)
    zh_cheng_match = re.search(r"([一二三四五六七八九十兩\d]+)\s*成半?", text)
    if zh_cheng_match:
        base = parse_zh_number(zh_cheng_match.group(1))
        if base is not None:
            ratio = base / 10.0
            if "成半" in zh_cheng_match.group(0):
                ratio += 0.05
            return ratio

    if "半" in text or "一半" in text or "half" in text:
        return 0.5

    if "全池" in text or "滿池" in text:
        return 1.0


    percent_match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if percent_match:
        return float(percent_match.group(1)) / 100.0

    frac_match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if frac_match:
        denom = float(frac_match.group(2))
        if denom > 0:
            return float(frac_match.group(1)) / denom

    zh_frac_match = re.search(r"([一二三四五六七八九十兩\d]+)\s*分之\s*([一二三四五六七八九十兩\d]+)", text)
    if zh_frac_match:
        denom = parse_zh_number(zh_frac_match.group(1))
        numer = parse_zh_number(zh_frac_match.group(2))
        if denom is not None and denom > 0 and numer is not None:
            return numer / denom



    if "pot" in text or "池" in text:
        num_match = re.search(r"(\d+(?:\.\d+)?)", text)
        if num_match:
            val = float(num_match.group(1))
            if val > 1.0:
                if val <= 5.0:
                    return val
                if val <= 100:
                    return val / 100.0
                return None
            return val

    return None

def coerce_amount(value: Any) -> Optional[float]:
    """Coerce various number formats to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).strip().lower().replace("bb", "")
    try:
        return float(raw)
    except ValueError:
        return None

# ==============================================================================
# Token & Action Normalization
# ==============================================================================

def normalize_action_token(token: Any) -> str:
    """Normalize poker action verbs (e.g. 'cbet' -> 'bet')."""
    if token is None:
        return ""
    t = str(token).lower().strip()
    if t in {"cbet", "c-bet", "donk", "lead", "下注", "打", "open"}:
        return "bet"
    if t in {"加注", "3bet", "3-bet", "4bet", "reraise", "re-raise", "all-in", "allin", "shove"}:
        return "raise"
    if t in {"跟注", "call"}:
        return "call"
    if t in {"過牌", "check"}:
        return "check"
    if t in {"棄牌", "蓋牌", "fold"}:
        return "fold"
    if t in {"limp"}:
        return "limp"
    return t

# ==============================================================================
# Structure Parsing
# ==============================================================================

def get_amount_from_dict(action: Dict[str, Any]) -> Optional[float]:
    """Extract explicit amount from action dict."""
    for key in ("amount", "amount_to", "to", "size"):
        if key in action:
            amt = coerce_amount(action.get(key))
            if amt is not None:
                return amt
    return None

def get_ratio_from_dict(action: Dict[str, Any]) -> Optional[float]:
    """Extract ratio/percentage from action dict."""
    for key in ("amount_ratio", "pot_ratio", "ratio"):
        if key in action:
            val = action.get(key)
            if isinstance(val, (int, float)):
                return float(val)
            ratio = extract_ratio(val)
            if ratio is not None:
                return ratio

    # Some models might put percent in amount_pct
    for key in ("amount_pct", "size_pct"):
        if key in action:
            val = action.get(key)
            if isinstance(val, (int, float)):
                return float(val) / 100.0
            ratio = extract_ratio(val)
            if ratio is not None:
                return ratio
    
    # Fallback: check standard amount fields for ratio-like strings
    for key in ("amount", "amount_to", "to", "size"):
        if key in action:
            ratio = extract_ratio(action.get(key))
            if ratio is not None:
                return ratio
    return None

def resolve_amount(action: Dict[str, Any], pot: float, big_blind: float) -> Optional[float]:
    """
    Determine the actual chip amount for an action, resolving ratios if needed.
    """
    amount = get_amount_from_dict(action)
    if amount is not None:
        return amount

    ratio = get_ratio_from_dict(action)
    if ratio is not None and pot > 0:
        return pot * ratio

    act = normalize_action_token(action.get("action", ""))
    if act == "limp":
        return float(big_blind)

    return None

def action_has_amount(action: Any) -> bool:
    """Check if action dict has any amount/size fields."""
    if not isinstance(action, dict):
        return False
    for key in _AMOUNT_KEYS:
        if key not in action:
            continue
        val = action.get(key)
        if val is None:
            continue
        if isinstance(val, (int, float)):
            if float(val) > 0:
                return True
            continue
        if str(val).strip():
            return True
    return False
