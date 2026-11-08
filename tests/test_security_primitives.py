import unittest

from ganesha.security.signing import canonical_payload, sign_payload, verify_payload


class SecurityCanonicalizationTests(unittest.TestCase):
    def test_non_string_object_keys_cannot_collide_after_json_coercion(self):
        secret = b"canonicalization-test-secret-32b"
        integer_key_payload = {1: "same"}
        string_key_payload = {"1": "same"}

        # Python's default JSON encoder used to serialize both objects identically.
        with self.assertRaisesRegex(ValueError, "object keys must be strings"):
            canonical_payload(integer_key_payload)
        with self.assertRaisesRegex(ValueError, "object keys must be strings"):
            sign_payload(secret, integer_key_payload)

        signature = sign_payload(secret, string_key_payload)
        self.assertTrue(verify_payload(secret, string_key_payload, signature))

    def test_nested_non_string_object_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "object keys must be strings"):
            canonical_payload({"outer": [{"inner": {1: "value"}}]})

    def test_non_finite_numbers_are_not_valid_canonical_json(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    canonical_payload({"value": value})

    def test_valid_json_payload_canonical_bytes_remain_stable(self):
        self.assertEqual(
            canonical_payload({"z": 1, "a": [True, None, "é"]}),
            '{"a":[true,null,"é"],"z":1}'.encode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
