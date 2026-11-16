"""Transport-independent document, rendering and installed-brand operations."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..core.config import Settings
from ..core.errors import InputValidationError
from ..studio.branding import list_profiles, load_profile
from .jobs import JobRunner
from .models import Job, User
from .repository import Repository


def _not_found(kind: str) -> InputValidationError:
    """Hide missing and foreign-owned rows behind the same stable error."""

    return InputValidationError(f"{kind} not found", code=f"{kind}_not_found")


def _submit_job(
    *,
    repository: Repository,
    runner: JobRunner,
    settings: Settings,
    user: User,
    document_id: str,
    brand: str,
    formats: list[str],
) -> str:
    """Validate an owned request, then persist and enqueue its web database job."""

    document = repository.get_document(document_id, user.id)
    if document is None:
        raise _not_found("document")
    if not formats or any(name not in {"tex", "pdf"} for name in formats):
        raise InputValidationError(
            "formats must be a nonempty subset of tex and pdf", code="unsupported_format"
        )
    if len(set(formats)) != len(formats):
        raise InputValidationError(
            "formats must not contain duplicates", code="unsupported_format"
        )
    load_profile(settings.branding_dir, brand)
    job_id = uuid.uuid4().hex
    repository.create_job(
        Job(
            id=job_id,
            document_id=document_id,
            user_id=user.id,
            status="pending",
            brand=brand,
            formats=json.dumps(formats, separators=(",", ":")),
            error_code=None,
            error_message=None,
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            started_at=None,
            finished_at=None,
            duration_ms=None,
        )
    )
    runner.submit(job_id)
    return job_id


def submit_render(
    *,
    repository: Repository,
    runner: JobRunner,
    settings: Settings,
    user: User,
    document_id: str,
    brand: str,
    output_format: str,
) -> dict[str, str]:
    """Submit TeX-only or TeX+PDF rendering and return its pending web job id."""

    if output_format not in {"tex", "pdf"}:
        raise InputValidationError(
            "output_format must be 'tex' or 'pdf'", code="unsupported_format"
        )
    formats = ["tex"] if output_format == "tex" else ["tex", "pdf"]
    job_id = _submit_job(
        repository=repository,
        runner=runner,
        settings=settings,
        user=user,
        document_id=document_id,
        brand=brand,
        formats=formats,
    )
    return {"job_id": job_id, "status": "pending"}


def get_document_status(
    *, repository: Repository, user: User, job_id: str
) -> dict[str, Any]:
    """Return a fixed, serializable job view without paths or download URLs."""

    job = repository.get_job(job_id, user.id)
    if job is None:
        raise _not_found("job")
    artifacts = repository.list_artifacts(job.id, user.id)
    error_message = job.error_message
    if job.error_code == "internal_error":
        error_message = "the job failed due to an internal error"
    elif error_message is not None:
        error_message = error_message[:2_000]
    return {
        "job_id": job.id,
        "status": job.status,
        "error_code": job.error_code,
        "error_message": error_message,
        "artifacts": [
            {"kind": artifact.kind, "bytes": artifact.bytes, "sha256": artifact.sha256}
            for artifact in artifacts
        ],
    }


def get_document_metadata(
    *, repository: Repository, user: User, document_id: str
) -> dict[str, str | int]:
    """Return owned display metadata, never source bytes or storage locations."""

    document = repository.get_document(document_id, user.id)
    if document is None:
        raise _not_found("document")
    return {
        "document_id": document.id,
        "filename": document.filename,
        "space": document.space,
        "created_at": document.created_at,
        "bytes": document.bytes,
        "sha256": document.sha256,
    }


def list_brand_profiles(settings: Settings) -> list[dict[str, Any]]:
    """Return manifests produced from every validated installed brand profile."""

    return [
        profile.as_manifest(branding_root=settings.branding_dir)
        for profile in list_profiles(settings.branding_dir)
    ]
