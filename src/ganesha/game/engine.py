"""Deterministic round state machine; receives stops only from a server-side RNG adapter."""
from typing import Dict, Iterable, List
from ganesha.math.config import CONFIG
from ganesha.game.math_port import DraftMathPort
from ganesha.math.engine import EmbeddedEpicFeatureUnavailable, UnspecifiedMathRule

class OutcomeStreamExhausted(RuntimeError):
    pass

class BonusBuyTermsUnavailable(RuntimeError):
    pass

class InvalidBonusBuyTerms(ValueError):
    pass

class InvalidMathOutcome(ValueError):
    """MathPort returned malformed, contradictory or unauthorized outcome data."""

class UnapprovedFeatureMechanic(InvalidMathOutcome):
    """A feature mechanic is incompatible with the current approved rule boundary."""

class GameEngine:
    def __init__(self, math_port=None):
        self.math_port = DraftMathPort() if math_port is None else math_port
        if not callable(getattr(self.math_port, "evaluate_stops", None)) or not callable(getattr(self.math_port, "award_free_spins", None)):
            raise TypeError("math_port must implement evaluate_stops and award_free_spins")
        self.round_cap_milli = CONFIG.max_round_win_milli
        self.spin_cap_milli = CONFIG.max_win_milli  # 1,000x per spin
        self.max_free_spins = CONFIG.feature_rules.max_total_free_spins

    def _run_free_spins(self, initial_spins, stop_vectors, payout_before_milli=0, max_spins=None):
        max_spins = self.max_free_spins if max_spins is None else max_spins
        remaining = min(initial_spins, max_spins)
        awarded_total = remaining
        played = 0
        payout_total = payout_before_milli
        events = []
        vectors = iter(stop_vectors)
        while remaining > 0 and played < max_spins and payout_total < self.round_cap_milli:
            try:
                stops = next(vectors)
            except StopIteration:
                raise OutcomeStreamExhausted("Insufficient server-side stop vectors to resolve all awarded Free Spins")
            result = self._validated_spin_result(
                self.math_port.evaluate_stops(stops, "FREE_SPINS"), "FREE_SPINS",
                self.spin_cap_milli,
            )
            played += 1
            remaining -= 1
            retrigger_requested = self.math_port.award_free_spins(result["scatter_count"], retrigger=True)
            if type(retrigger_requested) is not int or retrigger_requested < 0:
                raise InvalidMathOutcome("Free Spins retrigger award must be a non-negative integer")
            if retrigger_requested != 0:
                raise UnspecifiedMathRule("Free Spins retrigger rules are not user-authorized")
            retrigger_awarded = 0
            before = payout_total
            payout_total = min(self.round_cap_milli, payout_total + result["payout_milli"])
            jackpot_triggered = False
            events.append({
                "event": "FREE_SPIN_RESOLVED", "spin_number": played,
                "stops": list(stops), "result": result,
                "payout_awarded_milli": payout_total - before,
                "retrigger_requested": retrigger_requested,
                "retrigger_awarded": retrigger_awarded,
                "round_payout_after_milli": payout_total,
                "round_cap_applied": payout_total == self.round_cap_milli and before + result["payout_milli"] > self.round_cap_milli,
                "jackpot_triggered": jackpot_triggered,
            })
        return {"free_spins_played": played, "free_spins_awarded_total": awarded_total,
                "payout_total_milli": payout_total, "events": events,
                "round_cap_reached": payout_total >= self.round_cap_milli}

    def resolve_base_round(self, base_stops, free_spin_stop_vectors):
        base_result = self._validated_spin_result(
            self.math_port.evaluate_stops(base_stops, "BASE"), "BASE",
            self.spin_cap_milli,
        )
        base_payout = base_result["payout_milli"]
        if base_payout > self.round_cap_milli:
            raise InvalidMathOutcome("BASE payout exceeds the configured round maximum")
        initial_spins = base_result["free_spins_awarded"]
        feature = self._run_free_spins(initial_spins, free_spin_stop_vectors, base_payout,
                                       max_spins=CONFIG.feature_rules.max_base_free_spins) if initial_spins else {
            "free_spins_played": 0, "free_spins_awarded_total": 0,
            "payout_total_milli": base_payout, "events": [],
            "round_cap_reached": base_payout >= self.round_cap_milli,
        }
        return {
            "mode": "BASE", "base_result": base_result,
            "math_authority": getattr(self.math_port, "authority_status", "UNDECLARED"),
            "math_version": getattr(self.math_port, "version", "UNDECLARED"),
            "initial_free_spins": initial_spins,
            "free_spins_played": feature["free_spins_played"],
            "free_spins_awarded_total": feature["free_spins_awarded_total"],
            "feature_events": feature["events"],
            "total_payout_milli": feature["payout_total_milli"],
            "round_cap_reached": feature["round_cap_reached"],
        }


    @staticmethod
    def _validated_spin_result(result, mode, spin_cap_milli=None):
        if mode not in ("BASE", "FREE_SPINS"):
            raise InvalidMathOutcome("unsupported MathPort evaluation mode")
        if not isinstance(result, dict) or result.get("mode") != mode:
            raise InvalidMathOutcome("MathPort result must identify the requested mode")
        if spin_cap_milli is None:
            spin_cap_milli = CONFIG.max_win_milli
        if type(spin_cap_milli) is not int or spin_cap_milli <= 0:
            raise InvalidMathOutcome("configured per-spin payout cap must be a positive exact integer")
        for field in ("payout_milli", "scatter_count"):
            value = result.get(field)
            if type(value) is not int or value < 0:
                raise InvalidMathOutcome("%s must be a non-negative integer" % field)
        if result["payout_milli"] > spin_cap_milli:
            raise InvalidMathOutcome("spin payout exceeds the configured per-spin maximum")
        if result["scatter_count"] > 15:
            raise InvalidMathOutcome("Scatter count exceeds a 5x3 board")
        if mode == "BASE":
            award = result.get("free_spins_awarded")
            if type(award) is not int or award < 0:
                raise InvalidMathOutcome("BASE Free Spins award must be a non-negative integer")
            if result["scatter_count"] == 5:
                raise EmbeddedEpicFeatureUnavailable(
                    "5 Scatter selects embedded EPICBUY_V37; the provider feature payload is unavailable"
                )
            if result["scatter_count"] >= 6:
                raise UnspecifiedMathRule("6+ Scatter is rejected by the current BASE contract (fail closed)")
            expected_award = 10 if result["scatter_count"] == 3 else 12 if result["scatter_count"] == 4 else 0
            if award != expected_award:
                raise InvalidMathOutcome("BASE Free Spins award must be 10 for 3 Scatter, 12 for 4 Scatter, otherwise 0")
        elif result["scatter_count"] >= 3:
            raise UnspecifiedMathRule("Free Spins retrigger behavior is not user-authorized")
        if "jackpot_triggered" in result:
            jackpot = result["jackpot_triggered"]
            if type(jackpot) is not bool:
                raise InvalidMathOutcome("jackpot_triggered must be a boolean when present")
            if jackpot:
                raise UnapprovedFeatureMechanic(
                    "Jackpot events are prohibited by the published Stake Engine stateless-game requirements"
                )
        if mode == "FREE_SPINS" and "jackpot_triggered" not in result:
            raise InvalidMathOutcome("FREE_SPINS result must explicitly state jackpot_triggered=false")
        return result

    def get_bonus_buy_terms(self, mode):
        if mode not in ("MAGIC_BUY", "EPIC_BUY"):
            raise ValueError("Unknown Bonus Buy mode")
        terms_resolver = getattr(self.math_port, "resolve_bonus_buy_terms", None)
        if not callable(terms_resolver):
            raise BonusBuyTermsUnavailable(
                "MAGIC_BUY and EPIC_BUY require explicit Math-port terms; "
                "DraftMathPort does not authorize purchase cost or Free Spins count"
            )
        terms = terms_resolver(mode)
        return self._validate_bonus_buy_terms(mode, terms)

    def resolve_bonus_buy_round(self, mode, stop_vectors, terms=None):
        terms = self.get_bonus_buy_terms(mode) if terms is None else self._validate_bonus_buy_terms(mode, terms)
        feature = self._run_free_spins(terms["initial_free_spins"], stop_vectors, 0,
                                       max_spins=terms["max_stop_vectors"])
        return {
            "mode": mode,
            "purchase_cost_multiplier_milli": terms["purchase_cost_multiplier_milli"],
            "max_stop_vectors": terms["max_stop_vectors"],
            "math_authority": getattr(self.math_port, "authority_status", "UNDECLARED"),
            "math_version": getattr(self.math_port, "version", "UNDECLARED"),
            "initial_free_spins": terms["initial_free_spins"],
            "free_spins_played": feature["free_spins_played"],
            "free_spins_awarded_total": feature["free_spins_awarded_total"],
            "feature_events": feature["events"],
            "total_payout_milli": feature["payout_total_milli"],
            "round_cap_reached": feature["round_cap_reached"],
        }

    def _validate_bonus_buy_terms(self, mode, terms):
        if not isinstance(terms, dict) or set(terms) != {
            "mode", "initial_free_spins", "purchase_cost_multiplier_milli", "max_stop_vectors"
        }:
            raise InvalidBonusBuyTerms("Bonus Buy terms schema is invalid")
        if terms["mode"] != mode:
            raise InvalidBonusBuyTerms("Bonus Buy terms mode does not match the requested mode")
        initial_spins = terms["initial_free_spins"]
        multiplier = terms["purchase_cost_multiplier_milli"]
        max_vectors = terms["max_stop_vectors"]
        if type(initial_spins) is not int or not 1 <= initial_spins <= self.max_free_spins:
            raise InvalidBonusBuyTerms("initial_free_spins is outside the configured safety bound")
        if type(multiplier) is not int or multiplier <= 0:
            raise InvalidBonusBuyTerms("purchase_cost_multiplier_milli must be a positive integer")
        if type(max_vectors) is not int or not initial_spins <= max_vectors <= self.max_free_spins:
            raise InvalidBonusBuyTerms("max_stop_vectors must bound initial spins within the configured safety limit")
        return dict(terms)
