"""Unit tests for the LaTeX security policy (defense in depth).

The policy is the second line of defense: user content is already escaped, so
these tests exercise a compromised or buggy template on purpose.
"""

import unittest

from rose_nexus.core.errors import LatexPolicyViolation
from rose_nexus.security.latex_policy import validate_generated_latex

BASE_DOCUMENT = """% rose-nexus generated document
\\documentclass[11pt,A4]{article}
\\usepackage{geometry}
\\usepackage{graphicx}
\\usepackage{array}
\\usepackage{longtable}
\\usepackage{xcolor}
\\definecolor{rnaccent}{HTML}{B03A5B}
\\usepackage{hyperref}
\\usepackage{fancyhdr}
\\begin{document}
\\section{Título}
Texto.
\\end{document}
"""


def generated_document():
    return BASE_DOCUMENT


class PolicyTests(unittest.TestCase):
    def test_generated_document_passes(self):
        validate_generated_latex(generated_document())

    def test_missing_marker_is_rejected(self):
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex("\\documentclass{article}\\begin{document}x\\end{document}")
        self.assertEqual(caught.exception.code, "latex_missing_marker")

    def test_shell_escape_command_is_rejected(self):
        document = generated_document().replace(
            "\\begin{document}", "\\write18{rm -rf /}\n\\begin{document}"
        )
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex(document)
        self.assertEqual(caught.exception.code, "latex_forbidden_command")

    def test_shell_escape_package_is_rejected(self):
        document = generated_document().replace(
            "\\usepackage{geometry}", "\\usepackage{geometry}\n\\usepackage{shellesc}"
        )
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex(document)
        self.assertEqual(caught.exception.code, "latex_forbidden_package")

    def test_input_of_absolute_path_is_rejected(self):
        document = generated_document().replace(
            "\\begin{document}", "\\input{/etc/passwd}\n\\begin{document}"
        )
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex(document)
        self.assertEqual(caught.exception.code, "latex_forbidden_command")

    def test_graphics_with_parent_traversal_is_rejected(self):
        document = generated_document().replace(
            "\\begin{document}", "\\includegraphics{../../secret.png}\n\\begin{document}"
        )
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex(document)
        self.assertEqual(caught.exception.code, "latex_unsafe_asset")

    def test_lua_directive_is_rejected(self):
        document = generated_document().replace(
            "\\begin{document}", "\\directlua{os.execute('x')}\n\\begin{document}"
        )
        with self.assertRaises(LatexPolicyViolation) as caught:
            validate_generated_latex(document)
        self.assertEqual(caught.exception.code, "latex_forbidden_command")


if __name__ == "__main__":
    unittest.main()
