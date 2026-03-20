import unittest
import warnings

from strategy.engine import recommend_action
from strategy.ranges.range_utils import apply_action_history_to_ranges
from strategy.streets.postflop_utils import build_board_transition


def _base_features(street, board_cards, amount_to_call=0.0):
    return {
        "street": street,
        "hero_position": "BTN",
        "villain_position": "BB",
        "hero_is_ip": True,
        "hero_hole_cards": ["As", "Kd"],
        "board_cards": list(board_cards),
        "pot_bb": 5.5,
        "hero_stack_bb": 97.5,
        "amount_to_call": amount_to_call,
        "actions": {
            "preflop": [
                {"player": "BTN", "action": "open", "size_bb": 2.5},
                {"player": "BB", "action": "call", "size_bb": 2.5},
            ],
        },
    }


class StrategyRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=FutureWarning)

    def test_direct_flop_cbet_opportunity(self):
        features = _base_features("flop", ["Ah", "7c", "2d"])
        features["actions"]["flop"] = [{"player": "BB", "action": "check"}]

        result = recommend_action(features)
        ctx = result["context"]

        self.assertEqual(result["recommended_action"], "bet")
        self.assertEqual(ctx["line_state"], "cbet_opportunity")
        self.assertTrue(ctx["checked_to_hero"])
        self.assertEqual(ctx["initiative_owner"], "hero")

    def test_direct_turn_delayed_cbet_uses_previous_board(self):
        features = _base_features("turn", ["Ah", "7c", "2d", "Qc"])
        features["actions"]["flop"] = [
            {"player": "BB", "action": "check"},
            {"player": "BTN", "action": "check"},
        ]
        features["actions"]["turn"] = [{"player": "BB", "action": "check"}]

        result = recommend_action(features)
        ctx = result["context"]
        transition = ctx["board_transition"]

        self.assertEqual(result["recommended_action"], "bet")
        self.assertEqual(ctx["line_state"], "delayed_cbet_opportunity")
        self.assertEqual(transition["new_card"], "Qc")
        self.assertEqual(transition["previous_board_cards"], ["Ah", "7c", "2d"])

    def test_direct_river_triple_barrel_opportunity(self):
        features = _base_features("river", ["Ah", "7c", "2d", "Qc", "9c"])
        features["pot_bb"] = 40.5
        features["hero_stack_bb"] = 80.0
        features["actions"]["flop"] = [
            {"player": "BB", "action": "check"},
            {"player": "BTN", "action": "bet", "size_bb": 1.75},
            {"player": "BB", "action": "call", "size_bb": 1.75},
        ]
        features["actions"]["turn"] = [
            {"player": "BB", "action": "check"},
            {"player": "BTN", "action": "bet", "size_bb": 4.5},
            {"player": "BB", "action": "call", "size_bb": 4.5},
        ]
        features["actions"]["river"] = [{"player": "BB", "action": "check"}]

        result = recommend_action(features)
        ctx = result["context"]

        self.assertEqual(ctx["line_state"], "triple_barrel_opportunity")
        self.assertTrue(ctx["board_transition"]["has_scare"])

    def test_board_transition_detects_flush_completion(self):
        transition = build_board_transition(
            {"board_cards": ["Ah", "7c", "2c", "Qc"]},
            ["Ah", "7c", "2c", "Qc", "9c"],
        )

        self.assertEqual(transition["new_card"], "9c")
        self.assertTrue(transition["completes_flush"])
        self.assertTrue(transition["has_scare"])
        self.assertIn("flush", transition["scare_tags"])

    def test_postflop_actions_shrink_both_ranges(self):
        baseline = _base_features("flop", ["Ah", "7c", "2d"])
        baseline["actions"]["flop"] = [{"player": "BB", "action": "check"}]

        acted = _base_features("flop", ["Ah", "7c", "2d"])
        acted["actions"]["flop"] = [
            {"player": "BB", "action": "check"},
            {"player": "BTN", "action": "bet", "size_bb": 1.75},
            {"player": "BB", "action": "call", "size_bb": 1.75},
        ]

        hero_before, villain_before = apply_action_history_to_ranges(baseline, baseline["board_cards"])
        hero_after, villain_after = apply_action_history_to_ranges(acted, acted["board_cards"])

        self.assertLess(sum(hero_after.values()), sum(hero_before.values()))
        self.assertLess(sum(villain_after.values()), sum(villain_before.values()))


if __name__ == "__main__":
    unittest.main()
