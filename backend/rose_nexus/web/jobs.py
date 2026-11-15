"""Single-worker conversion queue that persists every observable job transition."""

from __future__ import annotations

import json
import queue
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..core.config import Settings
from ..core.errors import InputValidationError, RoseNexusError
from ..studio.pipeline import ConversionResult, convert_document
from .repository import Repository
from .storage import Storage, safe_display_name


Converter = Callable[..., ConversionResult]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _formats(serialized: str) -> tuple[str, ...]:
    decoded = json.loads(serialized)
    if not isinstance(decoded, list) or not all(isinstance(item, str) for item in decoded):
        raise InputValidationError(
            "job formats must be a JSON array of strings", code="unsupported_format"
        )
    return tuple(decoded)


class JobRunner:
    """Process submitted ids sequentially without allowing converter errors to escape."""

    def __init__(
        self,
        repository: Repository,
        storage: Storage,
        settings: Settings,
        converter: Converter = convert_document,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.settings = settings
        self.converter = converter
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Recover stale work and start the one background worker, once."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self.recover_interrupted()
            self._thread = threading.Thread(target=self._work, name="rose-web-jobs", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Request a graceful stop and wait at most ``timeout`` seconds."""

        with self._lock:
            thread = self._thread
            if thread is None or not thread.is_alive():
                return
            self._queue.put(None)
        if thread is not threading.current_thread():
            thread.join(timeout)

    def submit(self, job_id: str) -> None:
        """Queue a pending job id for sequential processing."""

        self._queue.put(job_id)

    def recover_interrupted(self) -> None:
        """Fail all jobs left running by a previous process or worker."""

        finished_at = _utc_now()
        for job in self.repository.list_jobs():
            if job.status == "running":
                self.repository.update_job_status(
                    job.id,
                    "failed",
                    error_code="interrupted",
                    error_message="the worker restarted before this job finished",
                    started_at=job.started_at,
                    finished_at=finished_at,
                )

    def _work(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                if job_id is None:
                    return
                try:
                    self._process(job_id)
                except Exception:
                    # A repository or storage failure must not silently kill the worker.
                    try:
                        self.repository.update_job_status(
                            job_id,
                            "failed",
                            error_code="internal_error",
                            error_message="the job could not be processed",
                            finished_at=_utc_now(),
                        )
                    except Exception:
                        pass
            finally:
                self._queue.task_done()

    def _process(self, job_id: str) -> None:
        started = time.perf_counter()
        try:
            job = self.repository.get_job(job_id)
            if job is None or job.status != "pending":
                return
            self.repository.update_job_status(job.id, "running", started_at=_utc_now())
            document = self.repository.get_document(job.document_id, job.user_id)
            if document is None:
                raise InputValidationError(
                    "the job source document does not exist", code="source_not_found"
                )
            original = self.storage.read_original(document.sha256)
            with tempfile.TemporaryDirectory(prefix="rose-web-") as temporary:
                source = Path(temporary) / safe_display_name(document.filename)
                source.write_bytes(original)
                result = self.converter(
                    source,
                    brand=job.brand,
                    formats=_formats(job.formats),
                    settings=self.settings,
                )
                self._store_result(job.id, document.filename, source.name, result)
            self.repository.update_job_status(
                job.id,
                "completed",
                finished_at=_utc_now(),
                duration_ms=_duration_ms(started),
            )
        except RoseNexusError as error:
            self.repository.update_job_status(
                job_id,
                "failed",
                error_code=error.code,
                error_message=error.message,
                finished_at=_utc_now(),
                duration_ms=_duration_ms(started),
            )
        except Exception as error:
            self.repository.update_job_status(
                job_id,
                "failed",
                error_code="internal_error",
                error_message=str(error) or error.__class__.__name__,
                finished_at=_utc_now(),
                duration_ms=_duration_ms(started),
            )

    def _store_result(
        self, job_id: str, display_name: str, temporary_name: str, result: ConversionResult
    ) -> None:
        produced = [
            ("source", result.job_dir / "source" / temporary_name),
            ("tex", result.tex_path),
        ]
        if result.pdf_path is not None:
            produced.append(("pdf", result.pdf_path))
        for kind, path in produced:
            record = self.storage.write_artifact(
                job_id,
                kind,
                path.read_bytes(),
                name=display_name if kind == "source" else None,
            )
            self.repository.add_artifact(
                job_id=job_id,
                kind=kind,
                relative_path=record.relative_path,
                sha256=record.sha256,
                bytes=record.bytes,
            )
