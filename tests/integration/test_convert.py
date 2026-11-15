"""Integration tests: fixtures -> .tex artifacts, manifest and determinism."""

import hashlib
import json
import pathlib
import tempfile
import unittest

from rose_nexus.core.config import Settings
from rose_nexus.core.errors import (
    BrandingError,
    InputValidationError,
    SandboxUnavailableError,
)
from rose_nexus.security.latex_policy import validate_generated_latex
from rose_nexus.studio.pipeline import convert_document

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BRANDING = REPO_ROOT / "branding"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "markdown"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ConvertCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.out = pathlib.Path(self._tmp.name) / "build"

    def tearDown(self):
        self._tmp.cleanup()

    def settings(self, **overrides):
        values = {"branding_dir": BRANDING, "output_dir": self.out}
        values.update(overrides)
        return Settings(**values)

    def convert(self, fixture, *, brand="demo", formats=("tex",), **kwargs):
        kwargs.setdefault("settings", self.settings())
        return convert_document(FIXTURES / fixture, brand=brand, formats=formats, **kwargs)


class FixtureConversionTests(ConvertCase):
    def test_the_ten_markdown_fixtures_convert_and_pass_the_policy(self):
        fixtures = sorted(FIXTURES.glob("*.md"))
        self.assertEqual(len(fixtures), 10)
        for fixture in fixtures:
            with self.subTest(fixture=fixture.name):
                result = self.convert(fixture.name)
                text = result.tex_path.read_text(encoding="utf-8")
                self.assertIn("\\begin{document}", text)
                self.assertGreater(len(text), 500)
                validate_generated_latex(text)

    def test_plain_text_is_not_interpreted_as_markdown(self):
        result = convert_document(
            FIXTURES / "11-plain.txt", brand="demo", settings=self.settings()
        )
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertNotIn("\\section", text)
        self.assertIn("*no*", text)
        self.assertIn("\\#", text)

    def test_generation_is_byte_deterministic(self):
        first = self.convert("08-long-text.md")
        second = self.convert("08-long-text.md")
        self.assertNotEqual(first.job_dir, second.job_dir)
        self.assertEqual(
            first.tex_path.read_bytes(),
            second.tex_path.read_bytes(),
            "the same input must produce the same .tex byte for byte",
        )

    def test_title_falls_back_to_the_first_heading(self):
        result = self.convert("01-headings.md")
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("\\title{Encabezado de nivel uno}", text)

    def test_front_matter_title_reaches_the_document(self):
        result = self.convert("10-frontmatter.md")
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("\\title{Documento con front matter}", text)
        self.assertNotIn("title: Documento con front matter", text)

    def test_explicit_title_overrides_front_matter(self):
        result = self.convert("10-frontmatter.md", title="Título explícito")
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("\\title{Título explícito}", text)

    def test_base_text_color_is_applied_at_begin_document(self):
        result = self.convert("01-headings.md")
        text = result.tex_path.read_text(encoding="utf-8")
        preamble = text.split("\\begin{document}")[0]
        self.assertIn("\\AtBeginDocument{\\color{RoseInk}}", preamble)
        self.assertNotIn("\n\\color{RoseInk}", preamble)


