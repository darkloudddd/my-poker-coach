from typing import List, Dict, Tuple, Any, Optional

# ==============================================================================
# 0. Imports & Setup
# ==============================================================================
from ..utils import (
    calculate_hand_strength, 
    RANKS, 
    SUITS
)
from features import canonicalize_hand
from .range_data import RFI_RANGES, FACING_OPEN, FACING_3BET, COLD_4BET

def _canonicalize_hand_code(code: str) -> str:
    """使用 features.canonicalize_hand 統一格式，保留原始值作為 fallback。"""
    if not code:
        return ""
    normalized = canonicalize_hand(str(code))
    return normalized if normalized else str(code)

def _canonicalize_hand_list(hand_list: List[str]) -> List[str]:
    if not hand_list:
        return []
    canon = [_canonicalize_hand_code(x) for x in hand_list if x]
    seen = set()
    out = []
    for x in canon:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _canonicalize_weighted_range(weighted: Dict[str, float]) -> Dict[str, float]:
    if not weighted:
        return {}
    out: Dict[str, float] = {}
    for k, v in weighted.items():
        out[_canonicalize_hand_code(k)] = float(v)
    return out

def _canonicalize_facing_open(table: Dict[str, Any]) -> Dict[str, Any]:
    if not table:
        return {}
    out: Dict[str, Any] = {}
    for defender_pos, sub in table.items():
        out[defender_pos] = {}
        for opener_pos, ranges in (sub or {}).items():
            out[defender_pos][opener_pos] = {}
            for act, hands in (ranges or {}).items():
                out[defender_pos][opener_pos][act] = _canonicalize_hand_list(hands) if isinstance(hands, list) else hands
    return out

def _canonicalize_facing_3bet(table: Dict[str, Any]) -> Dict[str, Any]:
    if not table:
        return {}
    out: Dict[str, Any] = {}
    for opener_pos, sub in table.items():
        out[opener_pos] = {}
        for threebettor_pos, ranges in (sub or {}).items():
            out[opener_pos][threebettor_pos] = {
                "4bet": _canonicalize_hand_list(ranges.get("4bet", [])),
                "call": _canonicalize_hand_list(ranges.get("call", [])),
            }
    return out

# --- Apply canonicalization ---
RFI_RANGES = {pos: _canonicalize_weighted_range(rng) for pos, rng in RFI_RANGES.items()}
FACING_OPEN = _canonicalize_facing_open(FACING_OPEN)
FACING_3BET = _canonicalize_facing_3bet(FACING_3BET)

# ==============================================================================
# 2. Preflop Range Lookup (for preflop solver)
# ==============================================================================

def _build_action_map(raise_hands, call_hands):
    out = {}
    for hand in raise_hands or []:
        out[hand] = {"raise": 1.0}
    for hand in call_hands or []:
        if hand in out:
            out[hand]["call"] = 1.0
        else:
            out[hand] = {"call": 1.0}
    return out


def get_preflop_range(range_type: str, hero_pos: str, villain_pos: str = None):
    'Return preflop ranges for RFI or facing actions.'
    rtype = str(range_type or "").strip().lower()
    hero = str(hero_pos or "").upper()
    villain = str(villain_pos or "").upper()

    if rtype in {"rfi", "open", "raise"}:
        return RFI_RANGES.get(hero, {})

    if rtype in {"iso"}:
        # Reuse RFI range for ISO, but maybe tighter logic can be added later
        return RFI_RANGES.get(hero, {})

    if rtype in {"cold_4bet", "cold4bet"}:
        table = COLD_4BET.get(hero, {})
        return _build_action_map(table.get("4bet", []), table.get("call", []))

    if rtype in {"facing_open", "facing", "vs_open"}:
        table = FACING_OPEN.get(hero, {}).get(villain, {})
        return _build_action_map(table.get("3bet", []), table.get("call", []))

    if rtype in {"facing_3bet", "facing3bet", "vs_3bet"}:
        table = FACING_3BET.get(hero, {}).get(villain, {})
        return _build_action_map(table.get("4bet", []), table.get("call", []))

    return {}

