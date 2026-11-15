"""Typed intermediate representation for parsed documents.

The AST is intentionally small: it is produced by :mod:`rose_nexus.studio.parser`
and consumed by :mod:`rose_nexus.studio.latex`. Nothing else should build nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Union


@dataclass(frozen=True)
class DocumentMeta:
    """Metadata from the YAML-like front matter. All values are strings."""

    title: str | None = None
    subtitle: str | None = None
    author: str | None = None
    date: str | None = None
    brand: str | None = None
    lang: str | None = None
    has_front_matter: bool = False


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Code:
    value: str


@dataclass(frozen=True)
class Strong:
    children: tuple["Inline", ...]


@dataclass(frozen=True)
class Emphasis:
    children: tuple["Inline", ...]


@dataclass(frozen=True)
class Link:
    children: tuple["Inline", ...]
    url: str


Inline = Union[Text, Code, Strong, Emphasis, Link]


@dataclass(frozen=True)
class Heading:
    level: int
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class Paragraph:
    children: tuple[Inline, ...]


@dataclass(frozen=True)
class BulletList:
    items: tuple[tuple[Inline, ...], ...]


@dataclass(frozen=True)
class OrderedList:
    items: tuple[tuple[Inline, ...], ...]


@dataclass(frozen=True)
class CodeBlock:
    content: str
    language: str | None = None


@dataclass(frozen=True)
class Quote:
    blocks: tuple["Block", ...]


@dataclass(frozen=True)
class Table:
    header: tuple[tuple[Inline, ...], ...]
    rows: tuple[tuple[tuple[Inline, ...], ...], ...]


@dataclass(frozen=True)
class Rule:
    pass


@dataclass(frozen=True)
class Image:
    alt: str
    path: str


Block = Union[
    Heading,
    Paragraph,
    BulletList,
    OrderedList,
    CodeBlock,
    Quote,
    Table,
    Rule,
    Image,
]


@dataclass(frozen=True)
class Document:
    meta: DocumentMeta = field(default_factory=DocumentMeta)
    blocks: tuple[Block, ...] = ()


def plain_text(node: object) -> str:
    """Return the human-readable text of a node, a block or a sequence.

    Used for titles, labels, test assertions and warnings. It never escapes: the
    LaTeX layer owns escaping.
    """

    if isinstance(node, (Text, Code)):
        return node.value
    if isinstance(node, (Strong, Emphasis, Link, Heading, Paragraph)):
        return plain_text(node.children)
    if isinstance(node, (BulletList, OrderedList)):
        return " ".join(plain_text(item) for item in node.items)
    if isinstance(node, CodeBlock):
        return node.content
    if isinstance(node, Quote):
        return " ".join(plain_text(block) for block in node.blocks)
    if isinstance(node, Table):
        cells = [plain_text(cell) for cell in node.header]
        for row in node.rows:
            cells.extend(plain_text(cell) for cell in row)
        return " ".join(cells)
    if isinstance(node, Image):
        return node.alt
    if isinstance(node, Rule):
        return ""
    if isinstance(node, (tuple, list)):
        return "".join(plain_text(item) for item in node)
    raise TypeError(f"cannot extract text from {type(node)!r}")
