"""Authenticated request verification with timestamp and persistent nonce replay checks."""
import math
import time
from .nonce import NonceRegistry
from .signing import sign_payload, timestamp_is_fresh, verify_payload


_SQLITE_INTEGER_MIN = -(2 ** 63)
_SQLITE_INTEGER_MAX = (2 ** 63) - 1


def _valid_time_number(value):
    if type(value) not in (int, float):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return _SQLITE_INTEGER_MIN <= value <= _SQLITE_INTEGER_MAX


def signed_envelope(payload, timestamp, nonce):
    return {"payload": payload, "timestamp": timestamp, "nonce": str(nonce)}


def sign_request(secret, payload, timestamp, nonce):
    return sign_payload(secret, signed_envelope(payload, timestamp, nonce))


def verify_request(secret, payload, signature, timestamp, nonce, registry, now=None, tolerance_seconds=60):
    now = time.time() if now is None else now
    if not _valid_time_number(timestamp) or not _valid_time_number(now):
        return False
    if not _valid_time_number(tolerance_seconds) or tolerance_seconds < 0:
        return False
    expires_at = timestamp + tolerance_seconds
    if not _valid_time_number(expires_at):
        return False
    if not isinstance(nonce, str) or not nonce:
        return False
    if not timestamp_is_fresh(timestamp, now=now, tolerance_seconds=tolerance_seconds):
        return False
    # HMAC-SHA256 signatures are exactly 64 lowercase hexadecimal characters.
    # Validate the untrusted wire type before compare_digest: Python raises
    # TypeError for mixed str/bytes and non-string operands rather than failing
    # closed, which can turn malformed requests into HTTP 500 responses.
    if (not isinstance(signature, str) or len(signature) != 64
            or any(char not in "0123456789abcdef" for char in signature)):
        return False
    try:
        valid_signature = verify_payload(secret, signed_envelope(payload, timestamp, nonce), signature)
    except (TypeError, ValueError, OverflowError):
        return False
    if not valid_signature:
        return False
    if not isinstance(registry, NonceRegistry):
        raise TypeError("Persistent NonceRegistry required")
    return registry.consume_once(nonce, int(expires_at), int(now))
