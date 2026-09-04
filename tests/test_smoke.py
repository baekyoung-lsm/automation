"""명령을 실제로 끝까지 돌려 보는 시험.

배선 시험(CliWiringTest)은 --help 만 본다. 핸들러 본문이 깨지는 것은
여기서 잡는다. 실제 파일을 만들고 cli.main 을 불러 종료 코드와 출력을 본다.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import cli, sheet, xlsx


class SmokeTest(unittest.TestCase):
    """모든 그룹에서 대표 명령을 하나씩 실제로 돌린다."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp())
        cls.home = cls.root / "집"
        cls.home.mkdir()
        cls._build_fixtures()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    @classmethod
    def _build_fixtures(cls):
        root = cls.root

        (root / "문서").mkdir()
        (root / "문서" / "보고서.txt").write_text("내용\n", encoding="utf-8")
        (root / "문서" / "사진.jpg").write_bytes(b"\xff\xd8\xff")
        (root / "문서" / "옛날.txt").write_bytes("한글 내용\n".encode("cp949"))

        (root / "명단.csv").write_text(
            "사번,이름,부서,입사일,연봉\n"
            "E1,홍길동,영업,2021-03-02,52000000\n"
            "E2,김철수,개발,2023-07-15,47000000\n"
            "E2,김철수,개발,2024-01-05,49000000\n"
            "E3,이영희,인사,2020-01-06,61000000\n", encoding="utf-8")
        (root / "급여.csv").write_text(
            "사번,평가\nE1,A\nE2,B\n", encoding="utf-8")
        xlsx.write_sheets(root / "명단.xlsx",
                          {"직원": [["사번", "이름"], ["E1", "홍길동"]]})

        (root / "응답1.json").write_text(
            json.dumps({"users": [{"id": 1, "name": "가"}], "total": 1,
                        "config": {"port": 8080}}, ensure_ascii=False),
            encoding="utf-8")
        (root / "응답2.json").write_text(
            json.dumps({"users": [{"id": 1, "name": "나"}], "total": "1"},
                       ensure_ascii=False), encoding="utf-8")

        (root / "app.log").write_text(
            "2026-09-01 10:00:01 INFO 시작\n"
            "2026-09-01 10:00:02 ERROR 결제 실패 order=1\n"
            "  at com.app.Pay.run(Pay.java:42)\n"
            "2026-09-01 11:00:03 ERROR 결제 실패 order=2\n"
            "2026-09-01 11:30:00 WARN 지연 900ms\n", encoding="utf-8")

        (root / "문서.md").write_text(
            "# 제목\n\n<!-- toc -->\n<!-- /toc -->\n\n## 하나\n\n"
            "[안쪽](#하나) [바깥](https://example.com)\n", encoding="utf-8")

        (root / ".env").write_text("DB_HOST=1.2.3.4\nDB_PASSWORD=비밀\n",
                                   encoding="utf-8")
        # 예시에만 있는 키를 하나 둬야 dev env 가 '빠진 키'를 잡는다
        (root / ".env.example").write_text("DB_HOST=<db_host>\nDEBUG=true\n",
                                           encoding="utf-8")

        (root / "requirements.txt").write_text("django==4.2\nrequests\n",
                                               encoding="utf-8")

        원고 = root / "원고"
        원고.mkdir()
        (원고 / "01화.txt").write_text(
            "# 1화\n\n" + "리안은 성문 앞에 섰다. " * 8 + "\n\n***\n\n"
            + '"늦었어." 카일이 말했다. ' * 8 + "\n", encoding="utf-8")
        (원고 / "02화.txt").write_text(
            "# 2화\n\n" + "카일은 탑에 올랐다. " * 10 + "\n"
            "2026년 3월 5일 아침이었다. 리안는 대답하지 않았다.\n", encoding="utf-8")

        저장소 = root / "저장소"
        저장소.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@e.c"],
                     ["config", "user.name", "테스터"]):
            subprocess.run(["git", *args], cwd=저장소, capture_output=True)
        (저장소 / "코드.py").write_text("# TODO(홍길동): 캐시 붙이기\nx = 1\n",
                                        encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=저장소, capture_output=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: 첫 커밋"],
                       cwd=저장소, capture_output=True)

    def run_cli(self, *args, expect: int = 0) -> str:
        """명령을 돌리고 표준 출력을 돌려준다. 홈은 임시 폴더로 돌린다."""
        out = io.StringIO()
        original = os.environ.get("HOME")
        os.environ["HOME"] = str(self.home)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = cli.main(list(args))
        finally:
            if original is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original

        text = out.getvalue()
        self.assertEqual(code, expect,
                         f"at {' '.join(args)} -> {code} (기대 {expect})\n{text}")
        return text

    def path(self, *parts) -> str:
        return str(self.root.joinpath(*parts))

    # ------------------------------------------------------------ file

    def test_file_group(self):
        self.assertIn("문서", self.run_cli("file", "organize", self.path("문서")))
        self.run_cli("file", "fixname", self.path("문서"))
        self.run_cli("file", "dupes", self.path("문서"), "--min-size", "1")
        self.assertIn("파일", self.run_cli("file", "tree", self.path()))
        self.assertIn("바뀐 파일", self.run_cli("file", "recent", self.path(),
                                                "-d", "1"))
        self.run_cli("file", "big", self.path())
        self.run_cli("file", "rename", self.path("문서"), "-t", "{seq:03d}{ext}")
        self.run_cli("file", "archive", self.path("문서"), "-g", "*.txt")
        sums = self.path("SUMS.txt")
        self.run_cli("file", "hash", self.path("원고"), "-o", sums)
        self.assertIn("모두 같습니다",
                      self.run_cli("file", "hash", self.path("원고"), "--check", sums))
        self.assertIn("왼쪽에만", self.run_cli("file", "diff", self.path("문서"),
                                               self.path("원고"), expect=1))

    # ------------------------------------------------------------ text

    def test_text_group(self):
        self.assertIn("인코딩", self.run_cli("text", "encoding", self.path("문서")))
        self.run_cli("text", "trim", self.path("문서"), "-g", "*.txt")
        self.run_cli("text", "replace", "없는말", "새말", self.path("문서"))
        self.assertIn("고유", self.run_cli("text", "lines", self.path("명단.csv")))
        self.assertIn("레벨", self.run_cli(
            "text", "extract", r"(?P<시각>\S+ \S+) (?P<레벨>\w+) (?P<메시지>.+)",
            self.path("app.log")))

        원본 = Path(self.path("문서")) / "보고서.txt"
        고침 = Path(self.path("문서")) / "보고서_고침.txt"
        고침.write_text(원본.read_text(encoding="utf-8") + "덧붙인 줄.\n",
                        encoding="utf-8")
        out = self.run_cli("text", "diff", str(원본), str(고침), expect=1)
        self.assertIn("덧붙인 줄.", out)
        self.assertIn("다른 곳이 없습니다",
                      self.run_cli("text", "diff", str(원본), str(원본)))

    # ----------------------------------------------------------- sheet

    def test_sheet_group(self):
        csv = self.path("명단.csv")
        self.assertIn("사번", self.run_cli("sheet", "peek", csv))
        self.assertIn("중복 키", self.run_cli("sheet", "check", csv, "--key", "사번",
                                              expect=1))
        self.run_cli("sheet", "clean", csv)
        self.run_cli("sheet", "cut", csv, "-c", "이름", "-c", "연봉")
        self.assertIn("개발", self.run_cli("sheet", "where", csv, "--eq", "부서=개발"))
        self.run_cli("sheet", "sort", csv, "--by", "연봉", "--desc")
        self.run_cli("sheet", "sample", csv, "-n", "2", "--seed", "1")
        self.run_cli("sheet", "pivot", csv, "--rows", "부서", "--values", "연봉")
        긴표 = self.path("긴표.csv")
        self.assertIn("항목", self.run_cli("sheet", "melt", csv, "--keep", "사번",
                                           "-o", 긴표))
        self.assertIn("항목", self.run_cli("sheet", "transpose", csv))
        self.assertIn("지운 행", self.run_cli("sheet", "dedupe", csv, "-k", "사번",
                                              "--keep", "max", "--by", "입사일"))
        self.assertIn("짝 찾음", self.run_cli("sheet", "join", csv,
                                              self.path("급여.csv"), "--on", "사번"))
        self.run_cli("sheet", "split", csv, "--by", "부서")
        self.assertIn("users", self.run_cli("sheet", "from-json",
                                            self.path("응답1.json"),
                                            "--path", "users"))
        self.assertIn("이름", self.run_cli("sheet", "to-json", csv, "--lines"))
        self.assertIn("통과", self.run_cli("sheet", "validate", csv,
                                          "--required", "이름"))
        self.assertIn("겹치지", self.run_cli("sheet", "validate", csv,
                                             "--unique", "사번", expect=1))
        self.assertIn("월급", self.run_cli("sheet", "fx", csv,
                                           "--add", "월급=연봉/12", "--round", "0"))
        out = self.path("보고서.html")
        self.run_cli("sheet", "report", csv, "--by", "부서", "--value", "연봉",
                     "-o", out)
        self.assertIn("<svg", Path(out).read_text(encoding="utf-8"))

        converted = self.path("변환.xlsx")
        self.run_cli("sheet", "convert", csv, "-o", converted)
        self.assertTrue(Path(converted).is_file())
        self.assertIn("사번", self.run_cli("sheet", "peek", self.path("명단.xlsx")))

    def test_sheet_fill(self):
        template = self.path("틀.txt")
        Path(template).write_text("{이름} 님 {부서}\n", encoding="utf-8")
        text = self.run_cli("sheet", "fill", self.path("명단.csv"), "-t", template)
        self.assertIn("홍길동", text)

    # ------------------------------------------------------------ json

    def test_json_group(self):
        one, two = self.path("응답1.json"), self.path("응답2.json")
        self.assertIn("users", self.run_cli("json", "schema", one))
        self.assertIn("타입 바뀜", self.run_cli("json", "diff", one, two, expect=1))
        self.assertIn("users[0].name", self.run_cli("json", "flat", one))
        self.assertIn("가", self.run_cli("json", "get", one, "users[0].name"))
        self.assertIn("9090", self.run_cli("json", "set", one, "config.port=9090"))
        self.run_cli("json", "show", one, "--sort")

    # ------------------------------------------------------------- dev

    def test_dev_group(self):
        self.assertIn("빠진 키",
                      self.run_cli("dev", "env", self.path(".env.example"),
                                   self.path(".env"), expect=1))
        synced = self.run_cli("dev", "env", self.path(".env.example"),
                              self.path(".env"), "--sync")
        self.assertIn("DB_PASSWORD=<db_password>", synced)
        self.assertNotIn("비밀", synced)          # 비밀값이 새어 나가면 안 된다
        self.assertIn("ERROR", self.run_cli("dev", "log", self.path("app.log")))
        # django 는 ==4.2 로 고정돼 있으니 열린 목록에는 requests 만 나온다
        loose = self.run_cli("dev", "deps", self.path(), "--loose")
        self.assertIn("requests", loose)
        self.assertIn("고정 1", loose)
        self.assertIn("KST", self.run_cli("dev", "time", "1700000000"))
        self.assertIn("월", self.run_cli("dev", "cron", "0 9 * * 1-5", "-n", "2"))
        self.assertIn("base64", self.run_cli("dev", "enc", "안녕"))
        self.run_cli("dev", "gen", "uuid")
        self.assertIn("마스킹", self.run_cli("dev", "mask", self.path("app.log")))

    # ------------------------------------------------------------- git

    def test_git_group(self):
        repo = self.path("저장소")
        self.assertIn("홍길동", self.run_cli("git", "todo", repo))
        self.assertIn("시크릿", self.run_cli("git", "scan", repo))
        self.assertIn("커밋", self.run_cli("git", "stats", repo))
        self.assertIn("새 기능", self.run_cli("git", "release", repo))
        self.assertIn("브랜치", self.run_cli("git", "branches", repo))
        self.run_cli("git", "sweep", repo)

    # ------------------------------------------------------------- doc

    def test_doc_group(self):
        md = self.path("문서.md")
        self.assertIn("하나", self.run_cli("doc", "toc", md))
        self.run_cli("doc", "toc", md, "--apply")
        self.assertIn("#하나", Path(md).read_text(encoding="utf-8"))
        self.run_cli("doc", "links", md)
        self.run_cli("doc", "check", md)

        out = self.path("쪼갠글")
        self.assertIn("--apply", self.run_cli("doc", "split", md, "-o", out))
        self.assertFalse(Path(out).exists())
        self.run_cli("doc", "split", md, "-o", out, "--apply")
        made = sorted(q.name for q in Path(out).iterdir())
        self.assertTrue(made and made[0].startswith("01-"), made)

        표 = Path(self.path("표.md"))
        표.write_text("| 이름 | 값 |\n|---|---|\n| 가나다 | 1 |\n",
                      encoding="utf-8")
        self.assertIn("--apply", self.run_cli("doc", "table", str(표)))
        self.run_cli("doc", "table", str(표), "--apply")
        from attools.mdkit import display_width

        줄 = 표.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len({display_width(l) for l in 줄}), 1)

    # ------------------------------------------------------------ life

    def test_life_group(self):
        self.assertIn("D+", self.run_cli("life", "dday", "2024-03-15",
                                         "--today", "2026-09-04"))
        self.assertIn("1인당", self.run_cli("life", "split", "가=30000", "나=10000"))
        self.assertIn("매달", self.run_cli("life", "loan", "3억", "4.2", "30"))
        self.assertIn("평", self.run_cli("life", "unit", "84㎡"))
        self.assertIn("영업일", self.run_cli("life", "workday", "2026-08-14", "+5"))
        self.assertIn("부가세", self.run_cli("life", "tax", "1100000"))
        달력 = self.run_cli("life", "cal", "2026-10", "-n", "2")
        self.assertIn("2026년 10월", 달력)
        self.assertIn("개천절", 달력)
        self.assertIn("음력", 달력)          # 설날·추석은 못 넣는다고 알려야 한다
        self.assertIn("만기 수령", self.run_cli(
            "life", "save", "--monthly", "50만", "--months", "24", "--rate", "3.5"))

    # ------------------------------------------------------------ keys

    def test_keys_group(self):
        self.assertIn("붙여넣기", self.run_cli("keys", "붙여넣기"))
        listed = self.run_cli("keys", "--list")
        self.assertIn("단축키", listed)
        self.assertIn(str(self.home), listed)     # 홈을 따라간다
        self.assertIn("확인", self.run_cli("keys", "--gaps"))
        self.run_cli("keys", "--set", "doc/표 만들기/word=Alt+N,T")

    def test_keys_html_export(self):
        out = self.path("단축키.html")
        self.run_cli("keys", "--html", out)
        self.assertIn("localStorage", Path(out).read_text(encoding="utf-8"))

    # ----------------------------------------------------------- novel

    def test_novel_group(self):
        원고 = self.path("원고")
        self.assertIn("원고지", self.run_cli("novel", "stats", 원고))
        self.run_cli("novel", "check", self.path("원고", "01화.txt"))
        self.assertIn("장면", self.run_cli("novel", "outline", 원고, "--min", "20"))
        self.assertIn("리안", self.run_cli("novel", "find", "리안", 원고,
                                           "--min", "20"))
        self.assertIn("조사", self.run_cli("novel", "names", 원고, "--min", "2",
                                           expect=1))
        self.assertIn("시간", self.run_cli("novel", "timeline", 원고, "--min", "20"))
        self.assertIn("대사", self.run_cli("novel", "dialogue", 원고, "--min", "2"))
        self.assertIn("어휘", self.run_cli("novel", "wordlist", 원고, "--min", "2"))
        self.run_cli("novel", "style", 원고)
        self.run_cli("novel", "snap", 원고, "--note", "시험")
        out = self.run_cli("novel", "pace", 원고, "--goal", "100매")
        self.assertIn("스냅샷 1개", out)
        self.assertIn("속도를 계산할 수 없습니다", out)

    def test_novel_export(self):
        out = self.path("투고본.html")
        self.run_cli("novel", "export", self.path("원고"), "--title", "제목",
                     "-o", out)
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("제목", html)
        self.assertIn("<h2", html)


if __name__ == "__main__":
    unittest.main()
