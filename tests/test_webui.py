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
