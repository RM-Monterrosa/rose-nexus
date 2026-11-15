"""Content-addressed originals and traversal-safe web job artifacts."""

from __future__ import annotations

import pathlib
import re
import unicodedata
from dataclasses import dataclass

from ..core.errors import LatexPolicyViolation
from ..storage.artifacts import sha256_bytes


_SAFE_JOB_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", re.ASCII)
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)
_KINDS = {"source", "tex", "pdf"}


@dataclass(frozen=True)
class Original:
    """The digest and storage path of one deduplicated original."""

    sha256: str
    path: pathlib.Path


@dataclass(frozen=True)
class ArtifactRecord:
    """Repository-ready metadata for one written artifact."""

    relative_path: str
    sha256: str
    bytes: int


def _unsafe(path: str) -> LatexPolicyViolation:
    return LatexPolicyViolation(
        "web storage paths must be safe relative slugs",
        code="unsafe_web_path",
        detail=path,
    )


def _validated_job_id(job_id: str) -> str:
    if (
        not _SAFE_JOB_ID.fullmatch(job_id)
        or ".." in job_id
        or pathlib.PurePosixPath(job_id).is_absolute()
        or pathlib.PureWindowsPath(job_id).is_absolute()
    ):
        raise _unsafe(job_id)
    return job_id


def safe_display_name(name: str) -> str:
    """Reduce an untrusted upload name to a nonempty, single display component."""

    component = name.replace("\\", "/").rsplit("/", 1)[-1]
    component = "".join(
        character for character in component if unicodedata.category(character) not in {"Cc", "Cf"}
    ).strip()
    return component if component not in {"", ".", ".."} else "document"


class Storage:
    """Store original bytes by digest and generated files below a validated job id."""

    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root)

    def save_original(self, data: bytes) -> Original:
        """Persist immutable bytes once at ``originals/<first2>/<sha256>``."""

        digest = sha256_bytes(data)
        target = self.root / "originals" / digest[:2] / digest
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as handle:
                handle.write(data)
        except FileExistsError:
            pass
        return Original(digest, target)

    def read_original(self, sha256: str) -> bytes:
        """Read an original by a validated content digest."""

        if not _SHA256.fullmatch(sha256):
            raise _unsafe(sha256)
        return (self.root / "originals" / sha256[:2] / sha256).read_bytes()

    def job_dir(self, job_id: str) -> pathlib.Path:
        """Return the path for a safe job id without touching the filesystem."""

        return self.root / "jobs" / _validated_job_id(job_id)

    def _target(self, job_id: str, relative_path: str) -> pathlib.Path:
        job_root = self.job_dir(job_id)
        relative = pathlib.PurePosixPath(relative_path)
        invalid = (
            not relative_path
            or "\\" in relative_path
            or "\x00" in relative_path
            or relative.is_absolute()
            or pathlib.PureWindowsPath(relative_path).is_absolute()
            or relative_path != relative.as_posix()
            or ".." in relative.parts
            or "." in relative.parts
        )
        if invalid:
            raise _unsafe(relative_path)
        target = job_root.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(job_root.resolve()):
            raise _unsafe(relative_path)
        return target

    def write_artifact(
        self,
        job_id: str,
        kind: str,
        data: bytes,
        *,
        name: str | None = None,
    ) -> ArtifactRecord:
        """Write a source, TeX or PDF artifact and return its verified metadata.

        ``name`` is used only for source artifacts, whose display filename is
        retained. TeX and PDF always use deterministic engine-owned filenames.
        """

        if kind not in _KINDS:
            raise _unsafe(kind)
        if kind == "source":
            relative_path = f"source/{safe_display_name(name or 'document')}"
        else:
            relative_path = "document.tex" if kind == "tex" else "document.pdf"
        target = self._target(job_id, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return ArtifactRecord(relative_path, sha256_bytes(data), len(data))

    def read_artifact(self, job_id: str, kind: str) -> bytes:
        """Read a generated artifact by kind, never by a client-provided path."""

        if kind not in _KINDS:
            raise _unsafe(kind)
        if kind == "source":
            source_root = self._target(job_id, "source/document").parent
            try:
                candidates = sorted(path for path in source_root.iterdir() if path.is_file())
            except FileNotFoundError:
                candidates = []
            if len(candidates) != 1:
                raise FileNotFoundError(f"expected one source artifact for job {job_id}")
            target = candidates[0]
        else:
            target = self._target(job_id, "document.tex" if kind == "tex" else "document.pdf")
        return target.read_bytes()
