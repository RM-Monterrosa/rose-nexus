"""Deterministic Markdown/TXT parser.

Supported blocks: headings ``#``..``#####``, paragraphs, simple bullet/ordered
lists, block quotes, fenced code, pipe tables, horizontal rules, block images and
front matter. Inline: strong, emphasis, code and links.

Everything else is rejected with an :class:`InputValidationError` carrying a
stable code. Silent degradation is a bug: a document must never lose content
without the operator knowing.
"""

from __future__ import annotations

import re

from ..core.errors import InputValidationError
from .model import (
    Block,
    BulletList,
    Code,
    CodeBlock,
    Document,
    DocumentMeta,
    Emphasis,
    Heading,
    Image,
    Inline,
    Link,
    OrderedList,
    Paragraph,
    Quote,
    Rule,
    Strong,
    Table,
    Text,
)

MAX_BLOCKS = 5000
MAX_TABLE_COLUMNS = 12
MAX_QUOTE_DEPTH = 3

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")
_BULLET = re.compile(r"^[-*+][ \t]+(.+?)[ \t]*$")
_ORDERED = re.compile(r"^\d{1,9}[.)][ \t]+(.+?)[ \t]*$")
_NESTED = re.compile(r"^[ \t]+(?:[-*+]|\d{1,9}[.)])[ \t]+")
_FENCE = re.compile(r"^(`{3,}|~{3,})[ \t]*([A-Za-z0-9_+.#-]*)[ \t]*$")
_RULE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
_IMAGE_ONLY = re.compile(r"^!\[([^\]]*)\]\(([^)\s]+)\)$")
_HTML_START = re.compile(r"^[ \t]*</?[A-Za-z][A-Za-z0-9-]*(?:[ \t][^>]*)?>")
_FRONT_KEY = re.compile(r"^([a-z][a-z0-9_]*)[ \t]*:[ \t]*(.*)$")
_SEP_CELL = re.compile(r":?-{3,}:?")

_FRONT_KEYS = ("title", "subtitle", "author", "date", "brand", "lang")
_ESCAPABLE = frozenset("\\`*_{}[]()#+-.!|>~")
_PIPE_SENTINEL = "\x00"


def _normalize(text: str) -> list[str]:
    if not isinstance(text, str):
        raise InputValidationError(
            "the document must be provided as text", code="invalid_input_type"
        )
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    control = _CONTROL.search(text)
    if control:
        raise InputValidationError(
            f"forbidden control character U+{ord(control.group(0)):04X}",
            code="control_character",
            detail=f"offset {control.start()}",
        )
    return text.split("\n")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _split_front_matter(lines: list[str]) -> tuple[DocumentMeta, int]:
    if not lines or lines[0].strip() != "---":
        return DocumentMeta(), 0
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise InputValidationError(
            "front matter opened with '---' but never closed", code="front_matter_unclosed"
        )
    values: dict[str, str] = {}
    for raw in lines[1:closing]:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _FRONT_KEY.match(line)
        if not match:
            raise InputValidationError(
                "front matter accepts only 'key: value' lines",
                code="front_matter_invalid_line",
                detail=line,
            )
        key, value = match.group(1), _unquote(match.group(2).strip())
        if key not in _FRONT_KEYS:
            raise InputValidationError(
                f"unknown front matter key '{key}'",
                code="front_matter_unknown_key",
                detail="allowed: " + ", ".join(_FRONT_KEYS),
            )
        if key in values:
            raise InputValidationError(
                f"duplicated front matter key '{key}'", code="front_matter_duplicate_key"
            )
        values[key] = value
    return (
        DocumentMeta(has_front_matter=True, **values),  # type: ignore[arg-type]
        closing + 1,
    )


def _split_row(line: str) -> list[str]:
    protected = line.replace("\\|", _PIPE_SENTINEL).strip()
    if protected.startswith("|"):
        protected = protected[1:]
    if protected.endswith("|"):
        protected = protected[:-1]
    return [cell.replace(_PIPE_SENTINEL, "|").strip() for cell in protected.split("|")]


def _is_table_separator(line: str) -> bool:
    if "|" not in line:
        return False
    cells = _split_row(line)
    return bool(cells) and all(_SEP_CELL.fullmatch(cell) for cell in cells)


def _line_kind(lines: list[str], index: int) -> str:
    line = lines[index]
    if not line.strip():
        return "blank"
    if _FENCE.match(line):
        return "fence"
    heading = _HEADING.match(line)
    if heading:
        return "heading6" if len(heading.group(1)) > 5 else "heading"
    if _RULE.match(line):
        return "rule"
    if _NESTED.match(line):
        return "nested"
    if _BULLET.match(line):
        return "bullet"
    if _ORDERED.match(line):
        return "ordered"
    if line.lstrip().startswith(">"):
        return "quote"
    if _HTML_START.match(line):
        return "html"
    if "|" in line and index + 1 < len(lines) and _is_table_separator(lines[index + 1]):
        return "table"
    if "![" in line:
        return "image_candidate"
    return "paragraph"


