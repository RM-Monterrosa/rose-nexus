"""Unit tests for brand profile loading and validation."""

import json
import pathlib
import tempfile
import unittest

from rose_nexus.core.errors import BrandingError
from rose_nexus.studio.branding import list_profiles, load_profile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BRANDING_ROOT = REPO_ROOT / "branding"

BASE_PROFILE = {
    "name": "tmp",
    "version": "1.0.0",
    "display_name": "Temporal",
    "provisional": True,
    "provisional_note": "Paleta de prueba, no corporativa.",
    "template": "document.tex.tmpl",
    "accent": "#112233",
    "support": "#445566",
    "ink": "#000000",
    "paper": "#FFFFFF",
    "page_size": "A4",
    "cover_style": "title-rule",
}


def toml_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, ensure_ascii=False)


def toml_text(data):
    return "\n".join(f"{key} = {toml_value(value)}" for key, value in data.items()) + "\n"


class TempBrandingRoot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        (self.root / "templates").mkdir()
        (self.root / "templates" / "document.tex.tmpl").write_text("{{body}}", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write_profile(self, name="tmp", overrides=None, drop=()):
        data = dict(BASE_PROFILE)
        data.update(overrides or {})
        for key in drop:
            data.pop(key, None)
        profile_dir = self.root / "profiles" / name
        profile_dir.mkdir(parents=True)
        (profile_dir / "profile.toml").write_text(toml_text(data), encoding="utf-8")
        return data


class RepositoryProfileTests(unittest.TestCase):
    def test_demo_profile_is_provisional_and_declares_it(self):
        profile = load_profile(BRANDING_ROOT, "demo")
        self.assertTrue(profile.provisional)
        self.assertEqual(profile.accent, "#B03A5B")
        self.assertEqual(profile.support, "#1F4E79")
        self.assertTrue(profile.provisional_note)
        self.assertIsNone(profile.logo)

    def test_invering_profile_carries_verified_source_and_greens(self):
        profile = load_profile(BRANDING_ROOT, "invering")
        self.assertFalse(profile.provisional)
        self.assertEqual(profile.source, "bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2")
        self.assertEqual(profile.accent, "#006838")
        self.assertEqual(profile.support, "#8DC63F")
        self.assertEqual(profile.ink, "#05130F")
        self.assertEqual(profile.paper, "#F2F5EF")
        self.assertIsNotNone(profile.logo)
        self.assertTrue(profile.logo.is_file())
        self.assertFalse(profile.fonts_verified)

    def test_list_profiles_is_sorted_and_complete(self):
        self.assertEqual([p.name for p in list_profiles(BRANDING_ROOT)], ["demo", "invering"])

    def test_unknown_profile_reports_a_clear_error(self):
        with self.assertRaises(BrandingError) as caught:
            load_profile(BRANDING_ROOT, "no-existe")
        self.assertEqual(caught.exception.code, "branding_profile_not_found")


class SchemaValidationTests(TempBrandingRoot):
    def test_minimal_valid_profile_loads(self):
        self.write_profile()
        profile = load_profile(self.root, "tmp")
        self.assertEqual(profile.accent, "#112233")
        self.assertFalse(profile.fonts_verified)

    def test_unknown_key_is_rejected(self):
        self.write_profile(overrides={"colour": "#000000"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_unknown_key")
        self.assertIn("colour", caught.exception.message)

    def test_missing_display_name_is_rejected(self):
        self.write_profile(drop=("display_name",))
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_missing_field")

    def test_non_provisional_requires_source_commit(self):
        self.write_profile(overrides={"provisional": False}, drop=("provisional_note",))
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_missing_source")

    def test_provisional_requires_a_note(self):
        self.write_profile(drop=("provisional_note",))
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_missing_provisional_note")

    def test_invalid_color_is_rejected(self):
        self.write_profile(overrides={"accent": "azul"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_invalid_color")

    def test_invalid_page_size_is_rejected(self):
        self.write_profile(overrides={"page_size": "A3"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_invalid_page_size")

    def test_invalid_cover_style_is_rejected(self):
        self.write_profile(overrides={"cover_style": "fancy"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_invalid_cover_style")

    def test_logo_cover_style_requires_a_logo(self):
        self.write_profile(overrides={"cover_style": "logo-rule"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_missing_logo")

    def test_template_traversal_is_rejected(self):
        self.write_profile(overrides={"template": "../evil.tmpl"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_unsafe_path")

    def test_missing_template_is_rejected(self):
        self.write_profile(overrides={"template": "no-existe.tmpl"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_template_not_found")

    def test_absolute_logo_path_is_rejected(self):
        self.write_profile(overrides={"cover_style": "logo-rule", "logo": "/etc/passwd"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_unsafe_path")

    def test_logo_outside_branding_root_is_rejected(self):
        outside = self.root.parent / "outside-logo.png"
        outside.write_bytes(b"not-an-image")
        try:
            self.write_profile(overrides={"cover_style": "logo-rule", "logo": "../outside-logo.png"})
            with self.assertRaises(BrandingError) as caught:
                load_profile(self.root, "tmp")
            self.assertEqual(caught.exception.code, "branding_unsafe_path")
        finally:
            outside.unlink()

    def test_missing_logo_file_is_rejected(self):
        self.write_profile(overrides={"cover_style": "logo-rule", "logo": "assets/nada.png"})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_logo_not_found")

    def test_logo_width_out_of_range_is_rejected(self):
        self.write_profile(
            overrides={"cover_style": "logo-rule", "logo": "assets/x.png", "logo_width_fraction": 1.4}
        )
        (self.root / "assets").mkdir()
        (self.root / "assets" / "x.png").write_bytes(b"png")
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_invalid_logo_width")

    def test_verified_fonts_require_a_body_font(self):
        self.write_profile(overrides={"fonts_verified": True})
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, "tmp")
        self.assertEqual(caught.exception.code, "branding_invalid_fonts")

    def test_unverified_fonts_are_declared_but_not_applied(self):
        self.write_profile(overrides={"font_body": "IBM Plex Sans", "fonts_verified": False})
        profile = load_profile(self.root, "tmp")
        self.assertEqual(profile.font_body, "IBM Plex Sans")
        self.assertFalse(profile.fonts_verified)

    def test_profile_name_cannot_escape_branding_root(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        profile_name = "../../" + outside.name
        profile_path = outside / "profile.toml"
        profile_path.write_text(toml_text(dict(BASE_PROFILE, name=profile_name)), encoding="utf-8")
        self.addCleanup(profile_path.unlink)
        with self.assertRaises(BrandingError) as caught:
            load_profile(self.root, profile_name)
        self.assertEqual(caught.exception.code, "branding_unsafe_path")

    def test_missing_branding_root_is_reported(self):
        with self.assertRaises(BrandingError) as caught:
            list_profiles(self.root / "no-existe")
        self.assertEqual(caught.exception.code, "branding_root_missing")


if __name__ == "__main__":
    unittest.main()
