"""Deterministic document conversion, job artifacts, and optional sandboxed PDF."""

from __future__ import annotations

import pathlib
import platform
import re
import shutil
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable

from rose_nexus import __version__

from ..core.config import Settings
from ..core.errors import (
    CompileError,
    InputValidationError,
    LatexPolicyViolation,
    SandboxUnavailableError,
)
from ..security.latex_policy import validate_generated_latex
from ..security.sandbox import (
    SandboxLimits,
    compile_document,
    detect_runtime,
    validate_image_reference,
)
from ..storage.artifacts import (
    Job,
    abort_job,
    create_job,
    finalize_job,
    sha256_bytes,
    write_bytes,
)
from .branding import BrandProfile, load_profile
from .latex import escape_text, render_body
from .model import Document, Heading, Image, Quote, plain_text
from .parser import parse_markdown, parse_plain_text
from .template import render_template


@dataclass(frozen=True)
class ConversionResult:
    """Published paths and the exact manifest produced for one conversion."""

    job_dir: pathlib.Path
    tex_path: pathlib.Path
    pdf_path: pathlib.Path | None
    manifest_path: pathlib.Path
    manifest: dict[str, Any]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _ResolvedImage:
    """A validated document image and its deterministic job-relative target."""

    declared_path: str
    source_path: pathlib.Path
    target: str


_ASSET_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_PAGE_SIZES = {"A4": "a4paper", "Letter": "letterpaper"}


def _settings(
    current: Settings | None,
    *,
    output_dir: pathlib.Path | str | None,
    branding_dir: pathlib.Path | str | None,
) -> Settings:
    resolved = current if current is not None else Settings.from_env()
    changes: dict[str, pathlib.Path] = {}
    if output_dir is not None:
        changes["output_dir"] = pathlib.Path(output_dir)
    if branding_dir is not None:
        changes["branding_dir"] = pathlib.Path(branding_dir)
    return replace(resolved, **changes) if changes else resolved


def _read_source(source: pathlib.Path, maximum: int) -> bytes:
    """Validate and read a source without creating the output directory."""

    if not source.is_file():
        raise InputValidationError(
            "the source document does not exist or is not a regular file",
            code="source_not_found",
            detail=source.as_posix(),
        )
    try:
        size = source.stat().st_size
    except OSError as error:
        raise InputValidationError(
            "the source document cannot be inspected",
            code="source_not_found",
            detail=str(error),
        ) from error
    if size > maximum:
        raise InputValidationError(
            f"the source document exceeds the {maximum}-byte input limit",
            code="input_too_large",
            detail=f"{size} bytes",
        )
    try:
        data = source.read_bytes()
    except OSError as error:
        raise InputValidationError(
            "the source document cannot be read",
            code="source_not_found",
            detail=str(error),
        ) from error
    if len(data) > maximum:
        raise InputValidationError(
            f"the source document exceeds the {maximum}-byte input limit",
            code="input_too_large",
            detail=f"{len(data)} bytes",
        )
    return data


def _decode_source(data: bytes) -> str:
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise InputValidationError(
            "the source document must be strict UTF-8",
            code="invalid_encoding",
            detail=f"byte {error.start}",
        ) from error


def _iter_images(document: Document) -> Iterable[Image]:
    """Yield image blocks in stable document order, including quoted blocks."""

    def walk(blocks: Iterable[object]) -> Iterable[Image]:
        for block in blocks:
            if isinstance(block, Image):
                yield block
            elif isinstance(block, Quote):
                yield from walk(block.blocks)

    yield from walk(document.blocks)


def _asset_name(path: pathlib.Path) -> str:
    sanitized = _ASSET_UNSAFE.sub("-", path.name).strip("-.")
    if not sanitized:
        sanitized = "image" + path.suffix.lower()
    return sanitized