def _flush(parts: list[Inline], buffer: list[str]) -> None:
    if not buffer:
        return
    value = "".join(buffer)
    buffer.clear()
    if value:
        parts.append(Text(value))


def _parse_inlines(text: str) -> tuple[Inline, ...]:
    parts: list[Inline] = []
    buffer: list[str] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char == "\\" and index + 1 < length and text[index + 1] in _ESCAPABLE:
            buffer.append(text[index + 1])
            index += 2
            continue
        if char == "`":
            closing = text.find("`", index + 1)
            if closing == -1:
                buffer.append(char)
                index += 1
                continue
            _flush(parts, buffer)
            parts.append(Code(text[index + 1 : closing]))
            index = closing + 1
            continue
        if text.startswith("**", index):
            closing = text.find("**", index + 2)
            if closing == -1:
                buffer.append("**")
                index += 2
                continue
            inner = text[index + 2 : closing]
            _flush(parts, buffer)
            parts.append(Strong(_parse_inlines(inner)) if inner.strip() else Text("****"))
            index = closing + 2
            continue
        if char == "*":
            closing = text.find("*", index + 1)
            if closing == -1:
                buffer.append(char)
                index += 1
                continue
            inner = text[index + 1 : closing]
            _flush(parts, buffer)
            parts.append(Emphasis(_parse_inlines(inner)) if inner.strip() else Text("**"))
            index = closing + 1
            continue
        if char == "[":
            label_end = text.find("](", index + 1)
            if label_end != -1:
                url_end = text.find(")", label_end + 2)
                if url_end != -1:
                    _flush(parts, buffer)
                    parts.append(
                        Link(
                            _parse_inlines(text[index + 1 : label_end]),
                            text[label_end + 2 : url_end].strip(),
                        )
                    )
                    index = url_end + 1
                    continue
            buffer.append(char)
            index += 1
            continue
        buffer.append(char)
        index += 1
    _flush(parts, buffer)
    return tuple(parts)


def _parse_heading(line: str) -> Heading:
    match = _HEADING.match(line)
    assert match is not None
    return Heading(level=len(match.group(1)), children=_parse_inlines(match.group(2)))


def _parse_fence(lines: list[str], index: int) -> tuple[CodeBlock, int]:
    opener = _FENCE.match(lines[index])
    assert opener is not None
    marker = opener.group(1)
    language = opener.group(2) or None
    body: list[str] = []
    cursor = index + 1
    while cursor < len(lines):
        candidate = lines[cursor].strip()
        if candidate and set(candidate) == {marker[0]} and len(candidate) >= len(marker):
            return CodeBlock(content="\n".join(body), language=language), cursor + 1
        body.append(lines[cursor])
        cursor += 1
    raise InputValidationError(
        f"code fence opened at line {index + 1} is never closed",
        code="unclosed_code_fence",
    )


def _parse_table(lines: list[str], index: int) -> tuple[Table, int]:
    header = _split_row(lines[index])
    separator = _split_row(lines[index + 1])
    if len(header) != len(separator):
        raise InputValidationError(
            "table header and separator declare a different number of columns",
            code="table_shape_mismatch",
            detail=f"header={len(header)} separator={len(separator)}",
        )
    if len(header) > MAX_TABLE_COLUMNS:
        raise InputValidationError(
            f"tables support at most {MAX_TABLE_COLUMNS} columns",
            code="table_too_wide",
            detail=f"found {len(header)}",
        )
    rows: list[tuple[tuple[Inline, ...], ...]] = []
    cursor = index + 2
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() or "|" not in line:
            break
        cells = _split_row(line)
        if len(cells) != len(header):
            raise InputValidationError(
                f"table row {cursor + 1} has {len(cells)} cells, expected {len(header)}",
                code="table_row_mismatch",
            )
        rows.append(tuple(_parse_inlines(cell) for cell in cells))
        cursor += 1
    return (
        Table(
            header=tuple(_parse_inlines(cell) for cell in header),
            rows=tuple(rows),
        ),
        cursor,
    )


