# strategy/eval/hand_eval.py
from typing import List, Tuple, Optional
from collections import Counter

try:
    from features import RANK_VALUE
except ImportError:
    RANK_VALUE = {r: i for i, r in enumerate("23456789TJQKA", start=2)}


def _parse_cards(cards: List[str]) -> List[Tuple[int, str]]:
    res: List[Tuple[int, str]] = []
    for c in cards or []:
        if not c:
            continue
        c = str(c).strip()
        if len(c) == 2:
            r_char = c[0].upper()
            suit = c[1].lower()
        elif len(c) == 3 and c.startswith("10"):
            r_char = "T"
            suit = c[2].lower()
        else:
            continue
        if r_char not in RANK_VALUE:
            continue
        res.append((RANK_VALUE[r_char], suit))
    return res


def _detect_straight(ranks: List[int]) -> Optional[Tuple[int, List[int]]]:
    if len(ranks) < 5:
        return None
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    for i in range(len(unique) - 4):
        window = unique[i:i + 5]
        if window[0] - window[4] == 4 and len(set(window)) == 5:
            high = 5 if window[0] == 5 and window[4] == 1 else window[0]
            return high, window
    return None


def _detect_straight_draw(all_ranks: List[int], hero_ranks: List[int]) -> Tuple[bool, bool]:
    ranks = set(all_ranks)
    hero = set(hero_ranks)
    if 14 in ranks:
        ranks.add(1)
    if 14 in hero:
        hero.add(1)
    for high in range(14, 4, -1):
        seq = {high, high - 1, high - 2, high - 3, high - 4}
        present = seq & ranks
        if len(present) == 4 and (seq & hero):
            missing = list(seq - present)[0]
            is_oesd = missing in {high, high - 4}
            return True, is_oesd
    return False, False


def _detect_flush_draw(
    hero_vals: List[Tuple[int, str]],
    all_vals: List[Tuple[int, str]],
) -> Tuple[bool, bool]:
    suit_counts = Counter([s for _, s in all_vals])
    for suit, count in suit_counts.items():
        if count == 4:
            hero_suited = [r for r, s in hero_vals if s == suit]
            if hero_suited:
                is_nut = max(hero_suited) == 14
                return True, is_nut
    return False, False


