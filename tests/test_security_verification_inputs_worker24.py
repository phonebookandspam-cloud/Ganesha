import os
import tempfile
import unittest

from ganesha.security.nonce import NonceRegistry
from ganesha.security.verification import sign_request, verify_request


class VerifyRequestInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = NonceRegistry(os.path.join(self.temp.name, "nonces.sqlite"))
        self.secret = b"verification-input-test-secret-32b"
        self.payload = {"operation": "test"}

    def tearDown(self):
        self.temp.cleanup()

    def _verify(self, timestamp, nonce, *, now=1000, tolerance=60):
        signature = sign_request(self.secret, self.payload, timestamp, nonce)
        return verify_request(
            self.secret, self.payload, signature, timestamp, nonce,
            self.registry, now=now, tolerance_seconds=tolerance,
        )

    def test_boolean_timestamp_is_rejected_even_when_it_is_fresh_at_unix_second_one(self):
        signature = sign_request(self.secret, self.payload, True, "bool-timestamp")
        self.assertFalse(verify_request(
            self.secret, self.payload, signature, True, "bool-timestamp",
            self.registry, now=1, tolerance_seconds=60,
        ))
        # The rejected boolean timestamp must not consume the nonce.
        self.assertTrue(self._verify(1, "bool-timestamp", now=1))

    def test_non_finite_timestamp_now_and_tolerance_fail_closed(self):
        for timestamp in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(timestamp=timestamp):
                self.assertFalse(verify_request(
                    self.secret, self.payload, "unused", timestamp, "nonce",
                    self.registry, now=1000,
                ))
        for now in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(now=now):
                self.assertFalse(self._verify(1000, "now-" + str(now), now=now))
        for tolerance in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(tolerance=tolerance):
                self.assertFalse(self._verify(1000, "tol-" + str(tolerance), tolerance=tolerance))

    def test_malformed_now_and_tolerance_fail_closed_without_raising(self):
        for now in ("1000", True, None, object()):
            with self.subTest(now=now):
                self.assertFalse(self._verify(1000, "bad-now-" + str(type(now)), now=now))
        for tolerance in ("60", True, None, object(), -1):
            with self.subTest(tolerance=tolerance):
                self.assertFalse(self._verify(1000, "bad-tol-" + str(type(tolerance)), tolerance=tolerance))
        self.assertFalse(self._verify(1000, "reusable-after-invalid", now="1000"))
        self.assertTrue(self._verify(1000, "reusable-after-invalid", now=1000))

    def test_timestamp_and_now_outside_sqlite_integer_range_fail_closed(self):
        too_large = 2 ** 63
        self.assertFalse(self._verify(too_large, "large-ts", now=too_large))
        self.assertFalse(self._verify(1000, "large-now", now=too_large))

    def test_float_unix_timestamp_remains_supported_and_nonce_must_be_string(self):
        self.assertTrue(self._verify(1000.25, "valid-float-ts", now=1000.5, tolerance=1.0))
        for nonce in (123, 1.5, b"nonce", True, None):
            with self.subTest(nonce=nonce):
                signature = sign_request(self.secret, self.payload, 1000, nonce)
                self.assertFalse(verify_request(
                    self.secret, self.payload, signature, 1000, nonce,
                    self.registry, now=1000,
                ))


if __name__ == "__main__":
    unittest.main()
