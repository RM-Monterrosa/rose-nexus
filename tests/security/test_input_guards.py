"""Security guards at the pipeline boundary.

Each test proves one rejection: the dangerous input is refused with a stable code
and no artifacts are written.
"""

import pathlib
import tempfile
import unittest

from rose_nexus.core.config import Settings
from rose_nexus.core.errors import InputValidationError, LatexPolicyViolation
from rose_nexus.security.latex_policy import validate_generated_latex
from rose_nexus.studio.pipeline import convert_document

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BRANDING = REPO_ROOT / "branding"


class GuardCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.src = self.base / "src"
        self.src.mkdir()
        self.out = self.base / "build"

    def tearDown(self):
        self._tmp.cleanup()

    def settings(self, **overrides):
        values = {"branding_dir": BRANDING, "output_dir": self.out}
        values.update(overrides)
        return Settings(**values)

    def document(self, text, name="doc.md"):
        target = self.src / name
        target.write_text(text, encoding="utf-8")
        return target

    def convert(self, source, **kwargs):
        kwargs.setdefault("settings", self.settings())
        return convert_document(source, brand="demo", **kwargs)

    def assert_no_job(self):
        if self.out.exists():
            self.assertEqual([path for path in self.out.iterdir() if path.is_dir()], [])


class ImageGuardTests(GuardCase):
    def test_parent_traversal_is_rejected(self):
        source = self.document("![x](../../etc/passwd)\n")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsafe_image_path")
        self.assert_no_job()

    def test_absolute_path_is_rejected(self):
        source = self.document("![x](/etc/passwd)\n")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsafe_image_path")

    def test_symlink_escaping_the_document_root_is_rejected(self):
        outside = self.base / "outside.png"
        outside.write_bytes(b"\x89PNG\r\n\x1a\n")
        (self.src / "link.png").symlink_to(outside)
        source = self.document("![x](link.png)\n")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsafe_image_path")

    def test_unsupported_image_type_is_rejected(self):
        (self.src / "foto.gif").write_bytes(b"GIF89a")
        source = self.document("![x](foto.gif)\n")
        with self.assertRaises(InputValidationError) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsupported_image_type")

    def test_oversized_image_is_rejected(self):
        (self.src / "grande.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        source = self.document("![x](grande.png)\n")
        with self.assertRaises(InputValidationError) as caught:
            self.convert(source, settings=self.settings(max_image_bytes=8))
        self.assertEqual(caught.exception.code, "image_too_large")
        self.assert_no_job()


class ContentGuardTests(GuardCase):
    def test_raw_latex_in_text_is_neutralized(self):
        source = self.document("Texto con \\write18{rm -rf /} dentro.\n")
        result = self.convert(source)
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertNotIn("\\write18", text)
        self.assertIn("textbackslash", text)
        validate_generated_latex(text)

    def test_javascript_link_is_rejected(self):
        source = self.document("[x](javascript:alert(1))\n")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsafe_link_scheme")
        self.assertEqual(caught.exception.exit_code, 3)

    def test_file_link_is_rejected(self):
        source = self.document("[x](file:///etc/passwd)\n")
        with self.assertRaises(LatexPolicyViolation) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsafe_link_scheme")

    def test_verbatim_terminator_is_rejected(self):
        source = self.document("```\n\\end{verbatim}\n```\n")
        with self.assertRaises(InputValidationError) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "code_block_terminator")
        self.assert_no_job()

    def test_control_character_is_rejected(self):
        source = self.src / "doc.md"
        source.write_bytes(b"# Titulo\n\nTexto\x00venenoso\n")
        with self.assertRaises(InputValidationError) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "control_character")

    def test_template_tokens_in_a_title_cannot_be_injected(self):
        source = self.document('---\ntitle: "{{title}}"\n---\n\nTexto.\n')
        result = self.convert(source)
        text = result.tex_path.read_text(encoding="utf-8")
        self.assertIn("\\{\\{title\\}\\}", text)
        validate_generated_latex(text)

    def test_tex_source_is_rejected(self):
        source = self.document("\\documentclass{article}\n", name="doc.tex")
        with self.assertRaises(InputValidationError) as caught:
            self.convert(source)
        self.assertEqual(caught.exception.code, "unsupported_source_type")


if __name__ == "__main__":
    unittest.main()