def calculate_hand_strength(hero_hole: List[str], board: List[str]) -> Tuple[str, str]:
    """
    分析手牌與公牌，回傳 (category, details)
    例如: ("set", "top_set"), ("draw", "flush_draw")
    """
    if not hero_hole:
        return "air", "no_cards"

    hero_vals = _parse_cards(hero_hole)
    board_vals = _parse_cards(board)

    if not board_vals:
        return _analyze_preflop(hero_vals)

    all_vals = hero_vals + board_vals
    hero_ranks = [r for r, _ in hero_vals]
    board_ranks = [r for r, _ in board_vals]
    all_ranks = hero_ranks + board_ranks

    rank_counts = Counter(all_ranks)
    board_counts = Counter(board_ranks)
    hero_counts = Counter(hero_ranks)
    board_unique = sorted(set(board_ranks), reverse=True)
    board_is_paired = any(c >= 2 for c in board_counts.values())

    suit_to_ranks = {}
    for r, s in all_vals:
        suit_to_ranks.setdefault(s, []).append(r)

    # Straight flush
    for suit, ranks in suit_to_ranks.items():
        if len(ranks) >= 5:
            straight = _detect_straight(ranks)
            if straight:
                _, seq = straight
                hero_in_sf = any((s == suit and r in seq) for r, s in hero_vals)
                detail = "made_straight_flush" if hero_in_sf else "board_straight_flush"
                return "straight_flush", detail

    # Quads
    quads = [r for r, c in rank_counts.items() if c == 4]
    if quads:
        quad_rank = quads[0]
        if hero_counts.get(quad_rank, 0) > 0:
            return "quads", "quads"
        return "quads", "board_quads"

    # Full house
    trips = sorted([r for r, c in rank_counts.items() if c == 3], reverse=True)
    pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
    if trips and (pairs or len(trips) >= 2):
        trip_rank = trips[0]
        pair_rank = pairs[0] if pairs else trips[1]
        hero_involved = hero_counts.get(trip_rank, 0) > 0 or hero_counts.get(pair_rank, 0) > 0
        detail = "full_house" if hero_involved else "board_full_house"
        return "full_house", detail

    # Flush
    for suit, ranks in suit_to_ranks.items():
        if len(ranks) >= 5:
            hero_suited = [r for r, s in hero_vals if s == suit]
            if not hero_suited:
                return "flush", "board_flush"
            detail = "nut_flush" if max(hero_suited) == 14 else "made_flush"
            return "flush", detail

    # Straight
    straight = _detect_straight(all_ranks)
    if straight:
        high, seq = straight
        board_straight = _detect_straight(board_ranks)
        hero_rank_set = set(hero_ranks)
        if 14 in hero_rank_set:
            hero_rank_set.add(1)
        hero_in_seq = any(r in hero_rank_set for r in seq)
        if board_straight and board_straight[0] >= high and not hero_in_seq:
            detail = "board_straight"
        else:
            detail = "made_straight"
        return "straight", detail

    # Trips / Set
    if trips:
        trip_rank = trips[0]
        if hero_counts.get(trip_rank, 0) == 2:
            return "set", "set"
        if hero_counts.get(trip_rank, 0) == 1:
            return "set", "trips"
        return "set", "board_trips"

    # Two pair
    if len(pairs) >= 2:
        pair_ranks = sorted(pairs, reverse=True)
        hero_pair_ranks = [r for r in pair_ranks if hero_counts.get(r, 0) > 0]
        board_pair_ranks = [r for r in pair_ranks if board_counts.get(r, 0) > 0]
        if len(board_pair_ranks) >= 2 and not hero_pair_ranks:
            return "two_pair", "board_two_pair"
        if len(board_pair_ranks) == 1 and len(hero_pair_ranks) == 1:
            top_board = board_unique[0] if board_unique else 0
            detail = "top_and_board" if hero_pair_ranks[0] == top_board else "pair_and_board"
            return "two_pair", detail
        return "two_pair", "two_pair"

    # One pair
    if pairs:
        pair_rank = pairs[0]
        if hero_counts.get(pair_rank, 0) == 2:
            if board_unique and pair_rank > board_unique[0]:
                return "overpair", "overpair"
            if board_unique and pair_rank < board_unique[-1]:
                return "bottom_pair", "underpair"
            return "middle_pair", "pocket_pair"
        if hero_counts.get(pair_rank, 0) == 1:
            if board_unique and pair_rank == board_unique[0]:
                kicker = max([r for r in hero_ranks if r != pair_rank], default=0)
                detail = "top_kicker" if kicker >= 13 else "weak_kicker"
                if board_is_paired:
                    detail = f"board_pair_{detail}"
                return "top_pair", detail
            if board_unique and pair_rank > board_unique[-1]:
                return "middle_pair", "middle_pair"
            return "bottom_pair", "bottom_pair"
        if board_counts.get(pair_rank, 0) >= 2:
            return "bottom_pair", "board_pair"

    # Draws
    is_fd, is_nut_fd = _detect_flush_draw(hero_vals, all_vals)
    is_sd, is_oesd = _detect_straight_draw(all_ranks, hero_ranks)
    if is_fd and is_sd:
        return "draw", "combo_draw"
    if is_fd:
        return "draw", "nut_flush_draw" if is_nut_fd else "flush_draw"
    if is_sd:
        return "draw", "open_straight_draw" if is_oesd else "gutshot_draw"

    return "air", "high_card"


def _analyze_preflop(hero_vals):
    r1, r2 = hero_vals[0][0], hero_vals[1][0]
    if r1 == r2:
        return "pair", "pocket_pair"
    if r1 >= 13 and r2 >= 13:
        return "high_card", "premium"
    return "high_card", ""
