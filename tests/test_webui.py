"""브라우저 화면 시험. 서버를 실제로 띄우고 두드린다."""

import json
import os
import pathlib
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import files, sheet, webui


class UiCase(unittest.TestCase):
    """서버를 띄우고 홈을 임시 폴더로 돌리는 뼈대. 시험은 물려받는 쪽에 둔다.

    이 자리에 시험을 두면 화면마다 물려받은 클래스에서 똑같은 시험이 한 번씩
    더 돈다. 열두 화면이면 열두 번이다.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.home = self.root / "home"
        self.home.mkdir()
        self.work = self.root / "일감"
        self.work.mkdir()

        self.prev_home = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)

        self.run = webui.start()
        self.base = "http://127.0.0.1:%d" % self.run.server.server_address[1]
        # poll_interval 을 줄여야 shutdown() 이 0.5초씩 기다리지 않는다
        self.thread = threading.Thread(
            target=self.run.server.serve_forever, kwargs={"poll_interval": 0.02},
            daemon=True)
        self.thread.start()

    def tearDown(self):
        self.run.server.shutdown()
        self.run.server.server_close()
        self.thread.join(timeout=5)
        if self.prev_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.prev_home
        shutil.rmtree(self.root, ignore_errors=True)

    # --- 도우미 -------------------------------------------------------
    def get(self, path):
        with urllib.request.urlopen(self.base + path) as res:
            return res.status, res.read().decode("utf-8")

    def post(self, path, payload, *, token=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if token is not False:
            headers["X-At-Token"] = token or self.run.token
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            self.base + path, data=json.dumps(payload).encode("utf-8"),
            headers=headers)
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read().decode("utf-8"))

    def make(self, name, content="내용"):
        p = self.work / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p


class WebUiTest(UiCase):
    """서버·열쇠와 파일 정리 화면."""

    # --- 열쇠 ---------------------------------------------------------
    def test_token_required_for_page(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/")
        self.assertEqual(ctx.exception.code, 403)

    def test_page_with_token(self):
        status, body = self.get("/?t=" + self.run.token)
        self.assertEqual(status, 200)
        self.assertIn("파일 정리", body)

    def test_app_page(self):
        status, body = self.get("/files?t=" + self.run.token)
        self.assertEqual(status, 200)
        self.assertIn("미리보기", body)

    def test_unknown_page(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get(quote("/없는것") + "?t=" + self.run.token)
        self.assertEqual(ctx.exception.code, 404)

    def test_post_without_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/preview", {"path": str(self.work)}, token=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_post_from_other_site(self):
        """다른 웹페이지가 몰래 부르지 못해야 한다."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/preview", {"path": str(self.work)},
                      origin="https://example.com")
        self.assertEqual(ctx.exception.code, 403)

    def test_local_origin_allowed(self):
        self.make("보고서.txt")
        status, data = self.post("/api/files/preview", {"path": str(self.work)},
                                 origin=self.base)
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)

    # --- 파일 정리 ----------------------------------------------------
    def test_preview_does_not_move(self):
        self.make("사진.jpg")
        status, data = self.post("/api/files/preview", {"path": str(self.work)})
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 1)
        self.assertTrue((self.work / "사진.jpg").exists())

    def test_audit_reports_what_it_looked_at(self):
        (self.work / "가.txt").write_text("같은 내용", encoding="utf-8")
        (self.work / "나.txt").write_text("같은 내용", encoding="utf-8")
        _, data = self.post("/api/files/audit", {"aroot": str(self.work)})
        kinds = {n["kind"] for n in data["notes"]}
        self.assertIn("중복", kinds)
        self.assertTrue(data["looked"])

    def test_audit_can_skip_duplicate_search(self):
        (self.work / "가.txt").write_text("같은 내용", encoding="utf-8")
        (self.work / "나.txt").write_text("같은 내용", encoding="utf-8")
        _, data = self.post("/api/files/audit",
                            {"aroot": str(self.work), "anodupes": True})
        self.assertNotIn("중복", {n["kind"] for n in data["notes"]})
        self.assertTrue(any("보지 않았습니다" in line for line in data["skipped"]))

    def test_pack_groups_under_the_limit(self):
        import os

        for name in ("가.bin", "나.bin", "다.bin"):
            (self.work / name).write_bytes(os.urandom(40_000))
        _, data = self.post("/api/files/pack_preview",
                            {"packroot": str(self.work), "packmax": "100000B"})
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["big"], [])

    def test_pack_names_a_file_that_is_too_big(self):
        import os

        (self.work / "큰것.bin").write_bytes(os.urandom(200_000))
        _, data = self.post("/api/files/pack_preview",
                            {"packroot": str(self.work), "packmax": "100000B"})
        self.assertEqual(data["big"][0][0], "큰것.bin")

    def test_pack_apply_writes_beside_the_folder(self):
        import os

        (self.work / "가.bin").write_bytes(os.urandom(10_000))
        _, data = self.post("/api/files/pack_apply",
                            {"packroot": str(self.work), "packmax": "100000B"})
        made = list(self.work.parent.glob(f"{self.work.name}-*.zip"))
        self.assertEqual(len(made), 1)
        self.assertEqual(data["saved"], str(self.work.parent))
        self.assertTrue((self.work / "가.bin").exists())    # 원본은 그대로

    def test_documents_and_scrub(self):
        import zipfile

        path = self.work / "계획서.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("docProps/core.xml",
                       "<cp:coreProperties xmlns:cp='c' xmlns:dc='d'>"
                       "<dc:title>계획</dc:title><dc:creator>김철수</dc:creator>"
                       "</cp:coreProperties>")
            z.writestr("word/document.xml", "<x/>")

        _, docs = self.post("/api/files/documents", {"docroot": str(self.work)})
        self.assertEqual(docs["count"], 1)
        self.assertEqual(docs["left"], [["계획서.docx", "김철수"]])

        _, plan = self.post("/api/files/scrub_preview",
                            {"docroot": str(self.work)})
        self.assertEqual(plan["rows"], [["계획서.docx", "만든 사람", "김철수"]])
        # 미리보기는 아무것도 만들지 않는다
        self.assertEqual(list(self.work.glob("*이름지움*")), [])

        _, done = self.post("/api/files/scrub_apply",
                            {"docroot": str(self.work)})
        self.assertEqual(len(done["made"]), 1)
        self.assertTrue(path.exists())      # 원본은 그대로
        _, after = self.post("/api/files/documents",
                             {"docroot": done["made"][0]})
        self.assertEqual(after["left"], [])

    def test_scrub_needs_a_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/scrub_preview", {"docroot": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_sync_preview_and_apply(self):
        source = self.work / "원본"
        backup = self.work / "백업"
        source.mkdir()
        backup.mkdir()
        (source / "가.txt").write_text("새것", encoding="utf-8")
        (source / "나.txt").write_text("바뀐 것", encoding="utf-8")
        (backup / "나.txt").write_text("옛것", encoding="utf-8")
        (backup / "라.txt").write_text("백업에만", encoding="utf-8")
        body = {"syncfrom": str(source), "syncto": str(backup)}

        _, data = self.post("/api/files/sync_preview", body)
        self.assertEqual(data["new"], ["가.txt"])
        self.assertEqual(data["changed"], ["나.txt"])
        self.assertEqual(data["extra"], ["라.txt"])
        self.assertFalse((backup / "가.txt").exists())

        _, done = self.post("/api/files/sync_apply", body)
        self.assertEqual(done["copied"], 2)
        self.assertEqual((backup / "나.txt").read_text("utf-8"), "바뀐 것")
        self.assertTrue((backup / "라.txt").is_file())      # 그대로 둔다
        kept = list((backup / files.OLD_VERSIONS_DIR).rglob("나.txt"))
        self.assertEqual(len(kept), 1)                      # 예전 판을 남긴다

    def test_sync_needs_a_backup_folder(self):
        source = self.work / "원본"
        source.mkdir()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/sync_preview",
                      {"syncfrom": str(source), "syncto": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_photos_show_and_strip(self):
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_files import exif_jpeg

        folder = self.work / "사진"
        folder.mkdir()
        (folder / "여행.jpg").write_bytes(exif_jpeg())

        _, data = self.post("/api/files/photos", {"photoroot": str(folder)})
        self.assertEqual(data["located"], 1)
        self.assertIn("37.56000, 126.97778", data["rows"][0])
        self.assertEqual(list(folder.glob("*정보지움*")), [])

        _, done = self.post("/api/files/photos_strip",
                            {"photoroot": str(folder)})
        self.assertEqual(len(done["made"]), 1)
        self.assertEqual(done["kept"], 1)          # 방향은 남긴다
        _, after = self.post("/api/files/photos",
                             {"photoroot": done["made"][0]})
        self.assertEqual(after["located"], 0)
        self.assertTrue((folder / "여행.jpg").is_file())   # 원본은 그대로

    def test_photos_strip_needs_something_to_remove(self):
        folder = self.work / "빈사진"
        folder.mkdir()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/photos_strip", {"photoroot": str(folder)})
        self.assertEqual(ctx.exception.code, 400)

    def test_pdf_from_images(self):
        import struct
        import zlib

        def chunk(kind, body):
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

        rows = b"".join(b"\x00" + bytes([10, 20, 30]) * 4 for _ in range(3))
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        folder = self.work / "스캔"
        folder.mkdir()
        (folder / "1.png").write_bytes(png)
        (folder / "2.png").write_bytes(png)
        (folder / "메모.txt").write_text("이건 그림이 아니다", encoding="utf-8")

        _, data = self.post("/api/files/pdf_preview", {"pdfroot": str(folder)})
        self.assertEqual(data["count"], 2)
        self.assertEqual(list(folder.parent.glob("*.pdf")), [])

        _, made = self.post("/api/files/pdf_make",
                            {"pdfroot": str(folder), "pdftitle": "제출용"})
        saved = Path(made["saved"])
        self.assertTrue(saved.is_file())
        from attools import pdf as pdfkit

        info = pdfkit.read_info(saved)
        self.assertEqual(info.pages, 2)
        self.assertEqual(info.title, "제출용")
        self.assertTrue((folder / "1.png").is_file())      # 원본은 그대로

    def test_pdf_needs_images(self):
        empty = self.work / "빈폴더"
        empty.mkdir()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/pdf_make", {"pdfroot": str(empty)})
        self.assertEqual(ctx.exception.code, 400)

    def test_pack_rejects_a_bad_size(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/pack_preview",
                      {"packroot": str(self.work), "packmax": "아주크게"})
        self.assertEqual(ctx.exception.code, 400)

    def test_apply_then_undo(self):
        self.make("사진.jpg")
        self.make("보고서.txt")
        _, data = self.post("/api/files/apply", {"path": str(self.work)})
        self.assertEqual(data["applied"], 2)
        self.assertFalse((self.work / "사진.jpg").exists())

        _, listed = self.post("/api/files/journals", {})
        self.assertEqual(len(listed["rows"]), 1)
        name = listed["rows"][0][0]

        _, undone = self.post("/api/files/undo", {"journal": name})
        self.assertEqual(undone["restored"], 2)
        self.assertEqual(undone["errors"], [])
        self.assertTrue((self.work / "사진.jpg").exists())

    def jpeg(self, name, taken=b"2024:03:15 14:30:00\x00"):
        import struct

        body = b"\xff\xd8"
        if taken is not None:
            tiff = b"II" + struct.pack("<HI", 42, 8)
            ifd0 = (struct.pack("<H", 1)
                    + struct.pack("<HHII", 0x8769, 4, 1, 26)
                    + struct.pack("<I", 0))
            sub = (struct.pack("<H", 1)
                   + struct.pack("<HHII", 0x9003, 2, 20, 44)
                   + struct.pack("<I", 0))
            exif = b"Exif\x00\x00" + tiff + ifd0 + sub + taken
            body += b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
        path = self.work / name
        path.write_bytes(body + b"\xff\xd9")
        return path

    def test_photo_mode_uses_taken_date(self):
        self.jpeg("가.jpg")
        self.jpeg("모름.jpg", None)
        _, data = self.post("/api/files/preview",
                            {"path": str(self.work), "mode": "photo-month"})
        self.assertEqual(data["rows"], [["가.jpg", "2024-03/가.jpg"]])
        self.assertTrue(any("두고 온" in note for note in data["notes"]))

    def test_photo_mode_mtime_fallback_is_flagged(self):
        self.jpeg("모름.jpg", None)
        _, data = self.post("/api/files/preview",
                            {"path": str(self.work), "mode": "photo-year",
                             "mtime": True})
        self.assertEqual(data["count"], 1)
        self.assertTrue(any("수정 시각" in note for note in data["notes"]))

    def twins(self):
        (self.work / "깊은").mkdir()
        body = "같은 내용" * 200
        (self.work / "원본.txt").write_text(body, encoding="utf-8")
        (self.work / "깊은" / "사본.txt").write_text(body, encoding="utf-8")

    def test_dupes_marks_one_keeper(self):
        self.twins()
        _, data = self.post("/api/files/dupes",
                            {"path": str(self.work), "min_size": "1"})
        self.assertEqual(data["groups"], 1)
        marks = [row[1] for row in data["rows"]]
        self.assertEqual(sorted(marks), ["남김", "중복"])

    def test_dupes_none(self):
        (self.work / "혼자.txt").write_text("혼자", encoding="utf-8")
        _, data = self.post("/api/files/dupes",
                            {"path": str(self.work), "min_size": "1"})
        self.assertEqual(data["groups"], 0)

    def test_collect_moves_and_undoes(self):
        self.twins()
        _, data = self.post("/api/files/collect_apply",
                            {"path": str(self.work), "min_size": "1"})
        self.assertEqual(data["applied"], 1)
        self.assertTrue((self.work / "원본.txt").exists())
        self.assertFalse((self.work / "깊은" / "사본.txt").exists())

        _, undone = self.post("/api/files/undo", {"journal": data["journal"]})
        self.assertEqual(undone["restored"], 1)
        self.assertTrue((self.work / "깊은" / "사본.txt").exists())

    def test_collect_twice_is_refused(self):
        self.twins()
        self.post("/api/files/collect_apply",
                  {"path": str(self.work), "min_size": "1"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/collect_preview",
                      {"path": str(self.work), "min_size": "1"})
        self.assertEqual(ctx.exception.code, 400)

    def test_collect_rejects_unknown_keep(self):
        self.twins()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/dupes",
                      {"path": str(self.work), "keep": "제일큰것"})
        self.assertEqual(ctx.exception.code, 400)

    def pair(self):
        left, right = self.work / "원본", self.work / "백업"
        left.mkdir()
        right.mkdir()
        (left / "가.txt").write_text("같음", encoding="utf-8")
        (right / "가.txt").write_text("같음", encoding="utf-8")
        (left / "나.txt").write_text("원본만", encoding="utf-8")
        (right / "다.txt").write_text("백업만", encoding="utf-8")
        (left / "라.txt").write_text("AAAA", encoding="utf-8")
        (right / "라.txt").write_text("BBBB", encoding="utf-8")
        return left, right

    def test_compare_folders(self):
        left, right = self.pair()
        _, data = self.post("/api/files/compare",
                            {"path": str(left), "other": str(right)})
        self.assertEqual((data["total"], data["same"]), (3, 1))
        kinds = {row[0] for row in data["rows"]}
        self.assertEqual(kinds, {"왼쪽에만", "오른쪽에만", "내용이 다름"})

    def test_compare_same_size_different_content(self):
        """크기가 같아도 내용이 다르면 잡아야 한다."""
        left, right = self.pair()
        _, data = self.post("/api/files/compare",
                            {"path": str(left), "other": str(right)})
        changed = [row for row in data["rows"] if row[0] == "내용이 다름"]
        self.assertEqual(changed[0][1], "라.txt")

    def test_compare_needs_two_folders(self):
        left, _right = self.pair()
        for body in ({"path": str(left)},
                     {"path": str(left), "other": str(left)}):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post("/api/files/compare", body)
            self.assertEqual(ctx.exception.code, 400)

    def test_compare_does_not_touch_files(self):
        left, right = self.pair()
        before = sorted(p.name for p in left.iterdir())
        self.post("/api/files/compare",
                  {"path": str(left), "other": str(right)})
        self.assertEqual(sorted(p.name for p in left.iterdir()), before)

    def test_listing(self):
        (self.work / "안쪽").mkdir()
        (self.work / "가.txt").write_text("내용", encoding="utf-8")
        (self.work / "안쪽" / "나.pdf").write_text("내용", encoding="utf-8")
        _, data = self.post("/api/files/listing", {"path": str(self.work)})
        self.assertEqual(data["count"], 2)
        self.assertIn("at file list", data["command"])

    def test_listing_save_next_to_folder(self):
        (self.work / "가.txt").write_text("내용", encoding="utf-8")
        _, data = self.post("/api/files/listing_save",
                            {"path": str(self.work), "format": ".csv"})
        saved = Path(data["saved"])
        self.assertTrue(saved.exists())
        self.assertEqual(saved.parent, self.work.parent)   # 폴더 안을 더럽히지 않는다

    def test_listing_empty_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/listing", {"path": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_apply_with_nothing_to_move(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/apply", {"path": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_folder_is_a_plain_message(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/preview", {"path": str(self.work / "없음")})
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("없습니다", payload["error"])

    def test_bad_mode_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/preview",
                      {"path": str(self.work), "mode": "rm -rf"})
        self.assertEqual(ctx.exception.code, 400)

    def test_undo_rejects_path_escape(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/files/undo", {"journal": "../../etc/passwd"})
        self.assertEqual(ctx.exception.code, 400)

    def test_unknown_action(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post(quote("/api/files/없는동작"), {})
        self.assertEqual(ctx.exception.code, 404)


class SheetAppTest(UiCase):
    """엑셀 화면. WebUiTest 의 서버·홈 설정을 그대로 쓴다."""

    def csv(self, name="명단.csv", body=None):
        path = self.work / name
        path.write_text(body if body is not None else
                        "이름, 나이 ,전화\n 홍길동 ,30,010-1\n홍길동,30,010-1\n"
                        "김철수,,010-2\n", encoding="utf-8")
        return path

    def test_peek(self):
        path = self.csv()
        _, data = self.post("/api/sheet/peek", {"path": str(path)})
        self.assertEqual(data["headers"], ["이름", "나이", "전화"])
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["columns"]), 3)

    def test_peek_rejects_other_formats(self):
        # txt 는 구분자 있는 표로 읽으므로 받는다. pdf 처럼 못 읽는 것만 막는다.
        path = self.work / "보고서.pdf"
        path.write_text("아무거나", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/peek", {"path": str(path)})
        self.assertEqual(ctx.exception.code, 400)

    def test_sheets_lists_every_sheet(self):
        from attools import xlsx

        path = self.work / "여러장.xlsx"
        xlsx.write_sheets(path, {"직원": [["사번"], ["E1"]], "빈시트": []})
        _, data = self.post("/api/sheet/sheets", {"path": str(path)})
        self.assertEqual(data["names"], ["직원", "빈시트"])
        self.assertEqual(data["rows"][1][3], "비어 있음")

    def test_sheets_refuses_csv(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/sheets", {"path": str(self.csv())})
        self.assertEqual(ctx.exception.code, 400)

    def test_check_finds_missing(self):
        path = self.csv()
        _, data = self.post("/api/sheet/check",
                            {"path": str(path), "required": "나이"})
        self.assertFalse(data["clean"])
        self.assertTrue(any("나이" in row[1] for row in data["rows"]))

    def test_check_unknown_column(self):
        path = self.csv()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/check", {"path": str(path), "key": "없는열"})
        self.assertEqual(ctx.exception.code, 400)

    def test_mask_hides_and_reports(self):
        path = self.csv("연락처.csv",
                        "이름,연락처\n홍길동,010-1234-5678\n이영희,연락처 없음\n")
        _, data = self.post("/api/sheet/mask_preview",
                            {"path": str(path),
                             "mspecs": [["이름", "이름"], ["연락처", "전화"]]})
        self.assertEqual(data["rows"][0], ["홍*동", "010-****-5678"])
        # 꼴을 모르는 값은 남기지 않고 통째로 가린 뒤 몇 행인지 알려 준다
        self.assertEqual(data["rows"][1][1], sheet.HIDDEN)
        self.assertEqual(data["unclear"], [["연락처", "3", "연락처 없음"]])

    def test_mask_needs_a_pick(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/mask_preview", {"path": str(self.csv())})
        self.assertEqual(ctx.exception.code, 400)

    def test_mask_save_leaves_the_original(self):
        path = self.csv("연락처.csv", "이름\n홍길동\n")
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/mask_save",
                            {"path": str(path), "mspecs": [["이름", "이름"]]})
        self.assertIn("(가림)", data["saved"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def forms(self):
        room = self.work / "제출"
        room.mkdir(exist_ok=True)
        (room / "영업.csv").write_text("제목,3월\n\n담당자,홍길동\n",
                                       encoding="utf-8")
        (room / "개발.csv").write_text("제목,3월\n\n담당자,김철수\n",
                                       encoding="utf-8")
        (room / "다른양식.csv").write_text("아무것도\n", encoding="utf-8")
        return room

    def test_collect_pulls_the_same_cell(self):
        _, data = self.post("/api/sheet/collect_preview",
                            {"cfolder": str(self.forms()), "cells": "B3=담당자"})
        self.assertEqual(data["count"], 3)
        self.assertEqual(sorted(r[1] for r in data["rows"]),
                         ["", "김철수", "홍길동"])
        self.assertEqual(data["empty"], ["다른양식.csv"])

    def test_collect_rejects_a_bad_address(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/collect_preview",
                      {"cfolder": str(self.forms()), "cells": "담당자"})
        self.assertEqual(ctx.exception.code, 400)

    def test_collect_saves_beside_the_folder(self):
        room = self.forms()
        _, data = self.post("/api/sheet/collect_save",
                            {"cfolder": str(room), "cells": "B3=담당자"})
        saved = Path(data["saved"])
        # 폴더 안에 넣으면 다음 취합에 자기 자신이 딸려 온다
        self.assertEqual(saved.parent, room.parent)
        self.assertTrue(saved.exists())

    def test_similar_finds_the_same_company(self):
        path = self.csv("거래처.csv",
                        "상호\n(주)가나상사\n주식회사 가나상사\n마바무역\n")
        _, data = self.post("/api/sheet/similar",
                            {"path": str(path), "simcol": "상호"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0][0], "표기만 다름")

    def test_similar_needs_a_column(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/similar", {"path": str(self.csv())})
        self.assertEqual(ctx.exception.code, 400)

    def test_dates_adds_columns(self):
        path = self.csv("주문.csv", "주문일,금액\n2026-03-02,100\n곧,200\n")
        _, data = self.post("/api/sheet/dates_preview",
                            {"path": str(path), "dcol": "주문일",
                             "dparts": ["요일", "연월"]})
        self.assertEqual(data["headers"][-2:], ["주문일 요일", "주문일 연월"])
        self.assertEqual(data["rows"][0][-2:], ["월", "2026-03"])
        # 날짜로 못 읽은 칸은 비워 두고 몇 행인지 알려 준다
        self.assertEqual(data["failed"], [["3", "곧"]])

    def test_dates_needs_a_part(self):
        path = self.csv("주문.csv", "주문일\n2026-03-02\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/dates_preview",
                      {"path": str(path), "dcol": "주문일", "dparts": []})
        self.assertEqual(ctx.exception.code, 400)

    def test_dates_save_leaves_the_original(self):
        path = self.csv("주문.csv", "주문일\n2026-03-02\n")
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/dates_save",
                            {"path": str(path), "dcol": "주문일",
                             "dparts": ["분기"]})
        self.assertIn("(날짜)", data["saved"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_age_adds_columns(self):
        path = self.csv("생일.csv",
                        "이름,생년월일\n가,1990-05-06\n나,900101-2345678\n"   # attools: ignore
                        "다,몰라\n")
        _, data = self.post("/api/sheet/age_preview",
                            {"path": str(path), "acol": "생년월일",
                             "aon": "2026-03-01", "agroup": True,
                             "asex": True})
        self.assertEqual(data["headers"][-3:],
                         ["생년월일 만나이", "생년월일 연령대", "생년월일 성별"])
        self.assertEqual(data["rows"][0][-3:], ["35", "30대", ""])
        self.assertEqual(data["rows"][1][-1], "여")
        self.assertEqual(data["failed"], [["4", "몰라"]])
        self.assertEqual(data["read"], 2)
        self.assertEqual(data["sexed"], 1)

    def test_age_needs_a_column(self):
        path = self.csv("생일.csv", "이름,생년월일\n가,1990-05-06\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/age_preview", {"path": str(path), "acol": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_age_save_leaves_the_original(self):
        path = self.csv("생일.csv", "이름,생년월일\n가,1990-05-06\n")
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/age_save",
                            {"path": str(path), "acol": "생년월일"})
        self.assertIn("(나이)", data["saved"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_ics_export(self):
        path = self.csv("일정.csv",
                        "일정,시작,끝,장소\n워크숍,2026-03-10,2026-03-12,양평\n"
                        "미정,언젠가,,\n")
        _, data = self.post("/api/sheet/ics_preview",
                            {"path": str(path), "ictitle": "일정",
                             "icstart": "시작", "icend": "끝",
                             "icplace": "장소"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["skipped"], [["3", "시작 날짜를 읽지 못했습니다"]])
        self.assertEqual(list(path.parent.glob("*.ics")), [])

        _, done = self.post("/api/sheet/ics_save",
                            {"path": str(path), "ictitle": "일정",
                             "icstart": "시작", "icend": "끝",
                             "icplace": "장소", "icalarm": "30"})
        body = Path(done["saved"]).read_text(encoding="utf-8")
        self.assertIn("SUMMARY:워크숍", body)
        self.assertIn("DTEND;VALUE=DATE:20260313", body)   # 그날까지
        self.assertIn("TRIGGER:-PT30M", body)

    def test_vcard_export(self):
        path = self.csv("거래처.csv",
                        "이름,회사,휴대전화\n홍길동,(주)가나,010-1\n,다라,010-2\n")
        _, data = self.post("/api/sheet/vcard_preview",
                            {"path": str(path), "vcname": "이름",
                             "vccompany": "회사", "vcmobile": "휴대전화"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["skipped"], [["3", "이름이 비었습니다"]])

        _, done = self.post("/api/sheet/vcard_save",
                            {"path": str(path), "vcname": "이름",
                             "vccompany": "회사", "vcmobile": "휴대전화"})
        body = Path(done["saved"]).read_text(encoding="utf-8")
        self.assertIn("FN:홍길동", body)
        self.assertIn("TEL;TYPE=CELL:010-1", body)

    def test_ics_needs_columns(self):
        path = self.csv("일정.csv", "일정,시작\n가,2026-03-10\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/ics_preview",
                      {"path": str(path), "ictitle": "일정", "icstart": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_mail_drafts(self):
        path = self.csv("정산.csv",
                        "이름,메일,금액\n홍길동,a@b.com,120000\n김철수,없음,5000\n")
        template = self.work / "본문.md"
        template.write_text("{이름}님, {금액:,}원입니다.\n", encoding="utf-8")
        body = {"path": str(path), "mltemplate": str(template),
                "mlsubject": "{이름}님 정산", "mlto": "메일"}

        _, data = self.post("/api/sheet/mail_preview", body)
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0][:2], ["a@b.com", "홍길동님 정산"])
        self.assertEqual(data["problems"][0][0], "3")
        self.assertIn("120,000원", data["first"])

        _, made = self.post("/api/sheet/mail_make", body)
        folder = Path(made["saved"])
        eml = list(folder.glob("*.eml"))
        self.assertEqual(len(eml), 1)
        self.assertIn("To: a@b.com", eml[0].read_text(encoding="utf-8"))

    def test_mail_needs_a_subject(self):
        path = self.csv("정산.csv", "이름,메일\n가,a@b.com\n")
        template = self.work / "본문.md"
        template.write_text("{이름}님\n", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/mail_preview",
                      {"path": str(path), "mltemplate": str(template),
                       "mlsubject": "", "mlto": "메일"})
        self.assertEqual(ctx.exception.code, 400)

    def test_mail_reports_unknown_placeholders(self):
        path = self.csv("정산.csv", "이름,메일\n가,a@b.com\n")
        template = self.work / "본문.md"
        template.write_text("{부서} 앞\n", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/mail_preview",
                      {"path": str(path), "mltemplate": str(template),
                       "mlsubject": "안내", "mlto": "메일"})
        self.assertEqual(ctx.exception.code, 400)

    def test_audit_collects_notes(self):
        path = self.csv("받은것.csv",
                        "상호,메일\n(주)가나,a@a.com\n주식회사 가나,b@a.com\n"
                        "다라,c@a.com\n")
        _, data = self.post("/api/sheet/audit", {"path": str(path)})
        kinds = {r[0] for r in data["rows"]}
        self.assertIn("개인정보", kinds)
        self.assertIn("표기 흔들림", kinds)
        self.assertTrue(data["looked"])          # 무엇을 봤는지 화면에도 준다

    def test_audit_on_a_clean_table(self):
        path = self.csv("깨끗.csv", "사번,이름\nE1,홍길동\nE2,김철수\n")
        _, data = self.post("/api/sheet/audit", {"path": str(path)})
        self.assertEqual(data["count"], 0)
        self.assertTrue(data["looked"])

    def test_chart_draws_svg(self):
        path = self.csv("매출.csv", "부서,금액\n영업,100\n개발,80\n영업,50\n")
        _, data = self.post("/api/sheet/chart",
                            {"path": str(path), "clabel": "부서",
                             "cvalue": "금액", "cunit": "원"})
        self.assertIn("<svg", data["svg"])
        self.assertEqual(data["rows"][0], ["영업", "150"])
        self.assertNotIn("saved", data)

    def test_chart_saves_an_svg_file(self):
        path = self.csv("매출.csv", "부서,금액\n영업,100\n")
        _, data = self.post("/api/sheet/chart",
                            {"path": str(path), "clabel": "부서",
                             "cvalue": "금액", "csave": True})
        saved = Path(data["saved"])
        self.assertEqual(saved.suffix, ".svg")
        self.assertIn("<svg", saved.read_text(encoding="utf-8"))

    def test_line_chart_needs_two_points(self):
        # 못 그리는 까닭을 그대로 전한다
        path = self.csv("한칸.csv", "부서,금액\n영업,100\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/chart",
                      {"path": str(path), "clabel": "부서", "cvalue": "금액",
                       "ckind": "line"})
        self.assertEqual(ctx.exception.code, 400)

    def test_chart_needs_numbers(self):
        path = self.csv("글자.csv", "부서,비고\n영업,가\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/chart",
                      {"path": str(path), "clabel": "부서", "cvalue": "비고"})
        self.assertEqual(ctx.exception.code, 400)

    def test_dday_counts_and_sorts(self):
        path = self.csv("일정.csv",
                        "일감,마감일\n최종,2026-12-25\n제안,2026-09-01\n미정,언젠가\n")
        _, data = self.post("/api/sheet/dday",
                            {"path": str(path), "ycol": "마감일",
                             "yon": "2026-09-07", "ysort": True})
        self.assertEqual(data["today"], "2026-09-07")
        self.assertEqual(data["rows"][0][0], "제안")     # 가까운 것부터
        self.assertEqual(data["rows"][-1][0], "미정")    # 못 읽은 것은 맨 뒤
        self.assertEqual(data["failed"], [["4", "언젠가"]])

    def test_dday_bad_reference_date(self):
        path = self.csv("일정.csv", "마감일\n2026-09-01\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/dday",
                      {"path": str(path), "ycol": "마감일", "yon": "언젠가"})
        self.assertEqual(ctx.exception.code, 400)

    def numbers(self):
        rows = "\n".join(str(v) for v in
                         [100, 105, 98, 102, 99, 101, 103, 97, 0, 100000])
        return self.csv("금액.csv", "금액\n" + rows + "\n")

    def test_outliers_finds_both_ends(self):
        _, data = self.post("/api/sheet/outliers",
                            {"path": str(self.numbers()), "ocol": "금액"})
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["counted"], 10)
        self.assertEqual({r[2] for r in data["rows"]}, {"높음", "낮음"})

    def test_outliers_says_when_there_is_too_little(self):
        path = self.csv("적은것.csv", "금액\n1\n2\n3\n")
        _, data = self.post("/api/sheet/outliers",
                            {"path": str(path), "ocol": "금액"})
        self.assertIn("말할 수 없습니다", data["note"])
        self.assertEqual(data["rows"], [])

    def test_replace_leaves_numbers_alone(self):
        path = self.csv("부서.csv", "부서,금액\n영업1팀,1000\n개발팀,2000\n")
        _, data = self.post("/api/sheet/replace_preview",
                            {"path": str(path), "rfind": "1000", "rto": "X"})
        self.assertEqual(data["changed"], 0)
        self.assertEqual(data["skipped"], 1)

    def test_replace_save_keeps_the_original(self):
        path = self.csv("부서.csv", "부서\n영업1팀\n")
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/replace_save",
                            {"path": str(path), "rfind": "영업1팀",
                             "rto": "세일즈1팀"})
        self.assertIn("(바꾼)", data["saved"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_replace_with_nothing_found(self):
        path = self.csv("부서.csv", "부서\n영업1팀\n")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/replace_save",
                      {"path": str(path), "rfind": "없는값", "rto": "가"})
        self.assertEqual(ctx.exception.code, 400)

    def merged(self):
        return self.csv("병합.csv",
                        "부서,이름,금액\n영업,홍길동,100\n,김철수,200\n"
                        "개발,이영희,300\n")

    def test_tidy_fills_and_totals(self):
        _, data = self.post("/api/sheet/tidy_preview",
                            {"path": str(self.merged()), "fcols": "부서",
                             "wanttotal": True, "tcols": "금액"})
        self.assertEqual([r[0] for r in data["rows"]],
                         ["영업", "영업", "개발", "합계"])
        self.assertEqual(data["rows"][-1][2], "600")
        self.assertEqual(len(data["steps"]), 2)

    def test_tidy_needs_something_to_do(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/tidy_preview",
                      {"path": str(self.merged()), "wanttotal": False})
        self.assertEqual(ctx.exception.code, 400)

    def test_tidy_unknown_column(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/tidy_preview",
                      {"path": str(self.merged()), "fcols": "없는열"})
        self.assertEqual(ctx.exception.code, 400)

    def test_tidy_save_leaves_the_original(self):
        path = self.merged()
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/tidy_save",
                            {"path": str(path), "fcols": "부서",
                             "wanttotal": True, "tkind": "avg"})
        self.assertIn("(정돈)", data["saved"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def months(self):
        last = self.csv("지난달.csv",
                        "사번,이름,연봉\nE1,홍길동,5000\nE2,김철수,4700\n")
        now = self.csv("이번달.csv",
                       "사번,이름,연봉\nE1,홍길동,5200\nE3,이영희,4900\n")
        return last, now

    def test_compare(self):
        last, now = self.months()
        _, data = self.post("/api/sheet/compare",
                            {"path": str(last), "other": str(now), "key": "사번"})
        self.assertEqual((data["added"], data["removed"], data["changed"]),
                         (1, 1, 1))
        self.assertFalse(data["same"])

    def test_compare_same_file(self):
        last, _now = self.months()
        _, data = self.post("/api/sheet/compare",
                            {"path": str(last), "other": str(last), "key": "사번"})
        self.assertTrue(data["same"])

    def test_compare_needs_a_key(self):
        last, now = self.months()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/compare",
                      {"path": str(last), "other": str(now)})
        self.assertEqual(ctx.exception.code, 400)

    def test_compare_unknown_key(self):
        last, now = self.months()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/compare",
                      {"path": str(last), "other": str(now), "key": "주문번호"})
        self.assertEqual(ctx.exception.code, 400)

    def test_merge_preview_writes_nothing(self):
        last, now = self.months()
        before = sorted(p.name for p in self.work.iterdir())
        _, data = self.post("/api/sheet/merge",
                            {"path": str(last), "other": str(now)})
        self.assertEqual(data["count"], 4)
        self.assertEqual(data["headers"][0], "출처")
        self.assertEqual(data["saved"], "")
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), before)

    def test_merge_save_keeps_both_originals(self):
        last, now = self.months()
        text = last.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/merge",
                            {"path": str(last), "other": str(now), "save": True})
        self.assertTrue(Path(data["saved"]).exists())
        self.assertEqual(last.read_text(encoding="utf-8"), text)
        self.assertTrue(now.exists())

    def staff(self):
        return self.csv("직원.csv",
                        "사번,이름,부서,연봉\nE1,홍길동,영업,5200\n"
                        "E2,김철수,개발,4700\nE3,이영희,개발,6100\n")

    def test_pick_filters_sorts_and_cuts(self):
        path = self.staff()
        _, data = self.post("/api/sheet/pick_preview",
                            {"path": str(path), "wcol": "부서", "wop": "eq",
                             "wval": "개발", "scol": "연봉", "desc": True,
                             "keep": "이름, 연봉"})
        self.assertEqual(data["headers"], ["이름", "연봉"])
        self.assertEqual(data["rows"], [["이영희", "6100"], ["김철수", "4700"]])
        self.assertEqual(len(data["steps"]), 3)

    def test_pick_command_covers_every_step(self):
        """한 줄로 적으면 정렬·열 고르기가 빠져 다른 결과가 된다."""
        path = self.staff()
        _, data = self.post("/api/sheet/pick_preview",
                            {"path": str(path), "wcol": "부서", "wop": "eq",
                             "wval": "개발", "scol": "연봉", "keep": "이름"})
        self.assertEqual(len(data["command"]), 3)
        self.assertIn("where", data["command"][0])
        self.assertIn("sort", data["command"][1])
        self.assertIn("cut", data["command"][2])

    def test_pick_unknown_column(self):
        path = self.staff()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/pick_preview",
                      {"path": str(path), "wcol": "없는열", "wop": "eq",
                       "wval": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_pick_save_refuses_empty_result(self):
        path = self.staff()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/pick_save",
                      {"path": str(path), "wcol": "부서", "wop": "eq",
                       "wval": "없는부서"})
        self.assertEqual(ctx.exception.code, 400)

    def test_pick_save_keeps_original(self):
        path = self.staff()
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/pick_save",
                            {"path": str(path), "wcol": "부서", "wop": "has",
                             "wval": "개"})
        self.assertTrue(Path(data["saved"]).exists())
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_search_across_files(self):
        self.csv("명단.csv", "사번,이름\nE1,홍길동\nE2,김철수\n")
        self.csv("평가.csv", "사번,평가\nE2,A\n")
        _, data = self.post("/api/sheet/search",
                            {"folder": str(self.work), "needle": "E2"})
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["rows"][0][2], "3")      # 머리글이 1행

    def test_search_needs_a_value(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/search", {"folder": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_search_missing_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/search",
                      {"folder": str(self.work / "없음"), "needle": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_sum_by_group(self):
        path = self.staff()
        _, data = self.post("/api/sheet/sum_preview",
                            {"path": str(path), "grows": "부서",
                             "agg": "sum", "gvalues": "연봉"})
        self.assertEqual(data["rows"], [["개발", "10800"], ["영업", "5200"]])

    def test_sum_count_needs_no_value_column(self):
        path = self.staff()
        _, data = self.post("/api/sheet/sum_preview",
                            {"path": str(path), "grows": "부서",
                             "agg": "count"})
        self.assertEqual(data["rows"], [["개발", "2"], ["영업", "1"]])

    def test_sum_says_what_is_missing(self):
        """합계인데 값 열이 없으면 0 을 내지 말고 무엇이 없는지 말한다."""
        path = self.staff()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/sum_preview",
                      {"path": str(path), "grows": "부서", "agg": "sum"})
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("값 열", payload["error"])

    def test_sum_needs_group_columns(self):
        path = self.staff()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/sum_preview", {"path": str(path)})
        self.assertEqual(ctx.exception.code, 400)

    def test_sum_save_keeps_original(self):
        path = self.staff()
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/sum_save",
                            {"path": str(path), "grows": "부서",
                             "agg": "count"})
        self.assertTrue(Path(data["saved"]).exists())
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_format_preview(self):
        path = self.csv("연락처.csv",
                        "이름,연락처\n홍길동,01012345678\n김철수,0100\n")
        _, data = self.post("/api/sheet/format_preview",
                            {"path": str(path), "specs": [["연락처", "전화"]]})
        self.assertEqual(data["rows"][0][1], "010-1234-5678")
        self.assertEqual(data["rows"][1][1], "0100")     # 모르는 것은 그대로
        self.assertEqual(data["left"][0][3], "규칙을 모름")

    def test_format_rejects_unknown_kind(self):
        path = self.csv()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/sheet/format_preview",
                      {"path": str(path), "specs": [["이름", "주민번호"]]})
        self.assertEqual(ctx.exception.code, 400)

    def test_format_rejects_broken_specs(self):
        path = self.csv()
        for specs in ([], "전화", [["이름"]], [[1, 2]]):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self.post("/api/sheet/format_preview",
                          {"path": str(path), "specs": specs})
            self.assertEqual(ctx.exception.code, 400)

    def test_format_save_keeps_original(self):
        path = self.csv("연락처.csv", "이름,연락처\n홍길동,01012345678\n")
        original = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/format_save",
                            {"path": str(path), "specs": [["연락처", "전화"]]})
        self.assertTrue(Path(data["saved"]).exists())
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_clean_preview_does_not_write(self):
        path = self.csv()
        before = sorted(p.name for p in self.work.iterdir())
        _, data = self.post("/api/sheet/clean_preview",
                            {"path": str(path), "dedupe": True})
        self.assertEqual(data["count"], 2)
        self.assertEqual(sorted(p.name for p in self.work.iterdir()), before)

    def test_clean_save_keeps_original(self):
        path = self.csv()
        original = path.read_text(encoding="utf-8")
        _, data = self.post("/api/sheet/clean_save",
                            {"path": str(path), "dedupe": True})
        saved = Path(data["saved"])
        self.assertTrue(saved.exists())
        self.assertNotEqual(saved, path)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_clean_save_twice_does_not_overwrite(self):
        path = self.csv()
        _, first = self.post("/api/sheet/clean_save", {"path": str(path)})
        _, second = self.post("/api/sheet/clean_save", {"path": str(path)})
        self.assertNotEqual(first["saved"], second["saved"])


class NovelAppTest(UiCase):
    """원고 화면. 읽기만 하므로 원고가 그대로인지도 본다."""

    def manuscript(self):
        root = self.work / "원고"
        root.mkdir()
        (root / "1화.txt").write_text(
            "리안은 문을 열었다. 리안은 말했다.\n\n"
            "\"어디 갔었어?\"\n\n하윤이 웃었다. 하윤이 대답했다.\n",
            encoding="utf-8")
        (root / "2화.txt").write_text(
            "리안이 떠났다. 그저 조용했다. 그저 아무 말도 없었다.\n\n"
            "\"괜찮아.\n", encoding="utf-8")
        return root

    def test_count(self):
        root = self.manuscript()
        _, data = self.post("/api/novel/count", {"path": str(root)})
        self.assertEqual(data["files"], 2)
        self.assertEqual(len(data["rows"]), 2)
        self.assertIn("합계", data["total"][0])

    def test_count_single_file(self):
        root = self.manuscript()
        _, data = self.post("/api/novel/count", {"path": str(root / "1화.txt")})
        self.assertEqual(data["files"], 1)

    def test_empty_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/novel/count", {"path": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_inspect_finds_unclosed_quote(self):
        root = self.manuscript()
        _, data = self.post("/api/novel/inspect", {"path": str(root)})
        self.assertEqual(data["quote_total"], 1)
        self.assertTrue(any("그저" in row[0] for row in data["adverbs"]))

    def test_cast_counts_people(self):
        root = self.manuscript()
        _, data = self.post("/api/novel/cast",
                            {"path": str(root), "min_count": "2"})
        found = {row[0] for row in data["rows"]}
        self.assertIn("리안", found)
        self.assertEqual(data["labels"], ["1화.txt", "2화.txt"])

    def test_cast_with_nothing_found(self):
        root = self.manuscript()
        _, data = self.post("/api/novel/cast",
                            {"path": str(root), "min_count": "99"})
        self.assertEqual(data["rows"], [])
        self.assertTrue(data["note"])

    def test_export_makes_a_new_file(self):
        root = self.manuscript()
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        _, data = self.post("/api/novel/export",
                            {"path": str(root), "format": "html",
                             "title": "시험작"})
        self.assertTrue(Path(data["saved"]).exists())
        for name, text in before.items():
            self.assertEqual((root / name).read_text(encoding="utf-8"), text)

    def test_export_every_format(self):
        root = self.manuscript()
        for kind in ("html", "epub", "docx", "md", "txt"):
            _, data = self.post("/api/novel/export",
                                {"path": str(root), "format": kind,
                                 "title": "시험작"})
            self.assertTrue(Path(data["saved"]).exists(), kind)

    def test_export_skips_earlier_exports(self):
        """투고본이 다음 투고본의 원고가 되면 안 된다."""
        root = self.manuscript()
        self.post("/api/novel/export",
                  {"path": str(root), "format": "md", "title": "시험작"})
        _, second = self.post("/api/novel/export",
                              {"path": str(root), "format": "txt",
                               "title": "시험작"})
        self.assertEqual(second["chapters"], 2)
        self.assertEqual(second["dropped"], 1)

    def test_export_rejects_unknown_format(self):
        root = self.manuscript()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/novel/export",
                      {"path": str(root), "format": "pdf"})
        self.assertEqual(ctx.exception.code, 400)

    def test_reading_does_not_change_files(self):
        root = self.manuscript()
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        for action in ("count", "inspect", "cast"):
            self.post("/api/novel/" + action, {"path": str(root)})
        after = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        self.assertEqual(before, after)


class LifeAppTest(UiCase):
    """일상 계산 화면. 숫자만 다루므로 파일은 만들지 않는다."""

    def test_dday(self):
        _, data = self.post("/api/life/dday",
                            {"date": "2026-03-15", "today": "2026-09-04"})
        self.assertIn("D+173", data["headline"])
        self.assertTrue(data["rows"])

    def test_dday_bad_date(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/dday", {"date": "언젠가"})
        self.assertEqual(ctx.exception.code, 400)

    def test_split(self):
        _, data = self.post("/api/life/split",
                            {"paid": "홍길동 84000\n김철수 12000\n이영희"})
        self.assertEqual(data["people"], 3)
        self.assertEqual(data["share"], "32,000원")
        self.assertEqual(len(data["moves"]), 2)

    def test_split_needs_people(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/split", {"paid": "  "})
        self.assertEqual(ctx.exception.code, 400)

    def test_loan_shrinks_long_schedule(self):
        _, data = self.post("/api/life/loan",
                            {"principal": "3억", "rate": "4", "months": "360"})
        self.assertEqual(len(data["rows"]), 24)
        self.assertEqual(data["skipped"], 336)

    def test_loan_rejects_long_grace(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/loan",
                      {"principal": "1000만", "months": "12", "grace": "24"})
        self.assertEqual(ctx.exception.code, 400)

    def test_unit(self):
        _, data = self.post("/api/life/unit", {"value": "84㎡"})
        self.assertEqual(data["group"], "넓이")
        self.assertTrue(any(row[0] == "평" for row in data["rows"]))

    def test_unit_unknown(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/unit", {"value": "몰라"})
        self.assertEqual(ctx.exception.code, 400)

    def test_vat_extract(self):
        _, data = self.post("/api/life/tax",
                            {"amount": "1100000", "mode": "extract"})
        self.assertEqual(data["rows"][0][1], "1,000,000원 (100만)")

    def test_withhold(self):
        _, data = self.post("/api/life/tax",
                            {"amount": "1000000", "mode": "withhold"})
        self.assertIn("실수령", data["headline"])

    def test_tax_rejects_unknown_mode(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/tax", {"amount": "1000", "mode": "훔치기"})
        self.assertEqual(ctx.exception.code, 400)

    def test_workday_add(self):
        _, data = self.post("/api/life/workday",
                            {"start": "2026-08-14", "target": "+5"})
        self.assertEqual(data["headline"], "2026-08-24(월)")

    def test_workday_between(self):
        _, data = self.post("/api/life/workday",
                            {"start": "2026-08-14", "target": "2026-08-31"})
        self.assertEqual(data["headline"], "11영업일")

    def test_workday_warns_about_lunar(self):
        """음력 명절은 계산하지 않는다. 조용히 빼놓지 않고 말한다."""
        _, data = self.post("/api/life/workday", {"start": "2026-08-14"})
        self.assertTrue(any("음력" in line for line in data["warning"]))

    def test_workday_bad_date(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/workday", {"start": "몰라"})
        self.assertEqual(ctx.exception.code, 400)

    def test_workday_refuses_huge_span(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/workday",
                      {"start": "2026-01-01", "target": "+99999"})
        self.assertEqual(ctx.exception.code, 400)

    def test_holidays(self):
        _, data = self.post("/api/life/holidays", {"year": "2026"})
        names = {row[2] for row in data["rows"]}
        self.assertIn("신정", names)
        self.assertTrue(any("대체공휴일" in n for n in names))

    def test_saving(self):
        _, data = self.post("/api/life/saving",
                            {"kind": "적금", "amount": "50만",
                             "months": "12", "rate": "3.5"})
        pairs = dict(data["rows"])
        self.assertEqual(pairs["원금 합계"], "6,000,000원 (600만)")
        self.assertIn("단리", data["note"])

    def test_saving_rejects_zero_months(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/saving", {"amount": "50만", "months": "0"})
        self.assertEqual(ctx.exception.code, 400)

    def test_rent_both_ways(self):
        _, to_monthly = self.post("/api/life/rent",
                                  {"deposit": "3억", "keep": "1억",
                                   "rate": "5.5"})
        self.assertIn("월세", to_monthly["headline"])
        _, to_deposit = self.post("/api/life/rent",
                                  {"monthly": "100만", "deposit": "1억",
                                   "rate": "5.5"})
        self.assertIn("보증금", to_deposit["headline"])

    def test_rent_refuses_bad_numbers(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/rent", {"deposit": "1억", "keep": "3억"})
        self.assertEqual(ctx.exception.code, 400)

    def test_worktime(self):
        _, data = self.post("/api/life/worktime",
                            {"spans": "09:00-18:30\n20:00-22:00",
                             "rest": "60", "rate": "12000"})
        self.assertEqual(data["headline"], "10시간 30분")
        pairs = dict(data["rows"])
        self.assertEqual(pairs["임금"], "126,000원")

    def test_worktime_bad_span(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/worktime", {"spans": "엉터리"})
        self.assertEqual(ctx.exception.code, 400)

    def test_won(self):
        _, data = self.post("/api/life/won", {"amount": "1250000"})
        self.assertEqual(data["korean"], "백이십오만")
        self.assertEqual(data["formal"], "일금 일백이십오만원정")


class LifeSeveranceTest(UiCase):
    """퇴직금 화면. 조건을 화면에서도 밝히는지까지 본다."""

    def test_amount_and_notes(self):
        _, data = self.post("/api/life/severance",
                            {"sjoined": "2021-03-02", "sleft": "2026-09-01",
                             "spay": "1500만"})
        self.assertIn("원", data["headline"])
        self.assertTrue(any("세전" in n for n in data["notes"]))
        self.assertTrue(any("퇴직소득세" in n for n in data["notes"]))

    def test_under_one_year_says_none(self):
        _, data = self.post("/api/life/severance",
                            {"sjoined": "2026-03-02", "sleft": "2026-09-01",
                             "spay": "900만"})
        self.assertEqual(data["headline"], "없음")
        self.assertTrue(any("1년 미만" in n for n in data["notes"]))

    def test_bad_dates(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/life/severance",
                      {"sjoined": "언제", "sleft": "2026-09-01", "spay": "100만"})
        self.assertEqual(ctx.exception.code, 400)


class TextAppTest(UiCase):
    """일괄 바꾸기 화면. 고친 뒤 되돌아오는지까지 본다."""

    def docs(self):
        root = self.work / "글"
        root.mkdir()
        (root / "1.md").write_text("리안은 웃었다.\n리안은 떠났다.\n",
                                   encoding="utf-8")
        (root / "2.md").write_text("하윤은 리안을 보았다.   \n", encoding="utf-8")
        (root / "메모.txt").write_text("리안\n", encoding="utf-8")
        return root

    def body(self, root, **extra):
        body = {"path": str(root), "glob": "*.md", "needle": "리안",
                "replacement": "리언"}
        body.update(extra)
        return body

    def test_preview_counts_hits(self):
        root = self.docs()
        _, data = self.post("/api/text/preview", self.body(root))
        self.assertEqual(data["count"], 2)      # txt 는 조건에서 빠진다
        self.assertEqual(data["hits"], 3)
        self.assertTrue(data["files"][0]["diff"])

    def test_find_does_not_write(self):
        root = self.docs()
        before = (root / "1.md").read_text(encoding="utf-8")
        _, data = self.post("/api/text/find", self.body(root))
        self.assertEqual(data["hits"], 3)
        self.assertEqual(data["files"], 2)
        self.assertEqual((root / "1.md").read_text(encoding="utf-8"), before)

    def test_find_needs_a_needle(self):
        root = self.docs()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/text/find", self.body(root, needle=""))
        self.assertEqual(ctx.exception.code, 400)

    def test_preview_does_not_write(self):
        root = self.docs()
        before = (root / "1.md").read_text(encoding="utf-8")
        self.post("/api/text/preview", self.body(root))
        self.assertEqual((root / "1.md").read_text(encoding="utf-8"), before)

    def test_apply_then_undo(self):
        root = self.docs()
        before = (root / "1.md").read_text(encoding="utf-8")
        _, data = self.post("/api/text/apply", self.body(root))
        self.assertEqual(data["applied"], 2)
        self.assertIn("리언", (root / "1.md").read_text(encoding="utf-8"))

        _, listed = self.post("/api/text/journals", {})
        self.assertEqual(len(listed["rows"]), 1)
        _, undone = self.post("/api/text/undo",
                              {"journal": listed["rows"][0][0]})
        self.assertEqual(undone["restored"], 2)
        self.assertEqual((root / "1.md").read_text(encoding="utf-8"), before)

    def test_apply_with_no_match(self):
        root = self.docs()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/text/apply", self.body(root, needle="없는말"))
        self.assertEqual(ctx.exception.code, 400)

    def test_trim_mode_needs_no_needle(self):
        root = self.docs()
        _, data = self.post("/api/text/preview",
                            {"path": str(root), "glob": "*.md", "mode": "trim"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["files"][0]["note"], "공백 정리")

    def test_bad_regex(self):
        root = self.docs()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/text/preview",
                      self.body(root, needle="(리안", regex=True))
        self.assertEqual(ctx.exception.code, 400)

    def test_needle_keeps_spaces(self):
        """공백까지 포함해 찾는 일이 있으므로 앞뒤를 다듬지 않는다."""
        root = self.docs()
        _, data = self.post("/api/text/preview",
                            self.body(root, needle="은 ", replacement="은씨 "))
        self.assertEqual(data["hits"], 3)

    def test_empty_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/text/preview",
                      {"path": str(self.work), "needle": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_undo_rejects_path_escape(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/text/undo", {"journal": "../../etc"})
        self.assertEqual(ctx.exception.code, 400)


class KeysAppTest(UiCase):
    """단축키 화면. 모르는 칸을 지어내지 않는지 본다."""

    def test_groups(self):
        _, data = self.post("/api/keys/groups", {})
        self.assertTrue(data["groups"])
        for group in data["groups"]:
            self.assertIn("unknown", group)

    def test_search(self):
        _, data = self.post("/api/keys/table", {"query": "찾기"})
        self.assertTrue(data["rows"])
        self.assertTrue(all("찾기" in row[0] or "찾" in row[0]
                            for row in data["rows"]))

    def test_unknown_group(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/keys/table", {"group": "없는그룹"})
        self.assertEqual(ctx.exception.code, 400)

    def test_gaps_lists_unconfirmed_cells(self):
        _, data = self.post("/api/keys/gaps", {})
        self.assertGreater(data["count"], 0)
        self.assertEqual(len(data["rows"][0]), 4)

    def test_gaps_can_be_narrowed_to_one_group(self):
        _, all_gaps = self.post("/api/keys/gaps", {})
        _, one = self.post("/api/keys/gaps", {"group": "os"})
        self.assertLess(one["count"], all_gaps["count"])

    def test_marks_are_kept_apart(self):
        """확인 못 한 칸(?)과 단축키가 없는 것(—)을 섞지 않는다."""
        _, data = self.post("/api/keys/table", {})
        marks = {cell for row in data["rows"] for cell in row[2:]}
        self.assertTrue(marks & {"?", "—"})
        self.assertNotIn("없음", marks)
        self.assertNotIn("", marks)


class DevAppTest(UiCase):
    """개발 잡일 화면. 읽고 계산만 한다."""

    def token(self, payload):
        import base64

        def part(obj):
            raw = json.dumps(obj).encode("utf-8")
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        return part({"alg": "HS256", "typ": "JWT"}) + "." + part(payload) + ".sig"

    def test_jwt(self):
        _, data = self.post("/api/dev/jwt",
                            {"token": self.token({"sub": "1", "exp": 1700000000})})
        self.assertIn("만료", data["state"])
        self.assertIn("HS256", data["header"])

    def test_jwt_garbage(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/jwt", {"token": "아무거나"})
        self.assertEqual(ctx.exception.code, 400)

    def test_when(self):
        _, data = self.post("/api/dev/when", {"value": "1735689600"})
        pairs = dict(data["rows"])
        self.assertEqual(pairs["epoch"], "1735689600")
        self.assertTrue(pairs["KST"].startswith("2025-01-01"))

    def test_cron(self):
        _, data = self.post("/api/dev/cron", {"expression": "0 9 * * 1-5"})
        self.assertIn("9시", data["describe"])
        self.assertEqual(len(data["rows"]), 8)
        for _when, weekday in data["rows"]:
            self.assertIn(weekday, "월화수목금")

    def test_cron_bad(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/cron", {"expression": "엉터리"})
        self.assertEqual(ctx.exception.code, 400)

    def test_mask(self):
        _, data = self.post("/api/dev/mask",
                            {"text": "연락처 010-1234-5678, token=abcdef123456"})
        self.assertNotIn("1234-5678", data["text"])
        self.assertEqual(data["found"], 2)

    def test_encode(self):
        _, data = self.post("/api/dev/encode", {"value": "가나"})
        pairs = dict(data["rows"])
        self.assertEqual(pairs["base64"], "6rCA64KY")

    def test_secret_length_and_count(self):
        _, data = self.post("/api/dev/secret",
                            {"kind": "pin", "length": "6", "count": "3"})
        self.assertEqual(len(data["values"]), 3)
        self.assertTrue(all(len(v) == 6 and v.isdigit() for v in data["values"]))

    def test_secret_rejects_unknown_kind(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/secret", {"kind": "개인키"})
        self.assertEqual(ctx.exception.code, 400)

    def log(self):
        path = self.work / "app.log"
        path.write_text(
            "2026-09-01 10:00:01 INFO GET /주문/12 200 45ms\n"
            "2026-09-01 10:00:02 ERROR 주문 3 조회 실패\n"
            "2026-09-01 10:00:03 ERROR 주문 7 조회 실패\n"
            "2026-09-01 10:00:04 INFO GET /주문/13 200 320ms\n",
            encoding="utf-8")
        return path

    def test_regex_with_groups(self):
        _, data = self.post("/api/dev/regex",
                            {"pattern": r"(\d{4})-(\d{2})-(\d{2})",
                             "text": "2026-03-15", "replace": r"\3/\2/\1"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["replaced"], "15/03/2026")

    def test_regex_bad_pattern(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/regex", {"pattern": "(", "text": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_regex_needs_text(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/regex", {"pattern": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_log_groups_repeated_errors(self):
        """숫자만 다른 에러는 한 무리로 묶어야 몇 번 났는지 보인다."""
        _, data = self.post("/api/dev/log", {"path": str(self.log())})
        self.assertEqual(dict(data["levels"])["ERROR"], "2")
        top = data["groups"][0]
        self.assertEqual((top[0], top[1]), ("ERROR", "2"))

    def test_log_route_timings(self):
        _, data = self.post("/api/dev/log", {"path": str(self.log())})
        self.assertEqual(len(data["routes"]), 1)
        self.assertEqual(data["routes"][0][1], "2")

    def test_log_empty_file(self):
        path = self.work / "빈.log"
        path.write_text("", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/log", {"path": str(path)})
        self.assertEqual(ctx.exception.code, 400)

    def sqlite(self):
        import sqlite3

        path = self.work / "가게.sqlite3"
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE 주문(번호 INTEGER, 이름 TEXT)")
        conn.execute("INSERT INTO 주문 VALUES (1, '홍길동')")
        conn.commit()
        conn.close()
        return path

    def test_db_lists_tables(self):
        _, data = self.post("/api/dev/db", {"path": str(self.sqlite())})
        self.assertEqual(data["names"], ["주문"])
        self.assertEqual(data["tables"][0][2], "1")

    def test_db_samples_a_table(self):
        _, data = self.post("/api/dev/db",
                            {"path": str(self.sqlite()), "table": "주문"})
        self.assertEqual(data["headers"], ["번호", "이름"])
        self.assertEqual(data["rows"], [["1", "홍길동"]])

    def test_db_refuses_writes(self):
        """읽기 전용으로 열지만, 무엇이 막혔는지 미리 말해 준다."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/db", {"path": str(self.sqlite()),
                                      "sql": "DELETE FROM 주문"})
        self.assertEqual(ctx.exception.code, 400)

    def test_db_rejects_other_files(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/db", {"path": str(self.log())})
        self.assertEqual(ctx.exception.code, 400)

    def test_depends(self):
        (self.work / "requirements.txt").write_text(
            "requests==2.31.0\nflask>=2\n", encoding="utf-8")
        _, data = self.post("/api/dev/depends", {"path": str(self.work)})
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["loose"], 1)          # flask 는 열려 있다

    def test_depends_missing_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/depends", {"path": str(self.work / "없음")})
        self.assertEqual(ctx.exception.code, 400)

    def test_depends_nothing_found(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/depends", {"path": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_lock_diff(self):
        def lock(name, version):
            path = self.work / name
            path.write_text(json.dumps(
                {"lockfileVersion": 3,
                 "packages": {"node_modules/react": {"version": version}}}),
                encoding="utf-8")
            return path

        _, data = self.post("/api/dev/locks",
                            {"before": str(lock("a.json", "18.2.0")),
                             "after": str(lock("b.json", "18.3.1"))})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0][0], "올림")

    def test_env_diff(self):
        (self.work / ".env.example").write_text("API_KEY=changeme\nDB=1\n",
                                                encoding="utf-8")
        (self.work / ".env").write_text("API_KEY=changeme\nEXTRA=2\n",
                                        encoding="utf-8")
        _, data = self.post("/api/dev/env",
                            {"example": str(self.work / ".env.example"),
                             "actual": str(self.work / ".env")})
        self.assertFalse(data["ok"])
        found = {name for _label, name in data["rows"]}
        self.assertEqual(found, {"DB", "API_KEY", "EXTRA"})


class DocAppTest(UiCase):
    """문서 화면. 고치는 동작은 백업이 남는지까지 본다."""

    def markdown(self):
        path = self.work / "문서.md"
        path.write_text(
            "# 제목\n\n<!-- toc -->\n<!-- /toc -->\n\n## 가\n\n"
            "[없는곳](#몰라)\n\n| a | bb |\n| --- | --- |\n| 1 | 2 |\n\n"
            "### 나\n", encoding="utf-8")
        return path

    def word(self, name="보고서.docx"):
        from attools import docx

        path = self.work / name
        docx.write_document(path, [docx.paragraph("첫 문단"),
                                   docx.table([["가", "나"], ["1", "2"]])])
        return path

    def test_from_docx_reads_paragraphs_and_tables(self):
        _, data = self.post("/api/doc/from_docx",
                            {"docx_path": str(self.word())})
        self.assertIn("첫 문단", data["text"])
        self.assertIn("| 가 | 나 |", data["text"])
        self.assertNotIn("saved", data)

    def test_from_docx_saves_beside_the_document(self):
        path = self.word()
        _, data = self.post("/api/doc/from_docx",
                            {"docx_path": str(path), "save": True})
        saved = Path(data["saved"])
        self.assertEqual(saved.parent, path.parent)
        self.assertTrue(saved.read_text(encoding="utf-8").startswith("첫 문단"))

    def test_from_docx_refuses_other_formats(self):
        other = self.work / "메모.md"
        other.write_text("# 가", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/from_docx", {"docx_path": str(other)})
        self.assertEqual(ctx.exception.code, 400)

    def test_from_docx_also_reads_hwpx(self):
        import zipfile

        path = self.work / "계획서.hwpx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/section0.xml",
                       "<hs:sec xmlns:hs='s' xmlns:hp='p'><hp:p><hp:run>"
                       "<hp:t>사업 계획서</hp:t></hp:run></hp:p></hs:sec>")
        _, data = self.post("/api/doc/from_docx", {"docx_path": str(path)})
        self.assertIn("사업 계획서", data["text"])
        self.assertIn("from-hwpx", data["command"])

    def test_doc_todo(self):
        folder = self.work / "회의록"
        folder.mkdir()
        (folder / "3월.md").write_text(
            "# 회의\n\n## 결정\n- [ ] 계약서 검토 @홍길동 2026-01-05\n"
            "- [x] 자료 취합\n- 그냥 메모\n", encoding="utf-8")

        _, data = self.post("/api/doc/todo", {"tdroot": str(folder)})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["late"], 1)
        self.assertEqual(data["rows"][0][2], "홍길동")

        _, mine = self.post("/api/doc/todo",
                            {"tdroot": str(folder), "tdwho": "김철수"})
        self.assertEqual(mine["count"], 0)
        _, every = self.post("/api/doc/todo",
                             {"tdroot": str(folder), "tdall": True})
        self.assertEqual(every["count"], 2)

    def test_doc_todo_needs_a_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/todo", {"tdroot": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_check_finds_dead_anchor(self):
        path = self.markdown()
        _, data = self.post("/api/doc/check", {"path": str(path)})
        self.assertFalse(data["clean"])
        self.assertEqual(data["rows"][0][0], "앵커 없음")
        self.assertEqual(len(data["headings"]), 3)

    def test_check_rejects_other_formats(self):
        path = self.work / "그림.png"
        path.write_bytes(b"x")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/check", {"path": str(path)})
        self.assertEqual(ctx.exception.code, 400)

    def test_from_html(self):
        _, data = self.post("/api/doc/from_html",
                            {"html": "<h1>제목</h1><ul><li>하나</li></ul>"})
        self.assertIn("# 제목", data["text"])
        self.assertIn("- 하나", data["text"])

    def test_from_html_needs_something(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/from_html", {"html": "   "})
        self.assertEqual(ctx.exception.code, 400)

    def test_from_html_empty_result(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/from_html", {"html": "<script>x=1</script>"})
        self.assertEqual(ctx.exception.code, 400)

    def test_terms(self):
        path = self.work / "용어.md"
        path.write_text("# 제목\n\nAPI 와 api 를 섞어 쓴다.\nAPI\n",
                        encoding="utf-8")
        _, data = self.post("/api/doc/terms", {"path": str(path)})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0][0], "대소문자")

    def test_images_finds_missing(self):
        png = self.work / "그림.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 4 + b"IHDR"
                        + (10).to_bytes(4, "big") + (20).to_bytes(4, "big")
                        + b"\x00" * 10)
        path = self.work / "그림문서.md"
        path.write_text("# 제목\n\n![](그림.png)\n\n![없음](없다.png)\n",
                        encoding="utf-8")
        _, data = self.post("/api/doc/images", {"path": str(path)})
        self.assertEqual((data["count"], data["missing"], data["no_alt"]),
                         (2, 1, 1))

    def test_images_none(self):
        path = self.markdown()
        _, data = self.post("/api/doc/images", {"path": str(path)})
        self.assertEqual(data["count"], 0)

    def test_toc_preview_does_not_write(self):
        path = self.markdown()
        before = path.read_text(encoding="utf-8")
        _, data = self.post("/api/doc/fix_preview",
                            {"path": str(path), "fix": "toc"})
        self.assertTrue(data["changed"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_toc_apply_leaves_backup(self):
        path = self.markdown()
        _, data = self.post("/api/doc/fix_apply",
                            {"path": str(path), "fix": "toc"})
        self.assertIn("- [가](#가)", path.read_text(encoding="utf-8"))
        self.assertTrue(data["journal"])
        _, listed = self.post("/api/text/journals", {})
        self.assertEqual(listed["rows"][0][0], data["journal"])

    def test_toc_without_marks_is_refused(self):
        path = self.work / "표시없음.md"
        path.write_text("# 제목\n\n## 가\n", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/fix_apply", {"path": str(path), "fix": "toc"})
        self.assertEqual(ctx.exception.code, 400)

    def test_table_fix(self):
        path = self.markdown()
        _, data = self.post("/api/doc/fix_preview",
                            {"path": str(path), "fix": "tables"})
        self.assertEqual(data["note"], "표 1개")

    def test_export_keeps_original(self):
        path = self.markdown()
        before = path.read_text(encoding="utf-8")
        for kind in ("html", "slides", "docx"):
            _, data = self.post("/api/doc/export",
                                {"path": str(path), "kind": kind})
            self.assertTrue(Path(data["saved"]).exists())
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_export_does_not_overwrite(self):
        path = self.markdown()
        _, first = self.post("/api/doc/export", {"path": str(path)})
        _, second = self.post("/api/doc/export", {"path": str(path)})
        self.assertNotEqual(first["saved"], second["saved"])


class JsonAppTest(UiCase):
    """JSON 화면. 붙여넣기와 파일 경로 둘 다 받는다."""

    SAMPLE = {"items": [{"id": 1, "name": "가", "tag": {"a": 1}},
                        {"id": 2, "name": "나"}]}

    def body(self):
        return json.dumps(self.SAMPLE, ensure_ascii=False)

    def file(self, name="응답.json", data=None):
        path = self.work / name
        path.write_text(json.dumps(data if data is not None else self.SAMPLE,
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def test_schema_marks_optional(self):
        _, data = self.post("/api/json/schema", {"body": self.body()})
        rows = {row[0]: row for row in data["rows"]}
        self.assertEqual(rows["items[].tag"][2], "예")
        self.assertEqual(rows["items[].id"][2], "")

    def test_schema_from_file(self):
        path = self.file()
        _, data = self.post("/api/json/schema", {"body_path": str(path)})
        self.assertEqual(data["name"], str(path))

    def test_broken_json(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/json/schema", {"body": "{망가진"})
        self.assertEqual(ctx.exception.code, 400)

    def test_nothing_given(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/json/schema", {})
        self.assertEqual(ctx.exception.code, 400)

    def test_flatten(self):
        _, data = self.post("/api/json/flatten", {"body": self.body()})
        self.assertEqual(data["headers"], ["id", "name", "tag.a"])
        self.assertEqual(data["count"], 2)

    def test_save_next_to_source(self):
        path = self.file()
        _, first = self.post("/api/json/save",
                             {"body_path": str(path), "format": ".csv"})
        self.assertEqual(Path(first["saved"]).parent, self.work)
        _, second = self.post("/api/json/save",
                              {"body_path": str(path), "format": ".csv"})
        self.assertNotEqual(first["saved"], second["saved"])

    def test_types(self):
        _, data = self.post("/api/json/types",
                            {"body": self.body(), "lang": "typescript"})
        self.assertIn("interface", data["code"])

    def test_types_rejects_unknown_language(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/json/types", {"body": self.body(), "lang": "코볼"})
        self.assertEqual(ctx.exception.code, 400)

    def test_compare_counts_breaking(self):
        after = {"items": [{"id": 1, "name": "가"}, {"id": 3, "name": "다"}]}
        _, data = self.post("/api/json/compare",
                            {"before": self.body(),
                             "after": json.dumps(after, ensure_ascii=False),
                             "key": "id"})
        self.assertFalse(data["same"])
        self.assertEqual(data["breaking"], 2)

    def test_compare_same(self):
        _, data = self.post("/api/json/compare",
                            {"before": self.body(), "after": self.body()})
        self.assertTrue(data["same"])


class GitAppTest(UiCase):
    """저장소 화면. 읽기만 하는지, 저장소가 아닐 때 말이 되는지 본다."""

    def repo(self):
        import subprocess

        root = self.work / "저장소"
        root.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@e.c"],
                     ["config", "user.name", "테스터"]):
            subprocess.run(["git", *args], cwd=root, capture_output=True)
        (root / "코드.py").write_text(
            "# TODO(홍길동): 캐시 붙이기\nkey = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: 첫 커밋"],
                       cwd=root, capture_output=True)
        return root

    def test_not_a_repo(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/git/scan", {"path": str(self.work)})
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/git/scan", {"path": str(self.work / "없음")})
        self.assertEqual(ctx.exception.code, 400)

    def test_scan(self):
        root = self.repo()
        _, data = self.post("/api/git/scan", {"path": str(root)})
        self.assertEqual(data["root"], str(root))
        self.assertIn("눈으로", data["note"])

    def test_branches_does_not_delete(self):
        root = self.repo()
        import subprocess

        before = subprocess.run(["git", "branch"], cwd=root,
                                capture_output=True, text=True).stdout
        self.post("/api/git/branches", {"path": str(root)})
        after = subprocess.run(["git", "branch"], cwd=root,
                               capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_todos(self):
        root = self.repo()
        _, data = self.post("/api/git/todos", {"path": str(root)})
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["rows"][0][0], "TODO")
        self.assertEqual(data["rows"][0][4], "홍길동")

    def test_todo_text_has_no_newline(self):
        root = self.repo()
        (root / "긴.py").write_text('x = """\n# TODO: 여러\n줄\n"""\n',
                                    encoding="utf-8")
        _, data = self.post("/api/git/todos", {"path": str(root)})
        for row in data["rows"]:
            self.assertNotIn("\n", row[3])

    def test_ready_needs_staged_files(self):
        root = self.repo()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/git/ready", {"path": str(root)})
        self.assertEqual(ctx.exception.code, 400)

    def test_ready_finds_debug_marks(self):
        """이번에 더한 줄에서만 찾는다. 원래 있던 줄까지 세면 못 본다."""
        import subprocess

        root = self.repo()
        (root / "코드.js").write_text("console.log('여기')\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        _, data = self.post("/api/git/ready", {"path": str(root)})
        self.assertEqual(data["staged"], 1)
        self.assertEqual(data["rows"][0][0], "디버그 흔적")

    def test_ready_clean(self):
        import subprocess

        root = self.repo()
        (root / "깨끗.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        _, data = self.post("/api/git/ready", {"path": str(root)})
        self.assertEqual(data["count"], 0)

    def test_release_draft(self):
        import subprocess

        root = self.repo()
        (root / "새것.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: 새 기능"],
                       cwd=root, capture_output=True)
        _, data = self.post("/api/git/release",
                            {"path": str(root), "title": "v0.1"})
        self.assertGreater(data["count"], 0)
        self.assertIn("## v0.1", data["text"])
        self.assertIn("새 기능", data["text"])

    def test_conflicts(self):
        root = self.repo()
        _, data = self.post("/api/git/conflicts", {"path": str(root)})
        self.assertEqual(data["total"], 0)

    def test_stats(self):
        root = self.repo()
        _, data = self.post("/api/git/stats",
                            {"path": str(root), "since": "10 years ago"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["authors"][0][0], "테스터")


class DocMergeAndGitHistoryTest(UiCase):
    """새로 붙인 두 카드. 서버 쪽 판단이 터미널과 같은지 본다."""

    def pieces(self):
        room = self.work / "장"
        room.mkdir(exist_ok=True)
        (room / "01.md").write_text("# 하나\n\n첫\n", encoding="utf-8")
        (room / "02.md").write_text("# 둘\n\n둘째\n", encoding="utf-8")
        return room

    def test_merge_shifts_headings(self):
        _, data = self.post("/api/doc/merge",
                            {"mfolder": str(self.pieces()), "mshift": "1",
                             "mtitle": "합본"})
        self.assertTrue(data["text"].startswith("# 합본"))
        self.assertIn("## 하나", data["text"])
        self.assertEqual(data["count"], 2)
        self.assertNotIn("saved", data)

    def test_merge_saves_beside_the_folder(self):
        room = self.pieces()
        _, data = self.post("/api/doc/merge",
                            {"mfolder": str(room), "msave": True})
        saved = Path(data["saved"])
        self.assertEqual(saved.parent, room.parent)

    def test_merge_needs_two_files(self):
        room = self.work / "하나만"
        room.mkdir(exist_ok=True)
        (room / "01.md").write_text("# 하나\n", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/doc/merge", {"mfolder": str(room)})
        self.assertEqual(ctx.exception.code, 400)

    def repo(self):
        import subprocess

        root = self.work / "저장소"
        root.mkdir(exist_ok=True)
        run = lambda *args: subprocess.run(["git", *args], cwd=root,
                                           capture_output=True, text=True)
        run("init", "-q")
        run("config", "user.email", "t@e.c")
        run("config", "user.name", "테스터")
        (root / "가.py").write_text("x = 1\n", encoding="utf-8")
        run("add", "-A")
        run("commit", "-q", "-m", "처음")
        return root

    def test_history_lists_commits(self):
        root = self.repo()
        _, data = self.post("/api/git/history",
                            {"path": str(root), "hfile": "가.py"})
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["rows"][0][4], "처음")
        self.assertEqual(data["people"], ["테스터"])

    def test_history_needs_a_file(self):
        root = self.repo()
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/git/history", {"path": str(root), "hfile": ""})
        self.assertEqual(ctx.exception.code, 400)

    def test_history_of_an_untracked_file(self):
        root = self.repo()
        (root / "새것.py").write_text("x", encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/git/history", {"path": str(root), "hfile": "새것.py"})
        self.assertEqual(ctx.exception.code, 400)


class LettersAppTest(UiCase):
    """글자 손질 화면. 파일이 아니라 붙여넣은 글만 다룬다."""

    def test_kbd_to_hangul(self):
        _, data = self.post("/api/letters/kbd", {"text": "dkssudgktpdy"})
        self.assertEqual(data["text"], "안녕하세요")
        self.assertIsNone(data["both"])

    def test_kbd_to_qwerty(self):
        _, data = self.post("/api/letters/kbd", {"text": "안녕하세요"})
        self.assertEqual(data["text"], "dkssudgktpdy")

    def test_kbd_mixed_shows_both(self):
        """어느 쪽인지 모를 때 한쪽을 고르면 나머지 절반이 망가진다."""
        _, data = self.post("/api/letters/kbd", {"text": "안녕 hi"})
        self.assertEqual(data["text"], "")
        self.assertEqual(data["both"]["en"], "dkssud hi")

    def test_kbd_forced_direction(self):
        _, data = self.post("/api/letters/kbd",
                            {"text": "안녕 hi", "to": "en"})
        self.assertEqual(data["text"], "dkssud hi")

    def test_empty_text(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/letters/kbd", {"text": "   "})
        self.assertEqual(ctx.exception.code, 400)

    def test_typo(self):
        _, data = self.post("/api/letters/typo", {"text": "몇일 뒤에 할께"})
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["fixed"], "며칠 뒤에 할게")

    def test_typo_clean_text(self):
        _, data = self.post("/api/letters/typo", {"text": "며칠 뒤에 할게"})
        self.assertEqual(data["total"], 0)

    def test_wrap(self):
        body = "한글 문장을 이렇게 길게 쓰면 화면에서 읽기가 어렵다. 그래서 접는다."
        _, data = self.post("/api/letters/wrap",
                            {"text": body, "width": "20"})
        self.assertGreater(len(data["text"].splitlines()), 1)

    def test_wrap_width_is_checked(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/letters/wrap", {"text": "가나다", "width": "1"})
        self.assertEqual(ctx.exception.code, 400)

    def test_table_from_tsv(self):
        """엑셀에서 복사하면 탭으로 나뉘어 붙는다."""
        _, data = self.post("/api/letters/table",
                            {"text": "이름\t부서\n홍길동\t영업\n"})
        self.assertIn("| 이름 | 부서 |", data["text"])
        self.assertEqual((data["count"], data["columns"]), (1, 2))

    def test_table_from_csv(self):
        _, data = self.post("/api/letters/table",
                            {"text": "이름,부서\n홍길동,영업\n"})
        self.assertIn("| 홍길동 | 영업 |", data["text"])

    def test_table_needs_two_lines(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/letters/table", {"text": "머리글만"})
        self.assertEqual(ctx.exception.code, 400)

    def test_pick(self):
        _, data = self.post("/api/letters/pick",
                            {"text": "hong@a.co 010-1234-5678 1,000원"})
        self.assertEqual(data["count"], 3)
        self.assertEqual({row[0] for row in data["rows"]},
                         {"이메일", "휴대폰", "금액"})

    def test_pick_unknown_kind(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/letters/pick",
                      {"text": "아무거나", "kinds": "주민번호"})
        self.assertEqual(ctx.exception.code, 400)

    def test_normalize(self):
        import unicodedata

        _, data = self.post("/api/letters/normalize",
                            {"text": unicodedata.normalize("NFD", "한글")})
        self.assertEqual(data["text"], "한글")
        self.assertTrue(data["decomposed"])


class FileSizeGuardTest(UiCase):
    """화면은 파일을 통째로 읽는다. 큰 파일에 서버가 멎지 않아야 한다."""

    def big(self, name, size):
        path = self.work / name
        with path.open("wb") as fh:
            fh.truncate(size)
        return path

    def test_log_has_its_own_limit(self):
        path = self.big("큰.log", 25 << 20)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/dev/log", {"path": str(path)})
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertIn("너무 큽니다", payload["error"])

    def test_json_uses_the_shared_limit(self):
        path = self.big("큰.json", 70 << 20)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/json/schema", {"body_path": str(path)})
        self.assertEqual(ctx.exception.code, 400)

    def test_normal_files_pass(self):
        path = self.work / "작은.log"
        path.write_text("2026-09-01 10:00:01 INFO 시작\n", encoding="utf-8")
        status, _ = self.post("/api/dev/log", {"path": str(path)})
        self.assertEqual(status, 200)


class RecentTest(UiCase):
    """최근에 넣은 경로 기억. 화면은 실행마다 포트가 달라 서버에 둔다."""

    def test_starts_empty(self):
        _, data = self.post("/api/-/recent", {"app": "files"})
        self.assertEqual(data["fields"], {})

    def test_remembers_newest_first(self):
        for value in ("~/다운로드", "~/사진", "~/다운로드"):
            self.post("/api/-/remember",
                      {"app": "files", "field": "path", "value": value})
        _, data = self.post("/api/-/recent", {"app": "files"})
        self.assertEqual(data["fields"]["path"], ["~/다운로드", "~/사진"])

    def test_keeps_only_a_few(self):
        for n in range(10):
            self.post("/api/-/remember",
                      {"app": "files", "field": "path", "value": f"/폴더{n}"})
        _, data = self.post("/api/-/recent", {"app": "files"})
        self.assertEqual(len(data["fields"]["path"]), 5)

    def test_screens_are_kept_apart(self):
        self.post("/api/-/remember",
                  {"app": "files", "field": "path", "value": "/가"})
        _, data = self.post("/api/-/recent", {"app": "sheet"})
        self.assertEqual(data["fields"], {})

    def test_unknown_screen(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/-/recent", {"app": "없는화면"})
        self.assertEqual(ctx.exception.code, 400)

    def test_bad_field_name(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/-/remember",
                      {"app": "files", "field": "../탈출", "value": "x"})
        self.assertEqual(ctx.exception.code, 400)

    def test_broken_store_does_not_break_the_screen(self):
        """망가진 기록 파일 때문에 화면이 안 뜨면 안 된다."""
        store = self.home / ".attools" / "ui-recent.json"
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("{망가짐", encoding="utf-8")
        _, data = self.post("/api/-/recent", {"app": "files"})
        self.assertEqual(data["fields"], {})

    def test_browse_lists_folders_and_files(self):
        (self.work / "안쪽").mkdir()
        (self.work / "가.txt").write_text("x", encoding="utf-8")
        (self.work / ".숨김").write_text("x", encoding="utf-8")
        _, data = self.post("/api/-/browse", {"path": str(self.work)})
        self.assertEqual(data["dirs"], ["안쪽"])
        self.assertEqual(data["files"], ["가.txt"])       # 숨김은 빼고
        self.assertEqual(data["here"], str(self.work))
        self.assertTrue(data["parent"])

    def test_browse_shows_hidden_when_asked(self):
        (self.work / ".숨김").write_text("x", encoding="utf-8")
        _, data = self.post("/api/-/browse",
                            {"path": str(self.work), "hidden": True})
        self.assertIn(".숨김", data["files"])

    def test_browse_from_a_file_shows_its_folder(self):
        path = self.work / "가.txt"
        path.write_text("x", encoding="utf-8")
        _, data = self.post("/api/-/browse", {"path": str(path)})
        self.assertEqual(data["here"], str(self.work))

    def test_browse_missing_folder(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/-/browse", {"path": str(self.work / "없음")})
        self.assertEqual(ctx.exception.code, 400)

    def test_browse_needs_no_screen(self):
        """폴더 훑기는 어느 화면에서 부르든 같다."""
        status, data = self.post("/api/-/browse", {"path": str(self.work)})
        self.assertEqual(status, 200)
        self.assertIn("here", data)

    def test_tables_offer_a_csv_button(self):
        """표는 어느 화면에서든 csv 로 내려받을 수 있어야 한다."""
        _status, body = self.get("/keys?t=" + self.run.token)
        self.assertIn('button.csv', body)          # 눌렀을 때의 처리
        self.assertIn('class="csv"', body)         # 표에 붙는 단추

    def test_javascript_keeps_its_backslashes(self):
        """공용 JS 는 raw 문자열이어야 정규식이 살아남는다."""
        from attools.webui import assets

        self.assertIn(r"replace(/\r?\n/g", assets.JS)
        self.assertNotIn("\r", assets.JS.replace(r"\r", ""))

    def test_page_defines_at_before_body_scripts(self):
        """본문 스크립트가 불러오자마자 AT 를 쓰는 화면이 있다."""
        _status, body = self.get("/files?t=" + self.run.token)
        self.assertLess(body.index("window.AT"), body.index("<main>"))


class LauncherTest(UiCase):
    """런처. 화면이 열두 개라 찾을 수 있어야 한다."""

    def launcher(self):
        """UiCase 의 self.home 은 임시 홈 경로라 이름을 겹치지 않게 둔다."""
        import urllib.request

        req = urllib.request.Request(self.base + "/?t=" + self.run.token)
        with urllib.request.urlopen(req) as res:
            return res.status, res.read().decode("utf-8")

    def test_every_screen_is_listed_with_search_words(self):
        from attools import webui

        status, body = self.launcher()
        self.assertEqual(status, 200)
        self.assertEqual(body.count('data-find="'), len(webui.load_apps()))
        self.assertIn('id="q"', body)          # 무엇을 하고 싶은지로 거른다

    def test_search_words_include_aliases(self):
        _status, body = self.launcher()
        self.assertIn("엑셀", body)            # sheet 화면의 별명
        self.assertIn("취합", body)            # 요약에 들어 있는 말

class BrowserCheckTest(unittest.TestCase):
    """화면 점검. 브라우저가 없는 곳에서도 이 시험은 돌아야 한다."""

    def test_finds_nothing_when_pointed_at_a_missing_file(self):
        import os

        from attools.webui import check

        previous = os.environ.get(check.BROWSER_ENV)
        os.environ[check.BROWSER_ENV] = "/없는/자리/chrome"
        try:
            self.assertIsNone(check.find_browser())
        finally:
            if previous is None:
                os.environ.pop(check.BROWSER_ENV, None)
            else:
                os.environ[check.BROWSER_ENV] = previous

    def test_console_lines_are_picked_and_noise_dropped(self):
        from attools.webui import check

        self.assertTrue(check.CONSOLE.search(
            '[1:1:INFO:CONSOLE:12] "Uncaught SyntaxError: x"'))
        self.assertTrue(check.NOISE.search(
            "[1:1:ERROR:dbus/bus.cc:408] Failed to connect to the bus"))

    def test_missing_browser_is_reported_not_crashed(self):
        """못 연 것과 열었는데 오류가 있는 것은 다르게 센다."""
        from attools.webui import check

        messages, trouble = check.check_page("/없는/자리/chrome",
                                             "http://127.0.0.1:1/")
        self.assertEqual(messages, [])
        self.assertIn("실행하지 못했습니다", trouble)

    def test_timeout_is_trouble_not_an_error(self):
        import shutil
        import tempfile

        from attools.webui import check

        root = tempfile.mkdtemp()
        try:
            slow = pathlib.Path(root) / "느린브라우저.sh"
            slow.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
            slow.chmod(0o755)
            messages, trouble = check.check_page(str(slow),
                                                 "http://127.0.0.1:1/",
                                                 timeout=0.3)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(messages, [])
        self.assertIn("끝나지 않았습니다", trouble)

    def test_screen_check_ok_flag(self):
        from attools.webui import check

        self.assertTrue(check.ScreenCheck("a", "가").ok)
        self.assertFalse(check.ScreenCheck("a", "가", trouble="느림").ok)
        self.assertFalse(check.ScreenCheck("a", "가", messages=["x"]).ok)

    def test_cli_says_so_without_a_browser(self):
        import contextlib
        import io
        import os

        from attools import cli
        from attools.webui import check

        previous = os.environ.get(check.BROWSER_ENV)
        os.environ[check.BROWSER_ENV] = "/없는/자리/chrome"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cli.main(["ui", "--check"])
        finally:
            if previous is None:
                os.environ.pop(check.BROWSER_ENV, None)
            else:
                os.environ[check.BROWSER_ENV] = previous
        # 못 연 것(2)과 자바스크립트 오류(1)를 부르는 쪽이 구분할 수 있어야
        # CI 가 «환경이 안 돼서 못 봄»을 실패로 세지 않는다.
        self.assertEqual(code, 2)
        self.assertIn("찾지 못했습니다", out.getvalue())


class CommandHintTest(UiCase):
    """화면이 보여 주는 터미널 명령이 실제로 되는 명령이어야 한다."""

    def accepts(self, command):
        """진짜 파서에 걸어 본다. 안내만 그럴듯하고 안 되면 더 나쁘다."""
        import shlex

        from attools import cli

        parts = shlex.split(command)
        self.assertEqual(parts[0], "at", command)
        cli.build_parser().parse_args(parts[1:])

    def test_file_commands(self):
        (self.work / "가.txt").write_text("내용", encoding="utf-8")
        for body in ({"path": str(self.work), "mode": "ext", "recursive": True},
                     {"path": str(self.work), "mode": "photo-month",
                      "mtime": True},
                     {"path": str(self.work), "mode": "fixname"},
                     {"path": str(self.work), "mode": "date-ext",
                      "hidden": True, "fixname": True}):
            _, data = self.post("/api/files/preview", body)
            self.accepts(data["command"])

    def test_files_scrub_command(self):
        import zipfile

        path = self.work / "계획서.docx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("docProps/core.xml",
                       "<cp:coreProperties xmlns:cp='c' xmlns:dc='d'>"
                       "<dc:creator>김철수</dc:creator></cp:coreProperties>")
            z.writestr("word/document.xml", "<x/>")
        _, docs = self.post("/api/files/documents", {"docroot": str(self.work)})
        self.accepts(docs["command"])
        _, plan = self.post("/api/files/scrub_preview",
                            {"docroot": str(self.work)})
        self.accepts(plan["command"])
        _, done = self.post("/api/files/scrub_apply",
                            {"docroot": str(self.work)})
        self.accepts(done["command"])

        _, shot = self.post("/api/files/pdf_preview",
                            {"pdfroot": str(self.work), "pdfpage": "letter",
                             "pdfmargin": True})
        self.accepts(shot["command"])

        _, shot = self.post("/api/files/photos", {"photoroot": str(self.work)})
        self.accepts(shot["command"])

    def test_text_commands(self):
        (self.work / "가.md").write_text("리안\n", encoding="utf-8")
        for body in ({"path": str(self.work), "needle": "리안",
                      "replacement": "리언", "glob": "*.md",
                      "ignore_case": True, "regex": True},
                     {"path": str(self.work), "mode": "trim"},
                     {"path": str(self.work), "mode": "crlf"}):
            _, data = self.post("/api/text/preview", body)
            self.accepts(data["command"])

    def test_files_audit_command(self):
        (self.work / "가.txt").write_text("내용", encoding="utf-8")
        _, data = self.post("/api/files/audit",
                            {"aroot": str(self.work), "ahidden": True})
        self.accepts(data["command"])

    def test_files_pack_command(self):
        import os

        (self.work / "가.bin").write_bytes(os.urandom(1_000))
        _, data = self.post("/api/files/pack_preview",
                            {"packroot": str(self.work), "packmax": "1MB",
                             "packglob": "*.bin"})
        self.accepts(data["command"])

    def test_apply_shows_how_to_undo(self):
        (self.work / "가.txt").write_text("내용", encoding="utf-8")
        _, data = self.post("/api/files/apply",
                            {"path": str(self.work), "mode": "ext"})
        self.assertEqual(data["command"], "at file undo")
        self.accepts(data["command"])

    def test_sheet_pivot_command(self):
        path = self.work / "직원.csv"
        path.write_text("부서,연봉\n개발,4700\n영업,5200\n", encoding="utf-8")
        _, data = self.post("/api/sheet/sum_preview",
                            {"path": str(path), "grows": "부서",
                             "agg": "sum", "gvalues": "연봉"})
        self.accepts(data["command"])

    def test_sheet_mask_and_collect_commands(self):
        path = self.work / "명단.csv"
        path.write_text("이름,연락처\n홍길동,010-1234-5678\n", encoding="utf-8")
        _, masked = self.post("/api/sheet/mask_save",
                              {"path": str(path),
                               "mspecs": [["이름", "이름"], ["연락처", "전화"]]})
        self.accepts(masked["command"])

        room = self.work / "제출"
        room.mkdir(exist_ok=True)
        (room / "가.csv").write_text("제목,3월\n\n담당자,홍길동\n",
                                     encoding="utf-8")
        _, got = self.post("/api/sheet/collect_preview",
                           {"cfolder": str(room), "cells": "B3=담당자",
                            "cglob": "*.csv"})
        self.accepts(got["command"])

    def test_sheet_chart_and_dday_commands(self):
        path = self.work / "매출.csv"
        path.write_text("부서,금액,마감일\n영업,100,2026-09-01\n",
                        encoding="utf-8")
        _, drawn = self.post("/api/sheet/chart",
                             {"path": str(path), "clabel": "부서",
                              "cvalue": "금액", "cunit": "원"})
        self.accepts(drawn["command"])
        _, left = self.post("/api/sheet/dday",
                            {"path": str(path), "ycol": "마감일",
                             "yon": "2026-09-07", "ysort": True})
        self.accepts(left["command"])

    def test_sheet_audit_command(self):
        path = self.work / "받은것.csv"
        path.write_text("사번,이름\nE1,홍길동\n", encoding="utf-8")
        _, data = self.post("/api/sheet/audit", {"path": str(path)})
        self.accepts(data["command"])

    def test_sheet_outliers_and_replace_commands(self):
        path = self.work / "금액.csv"
        path.write_text("금액,부서\n" + "\n".join(
            f"{v},영업1팀" for v in [100, 105, 98, 102, 99, 101, 103, 97, 0]) + "\n",
            encoding="utf-8")
        _, found = self.post("/api/sheet/outliers",
                             {"path": str(path), "ocol": "금액",
                              "omethod": "sigma", "ofactor": "2"})
        self.accepts(found["command"])
        _, changed = self.post("/api/sheet/replace_preview",
                               {"path": str(path), "rfind": "영업1팀",
                                "rto": "세일즈1팀", "rcols": "부서",
                                "rexact": True})
        self.accepts(changed["command"])

    def test_sheet_dates_command(self):
        path = self.work / "주문.csv"
        path.write_text("주문일\n2026-03-02\n", encoding="utf-8")
        _, data = self.post("/api/sheet/dates_preview",
                            {"path": str(path), "dcol": "주문일",
                             "dparts": ["요일", "주차"]})
        self.accepts(data["command"])

    def test_sheet_export_commands(self):
        path = self.work / "일정.csv"
        path.write_text("일정,시작,장소\n워크숍,2026-03-10,양평\n",
                        encoding="utf-8")
        _, data = self.post("/api/sheet/ics_preview",
                            {"path": str(path), "ictitle": "일정",
                             "icstart": "시작", "icplace": "장소",
                             "icalarm": "30"})
        self.accepts(data["command"])
        _, saved = self.post("/api/sheet/ics_save",
                             {"path": str(path), "ictitle": "일정",
                              "icstart": "시작"})
        self.accepts(saved["command"])

        cards = self.work / "거래처.csv"
        cards.write_text("이름,회사\n홍길동,(주)가나\n", encoding="utf-8")
        _, vc = self.post("/api/sheet/vcard_preview",
                          {"path": str(cards), "vcname": "이름",
                           "vccompany": "회사"})
        self.accepts(vc["command"])

    def test_sheet_mail_command(self):
        path = self.work / "정산.csv"
        path.write_text("이름,메일\n홍길동,a@b.com\n", encoding="utf-8")
        template = self.work / "본문.md"
        template.write_text("{이름}님\n", encoding="utf-8")
        _, data = self.post("/api/sheet/mail_preview",
                            {"path": str(path), "mltemplate": str(template),
                             "mlsubject": "{이름}님 안내", "mlto": "메일"})
        self.accepts(data["command"])
        _, made = self.post("/api/sheet/mail_make",
                            {"path": str(path), "mltemplate": str(template),
                             "mlsubject": "{이름}님 안내", "mlto": "메일"})
        self.accepts(made["command"])

    def test_sheet_age_command(self):
        path = self.work / "생일.csv"
        path.write_text("이름,생년월일\n가,1990-05-06\n", encoding="utf-8")
        _, data = self.post("/api/sheet/age_preview",
                            {"path": str(path), "acol": "생년월일",
                             "aon": "2026-03-01", "agroup": True,
                             "asex": True})
        self.accepts(data["command"])

    def test_sheet_tidy_commands(self):
        path = self.work / "병합.csv"
        path.write_text("부서,금액\n영업,100\n,200\n", encoding="utf-8")
        _, data = self.post("/api/sheet/tidy_preview",
                            {"path": str(path), "fcols": "부서",
                             "wanttotal": True, "tcols": "금액",
                             "tkind": "avg", "tlabel": "평균값"})
        self.assertEqual(len(data["command"]), 2)
        for line in data["command"]:
            self.accepts(line)

    def test_sheet_commands(self):
        path = self.work / "명단.csv"
        path.write_text("이름,연락처\n홍길동,01012345678\n", encoding="utf-8")
        _, clean = self.post("/api/sheet/clean_save",
                             {"path": str(path), "dedupe": True})
        self.accepts(clean["command"])
        _, formatted = self.post("/api/sheet/format_save",
                                 {"path": str(path),
                                  "specs": [["연락처", "전화"]]})
        self.accepts(formatted["command"])

    def test_doc_merge_and_git_history_commands(self):
        import subprocess

        room = self.work / "장"
        room.mkdir(exist_ok=True)
        (room / "01.md").write_text("# 하나\n", encoding="utf-8")
        (room / "02.md").write_text("# 둘\n", encoding="utf-8")
        _, merged = self.post("/api/doc/merge",
                              {"mfolder": str(room), "mshift": "1",
                               "mrule": True})
        self.accepts(merged["command"])

        root = self.work / "저장소2"
        root.mkdir(exist_ok=True)
        for args in (("init", "-q"), ("config", "user.email", "t@e.c"),
                     ("config", "user.name", "테스터")):
            subprocess.run(["git", *args], cwd=root, capture_output=True)
        (root / "가.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "처음"], cwd=root,
                       capture_output=True)
        _, story = self.post("/api/git/history",
                             {"path": str(root), "hfile": "가.py"})
        self.accepts(story["command"])

    def test_life_severance_command(self):
        _, data = self.post("/api/life/severance",
                            {"sjoined": "2021-03-02", "sleft": "2026-09-01",
                             "spay": "1500만", "sbonus": "400만"})
        self.accepts(data["command"])

    def test_life_annual_and_doc_docx_commands(self):
        _, annual = self.post("/api/life/annual",
                              {"joined": "2023-03-02", "on": "2026-09-07",
                               "ahead": "3"})
        self.accepts(annual["command"])

        from attools import docx

        path = self.work / "보고서.docx"
        docx.write_document(path, [docx.paragraph("가")])
        _, moved = self.post("/api/doc/from_docx", {"docx_path": str(path)})
        self.accepts(moved["command"])

        folder = self.work / "회의록"
        folder.mkdir()
        (folder / "가.md").write_text("- [ ] 할 일 @홍길동\n", encoding="utf-8")
        _, todo = self.post("/api/doc/todo",
                            {"tdroot": str(folder), "tdwho": "홍길동"})
        self.accepts(todo["command"])

    def test_sheet_similar_command(self):
        path = self.work / "거래처.csv"
        path.write_text("상호\n(주)가나\n주식회사 가나\n", encoding="utf-8")
        _, data = self.post("/api/sheet/similar",
                            {"path": str(path), "simcol": "상호",
                             "threshold": "0.9"})
        self.accepts(data["command"])

    def test_doc_commands(self):
        path = self.work / "문서.md"
        path.write_text("# 제목\n\n<!-- toc -->\n<!-- /toc -->\n\n## 가\n",
                        encoding="utf-8")
        _, fixed = self.post("/api/doc/fix_apply",
                             {"path": str(path), "fix": "toc"})
        self.accepts(fixed["command"])
        for kind in ("html", "slides", "docx"):
            _, made = self.post("/api/doc/export",
                                {"path": str(path), "kind": kind, "toc": True})
            self.accepts(made["command"])

    def test_novel_command(self):
        root = self.work / "원고"
        root.mkdir()
        (root / "1화.txt").write_text("리안은 웃었다.\n", encoding="utf-8")
        _, data = self.post("/api/novel/export",
                            {"path": str(root), "format": "epub",
                             "title": "시험작", "author": "나"})
        self.accepts(data["command"])

    def test_quoting(self):
        from attools.webui import form

        self.assertEqual(form.command("file", "organize", "/a b"),
                         "at file organize '/a b'")
        self.assertEqual(form.command("x", "리안"), "at x 리안")  # 한글은 그대로
        self.assertEqual(form.command("x", "it's"), "at x 'it'\\''s'")


class RegistryTest(unittest.TestCase):
    def test_find_by_korean_name(self):
        apps = webui.load_apps()
        self.assertIsNotNone(webui.find_app(apps, "파일정리"))
        self.assertIsNotNone(webui.find_app(apps, "파일 정리"))
        self.assertIsNotNone(webui.find_app(apps, "files"))
        self.assertIsNone(webui.find_app(apps, "없는화면"))

    def test_keys_are_ascii_and_unique(self):
        """주소에 그대로 들어가므로 아스키여야 한다."""
        apps = webui.load_apps()
        keys = [app.key for app in apps]
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            self.assertTrue(key.isascii() and key.isidentifier(), key)

    def test_launcher_groups_apps(self):
        """열 개가 넘으면 하는 일로 묶여 있어야 찾을 수 있다."""
        import re

        apps = webui.load_apps()
        body = webui.launcher_body(apps, "토큰")
        sections = re.findall(r"<h2>([^<]+)</h2>", body)
        self.assertEqual(sections, list(dict.fromkeys(a.section for a in apps)))
        for app in apps:
            self.assertIn("/" + app.key + "?t=토큰", body)

    def test_only_shows_one_app(self):
        apps = webui.load_apps()
        run = webui.start(apps[0], apps=apps)
        try:
            thread = threading.Thread(target=run.server.serve_forever,
                                      kwargs={"poll_interval": 0.02}, daemon=True)
            thread.start()
            with urllib.request.urlopen(run.url) as res:
                body = res.read().decode("utf-8")
            self.assertIn(apps[0].name, body)
            self.assertNotIn("다른 기능", body)
        finally:
            run.server.shutdown()
            run.server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
