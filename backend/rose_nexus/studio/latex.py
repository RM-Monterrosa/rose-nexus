"""LaTeX body generator.

Security rule: user content is *never* interpreted as LaTeX. Every character is
escaped through :func:`escape_text`, and the few structured constructs (links,
images) pass through strict validators. The only unescaped content allowed is
inside a ``verbatim`` environment, which the parser already restricts.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping
from urllib.parse import quote, urlsplit

from ..core.errors import InputValidationError, LatexPolicyViolation
from .model import (
    Block,
    BulletList,
    Code,
    CodeBlock,
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

ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}

SAFE_SCHEMES = frozenset({"http", "https", "mailto"})
HREF_SAFE = "/:?=+-.,;@!*'()[]"

SECTION_COMMANDS = {
    1: "section",
    2: "subsection",
    3: "subsubsection",
    4: "paragraph",
    5: "subparagraph",
}

_ASSET_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def escape_text(value: str) -> str:
    """Escape every LaTeX-special character in ``value``."""

    return "".join(ESCAPES.get(char, char) for char in value)


def escape_inline_code(value: str) -> str:
    """Escape inline code, keeping literal spaces readable in monospace."""

    return escape_text(value).replace(" ", r"\ ")


def safe_href(url: str) -> str:
    """Validate an external link and percent-encode everything LaTeX dislikes."""

    if not url or any(char in url for char in "\r\n\t"):
        raise LatexPolicyViolation("link URLs cannot be empty or multi-line", code="unsafe_link")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in SAFE_SCHEMES:
        raise LatexPolicyViolation(
            f"link scheme '{scheme or '(none)'}' is not allowed",
            code="unsafe_link_scheme",
            detail="allowed: " + ", ".join(sorted(SAFE_SCHEMES)),
        )
    if scheme in {"http", "https"} and not parts.netloc:
        raise LatexPolicyViolation(
            "absolute web links need a host", code="unsafe_link_scheme", detail=url
        )
    return quote(url, safe=HREF_SAFE)


def render_inlines(nodes: Iterable[Inline]) -> str:
    """Render inline nodes to LaTeX."""

    chunks: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            chunks.append(escape_text(node.value))
        elif isinstance(node, Code):
            chunks.append(r"\texttt{" + escape_inline_code(node.value) + "}")
        elif isinstance(node, Strong):
            chunks.append(r"\textbf{" + render_inlines(node.children) + "}")
        elif isinstance(node, Emphasis):
            chunks.append(r"\emph{" + render_inlines(node.children) + "}")
        elif isinstance(node, Link):
            chunks.append(
                r"\href{" + safe_href(node.url) + "}{" + render_inlines(node.children) + "}"
            )
        else:  # pragma: no cover - the AST is closed
            raise TypeError(f"unsupported inline node: {type(node)!r}")
    return "".join(chunks)


def _safe_asset(target: str) -> str:
    if not _ASSET_PATH.fullmatch(target) or target.startswith("/") or ".." in target.split("/"):
        raise LatexPolicyViolation(
            "asset paths must be relative and stay inside the job directory",
            code="unsafe_asset_path",
            detail=target,
        )
    return target


def _render_table(table: Table) -> str:
    columns = len(table.header)
    lines = [r"{\small", r"\begin{longtable}{" + "l" * columns + "}", r"\hline"]
    lines.append(" & ".join(render_inlines(cell) for cell in table.header) + r" \\")
    lines.append(r"\hline")
    lines.append(r"\endhead")
    for row in table.rows:
        lines.append(" & ".join(render_inlines(cell) for cell in row) + r" \\")
        lines.append(r"\hline")
    lines.append(r"\end{longtable}")
    lines.append("}")
    return "\n".join(lines)


def _render_block(block: Block, image_map: Mapping[str, str]) -> str:
    if isinstance(block, Heading):
        command = SECTION_COMMANDS.get(block.level)
        if command is None:  # pragma: no cover - parser rejects level 6
            raise InputValidationError(
                f"unsupported heading level {block.level}", code="heading_level_unsupported"
            )
        return "\\" + command + "{" + render_inlines(block.children) + "}"
    if isinstance(block, Paragraph):
        return render_inlines(block.children)
    if isinstance(block, BulletList):
        items = "\n".join(r"\item " + render_inlines(item) for item in block.items)
        return "\\begin{itemize}\n" + items + "\n\\end{itemize}"
    if isinstance(block, OrderedList):
        items = "\n".join(r"\item " + render_inlines(item) for item in block.items)
        return "\\begin{enumerate}\n" + items + "\n\\end{enumerate}"
    if isinstance(block, CodeBlock):
        if "\\end{verbatim}" in block.content:
            raise InputValidationError(
                "code blocks cannot contain the verbatim terminator",
                code="code_block_terminator",
                detail="split the block or remove the literal sequence",
            )
        return "\\begin{verbatim}\n" + block.content + "\n\\end{verbatim}"
    if isinstance(block, Quote):
        inner = "\n\n".join(_render_block(child, image_map) for child in block.blocks)
        return "\\begin{quote}\n" + inner + "\n\\end{quote}"
    if isinstance(block, Table):
        return _render_table(block)
    if isinstance(block, Rule):
        return "\\begin{center}\\rule{0.5\\linewidth}{0.4pt}\\end{center}"
    if isinstance(block, Image):
        target = image_map.get(block.path)
        if target is None:
            raise InputValidationError(
                "image was not resolved before generating LaTeX", code="image_not_resolved",
                detail=block.path,
            )
        return (
            "\\begin{center}\n"
            "\\includegraphics[width=\\linewidth,height=0.7\\textheight,keepaspectratio]{"
            + _safe_asset(target)
            + "}\n"
            "\\end{center}"
        )
    raise TypeError(f"unsupported block node: {type(block)!r}")  # pragma: no cover


def render_body(blocks: Iterable[Block], *, image_map: Mapping[str, str] | None = None) -> str:
    """Render parsed blocks to the LaTeX document body."""

    resolved: Mapping[str, str] = image_map or {}
    rendered = [_render_block(block, resolved) for block in blocks]
    rendered = [chunk for chunk in rendered if chunk]
    if not rendered:
        return ""
    return "\n\n".join(rendered) + "\n"
