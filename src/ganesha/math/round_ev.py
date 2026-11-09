"""Fail-closed full-round Math audit boundary.

The prior Draft-005 Free Spins retrigger, Buy-price and jackpot model is not
authorized. Full-mode RTP/variance cannot be calculated until those rules and
canonical inputs are supplied.
"""


def exact_full_mode_moments():
    return {
        "schema": "ganesha-independent-math-full-round-audit.v2",
        "status": "BLOCKED_UNSPECIFIED_RULES",
        "release_status": "SUPERSEDED_NOT_RELEASE_EVIDENCE",
        "canonical_math": False,
        "provider_approved": False,
        "public_claims_permitted": False,
        "stake_upload_permitted": False,
        "modes": {
            "BASE": {"status": "BLOCKED", "reason": "3=10 and 4=12 Free Spins are user-defined; 5-Scatter embedded EPIC payload/BASE-unit conversion and canonical probability inputs are unavailable; 6+ fails closed"},
            "FREE_SPINS": {"status": "BLOCKED", "reason": "Free Spins retrigger and termination rules are unresolved"},
            "MAGIC_BUY": {"status": "BLOCKED", "reason": "User price is ×100; canonical feature inputs, probability model and Provider approval are unavailable"},
            "EPIC_BUY": {"status": "BLOCKED", "reason": "User price is ×500; canonical feature inputs, probability model and Provider approval are unavailable"},
        },
        "metrics": {"rtp": "NOT_COMPUTED", "hit_frequency": "NOT_COMPUTED",
                    "variance": "NOT_COMPUTED", "volatility": "NOT_COMPUTED",
                    "payout_distribution": "NOT_COMPUTED", "streak_distribution": "NOT_COMPUTED",
                    "max_payout_frequency": "NOT_COMPUTED"},
        "design_targets_not_verified": {"rtp_percent": "96.50", "max_win_x": 50000},
        "blockers": [
            "Canonical 2026-09-27 Math JSON and the 58-field source manifest are absent.",
            "BASE 3=10 and 4=12 Free Spins are defined; 5 Scatter embedded EPIC payload and BASE-unit conversion are unavailable; 6+ fails closed; Free Spins retrigger remains fail closed.",
            "User-defined independent purchase prices are MAGIC ×100 and EPIC ×500; canonical feature inputs, probability distributions and mode-specific RTP are not approved.",
            "Stake stateless-game policy prohibits the historical jackpot mechanic.",
            "No complete approved single-bet path or Provider payout evidence proves 50,000x.",
        ],
    }
