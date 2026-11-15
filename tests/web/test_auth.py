"""Tests for password hashing, signed sessions and login throttling."""

import unittest

from rose_nexus.web.auth import (
    LoginThrottle,
    hash_password,
    new_token,
    sign_session,
    token_digest,
    verify_password,
    verify_session,
)


class PasswordTests(unittest.TestCase):
    def test_password_roundtrip(self):
        stored = hash_password("correct horse battery staple")
        self.assertTrue(verify_password("correct horse battery staple", stored))

    def test_wrong_password_is_rejected(self):
        stored = hash_password("right")
        self.assertFalse(verify_password("wrong", stored))

    def test_stored_format_has_five_separators(self):
        stored = hash_password("secret")
        self.assertEqual(stored.count("$"), 5)
        fields = stored.split("$")
        self.assertEqual(len(fields), 6)
        self.assertEqual(fields[:4], ["scrypt", str(2**14), "8", "1"])


class SessionTests(unittest.TestCase):
    def test_token_digest_differs_from_token(self):
        token = new_token()
        self.assertNotEqual(token_digest(token), token)
        self.assertEqual(len(token_digest(token)), 64)

    def test_sign_and_verify_session_roundtrip(self):
        signed = sign_session("session-123", "secret")
        self.assertEqual(verify_session(signed, "secret"), "session-123")

    def test_tampered_or_wrong_secret_session_is_rejected(self):
        signed = sign_session("session-123", "secret")
        self.assertIsNone(verify_session(signed.replace("session-123", "session-456"), "secret"))
        self.assertIsNone(verify_session(signed, "other-secret"))
        self.assertIsNone(verify_session("not-signed", "secret"))


class LoginThrottleTests(unittest.TestCase):
    def test_allows_five_then_blocks_and_resets_after_window(self):
        now = [1000.0]
        throttle = LoginThrottle(clock=lambda: now[0])
        key = "192.0.2.1:alice"
        for _ in range(5):
            self.assertTrue(throttle.allow(key))
            throttle.record_failure(key)
        self.assertFalse(throttle.allow(key))

        now[0] += 900
        self.assertTrue(throttle.allow(key))
        throttle.record_failure(key)
        throttle.reset(key)
        self.assertTrue(throttle.allow(key))


if __name__ == "__main__":
    unittest.main()
