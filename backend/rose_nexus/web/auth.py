"""Password, bearer-token, signed-session and brute-force protection helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable


_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_BYTES = 32
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Hash a UTF-8 password using scrypt and a fresh 128-bit salt."""

    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_BYTES,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt_b64}${digest_b64}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a stored scrypt value without raising on malformed input."""

    try:
        scheme, raw_n, raw_r, raw_p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(raw_n), int(raw_r), int(raw_p)
        # Reject unreasonable attacker-controlled work factors before scrypt.
        if not (2 <= n <= 2**20 and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 4):
            return False
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(digest_b64, validate=True)
        if not salt or not expected:
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except (ValueError, TypeError, binascii.Error):
        return False
    return hmac.compare_digest(candidate, expected)


def new_token(nbytes: int = 32) -> str:
    """Return a URL-safe cryptographically random bearer token."""

    return secrets.token_urlsafe(nbytes)


def token_digest(token: str) -> str:
    """Return the only token representation persisted by the web layer."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _secret_bytes(secret: str | bytes) -> bytes:
    return secret if isinstance(secret, bytes) else secret.encode("utf-8")


def _session_signature(session_id: str, secret: str | bytes) -> str:
    return hmac.new(_secret_bytes(secret), session_id.encode("utf-8"), hashlib.sha256).hexdigest()


def sign_session(session_id: str, secret: str | bytes) -> str:
    """Return ``session_id.hex_hmac`` for the future signed-cookie layer."""

    return f"{session_id}.{_session_signature(session_id, secret)}"


def verify_session(value: str, secret: str | bytes) -> str | None:
    """Return the authenticated session id, or ``None`` for any invalid value."""

    try:
        session_id, supplied = value.rsplit(".", 1)
    except (ValueError, AttributeError):
        return None
    if not session_id:
        return None
    expected = _session_signature(session_id, secret)
    return session_id if hmac.compare_digest(supplied, expected) else None


class LoginThrottle:
    """Bound failures per key in a fixed window using an injectable monotonic clock."""

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 900,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_attempts <= 0 or window_seconds <= 0:
            raise ValueError("throttle limits must be positive")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._failures: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def _expired(self, started: float, now: float) -> bool:
        return now - started >= self.window_seconds

    def allow(self, key: str) -> bool:
        """Report whether a new login attempt is currently permitted."""

        now = self._clock()
        with self._lock:
            current = self._failures.get(key)
            if current is None:
                return True
            started, failures = current
            if self._expired(started, now):
                self._failures.pop(key, None)
                return True
            return failures < self.max_attempts

    def record_failure(self, key: str) -> None:
        """Record a failed login, beginning a fresh window after expiry."""

        now = self._clock()
        with self._lock:
            started, failures = self._failures.get(key, (now, 0))
            if self._expired(started, now):
                started, failures = now, 0
            self._failures[key] = (started, failures + 1)

    def reset(self, key: str) -> None:
        """Clear all throttling state after a successful login."""

        with self._lock:
            self._failures.pop(key, None)
