"""받은 메일(.eml) 읽기 시험."""

import shutil
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import eml


class EmlTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name: str = "받은메일.eml", *, attach: bool = True,
             html: bool = False) -> Path:
        message = EmailMessage()
        message["From"] = "홍길동 <hong@example.com>"
        message["To"] = "kim@example.com"
        message["Subject"] = "3월 정산 자료 보냅니다"      # 한글 제목은 인코딩되어 담긴다
        message["Date"] = "Wed, 04 Mar 2026 09:12:00 +0900"
        if html:
            message.set_content("<p>표로 보냅니다</p>", subtype="html")
        else:
            message.set_content("첨부 확인 부탁드립니다.")
        if attach:
            message.add_attachment("이름,금액\n홍길동,1250000\n".encode("utf-8"),
                                   maintype="text", subtype="csv",
                                   filename="정산 내역.csv")
        path = self.root / name
        path.write_bytes(message.as_bytes())
        return path

    def test_headers_come_back_as_korean(self):
        mail = eml.read_mail(self.make())
        self.assertEqual(mail.subject, "3월 정산 자료 보냅니다")
        self.assertIn("hong@example.com", mail.sender)
        self.assertEqual(mail.when, "2026-03-04 09:12")
        self.assertIn("첨부 확인", mail.body)

    def test_attachments_are_listed_without_reading_them(self):
        mail = eml.read_mail(self.make())
        self.assertEqual([a.name for a in mail.attachments], ["정산 내역.csv"])
        self.assertEqual(mail.attachments[0].data, b"")     # keep_data 를 안 켰다
        self.assertGreater(mail.attachments[0].size, 0)

    def test_keep_data_gives_the_bytes(self):
        mail = eml.read_mail(self.make(), keep_data=True)
        self.assertIn("홍길동", mail.attachments[0].data.decode("utf-8"))

    def test_html_only_body_is_flagged(self):
        mail = eml.read_mail(self.make(attach=False, html=True))
        self.assertTrue(mail.html_only)
        self.assertIn("표로 보냅니다", mail.body)

    def test_empty_file_is_refused(self):
        path = self.root / "빈.eml"
        path.write_bytes(b"")
        with self.assertRaises(eml.EmlError):
            eml.read_mail(path)

    def test_collect_finds_only_eml(self):
        self.make("가.eml")
        (self.root / "메모.txt").write_text("x", encoding="utf-8")
        self.assertEqual([p.name for p in eml.collect(self.root)], ["가.eml"])

    def test_text_search_reads_mail(self):
        from attools import text

        body, kind = text.read_words_or_text(self.make())
        self.assertIn("3월 정산 자료", body)      # 제목도 함께 찾을 수 있어야 한다
        self.assertIn("정산 내역.csv", body)      # 첨부 이름으로도 찾는다
        self.assertEqual(kind, "메일 글자")

    def test_garbage_still_reads_as_an_empty_mail(self):
        # 메일 라이브러리는 아무 글이나 «머리글 없는 메일» 로 읽는다.
        # 그때도 터지지 않고 빈 값으로 와야 한다
        path = self.root / "아무글.eml"
        path.write_text("이건 메일이 아니다", encoding="utf-8")
        mail = eml.read_mail(path)
        self.assertEqual(mail.subject, "")
        self.assertEqual(mail.attachments, [])


if __name__ == "__main__":
    unittest.main()
