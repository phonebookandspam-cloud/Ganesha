import tempfile
import unittest
from pathlib import Path

from ganesha.security.nonce import NonceRegistry
from ganesha.security.verification import sign_request, verify_request


class VerifyRequestMalformedEnvelopeFailClosedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.registry = NonceRegistry(str(Path(self.temp.name) / 'nonce.sqlite'))
        self.secret = b'Ganesha-Provider-test-secret-32bytes-minimum'
        self.payload = {'round_id': 'round-1', 'amount': 100}
        self.timestamp = 1_800_000_000
        self.nonce = 'nonce-1'
        self.signature = sign_request(self.secret, self.payload, self.timestamp, self.nonce)

    def tearDown(self):
        self.temp.cleanup()

    def test_valid_hmac_signature_is_accepted_once(self):
        self.assertTrue(verify_request(self.secret, self.payload, self.signature,
                                       self.timestamp, self.nonce, self.registry,
                                       now=self.timestamp))

    def test_non_string_signature_types_fail_closed_without_raising(self):
        for signature in (None, b'x' * 64, 123, {}, [], object()):
            with self.subTest(signature_type=type(signature).__name__):
                self.assertFalse(verify_request(self.secret, self.payload, signature,
                                                self.timestamp, 'nonce-' + type(signature).__name__,
                                                self.registry, now=self.timestamp))

    def test_wrong_length_and_non_hex_signatures_fail_closed(self):
        for signature in ('', '0' * 63, '0' * 65, 'g' * 64, 'A' * 64):
            with self.subTest(signature=signature[:8]):
                self.assertFalse(verify_request(self.secret, self.payload, signature,
                                                self.timestamp, 'nonce-' + str(len(signature)) + signature[:1],
                                                self.registry, now=self.timestamp))

    def test_noncanonical_payload_fails_closed_without_raising(self):
        malformed_payload = {1: 'numeric key is not canonical JSON'}
        self.assertFalse(verify_request(self.secret, malformed_payload, self.signature,
                                        self.timestamp, 'nonce-bad-payload', self.registry,
                                        now=self.timestamp))

    def test_invalid_signature_does_not_consume_valid_nonce(self):
        self.assertFalse(verify_request(self.secret, self.payload, b'0' * 64,
                                        self.timestamp, self.nonce, self.registry,
                                        now=self.timestamp))
        self.assertTrue(verify_request(self.secret, self.payload, self.signature,
                                       self.timestamp, self.nonce, self.registry,
                                       now=self.timestamp))


if __name__ == '__main__':
    unittest.main()
