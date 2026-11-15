"""Command-line interface for deterministic conversion and environment reports."""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import platform
import statistics
import sys
from typing import Any

from . import __version__
from .ai.client import InferenceClient
from .ai.errors import InferenceHTTPError, InferenceProtocolError, InferenceUnavailable
from .ai.settings import InferenceSettings
from .core.config import ALLOWED_RUNTIMES, Settings
from .core.errors import InputValidationError, RoseNexusError, SandboxUnavailableError
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

    llm = commands.add_parser("llm", help="diagnose and exercise local inference")
    llm_commands = llm.add_subparsers(dest="llm_command", required=True)

    health = llm_commands.add_parser("health", help="check endpoint and model availability")
    _add_llm_options(health)

    ask = llm_commands.add_parser("ask", help="request one local chat completion")
    _add_llm_options(ask)
    ask.add_argument("--prompt", help="user prompt text")
    ask.add_argument("--prompt-file", type=pathlib.Path, help="UTF-8 user prompt file")
    ask.add_argument("--system", default="You are a helpful assistant.", help="system prompt")
    ask.add_argument("--max-tokens", type=int, help="maximum generated tokens")
    ask.add_argument("--temperature", type=float, help="sampling temperature")

    bench = llm_commands.add_parser("bench", help="measure repeated local completions")
    _add_llm_options(bench)
    bench.add_argument("--runs", type=int, default=3, help="number of runs, from 1 to 20")
    bench.add_argument("--prompt", default="Reply with a short benchmark response.")
    return parser


def _add_llm_options(command: argparse.ArgumentParser) -> None:
    """Add shared local-inference overrides and output selection."""
    command.add_argument("--endpoint", help="override the OpenAI-compatible endpoint")
    command.add_argument("--model", help="override the configured model name")
    command.add_argument("--json", action="store_true", help="emit a JSON result")


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


def _llm_settings(args: argparse.Namespace) -> InferenceSettings:
    """Build inference settings with explicit CLI overrides taking precedence."""
    settings = InferenceSettings.from_env()
    overrides: dict[str, Any] = {}
    if args.endpoint is not None:
        overrides["endpoint"] = args.endpoint
    if args.model is not None:
        overrides["model"] = args.model
    return dataclasses.replace(settings, **overrides)


def _llm_health(args: argparse.Namespace) -> int:
    """Report endpoint diagnostics without requiring inference to be enabled."""
    settings = _llm_settings(args)
    status = InferenceClient(settings).health()
    healthy = status.available and status.model_present
    if args.json:
        _print_json(
            {
                "ok": healthy,
                "health": {
                    **dataclasses.asdict(status),
                    "model": settings.model,
                },
            }
        )
    else:
        print(
            f"available={str(status.available).lower()} "
            f"model_present={str(status.model_present).lower()} "
            f"model={settings.model} latency_ms={status.latency_ms:.2f}"
        )
    if not healthy:
        print(
            "error: inference_model_unavailable: configured model is not present",
            file=sys.stderr,
        )
        return 4
    return 0


def _ask_prompt(args: argparse.Namespace) -> str:
    """Read exactly one bounded UTF-8 prompt without exposing its contents."""
    if (args.prompt is None) == (args.prompt_file is None):
        raise InputValidationError(
            "exactly one of --prompt or --prompt-file is required"
        )
    if args.prompt is not None:
        return args.prompt
    try:
        with args.prompt_file.open("rb") as prompt_file:
            raw_prompt = prompt_file.read(65537)
    except OSError as error:
        raise InputValidationError("prompt file could not be read") from error
    if len(raw_prompt) > 65536:
        raise InputValidationError(
            "prompt file exceeds the 65536-byte limit", code="prompt_too_large"
        )
    try:
        return raw_prompt.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise InputValidationError("prompt file must contain valid UTF-8") from error


def _llm_ask(args: argparse.Namespace) -> None:
    """Print one answer and its content-free inference measurements."""
    prompt = _ask_prompt(args)
    settings = _llm_settings(args)
    overrides: dict[str, Any] = {}
    if args.max_tokens is not None:
        overrides["max_tokens"] = args.max_tokens
    if args.temperature is not None:
        overrides["temperature"] = args.temperature
    settings = dataclasses.replace(settings, **overrides)
    answer = InferenceClient(settings).ask(args.system, prompt)
    if args.json:
        _print_json(
            {
                "ok": True,
                "answer": answer.text,
                "metrics": dataclasses.asdict(answer.metrics),
            }
        )
        return
    print(answer.text)
    print(f"metrics: {answer.metrics.as_log()}", file=sys.stderr)


def _llm_bench(args: argparse.Namespace) -> int:
    """Measure repeated completions and summarize successful measurements."""
    if not 1 <= args.runs <= 20:
        raise InputValidationError("--runs must be between 1 and 20")
    client = InferenceClient(_llm_settings(args))
    runs: list[dict[str, Any]] = []
    failures = 0
    for run_number in range(1, args.runs + 1):
        try:
            answer = client.ask("You are a helpful assistant.", args.prompt)
        except InferenceUnavailable:
            raise
        except (InferenceProtocolError, InferenceHTTPError) as error:
            failures += 1
            runs.append(
                {
                    "run": run_number,
                    "wall_ms": None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "tokens_per_second": None,
                    "finish_reason": None,
                    "error": error.code,
                }
            )
            continue
        metrics = answer.metrics
        runs.append(
            {
                "run": run_number,
                "wall_ms": metrics.latency_ms,
                "prompt_tokens": metrics.prompt_tokens,
                "completion_tokens": metrics.completion_tokens,
                "tokens_per_second": metrics.tokens_per_second,
                "finish_reason": metrics.finish_reason,
                "error": None,
            }
        )

    successful_runs = [run for run in runs if run["error"] is None]
    wall_times = [run["wall_ms"] for run in successful_runs]
    speeds = [
        run["tokens_per_second"]
        for run in successful_runs
        if run["tokens_per_second"] is not None
    ]
    summary = {
        "runs": args.runs,
        "failures": failures,
        "wall_median_ms": statistics.median(wall_times) if wall_times else None,
        "tok_s_median": statistics.median(speeds) if speeds else None,
    }
    if args.json:
        _print_json({"ok": failures == 0, "runs": runs, "summary": summary})
    else:
        print("run wall_ms prompt_tokens completion_tokens tok_s finish_reason")
        for run in runs:
            print(
                f"{run['run']} "
                f"{_bench_number(run['wall_ms'])} "
                f"{_bench_number(run['prompt_tokens'])} "
                f"{_bench_number(run['completion_tokens'])} "
                f"{_bench_number(run['tokens_per_second'])} "
                f"{run['finish_reason'] or '-'}"
            )
        print(
            f"summary: runs={summary['runs']} failures={summary['failures']} "
            f"wall_median_ms={_bench_number(summary['wall_median_ms'])} "
            f"tok_s_median={_bench_number(summary['tok_s_median'])}"
        )
    return 5 if failures else 0


def _bench_number(value: object) -> str:
    """Format numeric table cells without inventing unavailable measurements."""
    if value is None:
        return "-"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.2f}"  # type: ignore[arg-type]


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
        if args.command == "llm":
            if args.llm_command == "health":
                return _llm_health(args)
            if args.llm_command == "ask":
                _llm_ask(args)
                return 0
            return _llm_bench(args)

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
        json_output = bool(getattr(args, "json", False))
        if args.command == "llm" and args.llm_command == "health":
            json_output = False
        return _report_error(error, json_output=json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
