"""Focused regression tests for immutable canonical caps at guarded startup."""
import unittest
import tempfile
from pathlib import Path

from ganesha.game.engine import GameEngine
from ganesha.game.engine_payout_guard_r1 import EnginePayoutGuardError
from ganesha.math.config import CONFIG
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.standard_startup_v1 import GuardedGameEngine, _approved_engine, create_guarded_round_service
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger


class _OverCapMathPort:
    version = "worker4-over-cap-test"
    authority_status = "TEST_FIXTURE_ONLY"

    def evaluate_stops(self, stops, mode):
        payout = CONFIG.max_win_milli + 1
        return {
            "mode": mode,
            "payout_milli": payout,
            "raw_payout_milli": payout,
            "wild_multiplier": 1,
            "expanded_wild_reels": [],
            "max_win_capped": False,
            "scatter_count": 0,
            "free_spins_awarded": 0,
            "jackpot_triggered": False,
        }

    def award_free_spins(self, scatter_count, retrigger=False):
        return 0


class StandardStartupCanonicalCapLockTests(unittest.TestCase):
    def test_guarded_wallet_rejects_caps_above_canonical_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WalletLedger(Path(tmp) / "wallet.sqlite3")
            with self.assertRaisesRegex(ValueError, "canonical configured limit"):
                GuardedWalletLedger(ledger, spin_cap_milli=CONFIG.max_win_milli + 1)
            with self.assertRaisesRegex(ValueError, "canonical configured limit"):
                GuardedWalletLedger(ledger, round_cap_milli=CONFIG.max_round_win_milli + 1)

            guarded = GuardedWalletLedger(ledger)
            with self.assertRaises(AttributeError):
                guarded.spin_cap_milli = CONFIG.max_win_milli + 1
            with self.assertRaises(AttributeError):
                guarded.round_cap_milli = CONFIG.max_round_win_milli + 1
            with self.assertRaisesRegex(AttributeError, "immutable"):
                guarded._spin_cap_milli = CONFIG.max_win_milli + 1
            with self.assertRaisesRegex(AttributeError, "immutable"):
                guarded._round_cap_milli = CONFIG.max_round_win_milli + 1

    def test_guarded_engine_rejects_preinflated_delegate_caps(self):
        engine = GameEngine(_OverCapMathPort())
        engine.spin_cap_milli = CONFIG.max_win_milli + 1
        engine.round_cap_milli = CONFIG.max_round_win_milli + 1

        with self.assertRaisesRegex(ValueError, "canonical configured limits"):
            GuardedGameEngine(engine)

    def test_standard_factory_rejects_preinflated_delegate_caps(self):
        engine = GameEngine(_OverCapMathPort())
        engine.spin_cap_milli = CONFIG.max_win_milli + 1
        engine.round_cap_milli = CONFIG.max_round_win_milli + 1
        with tempfile.TemporaryDirectory() as tmp:
            ledger = WalletLedger(Path(tmp) / "wallet.sqlite3")
            with self.assertRaisesRegex(ValueError, "canonical configured limits"):
                create_guarded_round_service(
                    ledger,
                    stop_generator=HmacStopGenerator(b"worker4-canonical-cap-test-key-000000"),
                    game_engine=engine,
                    test_mode=True,
                )

    def test_delegate_cap_mutation_after_wrapping_cannot_raise_settlement_caps(self):
        engine = GameEngine(_OverCapMathPort())
        guarded = _approved_engine(engine, test_mode=True, canonical_math_approval=None)
        engine.spin_cap_milli = CONFIG.max_win_milli + 1
        engine.round_cap_milli = CONFIG.max_round_win_milli + 1

        self.assertEqual(guarded.spin_cap_milli, CONFIG.max_win_milli)
        self.assertEqual(guarded.round_cap_milli, CONFIG.max_round_win_milli)
        with self.assertRaises(EnginePayoutGuardError):
            guarded.resolve_base_round((0,) * 5, [])

    def test_guarded_engine_pins_delegate_and_approved_math_port_identity(self):
        original_port = _OverCapMathPort()
        engine = GameEngine(original_port)
        guarded = _approved_engine(engine, test_mode=True, canonical_math_approval=None)

        with self.assertRaisesRegex(AttributeError, "immutable"):
            guarded._delegate = GameEngine(original_port)
        with self.assertRaisesRegex(AttributeError, "immutable"):
            guarded._approved_math_port = _OverCapMathPort()

        engine.math_port = _OverCapMathPort()
        with self.assertRaisesRegex(RuntimeError, "changed after guarded startup approval"):
            guarded.resolve_base_round((0,) * 5, [])
        with self.assertRaisesRegex(RuntimeError, "changed after guarded startup approval"):
            _ = guarded.math_port


if __name__ == "__main__":
    unittest.main()
