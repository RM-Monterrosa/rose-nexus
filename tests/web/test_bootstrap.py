"""Behavior tests for idempotent local web-user bootstrap."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from rose_nexus.core.errors import InputValidationError
from rose_nexus.web.auth import verify_password
from rose_nexus.web.bootstrap import ensure_user
from rose_nexus.web.db import connect, migrate
from rose_nexus.web.repository import Repository


class BootstrapTests(unittest.TestCase):
    """Verify scrypt hashes, admin attribution and empty-password rejection."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="rose-bootstrap-test-")
        self.connection = connect(Path(self._temporary.name) / "web.db")
        migrate(self.connection)
        self.repository = Repository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self._temporary.cleanup()

    def test_ensure_user_stores_a_verifiable_scrypt_hash(self) -> None:
        user = ensure_user(self.repository, "alice", "a strong password")
        self.assertTrue(user.password_hash.startswith("scrypt$16384$8$1$"))
        self.assertNotEqual(user.password_hash, "a strong password")
        self.assertTrue(verify_password("a strong password", user.password_hash))
        self.assertFalse(verify_password("wrong", user.password_hash))
        stored = self.repository.get_user_by_username("alice")
        self.assertEqual(stored, user)

    def test_ensure_user_is_idempotent_by_username(self) -> None:
        first = ensure_user(self.repository, "alice", "first password")
        second = ensure_user(self.repository, "alice", "different password", is_admin=True)
        self.assertEqual(second, first)
        self.assertEqual(second.password_hash, first.password_hash)
        self.assertFalse(second.is_admin)

    def test_ensure_user_rejects_an_empty_password_without_creating_a_row(self) -> None:
        with self.assertRaises(InputValidationError) as caught:
            ensure_user(self.repository, "alice", "")
        self.assertEqual(caught.exception.code, "invalid_password")
        self.assertIsNone(self.repository.get_user_by_username("alice"))

    def test_ensure_user_marks_admin_accounts(self) -> None:
        user = ensure_user(self.repository, "root", "admin password", is_admin=True)
        self.assertTrue(user.is_admin)
        self.assertTrue(self.repository.get_user(user.id).is_admin)


if __name__ == "__main__":
    unittest.main()
