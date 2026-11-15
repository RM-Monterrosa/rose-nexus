"""Idempotent local-user creation for trusted administrative bootstrap."""

from __future__ import annotations

import getpass
import pathlib
import uuid
from datetime import datetime, timezone

from ..core.errors import InputValidationError
from . import auth
from .db import connect, migrate
from .models import User
from .repository import Repository


def ensure_user(
    repository: Repository, username: str, password: str, is_admin: bool = False
) -> User:
    """Return an existing username unchanged or create a scrypt-hashed local user."""

    existing = repository.get_user_by_username(username)
    if existing is not None:
        return existing
    if not username:
        raise InputValidationError("username must not be empty", code="invalid_username")
    if password == "":
        raise InputValidationError("password must not be empty", code="invalid_password")
    user = User(
        id=uuid.uuid4().hex,
        username=username,
        password_hash=auth.hash_password(password),
        created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        is_admin=is_admin,
    )
    return repository.create_user(user)


def create_user_interactive(
    path: pathlib.Path | str, username: str | None = None
) -> User:
    """Create a local user after securely prompting for a password when necessary."""

    database_path = pathlib.Path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database_path)
    try:
        migrate(connection)
        selected_username = username if username is not None else input("Usuario: ").strip()
        password = getpass.getpass("Contraseña: ")
        return ensure_user(Repository(connection), selected_username, password)
    finally:
        connection.close()
