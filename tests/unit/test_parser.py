"""Unit tests for the deterministic Markdown/TXT parser.

These tests define the supported subset and the exact failure modes. They are
written before the implementation on purpose (RED first).
"""

import unittest

from rose_nexus.core.errors import InputValidationError
from rose_nexus.studio.model import (
    BulletList,
    Code,
    CodeBlock,
    Emphasis,
    Heading,
    Image,
    Link,
    OrderedList,
    Paragraph,
    Quote,
    Rule,
    Strong,
    Table,
    Text,
    plain_text,
)
from rose_nexus.studio.parser import parse_markdown, parse_plain_text


class HeadingTests(unittest.TestCase):
    def test_levels_one_to_five_map_to_heading_blocks(self):
        doc = parse_markdown("# Uno\n\n## Dos\n\n### Tres\n\n#### Cuatro\n\n##### Cinco\n")
        self.assertEqual(
            [(block.level, plain_text(block.children)) for block in doc.blocks],
            [(1, "Uno"), (2, "Dos"), (3, "Tres"), (4, "Cuatro"), (5, "Cinco")],
        )

    def test_heading_level_six_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("###### Seis\n")
        self.assertEqual(caught.exception.code, "heading_level_unsupported")

    def test_hash_without_space_is_a_paragraph(self):
        doc = parse_markdown("#no-es-encabezado\n")
        self.assertIsInstance(doc.blocks[0], Paragraph)
        self.assertEqual(plain_text(doc.blocks[0].children), "#no-es-encabezado")


class FrontMatterTests(unittest.TestCase):
    def test_front_matter_is_extracted_and_kept_out_of_the_body(self):
        doc = parse_markdown(
            "---\ntitle: Título\nsubtitle: Sub\nauthor: Autora\ndate: 2026-11-15\n"
            "brand: demo\nlang: es\n---\n\n# Cuerpo\n"
        )
        self.assertTrue(doc.meta.has_front_matter)
        self.assertEqual(doc.meta.title, "Título")
        self.assertEqual(doc.meta.subtitle, "Sub")
        self.assertEqual(doc.meta.author, "Autora")
        self.assertEqual(doc.meta.date, "2026-11-15")
        self.assertEqual(doc.meta.brand, "demo")
        self.assertEqual(doc.meta.lang, "es")
        self.assertEqual(len(doc.blocks), 1)
        self.assertIsInstance(doc.blocks[0], Heading)

    def test_quoted_values_are_unquoted(self):
        doc = parse_markdown('---\ntitle: "Título con comillas"\n---\n\nTexto.\n')
        self.assertEqual(doc.meta.title, "Título con comillas")

    def test_unknown_key_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("---\nowner: alguien\n---\n\nTexto.\n")
        self.assertEqual(caught.exception.code, "front_matter_unknown_key")
        self.assertIn("owner", caught.exception.message)

    def test_unclosed_front_matter_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("---\ntitle: Sin cierre\n\nTexto.\n")
        self.assertEqual(caught.exception.code, "front_matter_unclosed")

    def test_duplicate_key_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("---\ntitle: Uno\ntitle: Dos\n---\n\nTexto.\n")
        self.assertEqual(caught.exception.code, "front_matter_duplicate_key")


class CodeBlockTests(unittest.TestCase):
    def test_fenced_code_preserves_content_and_language(self):
        doc = parse_markdown("```python\ndef suma(a, b):\n    return a + b\n```\n")
        block = doc.blocks[0]
        self.assertIsInstance(block, CodeBlock)
        self.assertEqual(block.language, "python")
        self.assertEqual(block.content, "def suma(a, b):\n    return a + b")

    def test_markdown_inside_code_is_not_interpreted(self):
        doc = parse_markdown("```\n# no es encabezado\n**no es fuerte**\n```\n")
        self.assertEqual(doc.blocks[0].content, "# no es encabezado\n**no es fuerte**")

    def test_tilde_fence_is_supported(self):
        doc = parse_markdown("~~~bash\necho hola\n~~~\n")
        self.assertIsInstance(doc.blocks[0], CodeBlock)
        self.assertEqual(doc.blocks[0].language, "bash")

    def test_unclosed_fence_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("```python\nprint(1)\n")
        self.assertEqual(caught.exception.code, "unclosed_code_fence")


