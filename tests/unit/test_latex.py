"""Unit tests for the LaTeX body generator: escaping, blocks and URL policy."""

import unittest

from rose_nexus.core.errors import InputValidationError, LatexPolicyViolation
from rose_nexus.studio.latex import escape_text, render_body, safe_href
from rose_nexus.studio.parser import parse_markdown


class EscapeTests(unittest.TestCase):
    def test_every_latex_special_is_escaped(self):
        self.assertEqual(
            escape_text(r"\ { } $ & # ^ _ % ~ < >"),
            r"\textbackslash{} \{ \} \$ \& \# \textasciicircum{} \_ \% "
            r"\textasciitilde{} \textless{} \textgreater{}",
        )

    def test_plain_words_are_untouched(self):
        self.assertEqual(escape_text("Hola mundo, ñandú"), "Hola mundo, ñandú")

    def test_backslash_becomes_a_single_text_command(self):
        self.assertEqual(escape_text("\\"), "\\textbackslash{}")


class BlockRenderingTests(unittest.TestCase):
    def render(self, source):
        return render_body(parse_markdown(source).blocks)

    def test_headings_use_sectioning_commands(self):
        body = self.render("# Uno\n\n## Dos\n\n### Tres\n")
        self.assertIn("\\section{Uno}", body)
        self.assertIn("\\subsection{Dos}", body)
        self.assertIn("\\subsubsection{Tres}", body)

    def test_raw_latex_from_user_text_is_neutralized(self):
        body = self.render("Texto con \\write18{rm -rf /} dentro.\n")
        self.assertNotIn("\\write18", body)
        self.assertIn("textbackslash", body)

    def test_bullet_and_ordered_lists(self):
        self.assertIn("\\begin{itemize}", self.render("- uno\n- dos\n"))
        self.assertIn("\\begin{enumerate}", self.render("1. uno\n2. dos\n"))

    def test_table_uses_longtable_and_escapes_cells(self):
        body = self.render("| a_b | c |\n| --- | --- |\n| 50% | `x` |\n")
        self.assertIn("\\begin{longtable}", body)
        self.assertIn("a\\_b", body)
        self.assertIn("50\\%", body)

    def test_code_block_is_verbatim(self):
        body = self.render("```python\nprint('x')\n```\n")
        self.assertIn("\\begin{verbatim}", body)
        self.assertIn("print('x')", body)

    def test_code_block_terminator_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            self.render("```\n\\end{verbatim}\n```\n")
        self.assertEqual(caught.exception.code, "code_block_terminator")

    def test_blockquote_and_rule(self):
        body = self.render("> Cita\n\n---\n")
        self.assertIn("\\begin{quote}", body)
        self.assertIn("\\rule", body)

    def test_inline_code_preserves_spaces(self):
        body = self.render("Usar `a b` aquí.\n")
        self.assertIn(r"\texttt{a\ b}", body)

    def test_image_requires_a_resolved_copy(self):
        blocks = parse_markdown("![Píxel](../assets/pixel.png)\n").blocks
        with self.assertRaises(InputValidationError) as caught:
            render_body(blocks)
        self.assertEqual(caught.exception.code, "image_not_resolved")

    def test_image_uses_the_resolved_relative_path(self):
        blocks = parse_markdown("![Píxel](../assets/pixel.png)\n").blocks
        body = render_body(blocks, image_map={"../assets/pixel.png": "assets/pixel.png"})
        self.assertIn("\\includegraphics", body)
        self.assertIn("{assets/pixel.png}", body)

    def test_resolved_image_path_cannot_escape(self):
        blocks = parse_markdown("![Píxel](../assets/pixel.png)\n").blocks
        with self.assertRaises(LatexPolicyViolation) as caught:
            render_body(blocks, image_map={"../assets/pixel.png": "../../etc/passwd.png"})
        self.assertEqual(caught.exception.code, "unsafe_asset_path")


class LinkTests(unittest.TestCase):
    def test_allowed_scheme_is_rendered(self):
        body = render_body(parse_markdown("[doc](https://example.com/a)\n").blocks)
        self.assertIn("\\href{https://example.com/a}{doc}", body)

    def test_javascript_scheme_is_rejected(self):
        with self.assertRaises(LatexPolicyViolation) as caught:
            render_body(parse_markdown("[x](javascript:alert(1))\n").blocks)
        self.assertEqual(caught.exception.code, "unsafe_link_scheme")

    def test_file_scheme_is_rejected(self):
        with self.assertRaises(LatexPolicyViolation) as caught:
            render_body(parse_markdown("[x](file:///etc/passwd)\n").blocks)
        self.assertEqual(caught.exception.code, "unsafe_link_scheme")

    def test_relative_link_is_rejected(self):
        with self.assertRaises(LatexPolicyViolation) as caught:
            render_body(parse_markdown("[x](../secreto)\n").blocks)
        self.assertEqual(caught.exception.code, "unsafe_link_scheme")

    def test_href_encodes_latex_and_url_specials(self):
        self.assertEqual(
            safe_href("https://example.com/a b?x=1&y=2#frag"),
            "https://example.com/a%20b?x=1%26y=2%23frag",
        )

    def test_mailto_is_allowed(self):
        self.assertEqual(safe_href("mailto:a@b.c"), "mailto:a@b.c")


if __name__ == "__main__":
    unittest.main()
