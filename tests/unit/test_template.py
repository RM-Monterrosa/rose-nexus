"""Unit tests for the strict LaTeX template renderer."""

import unittest

from rose_nexus.studio.template import TemplateError, render_template


class TemplateTests(unittest.TestCase):
    def test_known_tokens_are_replaced(self):
        self.assertEqual(
            render_template("A {{uno}} B {{ dos }}", {"uno": "1", "dos": "2"}),
            "A 1 B 2",
        )

    def test_unknown_token_is_an_error(self):
        with self.assertRaises(TemplateError) as caught:
            render_template("{{falta}}", {"otro": "x"})
        self.assertEqual(caught.exception.code, "template_unknown_token")
        self.assertIn("falta", caught.exception.message)

    def test_value_cannot_inject_a_token(self):
        with self.assertRaises(TemplateError) as caught:
            render_template("{{a}}", {"a": "{{b}}", "b": "x"})
        self.assertEqual(caught.exception.code, "template_value_invalid")

    def test_single_braces_are_literal_latex(self):
        self.assertEqual(
            render_template(r"\definecolor{x}{HTML}{{{c}}}", {"c": "FFFFFF"}),
            r"\definecolor{x}{HTML}{FFFFFF}",
        )

    def test_unterminated_token_is_an_error(self):
        with self.assertRaises(TemplateError) as caught:
            render_template("{{sin_cierre", {})
        self.assertEqual(caught.exception.code, "template_unterminated_token")

    def test_value_may_contain_latex_closing_braces(self):
        self.assertEqual(
            render_template("{{a}}", {"a": r"\AtBeginDocument{\color{x}}"}),
            r"\AtBeginDocument{\color{x}}",
        )

    def test_body_is_spliced_last_and_stays_opaque(self):
        out = render_template(
            "pre\n{{body}}\npost",
            {},
            body="\\begin{verbatim}{{ x }}\\end{verbatim}",
        )
        self.assertEqual(out, "pre\n\\begin{verbatim}{{ x }}\\end{verbatim}\npost")

    def test_missing_body_token_simply_drops_the_body(self):
        self.assertEqual(render_template("sin cuerpo", {}, body="ignorado"), "sin cuerpo")


if __name__ == "__main__":
    unittest.main()
