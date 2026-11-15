"""Strict ``{{token}}`` template renderer.

Versioned LaTeX templates are trusted repository files; their placeholder names
are not. Unknown or unterminated tokens are errors, and a substituted value may
not smuggle new tokens. The document body is spliced last, after validation, so
verbatim content can legitimately contain braces.
"""

from __future__ import annotations

import re
from typing import Mapping

from ..core.errors import RoseNexusError

_TOKEN = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
_BODY = "body"
_SENTINEL = "\x00rose-nexus-body\x00"


class TemplateError(RoseNexusError):
    """The template or the supplied values are structurally invalid."""

    code = "template_invalid"
    exit_code = 1


def render_template(
    text: str, values: Mapping[str, str], *, body: str = ""
) -> str:
    """Replace every ``{{name}}`` token with ``values[name]`` and splice ``body``."""

    if _SENTINEL in body:
        raise TemplateError(
            "the document body contains a reserved control sequence",
            code="template_value_invalid",
        )
    if _BODY in values:
        raise TemplateError(
            "the body must be passed with body=, not as a template value",
            code="template_value_invalid",
        )
    for name, value in values.items():
        if "{{" in value:
            raise TemplateError(
                f"template value '{name}' contains token openers",
                code="template_value_invalid",
            )
    allowed = set(values) | {_BODY}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in allowed:
            raise TemplateError(
                f"unknown template token '{{{{{name}}}}}'",
                code="template_unknown_token",
                detail="known: " + ", ".join(sorted(allowed)),
            )
        if name == _BODY:
            return _SENTINEL
        return values[name]

    rendered = _TOKEN.sub(replace, text)
    # A stray closing brace is legitimate LaTeX; an unmatched opener is not.
    if "{{" in rendered:
        raise TemplateError(
            "template contains an unterminated token", code="template_unterminated_token"
        )
    return rendered.replace(_SENTINEL, body)
