"""Canonical HMAC request signing primitives; secrets must be supplied at runtime."""
import hashlib
import hmac
import json
import time


def _require_string_object_keys(value):
    """Reject Python mappings that JSON would silently coerce into member names."""
    if isinstance(value, dict):
        for key, nested in value.items():
            if type(key) is not str:
                raise ValueError("canonical JSON object keys must be strings")
            _require_string_object_keys(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _require_string_object_keys(nested)


def canonical_payload(payload):
    _require_string_object_keys(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def sign_payload(secret, payload):
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError("HMAC secret must be at least 32 bytes")
    return hmac.new(secret, canonical_payload(payload), hashlib.sha256).hexdigest()


def verify_payload(secret, payload, supplied_signature):
    expected = sign_payload(secret, payload)
    return hmac.compare_digest(expected, supplied_signature or "")


def timestamp_is_fresh(timestamp, now=None, tolerance_seconds=60):
    now = time.time() if now is None else now
    return isinstance(timestamp, (int, float)) and abs(now - timestamp) <= tolerance_seconds
