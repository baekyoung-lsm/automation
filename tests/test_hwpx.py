"""한글 문서(hwpx) 읽기 시험. 진짜 한글 파일 대신 구조가 같은 견본을 만든다."""

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import hwpx, sheet, text

SECTION = """<?xml version="1.0" encoding="UTF-8"?>
<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"
        xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
 <hp:p><hp:run><hp:t>사업 계획서</hp:t></hp:run></hp:p>
 <hp:p><hp:run><hp:t>첫째 줄</hp:t><hp:t>과 이어짐</hp:t></hp:run></hp:p>
 <hp:p><hp:run><hp:tbl>
   <hp:tr>
     <hp:tc><hp:subList><hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p></hp:subList></hp:tc>
     <hp:tc><hp:subList><hp:p><hp:run><hp:t>금액</hp:t></hp:run></hp:p></hp:subList></hp:tc>
   </hp:tr>
   <hp:tr>
     <hp:tc><hp:subList><hp:p><hp:run><hp:t>인건비</hp:t></hp:run></hp:p></hp:subList></hp:tc>
     <hp:tc><hp:subList><hp:p><hp:run><hp:t>1,000</hp:t></hp:run></hp:p></hp:subList></hp:tc>
   </hp:tr>
 </hp:tbl></hp:run></hp:p>
</hs:sec>"""


class HwpxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name="계획서.hwpx", sections=None) -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", hwpx.MIMETYPE)
            z.writestr("version.xml", "<hv:HCFVersion/>")
            for number, body in enumerate(sections or [SECTION]):
                z.writestr(f"Contents/section{number}.xml", body)
        return path

    def test_reads_paragraphs_and_tables_in_order(self):
        parts = hwpx.read_document(self.make())
        self.assertEqual([kind for kind, _b in parts], ["문단", "문단", "표"])
        self.assertEqual(parts[0][1], "사업 계획서")
        self.assertEqual(parts[2][1], [["항목", "금액"], ["인건비", "1,000"]])

    def test_runs_in_one_paragraph_join(self):
        parts = hwpx.read_document(self.make())
        self.assertEqual(parts[1][1], "첫째 줄과 이어짐")

    def test_table_text_is_not_repeated_as_paragraphs(self):
        # iter() 로 훑으면 표 안 문단이 한 번 더 나온다. 옮긴 문서에 같은 글이 두 번 들어간다
        parts = hwpx.read_document(self.make())
        self.assertEqual(sum(1 for kind, _b in parts if kind == "문단"), 2)

    def test_text_around_a_table_in_one_paragraph(self):
        # 표를 품은 문단에 붙은 글자를 버리면 설명이 통째로 사라진다
        sec = ("<hs:sec xmlns:hs='s' xmlns:hp='p'><hp:p>"
               "<hp:run><hp:t>표 앞 설명</hp:t></hp:run>"
               "<hp:run><hp:tbl><hp:tr>"
               "<hp:tc><hp:p><hp:run><hp:t>가</hp:t></hp:run></hp:p></hp:tc>"
               "<hp:tc><hp:p><hp:run><hp:t>나</hp:t></hp:run></hp:p></hp:tc>"
               "</hp:tr></hp:tbl></hp:run>"
               "<hp:run><hp:t>표 뒤 설명</hp:t></hp:run>"
               "</hp:p></hs:sec>")
        parts = hwpx.read_document(self.make(sections=[sec]))
        self.assertEqual(parts, [("문단", "표 앞 설명"),
                                 ("표", [["가", "나"]]),
                                 ("문단", "표 뒤 설명")])

    def test_sections_keep_their_order(self):
        second = SECTION.replace("사업 계획서", "둘째 장")
        parts = hwpx.read_document(self.make(sections=[SECTION, second]))
        texts = [b for kind, b in parts if kind == "문단"]
        self.assertEqual(texts[0], "사업 계획서")
        self.assertEqual(texts[2], "둘째 장")

    def test_namespace_prefix_does_not_matter(self):
        # 판마다 접두사가 다르다. 붙잡아 두면 다음 판에서 조용히 아무것도 못 읽는다
        odd = SECTION.replace("hp:", "x:").replace("xmlns:hp=", "xmlns:x=")
        parts = hwpx.read_document(self.make(sections=[odd]))
        self.assertEqual(parts[0][1], "사업 계획서")

    def test_old_binary_hwp_says_what_to_do(self):
        path = self.root / "옛문서.hwp"
        path.write_bytes(b"\\xd0\\xcf\\x11\\xe0 not a zip")
        with self.assertRaises(hwpx.HwpxError) as ctx:
            hwpx.read_document(path)
        self.assertIn("hwpx 로", str(ctx.exception))

    def test_zip_without_sections(self):
        path = self.root / "빈것.hwpx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", hwpx.MIMETYPE)
        with self.assertRaises(hwpx.HwpxError) as ctx:
            hwpx.read_document(path)
        self.assertIn("본문을 찾지 못했습니다", str(ctx.exception))

    def test_read_text_puts_table_cells_on_one_line(self):
        body = hwpx.read_text(self.make())
        self.assertIn("항목\t금액", body)

    def test_markdown_has_a_table(self):
        out = hwpx.to_markdown(hwpx.read_document(self.make()))
        self.assertIn("| 항목 | 금액 |", out)
        self.assertIn("| --- | --- |", out)

    def test_tables_helper(self):
        self.assertEqual(len(hwpx.tables(self.make())), 1)

    # ---- 다른 곳에서 쓰는 자리

    def test_sheet_reads_tables(self):
        tables = sheet.tables_from_hwpx(self.make())
        self.assertEqual(tables[0].headers, ["항목", "금액"])
        self.assertEqual(tables[0].rows, [["인건비", 1000]])

    def test_sheet_error_for_old_hwp(self):
        path = self.root / "옛문서.hwp"
        path.write_bytes(b"not a zip")
        with self.assertRaises(sheet.SheetError):
            sheet.tables_from_hwpx(path)

    def test_text_reads_it_as_a_document(self):
        body, kind = text.read_words_or_text(self.make())
        self.assertEqual(kind, "한글 문단")
        self.assertIn("사업 계획서", body)

    def test_text_find_can_look_inside(self):
        self.make()
        import re

        found = text.find_in_files([p for p in text.iter_files([self.root],
                                                               documents=True)],
                                   re.compile("사업"), documents=True)
        self.assertEqual([f.path.name for f in found], ["계획서.hwpx"])


if __name__ == "__main__":
    unittest.main()
