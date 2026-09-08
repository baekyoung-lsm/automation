"""의존성 없는 docx 라이터·리더 시험."""

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



WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


class DocxReaderTest(unittest.TestCase):
    """워드가 실제로 내는 꼴(pStyle, numPr, w:br)을 그대로 만들어 읽힌다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, body: str, name="문서.docx") -> Path:
        path = self.root / name
        document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body>'
                    "</w:document>")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", document)
        return path

    def para(self, text, style="", numbered=False):
        props = ""
        if style:
            props += f'<w:pStyle w:val="{style}"/>'
        if numbered:
            props += "<w:numPr><w:ilvl w:val=\"0\"/></w:numPr>"
        props = f"<w:pPr>{props}</w:pPr>" if props else ""
        return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"

    def test_heading_styles_become_levels(self):
        body = self.para("큰 제목", "Heading1") + self.para("작은 제목", "Heading3")
        parts = docx.read_document(self.make(body))
        self.assertEqual(parts, [("제목1", "큰 제목"), ("제목3", "작은 제목")])

    def test_korean_heading_style_name(self):
        # 한글 워드는 스타일 이름이 «제목 1» 로 들어온다
        parts = docx.read_document(self.make(self.para("제목이다", "제목 2")))
        self.assertEqual(parts, [("제목2", "제목이다")])

    def test_numbered_paragraph_is_a_list(self):
        parts = docx.read_document(self.make(self.para("첫 항목", numbered=True)))
        self.assertEqual(parts, [("목록", "첫 항목")])

    def test_line_break_inside_a_paragraph(self):
        body = ("<w:p><w:r><w:t>위</w:t><w:br/><w:t>아래</w:t></w:r></w:p>")
        parts = docx.read_document(self.make(body))
        self.assertEqual(parts, [("문단", "위\n아래")])

    def test_empty_paragraphs_are_dropped(self):
        body = self.para("있음") + "<w:p/>" + self.para("   ")
        parts = docx.read_document(self.make(body))
        self.assertEqual(parts, [("문단", "있음")])

    def test_table_rows(self):
        cell = '<w:tc><w:p><w:r><w:t>{}</w:t></w:r></w:p></w:tc>'
        body = ("<w:tbl><w:tr>" + cell.format("이름") + cell.format("부서") +
                "</w:tr><w:tr>" + cell.format("홍길동") + cell.format("영업") +
                "</w:tr></w:tbl>")
        parts = docx.read_document(self.make(body))
        self.assertEqual(parts, [("표", [["이름", "부서"], ["홍길동", "영업"]])])

    def test_round_trip_through_the_writer(self):
        path = self.root / "쓴것.docx"
        docx.write_document(path, [docx.paragraph("한 문단"),
                                   docx.table([["가", "나"], ["1", "2"]])])
        parts = docx.read_document(path)
        self.assertEqual(parts[0], ("문단", "한 문단"))
        self.assertEqual(parts[1][0], "표")

    def test_not_a_word_file(self):
        bad = self.root / "가짜.docx"
        bad.write_text("이건 zip 이 아니다", encoding="utf-8")
        with self.assertRaises(docx.DocxError):
            docx.read_document(bad)

    def test_zip_without_document_xml(self):
        bad = self.root / "빈zip.docx"
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("아무것.txt", "x")
        with self.assertRaises(docx.DocxError) as ctx:
            docx.read_document(bad)
        self.assertIn("워드 문서가 아닙니다", str(ctx.exception))


class DocxToMarkdownTest(unittest.TestCase):
    def test_headings_and_lists(self):
        out = docx.to_markdown([("제목1", "큰 제목"), ("목록", "가"),
                                ("목록", "나"), ("문단", "본문")])
        self.assertEqual(out, "# 큰 제목\n\n- 가\n- 나\n본문\n")

    def test_table_becomes_a_markdown_table(self):
        out = docx.to_markdown([("표", [["이름", "부서"], ["홍길동", "영업"]])])
        self.assertIn("| 이름 | 부서 |", out)
        self.assertIn("| --- | --- |", out)

    def test_ragged_table_is_padded(self):
        out = docx.to_markdown([("표", [["가", "나"], ["1"]])])
        self.assertIn("| 1 |  |", out)

    def test_pipe_in_a_cell_is_escaped(self):
        out = docx.to_markdown([("표", [["가|나"]])])
        self.assertIn("가\\|나", out)

    def test_read_text_joins_everything(self):
        # 찾기·세기용이라 표도 한 줄씩 붙인다
        parts = [("제목1", "제목"), ("표", [["가", "나"]])]
        self.assertEqual(docx.to_markdown(parts).count("|"), 6)


class ForeignDocxTest(unittest.TestCase):
    """남이 만든 문서. 우리 라이터를 거치지 않은 모양을 손으로 만들어 본다."""

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, body: str) -> Path:
        path = self.root / "받은문서.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml",
                       f'<?xml version="1.0"?><w:document xmlns:w="{self.W}">'
                       f"<w:body>{body}</w:body></w:document>")
        return path

    def test_paragraph_inside_a_content_control(self):
        # 양식 문서에 흔한 w:sdt. 바로 아래 자식만 보면 통째로 빠진다
        path = self.make(
            "<w:p><w:r><w:t>앞 문단</w:t></w:r></w:p>"
            "<w:sdt><w:sdtContent><w:p><w:r><w:t>양식 칸</w:t></w:r></w:p>"
            "</w:sdtContent></w:sdt>")
        self.assertEqual([b for _k, b in docx.read_document(path)],
                         ["앞 문단", "양식 칸"])

    def test_hyperlink_text_is_kept(self):
        path = self.make("<w:p><w:hyperlink><w:r><w:t>링크 글자</w:t></w:r>"
                         "</w:hyperlink></w:p>")
        self.assertEqual(docx.read_text(path), "링크 글자")

    def test_tracked_insert_is_text_and_delete_is_not(self):
        path = self.make("<w:p><w:ins><w:r><w:t>넣은 말</w:t></w:r></w:ins>"
                         "<w:del><w:r><w:delText>지운 말</w:delText></w:r>"
                         "</w:del></w:p>")
        self.assertEqual(docx.read_text(path), "넣은 말")

    def test_table_cell_wrapped_in_a_control(self):
        path = self.make(
            "<w:tbl><w:tr><w:tc><w:sdt><w:sdtContent><w:p><w:r>"
            "<w:t>칸 값</w:t></w:r></w:p></w:sdtContent></w:sdt></w:tc>"
            "<w:tc><w:p><w:r><w:t>둘</w:t></w:r></w:p></w:tc>"
            "</w:tr></w:tbl>")
        self.assertEqual(docx.read_document(path)[0][1], [["칸 값", "둘"]])

    def test_section_marks_are_not_paragraphs(self):
        path = self.make("<w:p><w:r><w:t>글</w:t></w:r></w:p>"
                         "<w:sectPr><w:pgSz w:w='11906'/></w:sectPr>")
        self.assertEqual([b for _k, b in docx.read_document(path)], ["글"])


if __name__ == "__main__":
    unittest.main()