def _resolve_images(
    document: Document,
    source: pathlib.Path,
    *,
    maximum: int,
) -> tuple[dict[str, str], tuple[_ResolvedImage, ...]]:
    """Validate every declared image before any job directory is created."""

    root = source.parent.resolve()
    image_map: dict[str, str] = {}
    resolved: list[_ResolvedImage] = []
    for image in _iter_images(document):
        declared = image.path
        if declared in image_map:
            continue
        posix_path = pathlib.PurePosixPath(declared)
        windows_path = pathlib.PureWindowsPath(declared)
        unsafe = (
            not declared
            or "\\" in declared
            or "\x00" in declared
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or ".." in posix_path.parts
            or ".." in windows_path.parts
        )
        if unsafe:
            raise LatexPolicyViolation(
                "image paths must be relative and stay inside the document directory",
                code="unsafe_image_path",
                detail=declared,
            )
        try:
            candidate = (source.parent / declared).resolve()
            inside = candidate.is_relative_to(root)
        except (OSError, RuntimeError) as error:
            raise LatexPolicyViolation(
                "the image path cannot be resolved safely",
                code="unsafe_image_path",
                detail=declared,
            ) from error
        if not inside or not candidate.is_file():
            raise LatexPolicyViolation(
                "the image must be a regular file inside the document directory",
                code="unsafe_image_path",
                detail=declared,
            )
        if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise InputValidationError(
                "only PNG and JPEG document images are supported",
                code="unsupported_image_type",
                detail=declared,
            )
        try:
            size = candidate.stat().st_size
        except OSError as error:
            raise LatexPolicyViolation(
                "the image cannot be inspected safely",
                code="unsafe_image_path",
                detail=declared,
            ) from error
        if size > maximum:
            raise InputValidationError(
                f"the image exceeds the {maximum}-byte image limit",
                code="image_too_large",
                detail=declared,
            )
        target = f"assets/{len(resolved) + 1:02d}-{_asset_name(candidate)}"
        image_map[declared] = target
        resolved.append(_ResolvedImage(declared, candidate, target))
    return image_map, tuple(resolved)


def _document_title(
    document: Document,
    source: pathlib.Path,
    explicit: str | None,
) -> str:
    if explicit is not None:
        return explicit
    if document.meta.title is not None:
        return document.meta.title
    for block in document.blocks:
        if isinstance(block, Heading):
            return plain_text(block)
    return source.stem


def _escaped(value: str) -> str:
    """Escape text and avoid adjacent braces being read as template tokens."""

    escaped = escape_text(value)
    if escaped.startswith("{"):
        escaped = " " + escaped
    if escaped.endswith("}"):
        escaped += " "
    return escaped


def _comment(value: str) -> str:
    """Escape one provenance value without allowing extra comment lines."""

    return escape_text(value.replace("\r", " ").replace("\n", " "))


def _font_setup(profile: BrandProfile) -> str:
    if not profile.fonts_verified:
        return "% Declared fonts are not applied until their licenses are verified."
    chunks = ["\\usepackage{fontspec}"]
    if profile.font_body:
        chunks.append("\\setmainfont{" + _escaped(profile.font_body) + "}")
    if profile.font_mono:
        chunks.append("\\setmonofont{" + _escaped(profile.font_mono) + "}")
    if profile.font_display:
        chunks.append(
            "\\newfontfamily\\BrandDisplay{" + _escaped(profile.font_display) + "}"
        )
    return "\n".join(chunks)


def _watermark_setup(profile: BrandProfile) -> str:
    if not profile.watermark:
        return ""
    return "\n".join(
        (
            "\\usepackage{draftwatermark}",
            "\\SetWatermarkText{" + _escaped(profile.watermark) + "}",
            "\\SetWatermarkScale{0.55}",
            "\\SetWatermarkLightness{0.9}",
        )
    )


def _cover(profile: BrandProfile, title: str, subtitle: str, author: str, date: str) -> str:
    if profile.cover_style == "none":
        return ""
    lines = [
        "\\begin{titlepage}",
        "\\centering",
        "\\vspace*{18mm}",
        "{\\color{RoseAccent}\\rule{0.72\\linewidth}{1.2pt} }",
        "\\vspace{12mm}",
        "{\\Huge\\bfseries " + _escaped(title) + "\\par}",
    ]
    if subtitle:
        lines.append("\\vspace{4mm}{\\Large " + _escaped(subtitle) + "\\par}")
    if author:
        lines.append("\\vspace{10mm}{\\large " + _escaped(author) + "\\par}")
    if date:
        lines.append("\\vspace{2mm}" + escape_text(date) + "\\par")
    lines.extend(("\\vfill", "{\\large " + _escaped(profile.display_name) + "\\par}"))
    if profile.provisional:
        lines.append("\\vspace{3mm}{\\small\\bfseries PROVISIONAL\\par}")
        if profile.provisional_note:
            lines.append(
                "\\vspace{2mm}{\\small " + _escaped(profile.provisional_note) + "\\par}"
            )
    lines.append("\\vspace{10mm}")
    return "\n".join(lines)


def _footer(profile: BrandProfile) -> str:
    center = profile.footer_center
    if profile.provisional and "provisional" not in center.lower():
        center = (center + " · PROVISIONAL").strip()
    right = _escaped(profile.footer_right) if profile.footer_right else "\\thepage"
    return "\n".join(
        (
            "\\fancyfoot[L]{" + _escaped(profile.footer_left) + "}",
            "\\fancyfoot[C]{" + _escaped(center) + "}",
            "\\fancyfoot[R]{" + right + "}",
        )
    )


