"""Explicit fail-closed constructors for the guarded local RGS boundary.

Production callers must supply an independently maintained canonical-Math
approval verifier. The repository currently contains no approval trust store.
"""
import weakref

from ganesha.game.engine import GameEngine, InvalidMathOutcome
from ganesha.game.engine_payout_guard_r1 import EnginePayoutGuardError, validate_outcome_for_settlement
from ganesha.math.config import CONFIG
from ganesha.math.rng import HmacStopGenerator
from ganesha.rgs.service import RoundService
from ganesha.wallet.ledger import WalletLedger
from ganesha.wallet.settlement_boundary_v2_r2 import GuardedWalletLedger, create_guarded_server


_TEST_STARTUP_CAPABILITY = object()
_PRODUCTION_STARTUP_CAPABILITY = object()
_ENGINE_STARTUP_CAPABILITIES = weakref.WeakKeyDictionary()


class GuardedGameEngine:
    """GameEngine-compatible decorator enforcing settlement payout invariants."""
    __slots__ = ("_delegate", "_approved_math_port", "__weakref__")

    def __init__(self, delegate, *, _startup_capability=None):
        if not isinstance(delegate, GameEngine):
            raise TypeError("delegate must be a GameEngine")
        if (type(delegate.spin_cap_milli) is not int
                or delegate.spin_cap_milli != CONFIG.max_win_milli
                or type(delegate.round_cap_milli) is not int
                or delegate.round_cap_milli != CONFIG.max_round_win_milli):
            raise ValueError("GameEngine payout caps must match the canonical configured limits")
        if (_startup_capability is not _TEST_STARTUP_CAPABILITY
                and _startup_capability is not _PRODUCTION_STARTUP_CAPABILITY):
            raise RuntimeError("GuardedGameEngine must be constructed by the standard startup approval boundary")
        object.__setattr__(self, "_delegate", delegate)
        object.__setattr__(self, "_approved_math_port", delegate.math_port)
        _ENGINE_STARTUP_CAPABILITIES[self] = _startup_capability

    def __setattr__(self, name, value):
        if name in ("_delegate", "_approved_math_port"):
            try:
                object.__getattribute__(self, name)
            except AttributeError:
                pass
            else:
                raise AttributeError("guarded engine delegate and approved MathPort binding are immutable")
        object.__setattr__(self, name, value)

    def _assert_startup_capability(self, *, test_mode):
        expected = _TEST_STARTUP_CAPABILITY if test_mode else _PRODUCTION_STARTUP_CAPABILITY
        if _ENGINE_STARTUP_CAPABILITIES.get(self) is not expected:
            raise RuntimeError("GuardedGameEngine startup capability does not match the server approval mode")

    def _assert_approved_math_port_binding(self):
        if self._delegate.math_port is not self._approved_math_port:
            raise RuntimeError("GameEngine MathPort binding changed after guarded startup approval")

    @property
    def math_port(self):
        self._assert_approved_math_port_binding()
        return self._approved_math_port

    @property
    def spin_cap_milli(self):
        # Do not expose the delegate's mutable cap as the settlement authority.
        return CONFIG.max_win_milli

    @property
    def round_cap_milli(self):
        # Do not expose the delegate's mutable cap as the settlement authority.
        return CONFIG.max_round_win_milli

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def resolve_base_round(self, base_stops, free_spin_stop_vectors):
        self._assert_approved_math_port_binding()
        try:
            outcome = self._delegate.resolve_base_round(base_stops, free_spin_stop_vectors)
        except InvalidMathOutcome as exc:
            raise EnginePayoutGuardError(str(exc)) from exc
        self._assert_approved_math_port_binding()
        validate_outcome_for_settlement(
            outcome,
            spin_cap_milli=CONFIG.max_win_milli,
            round_cap_milli=CONFIG.max_round_win_milli,
        )
        return outcome

    def get_bonus_buy_terms(self, mode):
        raise RuntimeError("MAGIC_BUY and EPIC_BUY are disabled by the guarded startup boundary")

    def resolve_bonus_buy_round(self, mode, stop_vectors, terms=None):
        raise RuntimeError("MAGIC_BUY and EPIC_BUY are disabled by the guarded startup boundary")


def _approved_engine(game_engine, *, test_mode, canonical_math_approval):
    if type(test_mode) is not bool:
        raise TypeError("test_mode must be an exact boolean")
    engine = game_engine if game_engine is not None else GameEngine()
    if not isinstance(engine, GameEngine):
        raise TypeError("game_engine must be a GameEngine")
    if not test_mode:
        if not callable(canonical_math_approval):
            raise RuntimeError("production startup requires an independent canonical Math approval verifier")
        approved_math_port = engine.math_port
        try:
            approved = canonical_math_approval(approved_math_port)
        except Exception as exc:
            raise RuntimeError("canonical Math approval verification failed") from exc
        if engine.math_port is not approved_math_port:
            raise RuntimeError("GameEngine MathPort binding changed during canonical Math approval verification")
        if approved is not True:
            raise RuntimeError("canonical Math approval is absent or invalid")
    capability = _TEST_STARTUP_CAPABILITY if test_mode else _PRODUCTION_STARTUP_CAPABILITY
    return GuardedGameEngine(engine, _startup_capability=capability)


def create_guarded_round_service(ledger, *, stop_generator, game_engine=None, test_mode=False,
                                 canonical_math_approval=None, allow_test_vectors=False):
    """Construct RoundService with GuardedWalletLedger and guarded GameEngine."""
    if not isinstance(ledger, WalletLedger):
        raise TypeError("ledger must be a WalletLedger")
    if not isinstance(stop_generator, HmacStopGenerator):
        raise TypeError("stop_generator must be a server-side HmacStopGenerator")
    if type(allow_test_vectors) is not bool:
        raise TypeError("allow_test_vectors must be an exact boolean")
    if allow_test_vectors and not test_mode:
        raise ValueError("test vectors are available only in explicit test_mode")
    guarded_engine = _approved_engine(game_engine, test_mode=test_mode,
                                      canonical_math_approval=canonical_math_approval)
    guarded_wallet = GuardedWalletLedger(
        ledger, spin_cap_milli=guarded_engine.spin_cap_milli,
        round_cap_milli=guarded_engine.round_cap_milli,
    )
    return RoundService(
        guarded_wallet, game_engine=guarded_engine, stop_generator=stop_generator,
        allow_unapproved_math_for_tests=test_mode, allow_test_vectors_for_tests=allow_test_vectors,
    )


def create_guarded_rgs_server(host, port, ledger, *, stop_generator, sessions, nonce_registry,
                              frontend_root=None, game_engine=None, test_mode=False,
                              canonical_math_approval=None):
    """Create the existing guarded RGS server with startup approval enforced."""
    if not isinstance(ledger, WalletLedger):
        raise TypeError("ledger must be a WalletLedger")
    if not isinstance(stop_generator, HmacStopGenerator):
        raise TypeError("stop_generator must be a server-side HmacStopGenerator")
    guarded_engine = _approved_engine(game_engine, test_mode=test_mode,
                                      canonical_math_approval=canonical_math_approval)
    return create_guarded_server(
        host, port, ledger, stop_generator, sessions, nonce_registry,
        frontend_root=frontend_root, game_engine=guarded_engine,
        allow_unapproved_math_for_tests=test_mode,
    )
