"""Narrow game-to-math boundary; canonical Math adapters can replace the draft adapter."""
from ganesha.math.config import CONFIG
from ganesha.math.engine import board_from_stops, evaluate_board, free_spins_awarded


class DraftMathPort:
    """Local research adapter only. Its inputs are not canonical or Provider-approved."""
    authority_status = "DRAFT_ONLY_NOT_RELEASE_EVIDENCE"
    version = CONFIG.version

    def evaluate_stops(self, stops, mode):
        return evaluate_board(board_from_stops(stops), mode)

    def award_free_spins(self, scatter_count, retrigger=False):
        return free_spins_awarded(scatter_count, retrigger=retrigger)
