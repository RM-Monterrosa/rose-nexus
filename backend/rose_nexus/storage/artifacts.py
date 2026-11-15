"""Manage isolated job directories, artifact hashes and final manifests."""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from ..core.errors import LatexPolicyViolation

_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_UNSAFE_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Job:
    """Paths for a job's temporary workspace and final artifact directory."""

    job_id: str
    root: pathlib.Path
    work: pathlib.Path


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 digest of ``data``."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: pathlib.Path | str) -> str:
    """Return the SHA-256 digest of a file without loading it all in memory."""

    digest = hashlib.sha256()
    with pathlib.Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_slug(slug: str) -> str:
    normalized = _UNSAFE_SLUG.sub("-", slug.strip().lower()).strip("-")
    if not normalized:
        raise LatexPolicyViolation(
            "a job slug must contain an ASCII letter or digit",
            code="invalid_job_slug",
            detail=slug,
        )
    return normalized


def create_job(
    output_dir: pathlib.Path | str,
    slug: str,
    *,
    job_id: str | None = None,
) -> Job:
    """Create a new temporary job workspace without reusing final artifacts."""

    if job_id is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        job_id = f"{_safe_slug(slug)}-{timestamp}-{secrets.token_hex(3)}"
    elif not _SAFE_JOB_ID.fullmatch(job_id) or job_id in {".", ".."}:
        raise LatexPolicyViolation(
            "a job id must be a safe single path component",
            code="invalid_job_id",
            detail=job_id,
        )

    output = pathlib.Path(output_dir)
    job = Job(
        job_id=job_id,
        root=output / job_id,
        work=output / f".{job_id}.tmp",
    )
    if job.root.exists() or job.work.exists():
        raise LatexPolicyViolation(
            "the job directory already exists",
            code="job_exists",
            detail=job_id,
        )
    output.mkdir(parents=True, exist_ok=True)
    try:
        job.work.mkdir()
    except FileExistsError as error:
        raise LatexPolicyViolation(
            "the job directory already exists",
            code="job_exists",
            detail=job_id,
        ) from error
    return job


def _artifact_target(job: Job, relative: str) -> pathlib.Path:
    invalid = (
        not relative
        or "\\" in relative
        or "\x00" in relative
        or pathlib.PurePosixPath(relative).is_absolute()
        or pathlib.PureWindowsPath(relative).is_absolute()
    )
    relative_path = pathlib.PurePosixPath(relative)
    if (
        invalid
        or relative != relative_path.as_posix()
        or relative in {".", ".."}
        or ".." in relative_path.parts
    ):
        raise LatexPolicyViolation(
            "artifact paths must be normalized relative paths inside the job",
            code="unsafe_artifact_path",
            detail=relative,
        )

    work_root = job.work.resolve()
    target = job.work.joinpath(*relative_path.parts)
    if not target.resolve().is_relative_to(work_root):
        raise LatexPolicyViolation(
            "artifact paths must stay inside the job workspace",
            code="unsafe_artifact_path",
            detail=relative,
        )
    return target


def write_bytes(job: Job, relative: str, data: bytes) -> dict[str, Any]:
    """Write one job artifact and return its path, digest and byte count."""

    target = _artifact_target(job, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(job.work.resolve()):
        raise LatexPolicyViolation(
            "artifact paths must stay inside the job workspace",
            code="unsafe_artifact_path",
            detail=relative,
        )
    target.write_bytes(data)
    return {
        "path": relative,
        "sha256": sha256_bytes(data),
        "bytes": len(data),
    }


def finalize_job(job: Job, manifest: Mapping[str, Any]) -> pathlib.Path:
    """Write the canonical manifest, then atomically publish the job directory."""

    if job.root.exists():
        raise LatexPolicyViolation(
            "the job directory already exists",
            code="job_exists",
            detail=job.job_id,
        )
    serialized = json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    write_bytes(job, "manifest.json", serialized.encode("utf-8"))
    job.work.rename(job.root)
    return job.root


def abort_job(job: Job) -> None:
    """Remove only the unpublished temporary workspace, if it still exists."""

    if job.work.exists():
        shutil.rmtree(job.work)
