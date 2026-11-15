"""Compile generated LaTeX exclusively inside a hardened container runtime."""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass

from ..core.errors import CompileError, SandboxUnavailableError

_IMAGE_REFERENCE = re.compile(r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class SandboxLimits:
    """Resource and execution limits applied to every compilation pass."""

    timeout_seconds: int = 90
    memory: str = "1g"
    cpus: str = "1.0"
    pids: int = 128
    tmpfs_size: str = "64m"


@dataclass(frozen=True)
class SandboxRuntime:
    """A supported container runtime resolved on the executable path."""

    name: str
    path: pathlib.Path


@dataclass(frozen=True)
class CompileResult:
    """The PDF produced by two successful sandboxed LaTeX passes."""

    pdf_path: pathlib.Path


_MAX_LOG_CHARS = 4000


def _bounded_log(text: str) -> str:
    """Keep compiler diagnostics useful without dumping unbounded output."""

    if len(text) <= _MAX_LOG_CHARS:
        return text
    return (
        text[:_MAX_LOG_CHARS]
        + f"\n[... truncated: the sandbox log exceeded {_MAX_LOG_CHARS} characters ...]"
    )


def detect_runtime(preferred: str | None = None) -> SandboxRuntime | None:
    """Find the preferred runtime, then Podman, then Docker, if available."""

    candidates = ([preferred] if preferred else []) + ["podman", "docker"]
    seen: set[str] = set()
    for name in candidates:
        if name in seen:
            continue
        seen.add(name)
        executable = shutil.which(name)
        if executable is not None:
            return SandboxRuntime(name=name, path=pathlib.Path(executable))
    return None


def validate_image_reference(image: str) -> str:
    """Return a repository image pinned by an immutable SHA-256 digest."""

    if not image.strip():
        raise SandboxUnavailableError(
            "the sandbox image has not been provisioned",
            code="sandbox_image_not_provisioned",
        )
    if not _IMAGE_REFERENCE.fullmatch(image):
        raise SandboxUnavailableError(
            "the sandbox image must be pinned by a lowercase SHA-256 digest",
            code="sandbox_image_not_pinned",
            detail=image,
        )
    return image


def _mount_source(path: pathlib.Path | str) -> str:
    resolved = pathlib.Path(path).resolve()
    value = str(resolved)
    if "," in value or ":" in value:
        raise SandboxUnavailableError(
            "container mount paths cannot contain commas or colons",
            code="sandbox_mount_path_invalid",
            detail=value,
        )
    return value


def build_compile_argv(
    runtime: SandboxRuntime,
    *,
    image: str,
    source_dir: pathlib.Path | str,
    output_dir: pathlib.Path | str,
    limits: SandboxLimits,
) -> list[str]:
    """Build one hardened container invocation without invoking the runtime."""

    validate_image_reference(image)
    source = _mount_source(source_dir)
    output = _mount_source(output_dir)
    return [
        str(runtime.path),
        "run",
        "--rm",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        f"--pids-limit={limits.pids}",
        f"--memory={limits.memory}",
        f"--memory-swap={limits.memory}",
        f"--cpus={limits.cpus}",
        f"--tmpfs=/tmp:rw,noexec,nosuid,size={limits.tmpfs_size},mode=1777",
        # Volume syntax with :Z relabels the bind mount for SELinux. Without it
        # (or with --mount type=bind) the container cannot read /src on an
        # Enforcing Fedora host: the kernel denies access before xelatex runs.
        "-v",
        f"{source}:/src:ro,Z",
        "-v",
        f"{output}:/out:rw,Z",
        "--workdir=/src",
        "--env=SOURCE_DATE_EPOCH=0",
        image,
        "xelatex",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        "-output-directory=/out",
        "document.tex",
    ]


def compile_document(
    tex_path: pathlib.Path | str,
    *,
    image: str,
    limits: SandboxLimits,
    runtime_name: str | None = None,
) -> CompileResult:
    """Run two containerized XeLaTeX passes and return the resulting PDF path."""

    validate_image_reference(image)
    runtime = detect_runtime(runtime_name)
    if runtime is None:
        raise SandboxUnavailableError(
            "no supported container runtime is available",
            code="sandbox_runtime_unavailable",
            detail=runtime_name,
        )

    source_dir = pathlib.Path(tex_path).parent.resolve()
    output_dir = source_dir / "pdf"
    output_dir.mkdir(mode=0o777, parents=True, exist_ok=True)
    output_dir.chmod(0o777)
    argv = build_compile_argv(
        runtime,
        image=image,
        source_dir=source_dir,
        output_dir=output_dir,
        limits=limits,
    )

    environment = os.environ.copy()
    for _ in range(2):
        try:
            completed = subprocess.run(
                argv,
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CompileError(
                "the sandboxed LaTeX compilation timed out",
                code="compile_timeout",
                detail=f"timeout after {limits.timeout_seconds} seconds",
            ) from error
        if completed.returncode != 0:
            detail = _bounded_log((completed.stderr or completed.stdout).strip())
            raise CompileError(
                "the sandboxed LaTeX compilation failed",
                code="compile_failed",
                detail=detail,
            )

    return CompileResult(pdf_path=output_dir / "document.pdf")
