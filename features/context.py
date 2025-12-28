"""
Context / situation parsing extracted from agent.py
"""
from __future__ import annotations

import json
import re
import traceback
from typing import Dict, Any, List, Union

from .cards import parse_hand_string, normalize_card_input
from core.parser import (
    normalize_action_token,
    resolve_amount,
    action_has_amount,
)
from services.prompts import EXTRACTOR_SYSTEM_PROMPT
from services.llm_client import call_llm
from strategy.pot import compute_pot_bb, compute_amount_to_call


# ==========================================
# 解析輔助函式
# ==========================================




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

    state_prompt = ""
    if current_state:
        filtered_keys = [
            "hero_hole_cards",
            "board_cards",
            "actions",
            "hero_position",
            "villain_position",
            "pot_bb",
            "hero_stack_bb",
            "villain_stack_bb",
            "street",
            "is_3bet_pot",
            "villain_action",
        ]
        filtered_state = {k: v for k, v in current_state.items() if k in filtered_keys}
        state_prompt = f"【上一手狀態】: {json.dumps(filtered_state)}\n"

    user_message = f"{state_prompt}【用戶新指令】: {user_input}"

    json_str = call_llm(EXTRACTOR_SYSTEM_PROMPT, user_message)
    json_str = json_str.replace("```json", "").replace("```", "").strip()

    data = None
    try:
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            lines = json_str.splitlines()
            for line in lines:
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        break
                    except Exception:
                        continue

        if not data:
            print("解析失敗，LLM 回傳了什麼？")
            print(json_str)
            raise ValueError("無法解析 LLM 回應 (JSON 格式錯誤 或 為空)")

        if isinstance(data, list):
            print("(偵測到多個情境，將只分析第一手牌)")
            data = data[0] if data else {}

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        missing_fields = meta.get("missing_fields") or data.get("missing_fields") or []
        if "error" in data:
            raise ValueError(f"解析錯誤: {data['error']}")

        if missing_fields:
            # Filter out missing fields that can be inferred (specifically 'call' amounts)
            # The LLM might flag "actions.preflop.call.amount" as missing, but our logic computes it.
            real_missing = []
            for field in missing_fields:
                f_str = str(field).lower()
                # If it's a Call or Check action, we don't need the amount typically
                if "call.amount" in f_str or "check.amount" in f_str:
                    continue
                # Also if it's just "actions" but we actually have actions, ignore it? 
                # No, "actions" usually means the whole list is empty.
                real_missing.append(field)
            
            if real_missing:
                # [FIX]: Check if we have these fields in current_state specific logic
                final_missing = []
                for field in real_missing:
                    # Map field names from LLM to current_state keys
                    state_key = field
                    if field == "hero.cards" or field == "hero_hole_cards": state_key = "hero_hole_cards"
                    elif field == "board.cards" or field == "board_cards": state_key = "board_cards"
                    elif field == "hero.stack_bb" or field == "hero_stack_bb": state_key = "hero_stack_bb"
                    elif field == "villain.stack_bb" or field == "villain_stack_bb": state_key = "villain_stack_bb"
                    elif field == "hero.position" or field == "hero_position": state_key = "hero_position"
                    elif field == "villain.position" or field == "villain_position": state_key = "villain_position"
                    
                    # If current_state has it, we are good
                    val = current_state.get(state_key) if current_state else None
                    if val is not None and val != [] and val != "":
                        continue
                    
                    final_missing.append(field)

                if final_missing:
                    raise ValueError(f"資訊不足，請補充: {', '.join(map(str, final_missing))}")

        required_fields = [
            "hero_position",
            "villain_position",
            "hero_hole_cards",
            "hero_stack_bb",
            "villain_stack_bb",
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

        players = data.get("players") if isinstance(data.get("players"), dict) else {}
        hero_info = players.get("hero") if isinstance(players.get("hero"), dict) else {}
        villain_info = players.get("villain") if isinstance(players.get("villain"), dict) else {}

        if current_state is None:
            current_state = {}

        hero_pos = hero_info.get("position") or data.get("hero_position") or current_state.get("hero_position")
        villain_pos = villain_info.get("position") or data.get("villain_position") or current_state.get("villain_position")
        
        # Stacks: 0 is valid, so check for None explicitly
        hero_stack = hero_info.get("stack_bb")
        if hero_stack is None: hero_stack = data.get("hero_stack_bb")
        if hero_stack is None: hero_stack = current_state.get("hero_stack_bb")

        villain_stack = villain_info.get("stack_bb")
        if villain_stack is None: villain_stack = data.get("villain_stack_bb")
        if villain_stack is None: villain_stack = current_state.get("villain_stack_bb")

        hero_cards = hero_info.get("cards") or data.get("hero_hole_cards") or current_state.get("hero_hole_cards") or []

        board = data.get("board") if isinstance(data.get("board"), dict) else {}
        board_cards = board.get("cards") or data.get("board_cards") or current_state.get("board_cards") or []

        hero_cards = normalize_card_input(hero_cards)
        board_cards = normalize_card_input(board_cards)

        board_len = len(board_cards)
        street_map = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
        derived_street = street_map.get(board_len)
        street = data.get("street") or derived_street
        if derived_street:
            street = derived_street

        raw_actions = data.get("actions", [])
        if not raw_actions and current_state:
             raw_actions = current_state.get("actions", [])

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
                data["villain_action"] = inferred or "check"

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

        return data

    except ValueError:
        raise
    except Exception as e:
        print(f"數據處理錯誤 (Phase 1): {e}")
        traceback.print_exc()
        raise ValueError(f"系統發生未預期錯誤: {str(e)}")
