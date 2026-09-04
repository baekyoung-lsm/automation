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