def _render_document(
    document: Document,
    profile: BrandProfile,
    *,
    image_map: dict[str, str],
    title: str,
    subtitle: str,
    author: str,
    date: str,
    logo_target: str | None,
) -> str:
    """Render deterministic LaTeX with no paths, clocks, or job identifiers."""

    body = render_body(document.blocks, image_map=image_map)
    header_lines = [
        "% rose-nexus generated document",
        f"% Generator: Rose Nexus {_comment(__version__)}.",
        "% Brand: "
        + _comment(profile.display_name)
        + " ("
        + _comment(profile.version)
        + ").",
    ]
    if profile.source:
        header_lines.append("% Branding source commit: " + _comment(profile.source) + ".")
    if profile.provisional:
        header_lines.append(
            "% PROVISIONAL BRANDING: " + _comment(profile.provisional_note or "")
        )

    colors = "\n".join(
        (
            "% Brand palette: accent "
            + profile.accent
            + "; support "
            + profile.support
            + "; ink "
            + profile.ink
            + "; paper "
            + profile.paper
            + ".",
            "\\definecolor{RoseAccent}{HTML}{" + profile.accent.removeprefix("#") + "}",
            "\\definecolor{RoseSupport}{HTML}{" + profile.support.removeprefix("#") + "}",
            "\\definecolor{RoseInk}{HTML}{" + profile.ink.removeprefix("#") + "}",
            "\\definecolor{RosePaper}{HTML}{" + profile.paper.removeprefix("#") + "}",
            "\\AtBeginDocument{\\color{RoseInk}}",
        )
    )
    info = [
        "\\title{" + _escaped(title) + "}",
        "\\newcommand{\\documentsubtitle}{" + _escaped(subtitle) + "}",
        "\\author{" + _escaped(author) + "}",
        "\\date{" + _escaped(date) + "}",
    ]
    if document.meta.lang:
        info.append("\\newcommand{\\documentlanguage}{" + _escaped(document.meta.lang) + "}")

    cover = _cover(profile, title, subtitle, author, date)
    if profile.cover_style == "none":
        logo_block = ""
    else:
        pieces: list[str] = []
        if logo_target is not None:
            pieces.append(
                "\\includegraphics[width="
                + format(profile.logo_width_fraction, ".4f")
                + "\\linewidth]{"
                + logo_target
                + "}"
            )
        pieces.extend(("\\vfill", "\\end{titlepage}"))
        logo_block = "\n".join(pieces)

    values = {
        "header_comment": "\n".join(header_lines),
        "page_size": _PAGE_SIZES[profile.page_size],
        "colors": colors,
        "font_setup": _font_setup(profile),
        "watermark_setup": _watermark_setup(profile),
        "document_info": "\n".join(info),
        "footer_setup": _footer(profile),
        "cover": cover,
        "logo_block": logo_block,
    }
    template = profile.template.read_text(encoding="utf-8")
    return render_template(template, values, body=body)


def _record(job: Job, relative: str, data: bytes, kind: str) -> dict[str, Any]:
    record = write_bytes(job, relative, data)
    record["kind"] = kind
    return record


def _abort(job: Job) -> None:
    abort_job(job)


