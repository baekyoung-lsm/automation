"""HTTP 한 번 부르기 시험. 진짜 서버를 띄워서 확인한다."""

import contextlib
import http.server
import io
import json
import shutil
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import cli
from attools.code import devkit


class 시험서버(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        # 헤더 값은 latin-1 만 되므로 한글을 쓰지 않는다
        self.send_header("Authorization", "Bearer secret-token-value")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/none":
            self._send(404, json.dumps({"오류": "없습니다"}, ensure_ascii=False))
        elif self.path == "/plain":
            raw = "그냥 글".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        else:
            self._send(200, json.dumps({"메시지": "안녕"}, ensure_ascii=False))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        got = self.rfile.read(length).decode("utf-8")
        self._send(201, json.dumps({"받음": got, "형식": self.headers.get("Content-Type")},
                                   ensure_ascii=False))

    def log_message(self, *args):
        pass


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), 시험서버)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_reads_status_body_and_time(self):
        r = devkit.fetch(self.base + "/")
        self.assertEqual(r.status, 200)
        self.assertTrue(r.ok)
        self.assertEqual(json.loads(r.text())["메시지"], "안녕")
        self.assertGreater(r.seconds, 0)

    def test_error_response_is_a_result_not_an_exception(self):
        # 4xx 의 본문에 원인이 적혀 있는 일이 많다
        r = devkit.fetch(self.base + "/none")
        self.assertEqual(r.status, 404)
        self.assertFalse(r.ok)
        self.assertIn("없습니다", r.text())

    def test_charset_is_taken_from_the_header(self):
        r = devkit.fetch(self.base + "/plain")
        self.assertEqual(r.charset, "utf-8")
        self.assertEqual(r.text(), "그냥 글")
        self.assertEqual(r.kind, "text/plain")

    def test_post_sends_body_and_headers(self):
        r = devkit.fetch(self.base + "/", method="POST", body=b'{"a":1}',
                         headers={"Content-Type": "application/json"})
        got = json.loads(r.text())
        self.assertEqual(r.status, 201)
        self.assertEqual(got["받음"], '{"a":1}')
        self.assertEqual(got["형식"], "application/json")

    def test_secret_headers_are_masked(self):
        r = devkit.fetch(self.base + "/")
        shown = dict(r.safe_headers())["Authorization"]
        self.assertNotIn("secret-token-value", shown)
        self.assertTrue(shown.startswith("Be"))

    def test_parse_header(self):
        self.assertEqual(devkit.parse_header("X-Key: 값"), ("X-Key", "값"))
        with self.assertRaises(ValueError):
            devkit.parse_header("콜론없음")


if __name__ == "__main__":
    unittest.main()


class CallsTest(unittest.TestCase):
    """.http 파일을 차례대로 부르기. 진짜 서버에 대고 끝까지 돌린다."""

    @classmethod
    def setUpClass(cls):
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), 시험서버)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.file = self.root / "api.http"
        self.file.write_text(
            f"@host = {self.base}\n"
            "\n"
            "### 로그인\n"
            "POST {{host}}/login\n"
            "Content-Type: application/json\n"
            "# @save kind = 형식\n"
            "\n"
            '{"아이디": "{{user}}"}\n'
            "\n"
            "### 목록\n"
            "GET {{host}}/items\n"
            "X-Kind: {{kind}}\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_cli(self, *args, expect: int = 0) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["dev", "calls", str(self.file), *args])
        self.assertEqual(code, expect, out.getvalue())
        return out.getvalue()

    def test_preview_does_not_call_and_says_so(self):
        got = self.run_cli("--var", "user=kim")
        self.assertIn("보기만", got)
        self.assertIn("로그인", got)
        self.assertNotIn("201", got)

    def test_preview_does_not_call_a_saved_name_missing(self):
        """뒤 요청이 앞 요청에서 받는 값은 «모르는 이름» 이 아니다."""
        got = self.run_cli("--var", "user=kim")
        self.assertIn("앞 요청", got)
        self.assertNotIn("값을 모르는 이름", got)

    def test_missing_value_is_named_and_nothing_is_called(self):
        got = self.run_cli(expect=1)
        self.assertIn("user", got)
        self.assertIn("값을 모르는 이름", got)

    def test_runs_in_order_and_carries_the_saved_value(self):
        got = self.run_cli("--var", "user=kim", "--run", "--yes")
        self.assertIn("201", got)                      # 로그인
        self.assertIn("@save kind = application/json", got)
        self.assertIn("200", got)                      # 목록
        self.assertIn("모두 성공", got)

    def test_write_requests_are_not_called_without_a_yes(self):
        """POST·DELETE 는 되돌릴 수 없다. 확인 없이 나가면 안 된다."""
        got = self.run_cli("--var", "user=kim", "--run", expect=1)
        self.assertIn("되돌릴 수 없습니다", got)
        self.assertIn("부르지 않았습니다", got)
        self.assertNotIn("201", got)

    def test_only_runs_the_chosen_number(self):
        got = self.run_cli("--only", "2", "--var", "kind=x", "--run")
        self.assertIn("200", got)
        self.assertNotIn("로그인", got)

    def test_failure_stops_the_rest(self):
        self.file.write_text(
            f"### 없는 곳\nGET {self.base}/none\n\n"
            f"### 다음\nGET {self.base}/\n", encoding="utf-8")
        got = self.run_cli("--run", expect=1)
        self.assertIn("404", got)
        self.assertIn("여기서 멈춥니다", got)
        got = self.run_cli("--run", "--keep-going", expect=1)
        self.assertIn("실패 1개", got)

    def test_body_shown_on_request(self):
        got = self.run_cli("--only", "2", "--var", "kind=x", "--run", "--show", "2")
        self.assertIn("안녕", got)
