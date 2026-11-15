"""Command-line interface for deterministic conversion and environment reports."""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import platform
import sys
from typing import Any

from . import __version__
from .core.config import ALLOWED_RUNTIMES, Settings
from .core.errors import RoseNexusError, SandboxUnavailableError
from .security.sandbox import SandboxLimits, detect_runtime, validate_image_reference
from .studio.branding import list_profiles
from .studio.pipeline import ConversionResult, convert_document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rose",
        description="Convert Markdown and text documents into branded LaTeX and PDF.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    convert = commands.add_parser("convert", help="convert a .md or .txt document")
    convert.add_argument("source", type=pathlib.Path, metavar="SRC")
    convert.add_argument("--brand", help="brand profile name")
    convert.add_argument("--out", type=pathlib.Path, help="job output directory")
    convert.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=("tex", "pdf"),
        help="output format; repeat to request both",
    )
    convert.add_argument("--title")
    convert.add_argument("--subtitle")
    convert.add_argument("--author")
    convert.add_argument("--date")
    convert.add_argument("--branding-root", type=pathlib.Path)
    convert.add_argument("--json", action="store_true", help="emit a JSON result")

    brands = commands.add_parser("brands", help="list validated brand profiles")
    brands.add_argument("--branding-root", type=pathlib.Path)
    brands.add_argument("--json", action="store_true", help="emit a JSON result")

    doctor = commands.add_parser("doctor", help="report conversion and sandbox readiness")
    doctor.add_argument("--json", action="store_true", help="emit a JSON result")
    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _convert(args: argparse.Namespace, settings: Settings) -> None:
    result: ConversionResult = convert_document(
        args.source,
        brand=args.brand,
        output_dir=args.out,
        branding_dir=args.branding_root,
        formats=tuple(args.formats) if args.formats else ("tex",),
        title=args.title,
        subtitle=args.subtitle,
        author=args.author,
        date=args.date,
        settings=settings,
    )
    manifest = result.manifest
    if args.json:
        _print_json(
            {
                "ok": True,
                "job_dir": str(result.job_dir),
                "status": manifest["status"],
                "brand": manifest["brand"],
                "artifacts": manifest["artifacts"],
                "manifest": str(result.manifest_path),
            }
        )
        return
    for artifact in manifest["artifacts"]:
        print(result.job_dir / artifact["path"])
    print(result.manifest_path)


def _brands(args: argparse.Namespace, settings: Settings) -> None:
    root = args.branding_root if args.branding_root is not None else settings.branding_dir
    profiles = tuple(profile.as_manifest(branding_root=root) for profile in list_profiles(root))
    if args.json:
        _print_json({"ok": True, "profiles": list(profiles)})
        return
    for profile in profiles:
        state = "provisional" if profile["provisional"] else "verified"
        print(
            f"{profile['name']} {profile['version']} [{state}] "
            f"{profile['display_name']}"
        )


def _doctor(args: argparse.Namespace, settings: Settings) -> None:
    runtime = detect_runtime(settings.container_runtime)
    configured = bool(settings.sandbox_image)
    pinned = False
    if configured:
        try:
            validate_image_reference(settings.sandbox_image)
        except SandboxUnavailableError:
            pinned = False
        else:
            pinned = True

    branding_error: str | None = None
    try:
        profiles = [
            profile.as_manifest(branding_root=settings.branding_dir)
            for profile in list_profiles(settings.branding_dir)
        ]
    except RoseNexusError as error:
        profiles = []
        branding_error = str(error)

    runtime_allowed = runtime is not None and runtime.name in ALLOWED_RUNTIMES
    ready = bool(runtime_allowed and pinned and branding_error is None)
    limits = SandboxLimits(
        timeout_seconds=settings.compile_timeout_seconds,
        memory=settings.compile_memory,
        cpus=settings.compile_cpus,
        pids=settings.compile_pids,
    )
    branding: dict[str, Any] = {
        "root": str(settings.branding_dir),
        "profiles": profiles,
    }
    if branding_error is not None:
        branding["error"] = branding_error
    report = {
        "ok": True,
        "status": "ready" if ready else "degraded",
        "ready_to_compile": ready,
        "python": {
            "version": platform.python_version(),
            "version_info": list(sys.version_info[:3]),
            "executable": sys.executable,
        },
        "container": {
            "runtime": runtime.name if runtime is not None else None,
            "path": str(runtime.path) if runtime is not None else None,
            "allowed": runtime_allowed,
            "image": {"configured": configured, "pinned": pinned},
        },
        "branding": branding,
        "limits": dataclasses.asdict(limits),
    }
    if args.json:
        _print_json(report)
        return
    print(f"status: {report['status']}")
    print(f"ready_to_compile: {str(ready).lower()}")
    print(f"python: {report['python']['version']} ({sys.executable})")
    print(f"container runtime: {report['container']['runtime'] or 'unavailable'}")
    print(f"sandbox image pinned: {str(pinned).lower()}")
    print(f"branding root: {settings.branding_dir}")
    print(f"brand profiles: {', '.join(profile['name'] for profile in profiles) or 'none'}")
    if branding_error is not None:
        print(f"branding error: {branding_error}")


def _report_error(error: RoseNexusError, *, json_output: bool) -> int:
    print(f"error: {error.code}: {error.message}", file=sys.stderr)
    if error.detail:
        for line in str(error.detail).splitlines() or [""]:
            print(f"  {line}", file=sys.stderr)
    if isinstance(error, SandboxUnavailableError) and error.code != "sandbox_unavailable":
        # Keep the specific machine code while retaining the public category name.
        print("  category: sandbox_unavailable", file=sys.stderr)
    if json_output:
        _print_json({"ok": False, "error": error.as_dict()})
    return error.exit_code


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return its stable process exit code."""

    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "convert":
            _convert(args, settings)
        elif args.command == "brands":
            _brands(args, settings)
        elif args.command == "doctor":
            _doctor(args, settings)
        else:  # pragma: no cover - argparse makes this unreachable
            raise AssertionError(f"unsupported command: {args.command}")
    except RoseNexusError as error:
        return _report_error(error, json_output=bool(getattr(args, "json", False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
