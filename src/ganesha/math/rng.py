"""Server-side weighted stop generator with deterministic HMAC replay per round/spin."""
import hashlib
import hmac
from pathlib import Path
from ganesha.math.config import STOP_WEIGHTS, validate_config


def implementation_version():
    """Bind replay to the exact RNG implementation and probability-input source bytes."""
    root = Path(__file__).resolve().parents[3]
    digest = hashlib.sha256()
    for relative in ("src/ganesha/math/rng.py", "src/ganesha/math/config.py"):
        data = (root / relative).read_bytes()
        digest.update(relative.encode("utf-8") + b"\0" + data + b"\0")
    return "hmac-sha256-stop-v1:" + digest.hexdigest()

class HmacStopGenerator:
    def __init__(self, secret, version=None):
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise ValueError("RNG secret must be at least 32 bytes")
        if version is not None and (not isinstance(version, str) or not version or len(version) > 128):
            raise ValueError("RNG implementation version must be a non-empty string of at most 128 characters")
        validate_config()
        self._secret = secret
        self.version = version or implementation_version()

    def commitment(self, round_id):
        if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
            raise ValueError("round_id must be a non-empty string of at most 128 characters")
        message = ("commit|" + self.version + "|" + round_id).encode("utf-8")
        return hashlib.sha256(hmac.new(self._secret, message, hashlib.sha256).digest()).hexdigest()

    def _randbelow(self, limit, context):
        if type(limit) is not int or limit <= 0:
            raise ValueError("limit must be a positive integer")
        space = 1 << 256
        cutoff = space - (space % limit)
        counter = 0
        while True:
            message = (self.version + "|" + context + "|" + str(counter)).encode("utf-8")
            value = int.from_bytes(hmac.new(self._secret, message, hashlib.sha256).digest(), "big")
            if value < cutoff:
                return value % limit
            counter += 1

    def _weighted_stop(self, reel_index, round_id, spin_index):
        if type(reel_index) is not int or not 0 <= reel_index < len(STOP_WEIGHTS):
            raise ValueError("reel_index is outside the configured reel set")
        if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
            raise ValueError("round_id must be a non-empty string of at most 128 characters")
        if type(spin_index) is not int or spin_index < 0:
            raise ValueError("spin_index must be a non-negative integer")
        weights = STOP_WEIGHTS[reel_index]
        draw = self._randbelow(sum(weights), "%s|%d|%d" % (round_id, spin_index, reel_index))
        cumulative = 0
        for stop, weight in enumerate(weights):
            cumulative += weight
            if draw < cumulative:
                return stop
        raise AssertionError("Weighted stop selection escaped cumulative range")

    def stop_vector(self, round_id, spin_index):
        if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
            raise ValueError("round_id must be a non-empty string of at most 128 characters")
        if type(spin_index) is not int or spin_index < 0:
            raise ValueError("spin_index must be a non-negative integer")
        return tuple(self._weighted_stop(reel, round_id, spin_index) for reel in range(5))

    def stop_vectors(self, round_id, count):
        if not isinstance(round_id, str) or not round_id or len(round_id) > 128:
            raise ValueError("round_id must be a non-empty string of at most 128 characters")
        if type(count) is not int or count < 0 or count > 1000:
            raise ValueError("Invalid stop vector count")
        return [self.stop_vector(round_id, spin) for spin in range(count)]
