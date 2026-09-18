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

class ControlCharTest(unittest.TestCase):
    """PDF·로그에서 옮겨 온 글에 제어 문자가 섞여 온다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_control_characters_do_not_break_the_file(self):
        # 그대로 넣으면 워드가 «파일이 손상됐다» 며 열지 못한다
        path = self.root / "제어.docx"
        docx.write_document(path, [docx.paragraph("가\x07나\x0b다"),
                                   docx.table([["머리\x01글", "값"]])])
        parts = docx.read_document(path)
        self.assertEqual(parts[0], ("문단", "가나다"))
        self.assertEqual(parts[1], ("표", [["머리글", "값"]]))


class WrongFormatTest(unittest.TestCase):
    """같은 zip 이라도 알맹이를 보면 무엇인지 알 수 있다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, inner: str) -> Path:
        path = self.root / "받은문서.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(inner, "<x/>")
        return path

    def test_slides_and_sheets_are_named(self):
        for inner, hint in (("ppt/slides/slide1.xml", "from-pptx"),
                            ("xl/workbook.xml", "at sheet peek"),
                            ("Contents/section0.xml", "from-hwpx")):
            with self.assertRaises(docx.DocxError) as caught:
                docx.read_document(self.make(inner))
            self.assertIn(hint, str(caught.exception), inner)


class LockedDocxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_password_protected_document(self):
        # 암호 건 워드도 zip 이다. «워드 문서가 아니다» 로 알리면 엉뚱한 데를 본다
        path = self.root / "암호.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("EncryptedPackage", b"\x00" * 20)
        with self.assertRaises(docx.DocxError) as caught:
            docx.read_document(path)
        self.assertIn("암호", str(caught.exception))


class MergedCellTest(unittest.TestCase):
    """가로로 병합한 칸. 한 칸으로 세면 뒤 열 값이 통째로 사라진다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, body: str) -> Path:
        import zipfile

        W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        path = self.root / "표.docx"
        document = (f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
                    + body + "</w:body></w:document>")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", document)
        return path

    def test_grid_span_keeps_columns_lined_up(self):
        path = self.make(
            "<w:tbl>"
            '<w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>'
            "<w:p><w:r><w:t>합친 머리</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>금액</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>영업</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>교통비</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>1000</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl>")
        rows = docx.read_document(path)[0][1]
        self.assertEqual(rows[0], ["합친 머리", "", "금액"])
        self.assertEqual(rows[1], ["영업", "교통비", "1000"])



class FillDocumentTest(unittest.TestCase):
    """워드 양식에 값 채우기. 원본의 서식·이름공간이 살아 있어야 한다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.form = self.root / "위촉장.docx"
        docx.write_document(self.form, [
            docx.paragraph("위 촉 장", size=32, bold=True, center=True),
            docx.paragraph("성명: {이름}"),
            docx.paragraph("위 사람을 {직책}(으)로 위촉합니다."),
            docx.table([["항목", "값"], ["소속", "{소속}"]])])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def split_form(self) -> Path:
        """«{이름}» 이 run 세 개로 쪼개진 양식. 워드가 흔히 그렇게 만든다."""
        body = ('<w:p><w:r><w:rPr><w:b/></w:rPr>'
                '<w:t xml:space="preserve">귀하 </w:t></w:r>'
                '<w:r><w:t>{이</w:t></w:r><w:r><w:t>름</w:t></w:r>'
                '<w:r><w:t>} 님</w:t></w:r></w:p>')
        path = self.root / "쪼개진.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", docx.CONTENT_TYPES)
            z.writestr("_rels/.rels", docx.ROOT_RELS)
            z.writestr("word/document.xml",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       f"<w:document {docx.NS}><w:body>{body}"
                       f"{docx.SECTION}</w:body></w:document>")
        return path

    def test_placeholders_are_listed_in_order(self):
        self.assertEqual(docx.placeholders(self.form),
                         ["이름", "직책", "소속"])

    def test_values_land_in_paragraphs_and_tables(self):
        out = self.root / "채움.docx"
        report = docx.fill_document(self.form, out,
                                    {"이름": "김민수", "직책": "자문위원",
                                     "소속": "영업1팀"})
        self.assertEqual(report.filled, 3)
        got = docx.read_text(out)
        self.assertIn("성명: 김민수", got)
        self.assertIn("자문위원(으)로", got)
        self.assertIn("영업1팀", got)

    def test_a_placeholder_split_across_runs_is_still_filled(self):
        """워드는 «{이름}» 을 run 여러 개로 쪼개 둔다. 이어 붙여 찾아야 한다."""
        out = self.root / "쪼개진채움.docx"
        report = docx.fill_document(self.split_form(), out, {"이름": "김민수"})
        self.assertEqual(report.filled, 1)
        self.assertEqual(docx.read_text(out).strip(), "귀하 김민수 님")

    def test_other_formatting_in_that_paragraph_survives(self):
        """문단을 통째로 다시 쓰면 굵게·글꼴이 날아간다."""
        out = self.root / "서식.docx"
        docx.fill_document(self.split_form(), out, {"이름": "김민수"})
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:b/>", xml)

    def test_a_missing_value_is_left_alone_and_reported(self):
        """빈 칸으로 만들면 백 장을 만든 뒤에야 무엇이 빠졌는지 알게 된다."""
        out = self.root / "모자람.docx"
        report = docx.fill_document(self.form, out, {"이름": "김민수"})
        self.assertEqual(report.missing, ["직책", "소속"])
        self.assertIn("{직책}", docx.read_text(out))

    def test_the_template_is_not_touched(self):
        before = self.form.read_bytes()
        docx.fill_document(self.form, self.root / "x.docx", {"이름": "김"})
        self.assertEqual(self.form.read_bytes(), before)

    def test_every_other_part_is_copied_byte_for_byte(self):
        path = self.root / "그림있는.docx"
        with zipfile.ZipFile(self.form) as src, zipfile.ZipFile(path, "w") as dst:
            for item in src.infolist():
                dst.writestr(item.filename, src.read(item.filename))
            dst.writestr("word/media/도장.png", b"\x89PNG" + "가짜".encode())
        out = self.root / "그림채움.docx"
        docx.fill_document(path, out, {"이름": "김민수"})
        with zipfile.ZipFile(out) as z, zipfile.ZipFile(path) as o:
            self.assertEqual(z.namelist(), o.namelist())
            self.assertEqual(z.read("word/media/도장.png"),
                             o.read("word/media/도장.png"))

    def test_namespaces_and_compatibility_marks_survive(self):
        """mc:Ignorable 이 떨어지면 워드가 «파일이 손상됐다» 고 한다."""
        path = self.root / "진짜같은.docx"
        doc = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
               '<w:document xmlns:w="http://schemas.openxmlformats.org/'
               'wordprocessingml/2006/main" xmlns:mc="http://schemas.'
               'openxmlformats.org/markup-compatibility/2006" xmlns:w14='
               '"http://schemas.microsoft.com/office/word/2010/wordml" '
               'mc:Ignorable="w14"><w:body><w:p w14:paraId="12AB">'
               "<w:r><w:t>{업체} 귀중</w:t></w:r></w:p></w:body></w:document>")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("[Content_Types].xml", docx.CONTENT_TYPES)
            z.writestr("_rels/.rels", docx.ROOT_RELS)
            z.writestr("word/document.xml", doc)
        out = self.root / "공문.docx"
        docx.fill_document(path, out, {"업체": "한빛상사"})
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn('mc:Ignorable="w14"', xml)
        self.assertIn('w14:paraId="12AB"', xml)
        self.assertIn("한빛상사 귀중", xml)

    def test_headers_are_filled_too(self):
        """공문은 문서번호가 머리글에 있다."""
        path = self.root / "머리글.docx"
        with zipfile.ZipFile(self.form) as src, zipfile.ZipFile(path, "w") as dst:
            for item in src.infolist():
                dst.writestr(item.filename, src.read(item.filename))
            dst.writestr("word/header1.xml",
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         f"<w:hdr {docx.NS}><w:p><w:r><w:t>문서번호 {{번호}}"
                         "</w:t></w:r></w:p></w:hdr>")
        out = self.root / "머리글채움.docx"
        report = docx.fill_document(path, out, {"번호": "총무-2026-17"})
        self.assertIn("word/header1.xml", report.parts)
        with zipfile.ZipFile(out) as z:
            self.assertIn("총무-2026-17",
                          z.read("word/header1.xml").decode("utf-8"))

    def test_special_characters_are_escaped(self):
        out = self.root / "특수.docx"
        docx.fill_document(self.form, out, {"이름": "김 & 이 <주식회사>"})
        self.assertIn("김 & 이 <주식회사>", docx.read_text(out))

    def test_a_file_that_is_not_word_is_refused(self):
        bad = self.root / "가짜.docx"
        bad.write_bytes(b"not a zip")
        with self.assertRaises(docx.DocxError):
            docx.placeholders(bad)
        with self.assertRaises(docx.DocxError):
            docx.fill_document(bad, self.root / "x.docx", {"이름": "김"})


