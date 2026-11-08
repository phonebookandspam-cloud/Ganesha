import os
import sqlite3
from sqlite_test_support import connect as sqlite_connect
import tempfile
import unittest

from ganesha.security.nonce import NonceRegistry


class NonceRegistryInputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp.name, "nonces.sqlite")
        self.registry = NonceRegistry(self.database)

    def tearDown(self):
        self.temp.cleanup()

    def test_bytes_cannot_create_a_second_sqlite_identity_for_same_nonce(self):
        self.assertTrue(self.registry.consume_once("same-nonce", 200, 100))
        self.assertFalse(self.registry.consume_once(b"same-nonce", 200, 100))
        self.assertFalse(self.registry.consume_once("same-nonce", 200, 100))

        with sqlite_connect(self.database) as db:
            rows = db.execute(
                "SELECT nonce, typeof(nonce) FROM consumed_nonces"
            ).fetchall()
        self.assertEqual(rows, [("same-nonce", "text")])

    def test_non_string_nonce_inputs_fail_closed_without_consuming_string_nonce(self):
        for invalid_nonce in (b"nonce", 123, True, None):
            with self.subTest(nonce=invalid_nonce):
                self.assertFalse(self.registry.consume_once(invalid_nonce, 200, 100))

        self.assertTrue(self.registry.consume_once("nonce", 200, 100))
        self.assertFalse(self.registry.consume_once("nonce", 200, 100))

    def test_nonce_length_limit_remains_enforced(self):
        self.assertFalse(self.registry.consume_once("n" * 257, 200, 100))
        self.assertTrue(self.registry.consume_once("n" * 256, 200, 100))


if __name__ == "__main__":
    unittest.main()
