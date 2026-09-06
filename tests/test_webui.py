"""브라우저 화면 시험. 서버를 실제로 띄우고 두드린다."""

import json
import os
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

from attools import webui


class WebUiTest(unittest.TestCase):
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


class SheetAppTest(WebUiTest):
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


class NovelAppTest(WebUiTest):
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

    def test_reading_does_not_change_files(self):
        root = self.manuscript()
        before = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        for action in ("count", "inspect", "cast"):
            self.post("/api/novel/" + action, {"path": str(root)})
        after = {p.name: p.read_text(encoding="utf-8") for p in root.iterdir()}
        self.assertEqual(before, after)


class LifeAppTest(WebUiTest):
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

    def test_won(self):
        _, data = self.post("/api/life/won", {"amount": "1250000"})
        self.assertEqual(data["korean"], "백이십오만")
        self.assertEqual(data["formal"], "일금 일백이십오만원정")


class TextAppTest(WebUiTest):
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


class KeysAppTest(WebUiTest):
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

    def test_marks_are_kept_apart(self):
        """확인 못 한 칸(?)과 단축키가 없는 것(—)을 섞지 않는다."""
        _, data = self.post("/api/keys/table", {})
        marks = {cell for row in data["rows"] for cell in row[2:]}
        self.assertTrue(marks & {"?", "—"})
        self.assertNotIn("없음", marks)
        self.assertNotIn("", marks)


class DevAppTest(WebUiTest):
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


class DocAppTest(WebUiTest):
    """문서 화면. 고치는 동작은 백업이 남는지까지 본다."""

    def markdown(self):
        path = self.work / "문서.md"
        path.write_text(
            "# 제목\n\n<!-- toc -->\n<!-- /toc -->\n\n## 가\n\n"
            "[없는곳](#몰라)\n\n| a | bb |\n| --- | --- |\n| 1 | 2 |\n\n"
            "### 나\n", encoding="utf-8")
        return path

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


class JsonAppTest(WebUiTest):
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


class GitAppTest(WebUiTest):
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