class TableTests(unittest.TestCase):
    def test_pipe_table_with_separator_row(self):
        doc = parse_markdown(
            "| Parámetro | Valor |\n| --- | --- |\n| `page_size` | A4 |\n| cover | simple |\n"
        )
        table = doc.blocks[0]
        self.assertIsInstance(table, Table)
        self.assertEqual([plain_text(cell) for cell in table.header], ["Parámetro", "Valor"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual([plain_text(cell) for cell in table.rows[0]], ["page_size", "A4"])

    def test_pipe_line_without_separator_is_a_paragraph(self):
        doc = parse_markdown("| a | b |\n")
        self.assertIsInstance(doc.blocks[0], Paragraph)

    def test_too_many_columns_is_rejected(self):
        header = "| " + " | ".join(f"c{i}" for i in range(13)) + " |\n"
        separator = "| " + " | ".join("---" for _ in range(13)) + " |\n"
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown(header + separator)
        self.assertEqual(caught.exception.code, "table_too_wide")


class ListTests(unittest.TestCase):
    def test_bullet_list(self):
        doc = parse_markdown("- uno\n- dos con **fuerte**\n- tres\n")
        block = doc.blocks[0]
        self.assertIsInstance(block, BulletList)
        self.assertEqual(len(block.items), 3)
        self.assertIn(Strong, [type(part) for part in block.items[1]])

    def test_ordered_list(self):
        doc = parse_markdown("1. Validar\n2. Convertir\n")
        block = doc.blocks[0]
        self.assertIsInstance(block, OrderedList)
        self.assertEqual([plain_text(item) for item in block.items], ["Validar", "Convertir"])

    def test_nested_list_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("- uno\n  - anidado\n")
        self.assertEqual(caught.exception.code, "unsupported_nested_list")


class BlockTests(unittest.TestCase):
    def test_image_alone_in_a_paragraph_becomes_an_image_block(self):
        doc = parse_markdown("![Píxel](../assets/pixel.png)\n")
        block = doc.blocks[0]
        self.assertIsInstance(block, Image)
        self.assertEqual(block.alt, "Píxel")
        self.assertEqual(block.path, "../assets/pixel.png")

    def test_inline_image_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("Texto antes ![Píxel](../assets/pixel.png) texto después.\n")
        self.assertEqual(caught.exception.code, "inline_image_unsupported")

    def test_blockquote_is_parsed_recursively(self):
        doc = parse_markdown("> Cita uno\n> Cita dos\n")
        block = doc.blocks[0]
        self.assertIsInstance(block, Quote)
        self.assertEqual(plain_text(block.blocks[0]), "Cita uno Cita dos")

    def test_horizontal_rule(self):
        doc = parse_markdown("Texto.\n\n---\n\nMás texto.\n")
        self.assertEqual([type(block) for block in doc.blocks], [Paragraph, Rule, Paragraph])

    def test_raw_html_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("<script>alert(1)</script>\n")
        self.assertEqual(caught.exception.code, "unsupported_html")


class InlineTests(unittest.TestCase):
    def test_strong_emphasis_and_code(self):
        doc = parse_markdown("**fuerte** y *énfasis* y `código`.\n")
        kinds = [type(part) for part in doc.blocks[0].children]
        self.assertIn(Strong, kinds)
        self.assertIn(Emphasis, kinds)
        self.assertIn(Code, kinds)

    def test_nested_emphasis_inside_strong(self):
        doc = parse_markdown("**fuerte con *énfasis* adentro**\n")
        strong = doc.blocks[0].children[0]
        self.assertIsInstance(strong, Strong)
        self.assertIn(Emphasis, [type(part) for part in strong.children])

    def test_link_keeps_text_and_url(self):
        doc = parse_markdown("[documentación](https://pandoc.org/MANUAL.html)\n")
        link = doc.blocks[0].children[0]
        self.assertIsInstance(link, Link)
        self.assertEqual(plain_text(link.children), "documentación")
        self.assertEqual(link.url, "https://pandoc.org/MANUAL.html")

    def test_backslash_escape_keeps_literal_punctuation(self):
        doc = parse_markdown("\\*no es énfasis\\* y \\#literal\n")
        self.assertEqual(plain_text(doc.blocks[0].children), "*no es énfasis* y #literal")

    def test_soft_line_break_becomes_a_space(self):
        doc = parse_markdown("Primera línea\nsegunda línea\n")
        self.assertEqual(plain_text(doc.blocks[0].children), "Primera línea segunda línea")


class NormalizationTests(unittest.TestCase):
    def test_crlf_and_bom_are_normalized(self):
        doc = parse_markdown("\ufeff# Título\r\n\r\nTexto.\r\n")
        self.assertEqual(doc.blocks[0].level, 1)
        self.assertEqual(plain_text(doc.blocks[1].children), "Texto.")

    def test_nul_byte_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("Texto\x00conveneno\n")
        self.assertEqual(caught.exception.code, "control_character")

    def test_empty_document_is_rejected(self):
        with self.assertRaises(InputValidationError) as caught:
            parse_markdown("   \n\n\t\n")
        self.assertEqual(caught.exception.code, "empty_document")


class PlainTextTests(unittest.TestCase):
    def test_markdown_is_not_interpreted(self):
        doc = parse_plain_text("# no es encabezado\n\n*no* es énfasis\n")
        self.assertTrue(all(isinstance(block, Paragraph) for block in doc.blocks))
        self.assertEqual(plain_text(doc.blocks[0].children), "# no es encabezado")

    def test_paragraphs_are_split_by_blank_lines(self):
        doc = parse_plain_text("Uno.\n\nDos.\n")
        self.assertEqual([plain_text(block.children) for block in doc.blocks], ["Uno.", "Dos."])

    def test_plain_text_keeps_latex_specials_as_text(self):
        doc = parse_plain_text("$ & % # _ { } ~ ^ \\\n")
        self.assertEqual(plain_text(doc.blocks[0].children), "$ & % # _ { } ~ ^ \\")


if __name__ == "__main__":
    unittest.main()
