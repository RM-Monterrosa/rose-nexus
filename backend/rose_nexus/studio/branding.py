"""Brand profile loading and validation.

A profile is a versioned TOML file under ``branding/profiles/<name>/``. It carries
tokens plus provenance: a non-provisional profile must pin the source commit, and
a provisional one must explain itself. Nothing is inferred from asset names.
"""

from __future__ import annotations

import pathlib
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Mapping

from ..core.errors import BrandingError

REQUIRED_FIELDS = (
    "name",
    "version",
    "display_name",
    "provisional",
    "template",
    "accent",
    "support",
    "ink",
    "paper",
    "page_size",
    "cover_style",
)
OPTIONAL_FIELDS = (
    "source",
    "provisional_note",
    "logo",
    "logo_width_fraction",
    "font_display",
    "font_body",
    "font_mono",
    "fonts_verified",
    "footer_left",
    "footer_center",
    "footer_right",
    "watermark",
)
ALLOWED_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

PAGE_SIZES = frozenset({"A4", "Letter"})
COVER_STYLES = frozenset({"none", "title-rule", "logo-rule"})

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_COMMIT = re.compile(r"^[0-9a-f]{7,64}$")
_FONT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


@dataclass(frozen=True)
class BrandProfile:
    """Validated brand tokens and assets."""

    name: str
    version: str
    display_name: str
    provisional: bool
    template: pathlib.Path
    accent: str
    support: str
    ink: str
    paper: str
    page_size: str
    cover_style: str
    provisional_note: str | None = None
    source: str | None = None
    logo: pathlib.Path | None = None
    logo_width_fraction: float = 0.32
    font_display: str | None = None
    font_body: str | None = None
    font_mono: str | None = None
    fonts_verified: bool = False
    footer_left: str = ""
    footer_center: str = ""
    footer_right: str = ""
    watermark: str | None = None

    def as_manifest(self, *, branding_root: pathlib.Path) -> dict[str, Any]:
        """Return the provenance record written into the job manifest."""

        def relative(path: pathlib.Path | None) -> str | None:
            if path is None:
                return None
            return path.resolve().relative_to(branding_root.resolve()).as_posix()

        return {
            "name": self.name,
            "version": self.version,
            "display_name": self.display_name,
            "provisional": self.provisional,
            "provisional_note": self.provisional_note,
            "source": self.source,
            "template": relative(self.template),
            "logo": relative(self.logo),
            "palette": {
                "accent": self.accent,
                "support": self.support,
                "ink": self.ink,
                "paper": self.paper,
            },
            "page_size": self.page_size,
            "cover_style": self.cover_style,
            "fonts": {
                "display": self.font_display,
                "body": self.font_body,
                "mono": self.font_mono,
                "verified": self.fonts_verified,
            },
        }


