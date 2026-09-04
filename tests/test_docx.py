"""의존성 없는 docx 라이터 시험."""

import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import docx
from attools.docs import mdkit


class DocxWriterTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, parts) -> str:
        path = docx.write_document(self.root / "문서.docx", parts)
        with zipfile.ZipFile(path) as z:
            body = z.read("word/document.xml").decode("utf-8")
        ET.fromstring(body)          # 워드가 읽을 수 있는 XML 이어야 한다
        return body

    def test_required_parts_are_there(self):
        path = docx.write_document(self.root / "문서.docx", [docx.paragraph("글")])
        with zipfile.ZipFile(path) as z:
            self.assertEqual(sorted(z.namelist()),
                             ["[Content_Types].xml", "_rels/.rels",
                              "word/document.xml"])

    def test_text_is_escaped(self):
        body = self.write([docx.paragraph("<태그> & 기호")])
        self.assertIn("&lt;태그&gt;", body)
        self.assertIn("&amp;", body)

    def test_marks_are_applied(self):
        body = self.write([docx.paragraph("가", bold=True, italic=True,
                                          center=True, page_break=True)])
        self.assertIn("<w:b/>", body)
        self.assertIn("<w:i/>", body)
        self.assertIn('w:jc w:val="center"', body)
        self.assertIn('w:type="page"', body)

    def test_korean_font_and_mono(self):
        self.assertIn(docx.FONT, self.write([docx.paragraph("가")]))
        self.assertIn(docx.MONO, self.write([docx.paragraph("code", mono=True)]))

    def test_table_has_rows_and_borders(self):
        body = self.write([docx.table([["이름", "값"], ["가", "1"]])])
        self.assertEqual(body.count("<w:tr>"), 2)
        self.assertEqual(body.count("<w:tc>"), 4)
        self.assertIn("tblBorders", body)

    def test_short_table_row_is_padded(self):
        body = self.write([docx.table([["가", "나", "다"], ["1"]])])
        self.assertEqual(body.count("<w:tc>"), 6)

    def test_empty_document_still_opens(self):
        self.assertIn("<w:p>", self.write([]))


class MarkdownToDocxTest(unittest.TestCase):
    MD = ("# 보고서\n\n첫 문단 **굵게** 와 [링크](http://a.b).\n\n"
          "| 항목 | 값 |\n|---|---:|\n| 가 | 1 |\n\n"
          "- 목록\n  - 안쪽\n\n> 인용\n\n```\ncode line\n```\n")

    def parts(self) -> str:
        return "".join(mdkit.to_docx_parts(self.MD))

    def test_inline_marks_are_stripped_but_text_kept(self):
        body = self.parts()
        self.assertNotIn("**", body)
        self.assertIn("굵게", body)
        self.assertIn("링크", body)
        self.assertNotIn("http://a.b", body)      # 링크 주소는 글자로 남기지 않는다

    def test_table_becomes_a_real_table(self):
        self.assertIn("<w:tbl>", self.parts())

    def test_code_block_uses_mono_font(self):
        self.assertIn(docx.MONO, self.parts())

    def test_headings_are_bigger_and_bold(self):
        body = "".join(mdkit.to_docx_parts("# 제목\n"))
        self.assertIn("<w:b/>", body)
        self.assertIn('w:sz w:val="36"', body)

    def test_list_and_quote_are_indented(self):
        body = self.parts()
        self.assertIn("• 목록", body)
        self.assertIn("<w:i/>", body)             # 인용은 기울임


if __name__ == "__main__":
    unittest.main()