def convert_document(
    source: pathlib.Path | str,
    *,
    brand: str | None = None,
    output_dir: pathlib.Path | str | None = None,
    branding_dir: pathlib.Path | str | None = None,
    formats: Iterable[str] = ("tex",),
    title: str | None = None,
    subtitle: str | None = None,
    author: str | None = None,
    date: str | None = None,
    settings: Settings | None = None,
) -> ConversionResult:
    """Convert Markdown or plain text into a published, hashed job directory.

    Validation, brand selection, asset resolution, PDF preflight, and LaTeX
    policy validation happen before the job workspace is created. If PDF output
    is requested, both compilation passes run only through the hardened sandbox.
    """

    started = time.perf_counter()
    configuration = _settings(settings, output_dir=output_dir, branding_dir=branding_dir)
    source_path = pathlib.Path(source)
    if not source_path.is_file():
        raise InputValidationError(
            "the source document does not exist or is not a regular file",
            code="source_not_found",
            detail=source_path.as_posix(),
        )
    suffix = source_path.suffix.lower()
    if suffix not in {".md", ".txt"}:
        raise InputValidationError(
            "only .md and .txt source documents are supported",
            code="unsupported_source_type",
            detail=source_path.suffix,
        )
    source_bytes = _read_source(source_path, configuration.max_input_bytes)
    text = _decode_source(source_bytes)
    if suffix == ".md":
        document = parse_markdown(text, source_name=source_path.name)
        document_type = "markdown"
    else:
        document = parse_plain_text(text, source_name=source_path.name)
        document_type = "plain_text"

    format_names = tuple(formats)
    unknown_formats = sorted(set(format_names) - {"tex", "pdf"})
    if unknown_formats:
        raise InputValidationError(
            "only tex and pdf output formats are supported",
            code="unsupported_format",
            detail=", ".join(unknown_formats),
        )

    brand_name = brand if brand is not None else document.meta.brand or "invering"
    branding_root = configuration.branding_dir
    profile = load_profile(branding_root, brand_name)
    resolved_title = _document_title(document, source_path, title)
    resolved_subtitle = subtitle if subtitle is not None else document.meta.subtitle or ""
    resolved_author = author if author is not None else document.meta.author or ""
    resolved_date = date if date is not None else document.meta.date or ""

    wants_pdf = "pdf" in format_names
    runtime = None
    if wants_pdf:
        validate_image_reference(configuration.sandbox_image)
        runtime = detect_runtime(configuration.container_runtime)
        if runtime is None:
            raise SandboxUnavailableError(
                "no supported container runtime is available",
                code="sandbox_runtime_unavailable",
                detail=configuration.container_runtime,
            )

    image_map, images = _resolve_images(
        document, source_path, maximum=configuration.max_image_bytes
    )
    logo_target = "assets/00-logo" + profile.logo.suffix.lower() if profile.logo else None
    latex = _render_document(
        document,
        profile,
        image_map=image_map,
        title=resolved_title,
        subtitle=resolved_subtitle,
        author=resolved_author,
        date=resolved_date,
        logo_target=logo_target,
    )
    validate_generated_latex(latex)

    job = create_job(configuration.output_dir, source_path.stem)
    try:
        warnings: tuple[str, ...] = ()
        artifacts = [
            _record(job, f"source/{source_path.name}", source_bytes, "source")
        ]
        for image in images:
            artifacts.append(
                _record(job, image.target, image.source_path.read_bytes(), "image")
            )
        if profile.logo is not None and logo_target is not None:
            artifacts.append(_record(job, logo_target, profile.logo.read_bytes(), "logo"))
        artifacts.append(_record(job, "document.tex", latex.encode("utf-8"), "tex"))

        pdf_name: str | None = None
        if wants_pdf:
            limits = SandboxLimits(
                timeout_seconds=configuration.compile_timeout_seconds,
                memory=configuration.compile_memory,
                cpus=configuration.compile_cpus,
                pids=configuration.compile_pids,
            )
            # Compile inside a scratch directory: xelatex writes .aux/.log and its
            # own output that must never reach the published job directory.
            scratch = job.work / "_compile"
            scratch.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(job.work / "document.tex", scratch / "document.tex")
                # The .tex references assets/<file>; the sandbox must see them too.
                assets_dir = job.work / "assets"
                if assets_dir.is_dir():
                    shutil.copytree(assets_dir, scratch / "assets")
                compiled = compile_document(
                    scratch / "document.tex",
                    image=configuration.sandbox_image,
                    limits=limits,
                    runtime_name=runtime.name if runtime is not None else None,
                )
                if not compiled.pdf_path.is_file():
                    raise CompileError(
                        "the sandbox did not produce the expected PDF",
                        code="compile_output_missing",
                        detail=compiled.pdf_path.name,
                    )
                pdf_name = "document.pdf"
                artifacts.append(
                    _record(job, pdf_name, compiled.pdf_path.read_bytes(), "pdf")
                )
            finally:
                shutil.rmtree(scratch, ignore_errors=True)

        status = "compiled" if wants_pdf else "tex-only"
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "job_id": job.job_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": status,
            "source": {
                "name": source_path.name,
                "sha256": sha256_bytes(source_bytes),
                "bytes": len(source_bytes),
                "document_type": document_type,
            },
            "brand": profile.as_manifest(branding_root=branding_root),
            "artifacts": artifacts,
            "warnings": list(warnings),
            "tools": {
                "python": platform.python_version(),
                "container_runtime": runtime.name if runtime is not None else None,
                "sandbox_image": configuration.sandbox_image,
            },
            "duration_ms": max(0, round((time.perf_counter() - started) * 1000)),
        }
        root = finalize_job(job, manifest)
    except BaseException:
        _abort(job)
        # Removing an empty directory never deletes user content, and a refused
        # job must not leave an empty output root behind.
        try:
            configuration.output_dir.rmdir()
        except OSError:
            pass
        raise

    return ConversionResult(
        job_dir=root,
        tex_path=root / "document.tex",
        pdf_path=root / pdf_name if pdf_name is not None else None,
        manifest_path=root / "manifest.json",
        manifest=manifest,
        warnings=warnings,
    )