def _resolve_inside(
    root: pathlib.Path, relative: str, *, base: pathlib.Path | None = None
) -> pathlib.Path:
    if not relative or relative.startswith("/") or ".." in pathlib.PurePosixPath(relative).parts:
        raise BrandingError(
            "branding paths must be relative and stay inside the branding root",
            code="branding_unsafe_path",
            detail=relative,
        )
    candidate = ((base or root) / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise BrandingError(
            "branding path escapes the branding root",
            code="branding_unsafe_path",
            detail=relative,
        )
    return candidate


def _require(data: Mapping[str, Any], field: str, name: str) -> Any:
    if field not in data or data[field] == "" or data[field] is None:
        raise BrandingError(
            f"profile '{name}' is missing the required field '{field}'",
            code="branding_missing_field",
        )
    return data[field]


def _color(data: Mapping[str, Any], field: str, name: str) -> str:
    value = _require(data, field, name)
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise BrandingError(
            f"profile '{name}' has an invalid '{field}' color",
            code="branding_invalid_color",
            detail=str(value),
        )
    return value.upper()


def _font(data: Mapping[str, Any], field: str, name: str) -> str | None:
    value = data.get(field)
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _FONT_NAME.fullmatch(value):
        raise BrandingError(
            f"profile '{name}' has an invalid '{field}' font name",
            code="branding_invalid_fonts",
            detail=str(value),
        )
    return value


def _build(data: Mapping[str, Any], root: pathlib.Path, profile_name: str) -> BrandProfile:
    unknown = sorted(set(data) - set(ALLOWED_FIELDS))
    if unknown:
        raise BrandingError(
            f"profile '{profile_name}' declares unknown keys: " + ", ".join(unknown),
            code="branding_unknown_key",
            detail=", ".join(unknown),
        )

    name = _require(data, "name", profile_name)
    if name != profile_name:
        raise BrandingError(
            "profile name does not match its directory",
            code="branding_name_mismatch",
            detail=f"{name} != {profile_name}",
        )
    version = str(_require(data, "version", name))
    display_name = str(_require(data, "display_name", name))

    provisional = data.get("provisional")
    if not isinstance(provisional, bool):
        raise BrandingError(
            f"profile '{name}' must declare 'provisional' as a boolean",
            code="branding_missing_field",
        )

    note = data.get("provisional_note") or None
    source = data.get("source") or None
    if provisional:
        if not note:
            raise BrandingError(
                f"provisional profile '{name}' must explain itself in 'provisional_note'",
                code="branding_missing_provisional_note",
            )
    else:
        if not source or not isinstance(source, str) or not _COMMIT.fullmatch(source):
            raise BrandingError(
                f"non-provisional profile '{name}' must pin 'source' to a commit id",
                code="branding_missing_source",
            )

    page_size = str(_require(data, "page_size", name))
    if page_size not in PAGE_SIZES:
        raise BrandingError(
            f"profile '{name}' has an invalid page size",
            code="branding_invalid_page_size",
            detail=", ".join(sorted(PAGE_SIZES)),
        )
    cover_style = str(_require(data, "cover_style", name))
    if cover_style not in COVER_STYLES:
        raise BrandingError(
            f"profile '{name}' has an invalid cover style",
            code="branding_invalid_cover_style",
            detail=", ".join(sorted(COVER_STYLES)),
        )

    template = _resolve_inside(
        root, str(_require(data, "template", name)), base=root / "templates"
    )
    if not template.is_file():
        raise BrandingError(
            f"profile '{name}' references a missing template",
            code="branding_template_not_found",
            detail=template.name,
        )

    logo_value = data.get("logo") or None
    logo: pathlib.Path | None = None
    if logo_value:
        logo = _resolve_inside(root, str(logo_value))
        if not logo.is_file():
            raise BrandingError(
                f"profile '{name}' references a missing logo",
                code="branding_logo_not_found",
                detail=logo.name,
            )
    if cover_style == "logo-rule" and logo is None:
        raise BrandingError(
            f"profile '{name}' uses the logo cover style without a logo",
            code="branding_missing_logo",
        )

    width = data.get("logo_width_fraction", 0.32)
    if not isinstance(width, (int, float)) or isinstance(width, bool) or not 0 < float(width) <= 1:
        raise BrandingError(
            f"profile '{name}' has an invalid logo width fraction",
            code="branding_invalid_logo_width",
            detail=str(width),
        )

    font_display = _font(data, "font_display", name)
    font_body = _font(data, "font_body", name)
    font_mono = _font(data, "font_mono", name)
    fonts_verified = data.get("fonts_verified", False)
    if not isinstance(fonts_verified, bool) or (fonts_verified and font_body is None):
        raise BrandingError(
            f"profile '{name}' cannot verify fonts without a body font",
            code="branding_invalid_fonts",
        )

    return BrandProfile(
        name=name,
        version=version,
        display_name=display_name,
        provisional=provisional,
        provisional_note=str(note) if note else None,
        template=template,
        source=source,
        accent=_color(data, "accent", name),
        support=_color(data, "support", name),
        ink=_color(data, "ink", name),
        paper=_color(data, "paper", name),
        page_size=page_size,
        cover_style=cover_style,
        logo=logo,
        logo_width_fraction=float(width),
        font_display=font_display,
        font_body=font_body,
        font_mono=font_mono,
        fonts_verified=fonts_verified,
        footer_left=str(data.get("footer_left") or ""),
        footer_center=str(data.get("footer_center") or ""),
        footer_right=str(data.get("footer_right") or ""),
        watermark=str(data.get("watermark")) if data.get("watermark") else None,
    )


def _safe_profile_name(name: str) -> str:
    """Reject profile names that could escape ``profiles/<name>``."""

    if (
        not name
        or "/" in name
        or "\\" in name
        or "\x00" in name
        or ".." in name
        or name in {".", ".."}
    ):
        raise BrandingError(
            "brand profile names must be a single safe directory name",
            code="branding_unsafe_path",
            detail=name,
        )
    return name


def load_profile(branding_root: pathlib.Path | str, profile_name: str) -> BrandProfile:
    """Load and validate one profile from ``branding_root/profiles/<name>``."""

    root = pathlib.Path(branding_root)
    profile_name = _safe_profile_name(profile_name)
    profile_path = root / "profiles" / profile_name / "profile.toml"
    if not profile_path.is_file():
        raise BrandingError(
            f"brand profile '{profile_name}' was not found",
            code="branding_profile_not_found",
            detail=profile_path.as_posix(),
        )
    try:
        data = tomllib.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise BrandingError(
            f"brand profile '{profile_name}' is not valid TOML",
            code="branding_invalid_toml",
            detail=str(error),
        ) from error
    return _build(data, root, profile_name)


def list_profiles(branding_root: pathlib.Path | str) -> tuple[BrandProfile, ...]:
    """Load every profile under ``branding_root``, sorted by name."""

    root = pathlib.Path(branding_root)
    profiles_dir = root / "profiles"
    if not profiles_dir.is_dir():
        raise BrandingError(
            "branding root does not contain a profiles directory",
            code="branding_root_missing",
            detail=profiles_dir.as_posix(),
        )
    names = sorted(
        directory.name for directory in profiles_dir.iterdir() if (directory / "profile.toml").is_file()
    )
    return tuple(load_profile(root, name) for name in names)
