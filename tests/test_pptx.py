"""슬라이드(pptx) 읽기 시험. 진짜 파일 대신 구조가 같은 견본을 만든다."""

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, pptx, text

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def slide(*paragraphs: str, table: list | None = None) -> str:
    body = "".join(
        f"<p:sp><p:txBody><a:p><a:r><a:t>{one}</a:t></a:r></a:p></p:txBody></p:sp>"
        for one in paragraphs)
    if table:
        rows = "".join(
            "<a:tr>" + "".join(
                f"<a:tc><a:txBody><a:p><a:r><a:t>{cell}</a:t></a:r></a:p>"
                "</a:txBody></a:tc>" for cell in row) + "</a:tr>"
            for row in table)
        body += f"<p:graphicFrame><a:tbl>{rows}</a:tbl></p:graphicFrame>"
    return (f'<?xml version="1.0"?><p:sld xmlns:p="{P}" xmlns:a="{A}">'
            f"<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>")


class PptxTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, parts: dict, name: str = "발표.pptx") -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w") as z:
            for key, body in parts.items():
                z.writestr(key, body)
        return path

    def simple(self) -> Path:
        return self.make({
            "ppt/slides/slide1.xml": slide("사업 계획", "매출 30억"),
            "ppt/slides/slide2.xml": slide("조직 개편",
                                           table=[["팀", "인원"], ["영업", "5"]]),
        })

    def test_reads_paragraphs_and_tables(self):
        slides = pptx.read_slides(self.simple())
        self.assertEqual([s.title for s in slides], ["사업 계획", "조직 개편"])
        self.assertEqual(slides[1].blocks[-1],
                         ("표", [["팀", "인원"], ["영업", "5"]]))

    def test_order_follows_the_deck_not_the_file_name(self):
        # 슬라이드를 옮겨 붙인 파일은 이름 순서와 보이는 차례가 다르다
        rels = (f'<?xml version="1.0"?><Relationships xmlns="{R.replace("officeDocument/2006/relationships", "package/2006/relationships")}">'
                '<Relationship Id="rId9" Target="slides/slide2.xml"/>'
                '<Relationship Id="rId8" Target="slides/slide1.xml"/>'
                "</Relationships>")
        deck = (f'<?xml version="1.0"?><p:presentation xmlns:p="{P}" xmlns:r="{R}">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId9"/>'
                '<p:sldId id="257" r:id="rId8"/></p:sldIdLst></p:presentation>')
        path = self.make({
            "ppt/slides/slide1.xml": slide("나중"),
            "ppt/slides/slide2.xml": slide("먼저"),
            "ppt/_rels/presentation.xml.rels": rels,
            "ppt/presentation.xml": deck,
        })
        self.assertEqual([s.title for s in pptx.read_slides(path)], ["먼저", "나중"])

    def test_notes_only_when_asked(self):
        path = self.make({
            "ppt/slides/slide1.xml": slide("본문"),
            "ppt/notesSlides/notesSlide1.xml": slide("여기서 시간을 끌 것"),
        })
        self.assertEqual(pptx.read_slides(path)[0].notes, "")
        with_notes = pptx.read_slides(path, notes=True)
        self.assertIn("시간을 끌", with_notes[0].notes)

    def test_markdown_puts_the_first_line_as_a_heading(self):
        body = pptx.to_markdown(pptx.read_slides(self.simple()))
        self.assertIn("## 1. 사업 계획", body)
        self.assertIn("| 팀 | 인원 |", body)
        self.assertEqual(body.count("사업 계획"), 1)   # 제목을 두 번 적지 않는다

    def test_not_a_zip(self):
        path = self.root / "옛것.pptx"
        path.write_text("이건 pptx 가 아니다", encoding="utf-8")
        with self.assertRaises(pptx.PptxError) as caught:
            pptx.read_slides(path)
        self.assertIn(".ppt", str(caught.exception))

    def test_encrypted(self):
        path = self.make({"EncryptedPackage": "x"}, name="암호.pptx")
        with self.assertRaises(pptx.PptxError) as caught:
            pptx.read_slides(path)
        self.assertIn("암호", str(caught.exception))

    def test_text_search_reads_slides(self):
        path = self.simple()
        body, kind = text.read_words_or_text(path)
        self.assertIn("매출 30억", body)
        self.assertEqual(kind, "슬라이드 글자")

    def test_tables_go_to_the_sheet_side(self):
        from attools import sheet

        tables = sheet.tables_from_pptx(self.simple())
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].headers, ["팀", "인원"])
        self.assertEqual(tables[0].rows, [["영업", 5]])

    def test_slide_count_without_app_xml(self):
        # 파워포인트가 아닌 도구로 만든 파일에는 docProps/app.xml 이 없다
        meta = files.document_meta(self.simple())
        self.assertEqual(meta.slides, 2)


if __name__ == "__main__":
    unittest.main()
