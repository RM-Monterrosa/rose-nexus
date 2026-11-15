"""Validate generated LaTeX before it enters the compilation sandbox.

The renderer escapes user content, but this policy provides defense in depth
against template bugs and unsafe constructs in the final generated document.
"""

from __future__ import annotations

import re

from ..core.errors import LatexPolicyViolation

ALLOWED_PACKAGES = frozenset(
    {
        "geometry",
        "graphicx",
        "array",
        "longtable",
        "xcolor",
        "hyperref",
        "fancyhdr",
        "fontspec",
        "draftwatermark",
    }
)

_FORBIDDEN_COMMANDS = (
    "write18",
    "write",
    "openout",
    "openin",
    "closeout",
    "closein",
    "read",
    "immediate",
    "special",
    "catcode",
    "csname",
    "loop",
    "repeat",
    "ShellEscape",
    "directlua",
    "latelua",
)
_FORBIDDEN_COMMAND = re.compile(
    r"\\(?:" + "|".join(_FORBIDDEN_COMMANDS) + r")(?![A-Za-z@])"
)
_INPUT_COMMAND = re.compile(r"\\(?:input|include)\s*\{")
_GRAPHICS_COMMAND = re.compile(
    r"\\includegraphics(?:\s*\[[^\]\r\n]*\])?\s*\{([^{}\r\n]*)\}"
)
_PACKAGE_COMMAND = re.compile(
    r"\\usepackage(?:\s*\[[^\]\r\n]*\])?\s*\{([^{}\r\n]*)\}"
)
_ASSET_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")


def validate_generated_latex(source: str) -> None:
    """Raise ``LatexPolicyViolation`` unless ``source`` satisfies the policy."""

    if not source.startswith("% rose-nexus"):
        raise LatexPolicyViolation(
            "generated LaTeX must start with the Rose Nexus marker",
            code="latex_missing_marker",
        )

    forbidden = _FORBIDDEN_COMMAND.search(source) or _INPUT_COMMAND.search(source)
    if forbidden is not None:
        raise LatexPolicyViolation(
            "generated LaTeX contains a forbidden command",
            code="latex_forbidden_command",
            detail=forbidden.group(0),
        )

    for match in _GRAPHICS_COMMAND.finditer(source):
        target = match.group(1)
        if (
            not _ASSET_PATH.fullmatch(target)
            or target.startswith(("/", ".."))
            or ".." in target.split("/")
        ):
            raise LatexPolicyViolation(
                "included graphics must use a safe relative path",
                code="latex_unsafe_asset",
                detail=target,
            )

    for match in _PACKAGE_COMMAND.finditer(source):
        packages = [package.strip() for package in match.group(1).split(",")]
        if any(package not in ALLOWED_PACKAGES for package in packages):
            raise LatexPolicyViolation(
                "generated LaTeX uses a package outside the allowlist",
                code="latex_forbidden_package",
                detail=match.group(1),
            )
