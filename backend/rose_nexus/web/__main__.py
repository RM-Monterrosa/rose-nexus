"""Programmatic uvicorn serving and trusted local-user administration."""

from __future__ import annotations

import argparse
import os
import pathlib
from collections.abc import Sequence

from rose_nexus import __version__

from .app import build_app_from_env
from .bootstrap import create_user_interactive
from ..core.config import Settings


def _parser() -> argparse.ArgumentParser:
    """Define the intentionally loopback-only serving default."""

    parser = argparse.ArgumentParser(description="Rose Nexus web application")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--serve", action="store_true", help="serve the web application")
    action.add_argument("--create-user", metavar="USER", help="create a local user interactively")
    action.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicitly selected administrative or HTTP serving action."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.create_user is not None:
        settings = Settings.from_env()
        default_path = settings.output_dir / "rose-nexus.db"
        path = pathlib.Path(os.environ.get("ROSE_DB_PATH") or default_path)
        user = create_user_interactive(path, arguments.create_user)
        print(f"Usuario disponible: {user.username}")
        return 0
    if not arguments.serve:
        parser.print_help()
        return 0
    if not (1 <= arguments.port <= 65535):
        parser.error("--port must be between 1 and 65535")
    import uvicorn

    uvicorn.run(build_app_from_env(), host=arguments.host, port=arguments.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