class FillValueTest(unittest.TestCase):
    """채워 넣는 값이 이상할 때. 위촉장에 «None» 이 인쇄되면 안 된다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.form = self.root / "양식.docx"
        docx.write_document(self.form, [docx.paragraph("성명: {이름}")])

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def fill(self, values, name="채움.docx"):
        out = self.root / name
        return docx.fill_document(self.form, out, values), out

    def test_a_blank_cell_becomes_a_blank_spot_not_none(self):
        """표의 빈 칸은 None 으로 들어온다. str() 하면 «None» 이 찍힌다."""
        report, out = self.fill({"이름": None})
        self.assertNotIn("None", docx.read_text(out))
        self.assertEqual(report.blank, ["이름"])

    def test_an_empty_string_is_also_reported_as_blank(self):
        report, _out = self.fill({"이름": ""})
        self.assertEqual(report.blank, ["이름"])

    def test_a_filled_value_is_not_reported_as_blank(self):
        report, _out = self.fill({"이름": "김민수"})
        self.assertEqual(report.blank, [])

    def test_numbers_go_in_as_written(self):
        _report, out = self.fill({"이름": 12345})
        self.assertIn("12345", docx.read_text(out))

    def test_a_newline_becomes_a_real_line_break(self):
        """글자 «\\n» 을 그대로 넣으면 워드는 빈칸 하나로 보여 준다."""
        _report, out = self.fill({"이름": "첫 줄\n둘째 줄"})
        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        self.assertIn("<w:br/>", xml)
        self.assertIn("첫 줄\n둘째 줄", docx.read_text(out))

    def test_xml_in_a_value_cannot_break_the_document(self):
        _report, out = self.fill({"이름": "</w:t></w:r><w:r><w:t>몰래"})
        self.assertIn("</w:t></w:r><w:r><w:t>몰래", docx.read_text(out))

    def test_control_characters_are_dropped(self):
        """PDF·로그에서 옮겨 온 글에 섞여 온다. 그대로 넣으면 문서가 안 열린다."""
        _report, out = self.fill({"이름": "김\x00민\x07수"})
        self.assertIn("김민수", docx.read_text(out))

    def test_a_value_that_looks_like_a_placeholder_is_not_filled_again(self):
        _report, out = self.fill({"이름": "{다른자리}"})
        self.assertIn("{다른자리}", docx.read_text(out))
