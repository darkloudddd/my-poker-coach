# features package
# Thin aggregator: re-export card utilities and context parser

from .cards import (  # noqa: F401
    RANKS,
    SUITS,
    RANK_VALUE,
    get_rank_value,
    parse_card,
    parse_hand_string,
    canonicalize_hand,
    analyze_board,
)


def parse_poker_situation(*args, **kwargs):  # noqa: F401
    from .context import parse_poker_situation as _parse_poker_situation

    return _parse_poker_situation(*args, **kwargs)

__all__ = [
    "RANKS",
    "SUITS",
    "RANK_VALUE",
    "get_rank_value",
    "parse_card",
    "parse_hand_string",
    "canonicalize_hand",
    "analyze_board",
    "parse_poker_situation",
]