# ==============================================================================
# 3. Range Analyzer Class
# ==============================================================================

class RangeAnalyzer:
    """
    核心範圍處理類，進化為基於 1326 種具體組合 (Combos) 的精確計數系統。
    這允許考慮精確的阻擋牌效應 (Card Removal)。
    """
    
    def __init__(self):
        # 1326 種組合的完整映射 (HandCode -> List of Combos)
        self._hand_code_to_combos: Dict[str, List[Tuple[str, str]]] = self._generate_all_combos_map()
        # 反向映射 (Combo -> HandCode)
        self._combo_to_hand_code: Dict[Tuple[str, str], str] = self._generate_reverse_combo_map()
        
    def _generate_all_combos_map(self) -> Dict[str, List[Tuple[str, str]]]:
        """
        生成並映射所有 1326 種手牌組合。
        Key 格式範例: 'AA', 'AKs', 'AKo'
        """
        all_combos = {}
        ordered_ranks = "23456789TJQKA"
        current_suits = SUITS

        for i in range(len(ordered_ranks)):
            for j in range(len(ordered_ranks)):
                r1 = ordered_ranks[i]
                r2 = ordered_ranks[j]
                
                # 1. 對子
                if i == j:
                    key = r1 + r1
                    if key not in all_combos: all_combos[key] = []
                    for s1_idx in range(len(current_suits)):
                        for s2_idx in range(s1_idx + 1, len(current_suits)):
                            # 排序以保證一致性
                            c1, c2 = r1 + current_suits[s1_idx], r1 + current_suits[s2_idx]
                            all_combos[key].append(tuple(sorted((c1, c2))))
                            
                # 2. 非對子
                elif i > j:
                    high, low = r1, r2
                    key_s = high + low + "s"
                    key_o = high + low + "o"
                    
                    if key_s not in all_combos: all_combos[key_s] = []
                    if key_o not in all_combos: all_combos[key_o] = []
                    
                    for s1 in current_suits:
                        for s2 in current_suits:
                            combo = tuple(sorted((high + s1, low + s2)))
                            if s1 == s2:
                                all_combos[key_s].append(combo)
                            else:
                                if combo not in all_combos[key_o]:
                                    all_combos[key_o].append(combo)
        return all_combos

    def _generate_reverse_combo_map(self) -> Dict[Tuple[str, str], str]:
        mapping = {}
        for code, combos in self._hand_code_to_combos.items():
            for combo in combos:
                mapping[combo] = code
        return mapping
        
    def get_hand_combos(self, hand_code: str) -> Optional[List[Tuple[str, str]]]:
        if not hand_code: return None
        clean_code = hand_code.upper()
        if len(clean_code) == 3:
            clean_code = clean_code[:2] + clean_code[2].lower()
        return self._hand_code_to_combos.get(clean_code)

    def convert_weighted_range_to_combos(
        self, 
        weighted_range: Dict[str, float], 
        dead_cards: Optional[set] = None
    ) -> Dict[Tuple[str, str], float]:
        """將 HandCode 的權重範圍展開為具體的 1326 組合權重"""
        combo_range = {}
        dead_cards = dead_cards or set()
        
        for code, weight in weighted_range.items():
            combos = self.get_hand_combos(code)
            if not combos: continue
            
            # 分配權重給每個殘存組合
            valid_combos = [c for c in combos if c[0] not in dead_cards and c[1] not in dead_cards]
            if not valid_combos: continue
            
            # 權重應按比例分配 (如果總組合 6 個，剩 3 個，權重減半)
            # 但在 GTO 範圍中，我們通常保留原始權重直到被 Action 殺死
            # 這裡採用 standard normalization:
            for combo in valid_combos:
                combo_range[combo] = weight
        return combo_range

    def get_preflop_weighted_range(self, hero_pos: str, villain_pos: str, action: str = 'RFI') -> Dict[str, float]:
        """根據位置與行動獲取 Preflop 範圍權重"""
        weighted_range: Dict[str, float] = {}

        if action == 'RFI':
            if hero_pos in RFI_RANGES:
                return RFI_RANGES[hero_pos]

        elif action in ['3bet', 'call']:
            if hero_pos in FACING_OPEN and villain_pos in FACING_OPEN[hero_pos]:
                hand_list = FACING_OPEN[hero_pos][villain_pos].get(action, [])
                for hand_code in hand_list:
                    weighted_range[hand_code] = 1.0
                return weighted_range

        elif action in ['4bet', 'call_3bet']:
            if hero_pos in FACING_3BET and villain_pos in FACING_3BET[hero_pos]:
                k = '4bet' if action == '4bet' else 'call'
                hand_list = FACING_3BET[hero_pos][villain_pos].get(k, [])
                for hand_code in hand_list:
                    weighted_range[hand_code] = 1.0
                return weighted_range

        return {}
        
    def get_postflop_range_summary(
        self, 
        combo_range: Dict[Tuple[str, str], float], 
        board_cards: List[str]
    ) -> Dict[str, float]:
        """
        基於具體組合權重計算摘要。
        """
        from ..utils import calculate_hand_strength, effective_hand_category
        
        range_summary: Dict[str, float] = {
            "straight_flush": 0.0, "quads": 0.0, "full_house": 0.0, 
            "flush": 0.0, "straight": 0.0, "set": 0.0,
            "two_pair": 0.0, "overpair": 0.0, "top_pair": 0.0,
            "middle_pair": 0.0, "weak_pair": 0.0, "draw": 0.0, "air": 0.0,
            "total_active_combos": 0.0
        }

        if not combo_range: return range_summary
        board_set = set(board_cards)
        
        for combo, weight in combo_range.items():
            # 再次檢查 Dead Cards (Double check)
            if combo[0] in board_set or combo[1] in board_set: continue
            
            try:
                cat, details = calculate_hand_strength(list(combo), board_cards)
                eff_cat = effective_hand_category(cat, details)
                
                if eff_cat in range_summary:
                    range_summary[eff_cat] += weight
                else:
                    range_summary["air"] += weight
                range_summary["total_active_combos"] += weight
            except:
                range_summary["air"] += weight
                range_summary["total_active_combos"] += weight

        return range_summary
        
    def calculate_advantage(
        self,
        hero_combo_range: Dict[Tuple[str, str], float],
        villain_combo_range: Dict[Tuple[str, str], float],
        board_cards: List[str],
        features: Optional[Dict[str, Any]] = None,
        ctx: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        計算 Hero 相對於 Villain 的範圍優勢 (Range Advantage) 與堅果優勢 (Nut Advantage)。
        進化版本：包含權益實現修正 (Realized Advantage)。
        """
        hero_summary = self.get_postflop_range_summary(hero_combo_range, board_cards)
        villain_summary = self.get_postflop_range_summary(villain_combo_range, board_cards)

        def get_score(summary):
            if not summary or summary.get("total_active_combos", 0) == 0: return 0.5
            weights = {
                "straight_flush": 1.2, "quads": 1.1, "full_house": 1.0, 
                "flush": 0.95, "straight": 0.85, "set": 0.8,
                "two_pair": 0.7, "top_pair": 0.6,
                "middle_pair": 0.45, "weak_pair": 0.3, "draw": 0.25, "air": 0.1
            }
            total_freq = summary.get("total_active_combos", 1.0)
            
            score = 0.0
            for cat, freq in summary.items():
                if cat == "total_active_combos": continue
                score += (freq / total_freq) * weights.get(cat, 0.1)
            return score

        def get_nut_count(summary):
            # 堅果類別: Set 以上
            nut_cats = ["straight_flush", "quads", "full_house", "flush", "straight", "set"]
            return sum(summary.get(cat, 0) for cat in nut_cats)

        h_score = get_score(hero_summary)
        v_score = get_score(villain_summary)
        
        range_adv = h_score / v_score if v_score > 0 else 1.0
        
        # 權益實現修正 (Realized Advantage)
        realized_range_adv = range_adv
        h_rf = 1.0
        v_rf = 1.0
        if features and ctx:
            from ..utils import calculate_realization_factor
            hero_pos = features.get("hero_pos", "BTN")
            villain_pos = features.get("villain_pos", "BB")
            hero_is_ip = features.get("hero_is_ip", False)
            board_info = ctx.get("board_info", {})
            spr = ctx.get("spr", 15.0)
            
            h_rf = calculate_realization_factor(hero_pos, hero_is_ip, board_info, spr)
            v_rf = calculate_realization_factor(villain_pos, not hero_is_ip, board_info, spr)
            
            # 使用 R-Factor 比例修正
            realized_range_adv = range_adv * (h_rf / v_rf)

        h_nuts = get_nut_count(hero_summary)
        v_nuts = get_nut_count(villain_summary)
        
        nut_adv = (h_nuts / v_nuts) if v_nuts > 0 else (2.0 if h_nuts > 0 else 1.0)
        
        return {
            "range_advantage": round(range_adv, 2),
            "realized_range_advantage": round(realized_range_adv, 2),
            "nut_advantage": round(min(nut_adv, 5.0), 2),
            "hero_score": round(h_score, 2),
            "villain_score": round(v_score, 2),
            "hero_rf": h_rf,
            "villain_rf": v_rf,
            "hero_summary": hero_summary,
            "villain_summary": villain_summary
        }

    def filter_range_by_action(
        self, 
        base_combo_range: Dict[Tuple[str, str], float], 
        action: str, 
        street: str, 
        board_cards: List[str],
        board_info: Optional[Dict[str, Any]] = None
    ) -> Dict[Tuple[str, str], float]:
        """
        根據玩家行動過濾範圍 (Range Capping)。
        操作對象為 combo_range: Dict[Tuple[str, str], float]
        """
        if not base_combo_range: return {}
        
        from ..utils import calculate_hand_strength, effective_hand_category
        
        if not board_info and board_cards:
            from features import analyze_board
            board_info = analyze_board(board_cards)
        
        conn_score = board_info.get("connectedness_score", 0) if board_info else 0
        is_dynamic = board_info.get("is_dynamic", False) if board_info else False
        is_wet = conn_score >= 60 or is_dynamic
        
        filtered = base_combo_range.copy()
        
        for combo, weight in filtered.items():
            # 獲取該組合的實際牌力
            cat, details = calculate_hand_strength(list(combo), board_cards)
            eff_cat = effective_hand_category(cat, details)

            # 1. CHECK (Capping Logic)
            if action == 'check':
                if eff_cat in ["straight_flush", "quads", "full_house", "flush", "straight", "set"]:
                    penalty = 0.05 if is_wet else 0.2
                    filtered[combo] *= penalty
                elif eff_cat in ["two_pair", "top_pair"]:
                    filtered[combo] *= 0.6 if is_wet else 0.8
                    
            # 2. CALL (Bluff Catcher Logic)
            elif action == 'call':
                if eff_cat in ["straight_flush", "quads", "full_house", "flush", "straight"]:
                    penalty = 0.15 if is_wet else 0.4
                    filtered[combo] *= penalty
                elif eff_cat == "air":
                    filtered[combo] *= 0.4
                    
            # 3. BET / RAISE (Uncapping/Polarization Logic)
            elif action in ['bet', 'raise']:
                if eff_cat in ["middle_pair", "weak_pair"]:
                    filtered[combo] *= 0.4
        
        return filtered

# 初始化 RangeAnalyzer 實例，以便外部調用
RANGE_ANALYZER = RangeAnalyzer()
