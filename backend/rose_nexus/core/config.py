"""Configuration from environment variables (no ambient file loading)."""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass
from typing import Mapping

from .errors import InputValidationError

# Source-checkout root. Wheels are out of scope for H1: branding assets are read
# from the repository, which keeps provenance explicit.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

ALLOWED_RUNTIMES = frozenset({"docker", "podman"})


def _int_value(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise InputValidationError(
            f"{key} must be an integer", code="invalid_configuration", detail=str(error)
        ) from error
    if value <= 0:
        raise InputValidationError(f"{key} must be positive", code="invalid_configuration")
    return value


@dataclass(frozen=True)
class Settings:
    """Runtime configuration for the document pipeline."""

    branding_dir: pathlib.Path = REPO_ROOT / "branding"
    output_dir: pathlib.Path = REPO_ROOT / "build"
    max_input_bytes: int = 2_097_152
    max_image_bytes: int = 8_388_608
    container_runtime: str | None = None
    sandbox_image: str = ""
    compile_timeout_seconds: int = 90
    compile_memory: str = "1g"
    compile_cpus: str = "1.0"
    compile_pids: int = 128

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        runtime = (source.get("ROSE_CONTAINER_RUNTIME") or "").strip().lower() or None
        if runtime is not None and runtime not in ALLOWED_RUNTIMES:
            raise InputValidationError(
                "ROSE_CONTAINER_RUNTIME must be 'docker' or 'podman'",
                code="invalid_configuration",
                detail=runtime,
            )
        return cls(
            branding_dir=pathlib.Path(source.get("ROSE_BRANDING_DIR") or REPO_ROOT / "branding"),
            output_dir=pathlib.Path(source.get("ROSE_OUTPUT_DIR") or REPO_ROOT / "build"),
            max_input_bytes=_int_value(source, "ROSE_MAX_INPUT_BYTES", 2_097_152),
            max_image_bytes=_int_value(source, "ROSE_MAX_IMAGE_BYTES", 8_388_608),
            container_runtime=runtime,
            sandbox_image=(source.get("ROSE_SANDBOX_IMAGE") or "").strip(),
            compile_timeout_seconds=_int_value(source, "ROSE_COMPILE_TIMEOUT_SECONDS", 90),
            compile_memory=(source.get("ROSE_COMPILE_MEMORY") or "1g").strip(),
            compile_cpus=(source.get("ROSE_COMPILE_CPUS") or "1.0").strip(),
            compile_pids=_int_value(source, "ROSE_COMPILE_PIDS", 128),
        )
