"""Versioned V1 draft math configuration. Payouts are integer milli-bet units."""
from dataclasses import dataclass
from typing import Dict, Tuple

WILD = "WILD_GANESHA"
SCATTER = "SCATTER_LOTUS"
ELEPHANT = "ELEPHANT"
MOUSE = "MOUSE"
MODAK = "MODAK"
CHAKRA = "CHAKRA"
A = "A"
K = "K"
SYMBOLS = (WILD, SCATTER, ELEPHANT, MOUSE, MODAK, CHAKRA, A, K)

# Five independently versioned 13-stop strips. Stop index selects the top row;
# the next two cyclic stops form the middle and bottom rows.
REEL_STRIPS = (
    (WILD, ELEPHANT, A, MOUSE, SCATTER, K, MODAK, ELEPHANT, A, MOUSE, CHAKRA, K, ELEPHANT),
    (ELEPHANT, MOUSE, A, SCATTER, MODAK, K, WILD, A, ELEPHANT, MOUSE, CHAKRA, K, MODAK),
    (MOUSE, ELEPHANT, K, A, SCATTER, MODAK, WILD, MOUSE, A, CHAKRA, ELEPHANT, K, MODAK),
    (A, MOUSE, ELEPHANT, K, MODAK, SCATTER, CHAKRA, WILD, A, MOUSE, ELEPHANT, K, MODAK),
    (K, ELEPHANT, MOUSE, A, CHAKRA, MODAK, SCATTER, WILD, K, ELEPHANT, MOUSE, A, MODAK),
)

# Integer stop weights. Windows that expose Ganesha Wild are deliberately rare;
# this is a designed reel probability model, not a uniform-stop assumption.
STOP_WEIGHTS = (
    (10, 100, 30, 30, 30, 100, 100, 100, 100, 100, 100, 10, 10),
    (100, 30, 30, 30, 10, 10, 10, 100, 100, 100, 100, 100, 100),
    (100, 100, 30, 30, 10, 10, 10, 100, 100, 100, 100, 100, 100),
    (100, 100, 100, 30, 30, 10, 10, 10, 100, 100, 100, 100, 100),
    (100, 100, 100, 100, 30, 10, 10, 10, 100, 100, 100, 100, 100),
)

# Row index per reel, top=0, middle=1, bottom=2. All 20 paths are explicit.
PAYLINES = (
    (1, 1, 1, 1, 1), (0, 0, 0, 0, 0), (2, 2, 2, 2, 2),
    (0, 1, 2, 1, 0), (2, 1, 0, 1, 2), (0, 0, 1, 2, 2),
    (2, 2, 1, 0, 0), (1, 0, 0, 0, 1), (1, 2, 2, 2, 1),
    (0, 1, 1, 1, 0), (2, 1, 1, 1, 2), (1, 0, 1, 2, 1),
    (1, 2, 1, 0, 1), (0, 0, 1, 1, 2), (2, 2, 1, 1, 0),
    (0, 1, 0, 1, 0), (2, 1, 2, 1, 2), (1, 1, 0, 1, 1),
    (1, 1, 2, 1, 1), (0, 2, 0, 2, 0),
)

# payout for 3/4/5 consecutive matches from reel 1, in 0.001x units.
PAYTABLE_MILLI: Dict[str, Dict[int, int]] = {
    WILD: {3: 1950, 4: 9750, 5: 78000},
    ELEPHANT: {3: 780, 4: 3900, 5: 19500},
    MOUSE: {3: 585, 4: 2730, 5: 9750},
    MODAK: {3: 390, 4: 1950, 5: 7020},
    CHAKRA: {3: 312, 4: 1560, 5: 5850},
    A: {3: 195, 4: 780, 5: 3120},
    K: {3: 156, 4: 585, 5: 2340},
}

@dataclass(frozen=True)
class FeatureRules:
    # Defensive implementation ceilings only; these are not feature award rules.
    # The only user-authoritative BASE award is exactly 3 Scatter => exactly 10 spins.
    max_total_free_spins: int = 50
    max_base_free_spins: int = 49
    # Draft-only Wild Expansion assumptions; not canonical or Provider-approved.
    free_spin_wild_reel_multiplier: int = 2
    max_wild_reel_multiplier: int = 64

@dataclass(frozen=True)
class GameConfig:
    version: str = "full-scratch-v1-draft-005"
    target_rtp_percent: str = "96.50"
    max_win_milli: int = 1_000_000  # draft safety cap: 1,000x per spin
    max_round_win_milli: int = 50_000_000  # 50,000x design cap; no approved/reachable route established
    base_wager_minor_units: int = 100
    feature_rules: FeatureRules = FeatureRules()

PAYOUT_SCALE_NUMERATOR = 991861
PAYOUT_SCALE_DENOMINATOR = 1000000

CONFIG = GameConfig()


def validate_config() -> None:
    if len(REEL_STRIPS) != 5 or any(len(reel) != 13 for reel in REEL_STRIPS):
        raise ValueError("V1 requires exactly five 13-stop reel strips")
    if (len(STOP_WEIGHTS) != 5
            or any(len(weights) != 13 or any(type(weight) is not int or weight <= 0 for weight in weights)
                   for weights in STOP_WEIGHTS)):
        raise ValueError("Each of five reels requires 13 positive integer stop weights")
    if (len(PAYLINES) != 20
            or any(len(line) != 5 or any(type(row) is not int or row not in (0, 1, 2) for row in line)
                   for line in PAYLINES)):
        raise ValueError("V1 requires exactly 20 valid five-reel paylines")
    if (len(SYMBOLS) != 8 or len(set(SYMBOLS)) != len(SYMBOLS)
            or any(not isinstance(symbol, str) or not symbol for symbol in SYMBOLS)
            or any(symbol not in SYMBOLS for reel in REEL_STRIPS for symbol in reel)):
        raise ValueError("Symbol inventory / reel strip mismatch")
    if set(PAYTABLE_MILLI) != set(SYMBOLS) - {SCATTER}:
        raise ValueError("Every non-Scatter symbol must have a paytable")
    for symbol, payouts in PAYTABLE_MILLI.items():
        if (not isinstance(payouts, dict) or set(payouts) != {3, 4, 5}
                or any(type(value) is not int or value < 0 for value in payouts.values())):
            raise ValueError("Paytable values must be non-negative integer 3/4/5-of-a-kind payouts")
    for value in (CONFIG.max_win_milli, CONFIG.max_round_win_milli,
                  CONFIG.base_wager_minor_units, PAYOUT_SCALE_NUMERATOR,
                  PAYOUT_SCALE_DENOMINATOR):
        if type(value) is not int or value <= 0:
            raise ValueError("Math limits, wager and payout scales must be positive integers")