def _parse_list(lines: list[str], index: int, kind: str) -> tuple[Block, int]:
    pattern = _BULLET if kind == "bullet" else _ORDERED
    items: list[tuple[Inline, ...]] = []
    cursor = index
    while cursor < len(lines):
        match = pattern.match(lines[cursor])
        if not match:
            break
        items.append(_parse_inlines(match.group(1)))
        cursor += 1
        if cursor < len(lines) and _NESTED.match(lines[cursor]):
            raise InputValidationError(
                "nested lists are not supported yet", code="unsupported_nested_list"
            )
    if kind == "bullet":
        return BulletList(items=tuple(items)), cursor
    return OrderedList(items=tuple(items)), cursor


def _parse_quote(lines: list[str], index: int, depth: int = 0) -> tuple[Quote, int]:
    if depth > MAX_QUOTE_DEPTH:
        raise InputValidationError(
            "block quotes are nested too deeply", code="quote_nesting_too_deep"
        )
    collected: list[str] = []
    cursor = index
    while cursor < len(lines):
        stripped = lines[cursor].lstrip()
        if not stripped.startswith(">"):
            break
        remainder = stripped[1:]
        collected.append(remainder[1:] if remainder.startswith(" ") else remainder)
        cursor += 1
    return Quote(blocks=tuple(_parse_blocks(collected, 0, depth + 1))), cursor


def _parse_paragraph(lines: list[str], index: int) -> tuple[Paragraph, int]:
    collected: list[str] = []
    cursor = index
    while cursor < len(lines) and _line_kind(lines, cursor) == "paragraph":
        collected.append(re.sub(r"[ \t]+", " ", lines[cursor].strip()))
        cursor += 1
    return Paragraph(children=_parse_inlines(" ".join(collected))), cursor


def _parse_image_candidate(line: str) -> Image:
    stripped = line.strip()
    match = _IMAGE_ONLY.fullmatch(stripped)
    if match:
        return Image(alt=match.group(1), path=match.group(2))
    raise InputValidationError(
        "images must be alone in their paragraph", code="inline_image_unsupported"
    )


def _parse_blocks(lines: list[str], start: int, depth: int = 0) -> list[Block]:
    blocks: list[Block] = []
    index = start
    while index < len(lines):
        kind = _line_kind(lines, index)
        if kind == "blank":
            index += 1
            continue
        if kind == "heading":
            blocks.append(_parse_heading(lines[index]))
            index += 1
        elif kind == "heading6":
            raise InputValidationError(
                "heading level 6 is not supported", code="heading_level_unsupported"
            )
        elif kind == "fence":
            block, index = _parse_fence(lines, index)
            blocks.append(block)
        elif kind == "rule":
            blocks.append(Rule())
            index += 1
        elif kind == "table":
            block, index = _parse_table(lines, index)
            blocks.append(block)
        elif kind == "quote":
            block, index = _parse_quote(lines, index, depth)
            blocks.append(block)
        elif kind in ("bullet", "ordered"):
            block, index = _parse_list(lines, index, kind)
            blocks.append(block)
        elif kind == "nested":
            raise InputValidationError(
                "nested lists are not supported yet", code="unsupported_nested_list"
            )
        elif kind == "html":
            raise InputValidationError(
                "raw HTML is not supported", code="unsupported_html", detail=lines[index].strip()
            )
        elif kind == "image_candidate":
            blocks.append(_parse_image_candidate(lines[index]))
            index += 1
        else:
            block, index = _parse_paragraph(lines, index)
            blocks.append(block)
        if len(blocks) > MAX_BLOCKS:
            raise InputValidationError(
                f"documents support at most {MAX_BLOCKS} blocks", code="document_too_complex"
            )
    return blocks


def parse_markdown(text: str, *, source_name: str = "document") -> Document:
    """Parse a Markdown document into a typed AST."""

    lines = _normalize(text)
    meta, start = _split_front_matter(lines)
    blocks = _parse_blocks(lines, start)
    if not blocks:
        raise InputValidationError(
            "the document has no content", code="empty_document", detail=source_name
        )
    return Document(meta=meta, blocks=tuple(blocks))


def parse_plain_text(text: str, *, source_name: str = "document") -> Document:
    """Parse plain text as paragraphs; Markdown syntax is never interpreted."""

    lines = _normalize(text)
    blocks: list[Block] = []
    paragraph: list[str] = []
    for line in lines:
        if not line.strip():
            if paragraph:
                blocks.append(Paragraph(children=(Text(" ".join(paragraph).strip()),)))
                paragraph = []
            continue
        paragraph.append(re.sub(r"[ \t]+", " ", line.strip()))
    if paragraph:
        blocks.append(Paragraph(children=(Text(" ".join(paragraph).strip()),)))
    if not blocks:
        raise InputValidationError(
            "the document has no content", code="empty_document", detail=source_name
        )
    return Document(meta=DocumentMeta(), blocks=tuple(blocks))