class BrandingIntegrationTests(ConvertCase):
    def test_default_brand_is_the_verified_invering_identity(self):
        result = self.convert("01-headings.md", brand=None)
        self.assertEqual(result.manifest["brand"]["name"], "invering")
        self.assertFalse(result.manifest["brand"]["provisional"])
        self.assertEqual(
            result.manifest["brand"]["source"],
            "bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2",
        )

    def test_manifest_records_provisional_branding(self):
        result = self.convert("02-emphasis.md", brand="demo")
        manifest = result.manifest
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["status"], "tex-only")
        self.assertTrue(manifest["brand"]["provisional"])
        self.assertEqual(manifest["brand"]["name"], "demo")
        self.assertTrue(manifest["brand"]["provisional_note"])
        self.assertEqual(
            manifest["source"]["sha256"],
            sha256((FIXTURES / "02-emphasis.md").read_bytes()),
        )
        artifact_paths = [item["path"] for item in manifest["artifacts"]]
        self.assertIn("document.tex", artifact_paths)
        manifest_path = result.job_dir / "manifest.json"
        self.assertTrue(manifest_path.is_file())
        self.assertEqual(
            json.loads(manifest_path.read_text(encoding="utf-8")), manifest
        )

    def test_invering_profile_uses_verified_tokens_and_logo(self):
        result = self.convert("01-headings.md", brand="invering")
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("#006838", text)
        self.assertIn("\\includegraphics", text)
        self.assertEqual(
            result.manifest["brand"]["source"], "bd5dd8aff92e3ffdb43cc99b78f3d8da1f6b8cb2"
        )
        self.assertFalse(result.manifest["brand"]["provisional"])

    def test_front_matter_can_select_the_brand(self):
        source = pathlib.Path(self._tmp.name) / "doc.md"
        source.write_text("---\ntitle: Con marca\nbrand: invering\n---\n\nTexto.\n", encoding="utf-8")
        result = convert_document(source, settings=self.settings())
        self.assertEqual(result.manifest["brand"]["name"], "invering")

    def test_unknown_front_matter_brand_is_rejected(self):
        source = pathlib.Path(self._tmp.name) / "doc.md"
        source.write_text("---\nbrand: inexistente\n---\n\nTexto.\n", encoding="utf-8")
        with self.assertRaises(BrandingError) as caught:
            convert_document(source, settings=self.settings())
        self.assertEqual(caught.exception.code, "branding_profile_not_found")

    def test_image_is_copied_into_the_job_assets(self):
        result = self.convert("06-image.md")
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("{assets/", text)
        assets = [path for path in result.job_dir.rglob("*") if path.is_file() and "assets" in path.parts]
        self.assertTrue(assets, "the image must be copied into the job")

    def test_source_copy_is_immutable(self):
        result = self.convert("03-lists.md")
        copies = list((result.job_dir / "source").glob("*"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), (FIXTURES / "03-lists.md").read_bytes())


class FailureTests(ConvertCase):
    def test_pdf_without_provisioned_image_fails_before_writing(self):
        with self.assertRaises(SandboxUnavailableError) as caught:
            self.convert("01-headings.md", formats=("tex", "pdf"))
        self.assertEqual(caught.exception.code, "sandbox_image_not_provisioned")
        self.assertFalse(self.out.exists(), "a refused job must not create artifacts")

    def test_missing_source_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            convert_document(self.out / "nada.md", settings=self.settings())
        self.assertEqual(caught.exception.code, "source_not_found")

    def test_unsupported_extension_is_rejected(self):
        source = pathlib.Path(self._tmp.name) / "informe.docx"
        source.write_bytes(b"pk\x03\x04")
        with self.assertRaises(InputValidationError) as caught:
            convert_document(source, settings=self.settings())
        self.assertEqual(caught.exception.code, "unsupported_source_type")

    def test_oversized_input_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            self.convert("08-long-text.md", settings=self.settings(max_input_bytes=50))
        self.assertEqual(caught.exception.code, "input_too_large")

    def test_invalid_utf8_is_rejected(self):
        source = pathlib.Path(self._tmp.name) / "roto.md"
        source.write_bytes(b"# T\xedtulo\n\n\xff\xfe no es utf-8\n")
        with self.assertRaises(InputValidationError) as caught:
            convert_document(source, settings=self.settings())
        self.assertEqual(caught.exception.code, "invalid_encoding")

    def test_output_directory_is_created(self):
        result = self.convert("01-headings.md")
        self.assertTrue(result.job_dir.is_dir())
        self.assertTrue((result.job_dir / "manifest.json").is_file())


if __name__ == "__main__":
    unittest.main()
