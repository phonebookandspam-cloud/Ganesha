"""Deterministic development-only MathPort for exercising the independent runtime.

This adapter is intentionally not canonical Math, does not model probabilities,
and must never be wired to a financial RoundService.
"""
import copy

from ganesha.math.engine import EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule
from ganesha.math.config import WILD


BASE_BOARD = [
    ["A", "SCATTER_LOTUS", "K"],
    ["MOUSE", "A", "SCATTER_LOTUS"],
    ["K", "ELEPHANT", "A"],
    ["SCATTER_LOTUS", "CHAKRA", "MOUSE"],
    ["A", "K", "MODAK"],
]
FEATURE_BOARD = [
    ["A", "K", "CHAKRA"], ["MOUSE", "A", "K"], [WILD, "A", "MODAK"],
    ["K", "CHAKRA", "A"], ["A", "MOUSE", "K"],
]
FEATURE_DISPLAY = copy.deepcopy(FEATURE_BOARD)
FEATURE_DISPLAY[2] = [WILD, WILD, WILD]


class LocalRuntimeMathPort:
    authority_status = "DEVELOPMENT_ONLY_NOT_CANONICAL"
    version = "local-runtime-math-simulation-v1"

    def evaluate_stops(self, stops, mode):
        if mode == "BASE":
            return {"mode": mode, "board": copy.deepcopy(BASE_BOARD),
                    "display_board": copy.deepcopy(BASE_BOARD), "payout_milli": 1000,
                    "raw_payout_milli": 1000, "wild_multiplier": 1,
                    "expanded_wild_reels": [], "max_win_capped": False,
                    "scatter_count": 3, "free_spins_awarded": 10}
        if mode == "FREE_SPINS":
            return {"mode": mode, "board": copy.deepcopy(FEATURE_BOARD),
                    "display_board": copy.deepcopy(FEATURE_DISPLAY), "payout_milli": 50,
                    "raw_payout_milli": 25, "max_win_capped": False,
                    "scatter_count": 0, "expanded_wild_reels": [2],
                    "wild_multiplier": 2, "jackpot_triggered": False}
        raise ValueError("unsupported simulation mode")

    def award_free_spins(self, scatter_count, retrigger=False):
        if type(scatter_count) is not int or not 0 <= scatter_count <= 15:
            raise ValueError("scatter_count must be an integer in [0, 15]")
        if type(retrigger) is not bool:
            raise ValueError("retrigger must be a boolean")
        if retrigger:
            if scatter_count < 3:
                return 0
            raise UnspecifiedMathRule("Free Spins retrigger rules are not user-authorized")
        if scatter_count < 3:
            return 0
        if scatter_count == 3:
            return 10
        if scatter_count == 4:
            return 12
        if scatter_count == 5:
            raise EmbeddedEpicFeatureUnavailable(
                "5 Scatter requires the Provider-authoritative embedded EPIC payload and BASE-unit conversion"
            )
        raise UnspecifiedMathRule("6+ Scatter behavior is unspecified")
