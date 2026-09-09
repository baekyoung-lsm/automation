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
import zipfile
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

    # ---------------------------------------------- 엉뚱한 입력 (역추적 금지)

    def test_broken_journals_answer_in_korean(self):
        """되돌리기에 망가진 저널을 줘도 역추적이 뜨면 안 된다."""
        가짜 = Path(self.path("가짜.jsonl"))
        가짜.write_text("{망가진\n", encoding="utf-8")
        for group in ("file", "text"):
            out = self.run_cli(group, "undo", str(가짜), expect=1)
            self.assertIn("읽지 못했습니다", out)

        폴더 = Path(self.path("문서"))
        self.assertIn("저널 파일이 아닙니다",
                      self.run_cli("file", "undo", str(폴더), expect=1))

    # ------------------------------------------------------------ file

    def test_file_group(self):
        self.run_cli("file", "photos", self.path("문서"))
        self.assertIn("파일", self.run_cli("file", "list", self.path("문서")))
        self.run_cli("file", "list", self.path("문서"),
                     "-o", self.path("목록.csv"))
        문서폴더 = Path(self.path("속성"))
        문서폴더.mkdir(exist_ok=True)
        import zipfile

        with zipfile.ZipFile(문서폴더 / "계획서.docx", "w") as z:
            z.writestr("docProps/core.xml",
                       "<cp:coreProperties xmlns:cp='c' xmlns:dc='d'>"
                       "<dc:creator>김철수</dc:creator></cp:coreProperties>")
            z.writestr("word/document.xml", "<x/>")
        (문서폴더 / "보고서.pdf").write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Page>>endobj\n%%EOF\n")
        with zipfile.ZipFile(문서폴더 / "예산안.hwpx", "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/content.hpf",
                       "<opf:package xmlns:opf='o' xmlns:dc='d'><opf:metadata>"
                       "<dc:creator>박영희</dc:creator></opf:metadata>"
                       "</opf:package>")
        속성 = self.run_cli("file", "docs", str(문서폴더))
        self.assertIn("김철수", 속성)
        self.assertIn("PDF", 속성)
        self.assertIn("박영희", 속성)
        self.assertIn("밖으로 보내기 전에", 속성)
        찍은사진 = Path(self.path("찍은사진"))
        찍은사진.mkdir(exist_ok=True)
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_files import exif_jpeg

        (찍은사진 / "여행.jpg").write_bytes(exif_jpeg())
        정보 = self.run_cli("file", "exif", str(찍은사진))
        self.assertIn("37.56", 정보)
        self.run_cli("file", "exif", str(찍은사진), "--strip", "--apply")
        지운사진 = list(찍은사진.glob("*정보지움*"))
        self.assertEqual(len(지운사진), 1)
        self.assertNotIn("37.56", self.run_cli("file", "exif", str(지운사진[0])))

        사진 = Path(self.path("사진"))
        사진.mkdir(exist_ok=True)
        import struct
        import zlib

        def chunk(kind, body):
            return (struct.pack(">I", len(body)) + kind + body
                    + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

        줄 = b"".join(b"\x00" + bytes([200, 100, 50]) * 8 for _ in range(6))
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 6, 8, 2, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(줄)) + chunk(b"IEND", b""))
        (사진 / "1.png").write_bytes(png)
        (사진 / "2.png").write_bytes(png)
        묶음 = self.path("스캔.pdf")
        만든pdf = self.run_cli("file", "pdf", str(사진), "-o", 묶음,
                             "--title", "제출용")
        self.assertIn("2쪽", 만든pdf)
        self.assertIn("쪽 수",
                      self.run_cli("file", "docs", 묶음))

        뽑음 = self.path("뒷장.pdf")
        self.assertIn("고른 쪽 1개",
                      self.run_cli("file", "pdfcut", 묶음, "--pages", "2",
                                   "-o", 뽑음))
        self.assertIn("전체 1쪽", self.run_cli("file", "pdfcut", 뽑음))
        합본 = self.path("합본.pdf")
        self.assertIn("3쪽",
                      self.run_cli("file", "pdfjoin", 묶음, 뽑음, "-o", 합본))
        번호 = self.path("번호붙임.pdf")
        찍음 = self.run_cli("file", "pdfnum", 합본, "--skip", "1", "-o", 번호)
        self.assertIn("아래 가운데", 찍음)
        self.assertIn("3쪽", self.run_cli("file", "pdfcut", 번호))
        # 쪽 번호는 글자로 찍혔으므로 다시 꺼내 읽을 수 있어야 한다
        꺼냄 = self.run_cli("file", "pdftext", 번호)
        self.assertIn("1 / 2", 꺼냄)
        # 그림만 든 쪽은 «글자가 없는 쪽» 으로 알린다 (스캔본 안내)
        그림만 = self.run_cli("file", "pdftext", 묶음, expect=1)
        self.assertIn("글자가 없는 쪽", 그림만)
        # 폴더를 주면 한꺼번에. 못 연 파일도 표에 남긴다
        모음 = Path(self.path("피디에프모음"))
        모음.mkdir(exist_ok=True)
        shutil.copy(번호, 모음 / "번호.pdf")
        (모음 / "깨진.pdf").write_text("이건 PDF 가 아니다", encoding="utf-8")
        한꺼번에 = self.run_cli("file", "pdftext", str(모음),
                             "-o", self.path("꺼낸글"), expect=1)
        self.assertIn("못 연 파일 1개", 한꺼번에)
        self.assertTrue(Path(self.path("꺼낸글", "번호.txt")).is_file())

        pdf폴더 = Path(self.path("피디에프"))
        pdf폴더.mkdir(exist_ok=True)
        self.run_cli("file", "pdf", str(사진), "-o", str(pdf폴더 / "이름.pdf"),
                     "--title", "제출용")
        지움 = self.run_cli("file", "scrub", str(pdf폴더))
        # 우리가 만든 PDF 에는 사람 이름이 안 들어간다
        self.assertIn("남은 사람·회사 이름이 없습니다", 지움)
        self.assertFalse(list(pdf폴더.glob("*이름지움*")))

        백업 = Path(self.path("백업"))
        옮김 = self.run_cli("file", "sync", self.path("문서"), str(백업))
        self.assertIn("미리보기", 옮김)
        self.assertFalse(백업.exists())
        self.run_cli("file", "sync", self.path("문서"), str(백업), "--apply")
        self.assertTrue((백업 / "보고서.txt").is_file())

        미리 = self.run_cli("file", "scrub", str(문서폴더))
        self.assertIn("미리보기", 미리)
        self.assertFalse(list(문서폴더.glob("*이름지움*")))
        self.run_cli("file", "scrub", str(문서폴더), "--apply")
        지운것 = sorted(문서폴더.glob("*이름지움*"))
        self.assertEqual(len(지운것), 2)          # 워드와 한글 둘 다
        for 사본 in 지운것:
            남은것 = self.run_cli("file", "docs", str(사본))
            self.assertNotIn("김철수", 남은것)
            self.assertNotIn("박영희", 남은것)
        self.assertIn("문서", self.run_cli("file", "organize", self.path("문서")))
        self.run_cli("file", "fixname", self.path("문서"))
        self.run_cli("file", "dupes", self.path("문서"), "--min-size", "1")
        self.run_cli("file", "dupes", self.path("문서"), "--min-size", "1",
                     "--collect", self.path("문서", "_중복"))
        self.assertIn("파일", self.run_cli("file", "tree", self.path()))
        self.assertIn("바뀐 파일", self.run_cli("file", "recent", self.path(),
                                                "-d", "1"))
        self.run_cli("file", "big", self.path())
        self.run_cli("file", "rename", self.path("문서"), "-t", "{seq:03d}{ext}")
        self.run_cli("file", "archive", self.path("문서"), "-g", "*.txt")
        폴더훑기 = self.run_cli("file", "audit", self.path("문서"))
        self.assertIn("본 것", 폴더훑기)
        목록 = Path(self.path("이름목록.csv"))
        목록.write_text("현재 이름,새 이름\n보고서.txt,제출-001.txt\n",
                      encoding="utf-8")
        바꿈 = self.run_cli("file", "rename", self.path("문서"),
                          "--map", str(목록))
        self.assertIn("제출-001.txt", 바꿈)
        self.assertIn("총 1개", 바꿈)          # 기본은 미리보기
        담기 = self.run_cli("file", "pack", self.path("문서"), "--max", "1MB")
        self.assertIn("묶음", 담기)
        self.run_cli("file", "pack", self.path("문서"), "--max", "1MB",
                     "-o", self.path("보낼것"), "--apply")
        self.assertTrue(list(Path(self.path("보낼것")).glob("*.zip")))

        import struct
        import zlib

        def png_chunk(tag, body):
            return (struct.pack(">I", len(body)) + tag + body
                    + struct.pack(">I", zlib.crc32(tag + body)))

        그림 = Path(self.path("문서")) / "표지.png"
        그림.write_bytes(b"\x89PNG\r\n\x1a\n"
                         + png_chunk(b"IHDR", struct.pack(">IIBBBBB", 800, 600, 8, 2, 0, 0, 0))
                         + png_chunk(b"IEND", b""))
        self.assertIn("800x600", self.run_cli("file", "image", self.path("문서")))

        규칙 = self.path("규칙.json")
        Path(규칙).write_text(json.dumps(
            {"규칙": [{"이름": "글", "패턴": "*.txt", "폴더": "모은글/{년}"}]},
            ensure_ascii=False), encoding="utf-8")
        나눌곳 = Path(self.path("받은자료"))
        나눌곳.mkdir()
        (나눌곳 / "계약서.txt").write_text("내용\n", encoding="utf-8")
        깊은곳 = Path(self.path("받은자료")) / "안쪽"
        깊은곳.mkdir(parents=True, exist_ok=True)
        (깊은곳 / "깊은파일.txt").write_text("x", encoding="utf-8")
        self.assertIn("--apply", self.run_cli("file", "flatten", self.path("받은자료")))
        self.run_cli("file", "flatten", self.path("받은자료"), "--apply")
        self.assertTrue((Path(self.path("받은자료")) / "깊은파일.txt").is_file())

        나눔 = self.run_cli("file", "route", str(나눌곳), "--rules", 규칙)
        self.assertIn("모은글", 나눔)
        self.run_cli("file", "route", str(나눌곳), "--rules", 규칙, "--apply")
        self.assertTrue(list(나눌곳.glob("모은글/*/계약서.txt")))

        import zipfile

        class Cp949Info(zipfile.ZipInfo):
            def _encodeFilenameFlags(self):
                return self.filename.encode("cp949"), 0

        zip경로 = Path(self.path("윈도우.zip"))
        with zipfile.ZipFile(zip경로, "w") as z:
            z.writestr(Cp949Info("보고서/1분기.txt"), "내용")
        푼곳 = self.path("푼것")
        self.assertIn("1분기.txt",
                      self.run_cli("file", "unzip", str(zip경로), "-o", 푼곳))
        self.run_cli("file", "unzip", str(zip경로), "-o", 푼곳, "--apply")
        self.assertTrue((Path(푼곳) / "보고서" / "1분기.txt").is_file())
        sums = self.path("SUMS.txt")
        self.run_cli("file", "hash", self.path("원고"), "-o", sums)
        self.assertIn("모두 같습니다",
                      self.run_cli("file", "hash", self.path("원고"), "--check", sums))
        self.assertIn("왼쪽에만", self.run_cli("file", "diff", self.path("문서"),
                                               self.path("원고"), expect=1))

    # ------------------------------------------------------------ text

    def test_text_group(self):
        self.assertIn("안녕하세요", self.run_cli("text", "kbd", "dkssudgktpdy"))
        self.assertIn("날짜", self.run_cli("text", "pick", self.path("원고")))
        # 받은 워드·한글·PDF 안의 값도 --docx 로 함께 뽑는다
        from attools import docx as docxkit

        받은 = Path(self.path("받은문서"))
        받은.mkdir(exist_ok=True)
        docxkit.write_document(받은 / "명세.docx", [
            docxkit.paragraph("담당 hong@example.com 010-1234-5678")])
        self.assertIn("이메일",
                      self.run_cli("text", "pick", str(받은), "--docx"))
        셈 = self.run_cli("text", "count", self.path("원고"))
        self.assertIn("원고지", 셈)
        넘침 = self.run_cli("text", "count", self.path("원고"),
                          "--limit-chars", "10", expect=1)
        self.assertIn("초과", 넘침)
        self.assertIn("곳", self.run_cli("text", "find", "리안", self.path("원고")))
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

        오타 = Path(self.path("문서")) / "오타.txt"
        오타.write_text("몇일 전에 문을 잠궈 놨다.\n", encoding="utf-8")
        self.assertIn("며칠", self.run_cli("text", "typo", str(오타), expect=1))

        긴글 = Path(self.path("문서")) / "긴글.md"
        긴글.write_text("한국어 문장이 아주 길게 이어지는 경우에 줄을 접어야 한다.\n",
                        encoding="utf-8")
        self.assertIn("--apply", self.run_cli("text", "wrap", str(긴글), "-w", "20"))
        self.assertIn("반복되는 문장",
                      self.run_cli("text", "repeat", str(긴글), str(긴글),
                                   "--min-chars", "10", expect=1))
        self.run_cli("text", "wrap", str(긴글), "-w", "20", "--apply")
        self.assertGreater(len(긴글.read_text(encoding="utf-8").splitlines()), 1)
        self.run_cli("text", "typo", str(오타), "--apply")
        self.assertIn("며칠 전에 문을 잠가", 오타.read_text(encoding="utf-8"))

    # ----------------------------------------------------------- sheet

    def test_sheet_group(self):
        csv = self.path("명단.csv")
        self.run_cli("sheet", "convert", csv, "-o", self.path("명단.md"))
        self.assertIn("E1", self.run_cli("sheet", "find", "E1", self.path()))
        표문서 = Path(self.path("표문서.md"))
        표문서.write_text("# 보고\n\n| 이름 | 금액 |\n| --- | ---: |\n"
                        "| 홍길동 | 1,200 |\n", encoding="utf-8")
        표뽑기 = self.run_cli("sheet", "from-md", str(표문서),
                            "-o", self.path("표.csv"))
        self.assertIn("이름", 표뽑기)
        self.assertIn("1200", Path(self.path("표.csv")).read_text(encoding="utf-8"))
        모음 = self.run_cli("sheet", "collect", self.path(), "--cell", "A1=머리",
                           "--glob", "명단.csv")
        self.assertIn("명단.csv", 모음)
        서식폴더 = Path(self.path("서식"))
        서식폴더.mkdir(exist_ok=True)
        (서식폴더 / "영업.csv").write_text("사번,이름\nE1,홍길동\n",
                                          encoding="utf-8")
        (서식폴더 / "개발.csv").write_text("사번,이름\nE2,김철수\n",
                                          encoding="utf-8")
        (서식폴더 / "인사.csv").write_text("사번,이름,비고\nE3,이영희,추가\n",
                                          encoding="utf-8")
        폴더합치기 = self.run_cli("sheet", "merge", str(서식폴더),
                              "-o", self.path("폴더합본.csv"))
        self.assertIn("표 파일 3개를 찾았습니다", 폴더합치기)

        서식 = self.run_cli("sheet", "forms", str(서식폴더), expect=1)
        self.assertIn("열 다름", 서식)
        self.assertIn("비고", 서식)
        # 시트가 여럿인 엑셀을 고칠 때 나머지 시트가 조용히 사라지면 안 된다
        여러시트 = self.path("여러시트.xlsx")
        xlsx.write_sheets(Path(여러시트), {
            "1월": [["부서", "금액"], ["영업", " 1,000원 "]],
            "메모": [["비고"], ["그대로 있어야 한다"]]})
        경고 = self.run_cli("sheet", "clean", 여러시트, "--sheet", "1월",
                          "-o", self.path("한시트.xlsx"))
        self.assertIn("--keep-sheets", 경고)
        self.run_cli("sheet", "clean", 여러시트, "--sheet", "1월",
                     "-o", self.path("다시트.xlsx"), "--keep-sheets")
        self.assertEqual(xlsx.sheet_names(Path(self.path("다시트.xlsx"))),
                         ["1월", "메모"])

        # 교차표는 열이 수십 개가 되기 쉽다. 화면에는 앞쪽과 합계만 보인다
        넓은표 = self.path("넓은표.csv")
        Path(넓은표).write_text(
            "부서,달,금액\n" + "".join(f"영업,{m}월,{m * 10}\n" for m in range(1, 13)),
            encoding="utf-8")
        넓게 = self.run_cli("sheet", "pivot", 넓은표, "--rows", "부서",
                          "--cols", "달", "--values", "금액", "--cols-shown", "3")
        self.assertIn("열", 넓게)
        self.assertIn("합계", 넓게)

        # 표 위에 제목 줄이 한 줄 있는 파일. 실무에서 제일 흔한 어긋남이다
        제목줄 = self.path("제목줄.xlsx")
        xlsx.write_sheets(Path(제목줄), {"지출": [
            ["2026년 3월 지출 내역", None, None],
            ["부서", "항목", "금액"],
            ["영업1팀", "교통비", 12000]]})
        훑음 = self.run_cli("sheet", "audit", 제목줄)
        self.assertIn("--header-row 2", 훑음)
        self.assertIn("볼 만한 곳이 없습니다",
                      self.run_cli("sheet", "audit", 제목줄, "--header-row", "2"))

        전표 = Path(self.path("전표.csv"))
        전표.write_text("전표번호,제출일\n1001,2026-03-05\n1002,2026-03-06\n"
                      "1004,2026-03-09\n", encoding="utf-8")
        라벨 = Path(self.path("라벨.html"))
        만든라벨 = self.run_cli("sheet", "labels", csv, "--line", "{이름} 님",
                             "-o", str(라벨))
        self.assertIn("저장", 만든라벨)
        self.assertIn("class=\"cell\"", 라벨.read_text(encoding="utf-8"))

        빠짐 = self.run_cli("sheet", "gaps", str(전표), "-c", "전표번호", expect=1)
        self.assertIn("1003", 빠짐)
        평일 = self.run_cli("sheet", "gaps", str(전표), "-c", "제출일",
                          "--every", "weekday")
        self.assertIn("빠진 것이 없습니다", 평일)     # 3/7·3/8 은 주말이다
        self.run_cli("sheet", "book", csv, self.path("급여.csv"),
                     "-o", self.path("통합.xlsx"))
        self.assertIn("직원", self.run_cli("sheet", "sheets",
                                          self.path("명단.xlsx")))
        나눔 = self.run_cli("sheet", "unbook", self.path("통합.xlsx"),
                           "-o", self.path("나눈것"))
        self.assertIn("미리보기", 나눔)            # 기본은 미리보기다
        self.assertFalse(Path(self.path("나눈것")).exists())
        self.run_cli("sheet", "unbook", self.path("통합.xlsx"),
                     "-o", self.path("나눈것"), "--apply")
        self.assertTrue(list(Path(self.path("나눈것")).glob("*.xlsx")))
        훑기 = self.run_cli("sheet", "audit", csv)
        self.assertIn("본 것", 훑기)
        드문값 = self.run_cli("sheet", "outliers", csv, "-c", "연봉")
        self.assertIn("숫자로 읽은 칸", 드문값)
        바꿈 = self.run_cli("sheet", "replace", csv, "개발", "R&D", "-c", "부서")
        self.assertIn("R&D", 바꿈)
        남은 = self.run_cli("sheet", "dday", csv, "-c", "입사일",
                          "--on", "2026-09-07", "--sort")
        self.assertIn("지남", 남은)
        날짜 = self.run_cli("sheet", "dates", csv, "-c", "입사일", "--add", "요일")
        self.assertIn("입사일 요일", 날짜)
        나이표 = Path(self.path("생일.csv"))
        나이표.write_text("이름,생년월일\n가,1990-05-06\n나,900101-2345678\n",   # attools: ignore
                        encoding="utf-8")
        근태 = Path(self.path("근태.csv"))
        근태.write_text("날짜,출근,퇴근\n2026-03-02,09:00,18:00\n"
                      "2026-03-03,09:00,21:30\n", encoding="utf-8")
        시간 = self.run_cli("sheet", "worktime", str(근태), "--start", "출근",
                          "--end", "퇴근", "--date", "날짜")
        self.assertIn("실근무", 시간)
        self.assertIn("근로기준법", 시간)
        임금 = self.run_cli("sheet", "worktime", str(근태), "--start", "출근",
                          "--end", "퇴근", "--date", "날짜", "--hourly", "10030")
        self.assertIn("임금 합계", 임금)
        self.assertIn("일당", 임금)
        self.assertIn("5인 미만", 임금)

        나이 = self.run_cli("sheet", "age", str(나이표), "-c", "생년월일",
                          "--group", "--sex", "--on", "2026-03-01")
        self.assertIn("30대", 나이)
        self.assertIn("만 나이", 나이)
        sql = self.run_cli("sheet", "to-sql", csv, "-t", "직원", "--create")
        self.assertIn("INSERT INTO", sql)
        일정 = Path(self.path("일정.csv"))
        일정.write_text("일정,시작,끝\n워크숍,2026-03-10 14:00,2026-03-10 16:00\n",
                       encoding="utf-8")
        캘린더 = self.path("일정.ics")
        self.run_cli("sheet", "ics", str(일정), "--title", "일정",
                     "--start", "시작", "--end", "끝", "-o", 캘린더)
        만든것 = Path(캘린더).read_text(encoding="utf-8")
        self.assertIn("BEGIN:VEVENT", 만든것)
        연락처 = Path(self.path("거래처.csv"))
        연락처.write_text("이름,회사,휴대전화\n홍길동,(주)가나,010-1234-5678\n",
                        encoding="utf-8")
        vcf = self.path("연락처.vcf")
        self.run_cli("sheet", "vcard", str(연락처), "--name", "이름",
                     "--company", "회사", "--mobile", "휴대전화", "-o", vcf)
        카드 = Path(vcf).read_text(encoding="utf-8")
        self.assertIn("FN:홍길동", 카드)
        self.assertIn("TEL;TYPE=CELL:010-1234-5678", 카드)
        되읽기 = self.run_cli("sheet", "from-vcard", vcf)
        self.assertIn("홍길동", 되읽기)
        일정되읽기 = self.run_cli("sheet", "from-ics", 캘린더)
        self.assertIn("워크숍", 일정되읽기)
        본문틀 = Path(self.path("본문.md"))
        본문틀.write_text("{이름}님, 안녕하세요.\n", encoding="utf-8")
        정산 = Path(self.path("정산.csv"))
        정산.write_text("이름,메일\n홍길동,a@b.com\n", encoding="utf-8")
        초안폴더 = self.path("메일초안")
        미리 = self.run_cli("sheet", "mail", str(정산), "-t", str(본문틀),
                          "--subject", "{이름}님 안내", "--to", "메일",
                          "-o", 초안폴더)
        self.assertIn("미리보기", 미리)
        self.assertFalse(Path(초안폴더).exists())
        self.run_cli("sheet", "mail", str(정산), "-t", str(본문틀),
                     "--subject", "{이름}님 안내", "--to", "메일",
                     "-o", 초안폴더, "--apply")
        만든메일 = list(Path(초안폴더).glob("*.eml"))
        self.assertEqual(len(만든메일), 1)
        self.assertIn("To: a@b.com",
                      만든메일[0].read_text(encoding="utf-8"))
        self.assertIn("DTSTART;TZID=Asia/Seoul:20260310T140000", 만든것)
        self.assertIn("가림", self.run_cli("sheet", "mask", csv, "--name", "이름"))
        self.assertIn("형식", self.run_cli("sheet", "format", csv,
                                           "--date", "입사일", "--number", "연봉"))
        self.assertIn("사번", self.run_cli("sheet", "peek", csv))
        self.assertIn("홍길동", self.run_cli("sheet", "row", csv, "--eq", "사번=E1"))
        self.assertIn("중앙값", self.run_cli("sheet", "peek", csv, "--stats"))
        self.assertIn("중복 키", self.run_cli("sheet", "check", csv, "--key", "사번",
                                              expect=1))
        self.run_cli("sheet", "clean", csv)
        self.run_cli("sheet", "cut", csv, "-c", "이름", "-c", "연봉")
        self.assertIn("개발", self.run_cli("sheet", "where", csv, "--eq", "부서=개발"))
        self.run_cli("sheet", "sort", csv, "--by", "연봉", "--desc")
        self.assertIn("값 있음", self.run_cli("sheet", "where", csv,
                                              "--filled", "이름"))
        self.assertIn("성명", self.run_cli("sheet", "rename", csv,
                                          "--map", "이름=성명"))

        섞어 = self.run_cli("sheet", "sort", csv, "--by", "부서", "--by", "연봉:내림")
        self.assertIn("부서 오름, 연봉 내림", 섞어)
        self.run_cli("sheet", "sample", csv, "-n", "2", "--seed", "1")
        self.assertIn("빈 칸", self.run_cli("sheet", "filldown", csv, "-c", "부서"))
        self.assertIn("합계", self.run_cli("sheet", "total", csv, "-c", "연봉"))
        # 집계한 금액은 자릿점을 넣어 보여 준다 (파일에는 숫자 그대로 담는다)
        모음 = self.run_cli("sheet", "pivot", csv, "--rows", "부서",
                          "--values", "연봉")
        self.assertRegex(모음, r"\d,\d{3}")
        긴표 = self.path("긴표.csv")
        self.assertIn("항목", self.run_cli("sheet", "melt", csv, "--keep", "사번",
                                           "-o", 긴표))
        self.assertIn("항목", self.run_cli("sheet", "transpose", csv))
        self.assertIn("갈랐습니다", self.run_cli("sheet", "expand", csv,
                                                 "--col", "이름", "--sep", " "))
        self.assertIn("합쳤습니다", self.run_cli("sheet", "combine", csv,
                                                 "--cols", "이름,부서", "--into", "표시"))
        self.assertIn("열 구조가 같습니다",
                      self.run_cli("sheet", "diff", csv, csv, "--columns"))
        self.assertIn("다른 칸이 없습니다",
                      self.run_cli("sheet", "diff", csv, csv, "--cells"))
        내역 = self.path("변경내역.csv")
        self.run_cli("sheet", "diff", csv, self.path("급여.csv"),
                     "--key", "사번", "-o", 내역, expect=1)
        self.assertIn("무엇", Path(내역).read_text(encoding="utf-8-sig"))
        시트견줌 = self.run_cli("sheet", "diff", self.path("명단.xlsx"),
                             "--sheet", "직원", "--other-sheet", "직원",
                             "--key", "사번")
        self.assertIn("차이가 없습니다", 시트견줌)
        시트파일 = self.path("부서별.xlsx")
        self.run_cli("sheet", "split", csv, "--by", "부서",
                     "--sheets", 시트파일, "--apply")
        self.assertGreater(len(xlsx.sheet_names(Path(시트파일))), 1)
        self.assertIn("보이는", self.run_cli("sheet", "similar", csv, "-c", "이름"))
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

        거래처 = self.path("거래처.csv")
        Path(거래처).write_text("이름,사업자번호\n가게,124-81-00998\n나게,123-45-67890\n",
                                encoding="utf-8")
        self.assertIn("사업자번호 형식",
                      self.run_cli("sheet", "validate", 거래처,
                                   "--format", "사업자번호=사업자번호", expect=1))
        self.assertIn("월급", self.run_cli("sheet", "fx", csv,
                                           "--add", "월급=연봉/12", "--round", "0"))
        수식본 = self.path("수식.xlsx")
        self.run_cli("sheet", "fx", csv, "--add", "월급=연봉/12", "--formula",
                     "-o", 수식본)
        with zipfile.ZipFile(수식본) as z:
            안 = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("<f>", 안)
        그림 = self.path("부서별.svg")
        self.run_cli("sheet", "chart", csv, "--label", "부서", "--value", "연봉",
                     "-o", 그림)
        self.assertIn("<svg", Path(그림).read_text(encoding="utf-8"))
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
        Path(template).write_text("{이름:은/는} {부서:으로/로} 갑니다.\n",
                                   encoding="utf-8")
        text = self.run_cli("sheet", "fill", self.path("명단.csv"), "-t", template)
        self.assertIn("홍길동은", text)

    # ------------------------------------------------------------ json

    def test_json_group(self):
        one, two = self.path("응답1.json"), self.path("응답2.json")
        self.assertIn("users", self.run_cli("json", "schema", one))
        self.assertIn("타입 바뀜", self.run_cli("json", "diff", one, two, expect=1))
        self.assertIn("users[0].name", self.run_cli("json", "flat", one))
        self.assertIn("가", self.run_cli("json", "get", one, "users[0].name"))
        self.assertIn("9090", self.run_cli("json", "set", one, "config.port=9090"))
        self.run_cli("json", "show", one, "--sort")
        합친 = self.run_cli("json", "merge", one, two)
        타입 = self.run_cli("json", "types", one, "--name", "응답")
        self.assertIn("@dataclass", 타입)
        self.assertIn("export interface",
                      self.run_cli("json", "types", one, "--lang", "ts"))
        self.assertIn("겹쳤습니다", 합친)

    # ------------------------------------------------------------- dev

    def test_dev_group(self):
        self.assertIn("곳이 걸립니다",
                      self.run_cli("dev", "re", r"\d+", "주문 12건"))
        self.assertIn("빠진 키",
                      self.run_cli("dev", "env", self.path(".env.example"),
                                   self.path(".env"), expect=1))
        synced = self.run_cli("dev", "env", self.path(".env.example"),
                              self.path(".env"), "--sync")
        self.assertIn("DB_PASSWORD=<db_password>", synced)
        self.assertNotIn("비밀", synced)          # 비밀값이 새어 나가면 안 된다
        self.assertIn("ERROR", self.run_cli("dev", "log", self.path("app.log")))
        자름 = self.run_cli("dev", "log", self.path("app.log"),
                          "--since", "2026-09-01 10:00", "-o", self.path("자른.log"))
        self.assertIn("줄 중", 자름)
        self.assertTrue(Path(self.path("자른.log")).is_file())
        접근 = Path(self.path("access.log"))
        접근.write_text(
            '10.0.0.1 - - [01/Sep/2026:10:00:00 +0900] "GET /api/pay HTTP/1.1" 200 12 30ms\n'
            '10.0.0.2 - - [01/Sep/2026:10:00:01 +0900] "GET /api/pay HTTP/1.1" 500 12 900ms\n',
            encoding="utf-8")
        느림 = self.run_cli("dev", "slow", str(접근))
        self.assertIn("상태 코드", 느림)
        self.assertIn("5xx", 느림)
        # 레벨이 없는 접근 로그는 log 에서 볼 것이 없다 - 갈 곳을 알려 준다
        self.assertIn("at dev slow", self.run_cli("dev", "log", str(접근)))

        웹로그 = Path(self.path("web.log"))
        웹로그.write_text("2026-09-01 10:00:02 INFO GET /pay 500\n",
                        encoding="utf-8")
        줄기 = self.run_cli("dev", "timeline", self.path("app.log"), str(웹로그))
        self.assertIn("[web]", 줄기)
        self.assertIn("[app]", 줄기)
        죽은주소 = self.run_cli("dev", "health", "http://127.0.0.1:1/없음",
                              "--timeout", "1", expect=1)
        self.assertIn("안 되는 것 1개", 죽은주소)
        self.assertIn("성공", self.run_cli("dev", "retry", "--", "true"))

        저장소 = Path(self.path("받은저장소"))
        (저장소 / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        (저장소 / "pyproject.toml").write_text("[project]\nname='x'\n",
                                              encoding="utf-8")
        (저장소 / "tests").mkdir(exist_ok=True)
        (저장소 / "tests" / "test_x.py").write_text("", encoding="utf-8")
        (저장소 / ".github" / "workflows" / "ci.yml").write_text(
            "jobs:\n  a:\n    steps:\n      - run: python -m unittest\n",
            encoding="utf-8")
        훑음 = self.run_cli("dev", "doctor", str(저장소))
        self.assertIn("unittest discover -s tests", 훑음)
        self.assertIn("CI 가 돌리는 명령", 훑음)

        주소 = self.run_cli("dev", "url",
                          "https://api.example.com/v1/주문?q=%ED%99%8D&token=abc",
                          "--mask")
        self.assertIn("token=***", 주소)
        self.assertIn("홍", 주소)

        아이콘 = Path(self.path("아이콘.png"))
        아이콘.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        박기 = self.run_cli("dev", "enc", "--file", str(아이콘), "--data-uri")
        self.assertIn("data:image/png;base64,", 박기)
        self.run_cli("dev", "enc", "--file", str(아이콘),
                     "-o", self.path("아이콘.b64"))
        self.assertTrue(Path(self.path("아이콘.b64")).is_file())

        import sqlite3

        db = self.path("가게.db")
        conn = sqlite3.connect(db)
        conn.execute("CREATE TABLE 주문(번호 INTEGER PRIMARY KEY, 금액 INTEGER)")
        conn.execute("INSERT INTO 주문(금액) VALUES (1000)")
        conn.commit()
        conn.close()
        self.assertIn("주문", self.run_cli("dev", "db", db))
        self.assertIn("금액", self.run_cli("dev", "db", db, "--table", "주문"))
        self.assertIn("1000", self.run_cli("dev", "db", db, "-q",
                                           "select 금액 from 주문"))

        spec = self.path("openapi.json")
        Path(spec).write_text(json.dumps({
            "openapi": "3.0.0", "info": {"title": "주문 API", "version": "1.0"},
            "paths": {"/orders": {"get": {"summary": "목록",
                                          "responses": {"200": {}, "400": {}}}}},
        }, ensure_ascii=False), encoding="utf-8")
        self.assertIn("/orders", self.run_cli("dev", "api", spec))

        예시스펙 = self.path("openapi-example.json")
        Path(예시스펙).write_text(json.dumps({
            "openapi": "3.0.0", "info": {"title": "주문", "version": "1.0"},
            "paths": {"/orders": {"get": {"responses": {"200": {"content": {
                "application/json": {"schema": {"type": "object", "properties": {
                    "금액": {"type": "integer"}}}}}}}}}},
        }, ensure_ascii=False), encoding="utf-8")
        빈스펙 = self.path("openapi-empty.json")
        Path(빈스펙).write_text(json.dumps({"openapi": "3.0.0", "paths": {}}),
                              encoding="utf-8")
        # 서버를 띄우는 명령이라 여기서는 띄우기 전에 걸리는 자리만 본다
        self.assertIn("엔드포인트가 없습니다",
                      self.run_cli("dev", "mock", 빈스펙, expect=1))

        예시 = self.run_cli("dev", "api", 예시스펙, "--example")
        self.assertIn('"금액": 1', 예시)
        예시파일 = self.path("예시.json")
        self.run_cli("dev", "api", 예시스펙, "--example", "-o", 예시파일)
        self.assertIn("금액", Path(예시파일).read_text(encoding="utf-8"))

        옛스펙 = self.path("openapi-old.json")
        Path(옛스펙).write_text(json.dumps({
            "openapi": "3.0.0", "info": {"title": "주문 API", "version": "0.9"},
            "paths": {"/orders": {"get": {"responses": {"200": {}, "400": {}}}},
                      "/old": {"get": {"responses": {"200": {}}}}},
        }, ensure_ascii=False), encoding="utf-8")
        견줌 = self.run_cli("dev", "api", spec, "--diff", 옛스펙, expect=1)
        self.assertIn("사라진 엔드포인트", 견줌)

        옛락 = self.path("old-lock.json")
        새락 = self.path("new-lock.json")
        Path(옛락).write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "node_modules/react": {"version": "18.2.0"}}}), encoding="utf-8")
        Path(새락).write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "node_modules/react": {"version": "19.0.0"}}}), encoding="utf-8")
        소스 = Path(self.path("소스"))
        소스.mkdir()
        (소스 / "a.py").write_text("import os\nimport sys\n\nprint(sys.argv)\n",
                                   encoding="utf-8")
        self.assertIn("import os",
                      self.run_cli("dev", "unused", str(소스), expect=1))
        구조 = self.run_cli("dev", "outline", str(소스))
        self.assertIn("a.py", 구조)
        줄수 = self.run_cli("dev", "loc", str(소스))
        self.assertIn("파이썬", 줄수)
        관계 = self.run_cli("dev", "imports", str(소스))
        self.assertIn("고리", 관계)
        (소스 / "새것.py").write_text("import tomllib\n\nprint(tomllib)\n",
                                     encoding="utf-8")
        판 = self.run_cli("dev", "pyver", str(소스), "--target", "3.10", expect=1)
        self.assertIn("3.11", 판)
        self.assertIn("import tomllib", 판)
        인증서 = self.run_cli("dev", "cert", "127.0.0.1", "--port", "9",
                            "--timeout", "1", expect=1)
        self.assertIn("연결하지 못했습니다", 인증서)
        훑기 = self.run_cli("dev", "doctor", str(소스))
        self.assertIn("찾은 것만 적었습니다", 훑기)

        잠금 = self.run_cli("dev", "lock", 옛락, 새락)
        self.assertIn("react", 잠금)
        self.assertIn("맨 앞 숫자", 잠금)

        가짜 = self.path("시험자료.csv")
        만든것 = self.run_cli("dev", "fake", "-c", "이름", "-c", "연락처=전화",
                              "-n", "5", "--seed", "1", "-o", 가짜)
        self.assertIn("5행", 만든것)
        self.assertIn("010-", Path(가짜).read_text(encoding="utf-8"))
        느림 = self.run_cli("dev", "slow", self.path("app.log"))
        self.assertIn("p95", 느림)
        self.assertIn("900", 느림)
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
        내일 = self.run_cli("git", "mine", repo, "--since", "10 years ago")
        self.assertIn("커밋", 내일)
        이력 = self.run_cli("git", "history", "코드.py", repo)
        self.assertIn("커밋", 이력)
        주인 = self.run_cli("git", "owners", repo)
        self.assertIn("주로 만진 사람", 주인)
        self.assertIn("커밋 수로만 셉니다", 주인)
        훅 = self.run_cli("git", "hook", repo)
        self.assertIn("없음", 훅)
        self.run_cli("git", "hook", repo, "--install", "--apply")
        self.assertIn("우리 것", self.run_cli("git", "hook", repo))
        self.run_cli("git", "hook", repo, "--remove", "--apply")
        self.assertIn("커밋", self.run_cli("git", "stats", repo))
        self.assertIn("새 기능", self.run_cli("git", "release", repo))
        self.assertIn("브랜치", self.run_cli("git", "branches", repo))
        self.run_cli("git", "sweep", repo)
        self.assertIn("충돌 표시가 없습니다", self.run_cli("git", "conflicts", repo))
        self.assertIn("스테이징된 파일이 없습니다",
                      self.run_cli("git", "ready", repo, expect=1))
        self.assertIn("판본", self.run_cli("git", "heavy", repo, "--top", "3"))

    # ------------------------------------------------------------- doc

    def test_doc_group(self):
        md = self.path("문서.md")
        self.assertIn("하나", self.run_cli("doc", "toc", md))
        self.run_cli("doc", "toc", md, "--apply")
        self.assertIn("#하나", Path(md).read_text(encoding="utf-8"))
        self.run_cli("doc", "links", md)
        self.run_cli("doc", "check", md)

        조각들 = Path(self.path("조각"))
        조각들.mkdir(exist_ok=True)
        (조각들 / "01.md").write_text("# 하나\n\n첫\n", encoding="utf-8")
        (조각들 / "02.md").write_text("# 둘\n\n둘째\n", encoding="utf-8")
        합본 = self.run_cli("doc", "merge", str(조각들), "--shift", "1",
                          "--title", "합본", "-o", self.path("합본.md"))
        self.assertIn("저장", 합본)
        self.assertIn("## 하나",
                      Path(self.path("합본.md")).read_text(encoding="utf-8"))

        out = self.path("쪼갠글")
        self.assertIn("--apply", self.run_cli("doc", "split", md, "-o", out))
        self.assertFalse(Path(out).exists())
        self.run_cli("doc", "split", md, "-o", out, "--apply")
        made = sorted(q.name for q in Path(out).iterdir())
        self.assertTrue(made and made[0].startswith("01-"), made)

        self.assertIn("표를 찾지 못했습니다",
                      self.run_cli("doc", "tables", md, expect=1))

        표 = Path(self.path("표.md"))
        표.write_text("| 이름 | 값 |\n|---|---|\n| 가나다 | 1 |\n",
                      encoding="utf-8")
        self.assertIn("--apply", self.run_cli("doc", "table", str(표)))
        self.run_cli("doc", "table", str(표), "--apply")
        from attools.docs.mdkit import display_width

        줄 = 표.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len({display_width(l) for l in 줄}), 1)
        그림문서 = Path(self.path("그림문서.md"))
        그림문서.write_text("# 안내\n\n![없음](그림/사라진것.png)\n", encoding="utf-8")
        워드 = self.path("문서.docx")
        self.run_cli("doc", "docx", md, "-o", 워드)
        with zipfile.ZipFile(워드) as z:
            self.assertIn("word/document.xml", z.namelist())
        워드2 = self.path("문서2.docx")
        self.run_cli("doc", "docx", md, "-o", 워드2)
        견줌 = self.run_cli("text", "diff", 워드, 워드2, expect=0)
        self.assertIn("워드·한글 문서는 문단 글자만", 견줌)

        한글문서 = Path(self.path("계획서.hwpx"))
        with zipfile.ZipFile(한글문서, "w") as z:
            z.writestr("mimetype", "application/hwp+zip")
            z.writestr("Contents/section0.xml",
                       "<hs:sec xmlns:hs='s' xmlns:hp='p'>"
                       "<hp:p><hp:run><hp:t>사업 계획서</hp:t></hp:run></hp:p>"
                       "<hp:p><hp:run><hp:tbl><hp:tr>"
                       "<hp:tc><hp:p><hp:run><hp:t>항목</hp:t></hp:run></hp:p></hp:tc>"
                       "<hp:tc><hp:p><hp:run><hp:t>금액</hp:t></hp:run></hp:p></hp:tc>"
                       "</hp:tr><hp:tr>"
                       "<hp:tc><hp:p><hp:run><hp:t>인건비</hp:t></hp:run></hp:p></hp:tc>"
                       "<hp:tc><hp:p><hp:run><hp:t>1000</hp:t></hp:run></hp:p></hp:tc>"
                       "</hp:tr></hp:tbl></hp:run></hp:p></hs:sec>")
        한글옮김 = self.run_cli("doc", "from-hwpx", str(한글문서))
        self.assertIn("사업 계획서", 한글옮김)
        self.assertIn("| 항목 | 금액 |", 한글옮김)
        한글표 = self.run_cli("sheet", "from-hwpx", str(한글문서))
        self.assertIn("인건비", 한글표)

        슬라이드 = Path(self.path("발표.pptx"))
        P = "http://schemas.openxmlformats.org/presentationml/2006/main"
        A = "http://schemas.openxmlformats.org/drawingml/2006/main"
        with zipfile.ZipFile(슬라이드, "w") as z:
            z.writestr("ppt/slides/slide1.xml",
                       f'<?xml version="1.0"?><p:sld xmlns:p="{P}" xmlns:a="{A}">'
                       "<p:cSld><p:spTree><p:sp><p:txBody>"
                       "<a:p><a:r><a:t>사업 계획</a:t></a:r></a:p>"
                       "<a:p><a:r><a:t>매출 30억</a:t></a:r></a:p>"
                       "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")
        슬라이드옮김 = self.run_cli("doc", "from-pptx", str(슬라이드))
        self.assertIn("## 1. 사업 계획", 슬라이드옮김)
        self.assertIn("매출 30억", 슬라이드옮김)

        되돌린 = self.run_cli("doc", "from-docx", 워드)
        self.assertIn("하나", 되돌린)
        표뽑기 = self.run_cli("sheet", "from-docx", 워드, expect=1)
        self.assertIn("표가 없습니다", 표뽑기)
        되돌린 = self.run_cli("doc", "from-docx", 워드)
        self.assertIn("하나", 되돌린)

        웹문서 = Path(self.path("웹문서.html"))
        웹문서.write_text("<h1>안내</h1><p>웹에서 <b>복사</b>한 글.</p>",
                          encoding="utf-8")
        옮김 = self.path("옮긴글.md")
        self.run_cli("doc", "from-html", str(웹문서), "-o", 옮김)
        self.assertIn("# 안내", Path(옮김).read_text(encoding="utf-8"))

        목록 = self.run_cli("doc", "index", self.path())
        self.assertIn("](", 목록)

        발표 = Path(self.path("발표.md"))
        발표.write_text("# 제목\n\n발표자\n\n---\n\n## 첫 장\n\n- 하나\n",
                        encoding="utf-8")
        슬라이드 = self.path("발표.html")
        self.assertIn("2장", self.run_cli("doc", "slides", str(발표), "-o", 슬라이드))
        self.assertIn("<section>", Path(슬라이드).read_text(encoding="utf-8"))

        html출력 = self.path("문서.html")
        self.run_cli("doc", "html", md, "-o", html출력, "--toc")
        만든것 = Path(html출력).read_text(encoding="utf-8")
        self.assertIn("<h1", 만든것)
        self.assertIn("@media print", 만든것)

        점검 = self.run_cli("doc", "lint", md)
        self.assertIn("문서 1개를 봤습니다", 점검)

        회의록 = Path(self.path("회의록.md"))
        회의록.write_text("# 회의\n\n## 결정\n- [ ] 계약서 검토 @홍길동 2026-01-05\n"
                        "- [x] 자료 취합\n", encoding="utf-8")
        할일 = self.run_cli("doc", "todo", str(회의록), expect=1)   # 기한이 지났다
        self.assertIn("홍길동", 할일)
        self.assertIn("지남", 할일)

        # 회의록을 .txt 로 적는 사람이 많다. 조용히 빼지 않고 --txt 로 본다
        회의폴더 = Path(self.path("회의록모음"))
        회의폴더.mkdir(exist_ok=True)
        (회의폴더 / "3월회의.txt").write_text(
            "회의\n- [ ] 자료 정리 @김철수 2026-01-05\n", encoding="utf-8")
        빠짐 = self.run_cli("doc", "todo", str(회의폴더), expect=1)
        self.assertIn("--txt", 빠짐)
        본것 = self.run_cli("doc", "todo", str(회의폴더), "--txt", expect=1)
        self.assertIn("김철수", 본것)

        크기 = self.run_cli("doc", "stats", md)
        self.assertIn("읽기(분)", 크기)
        self.assertIn("문서.md", 크기)

        용어문서 = Path(self.path("용어.md"))
        용어문서.write_text("API 설명. api 사용. Api 응답.\n", encoding="utf-8")
        self.assertIn("대소문자",
                      self.run_cli("doc", "terms", str(용어문서), expect=1))

        이미지 = self.run_cli("doc", "images", str(그림문서), expect=1)
        self.assertIn("없음", 이미지)
        self.assertIn("없는 파일 1개", 이미지)

        뽑기 = self.path("뽑은표.csv")
        self.run_cli("doc", "tables", str(표), "-n", "1", "-o", 뽑기)
        self.assertIn("가나다", Path(뽑기).read_text(encoding="utf-8"))

    # ------------------------------------------------------------ life

    def test_life_group(self):
        self.assertIn("D+", self.run_cli("life", "dday", "2024-03-15",
                                         "--today", "2026-09-04"))
        self.assertIn("1인당", self.run_cli("life", "split", "가=30000", "나=10000"))
        self.assertIn("매달", self.run_cli("life", "loan", "3억", "4.2", "30"))
        self.assertIn("평", self.run_cli("life", "unit", "84㎡"))
        self.assertIn("영업일", self.run_cli("life", "workday", "2026-08-14", "+5"))
        self.assertIn("퇴직금", self.run_cli("life", "severance", "2020-03-02",
                                          "2026-09-01", "--pay", "1500만"))
        self.assertIn("연차", self.run_cli("life", "annual", "2020-03-02",
                                          "--on", "2026-09-07", "--table", "2"))
        self.assertIn("부가세", self.run_cli("life", "tax", "1100000"))
        시급 = self.run_cli("life", "hourly", "300만", "--overtime", "10")
        self.assertIn("통상시급", 시급)
        self.assertIn("연장 10시간", 시급)
        주휴 = self.run_cli("life", "weekly", "10030", "--hours", "20")
        self.assertIn("주휴수당", 주휴)
        self.assertIn("계산식", 주휴)
        self.assertIn("15시간 미만",
                      self.run_cli("life", "weekly", "10030", "--hours", "10"))
        self.assertIn("월세", self.run_cli("life", "rent", "--deposit", "5억",
                                           "--keep", "1억"))
        self.assertIn("일금", self.run_cli("life", "won", "125만"))
        근무 = self.run_cli("life", "time", "09:00-18:30", "--break", "60")
        self.assertIn("8시간 30분", 근무)
        self.assertIn("12:20", self.run_cli("life", "time", "09:00", "+3h20m"))
        시차 = self.run_cli("life", "tz", "14:00", "--to", "뉴욕", "--overlap", "뉴욕")
        self.assertIn("America/New_York", 시차)
        self.assertIn("겹치는", 시차)
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
        # 원고는 화마다 파일로 나눠 둔다 - 폴더째 볼 수 있어야 한다
        묶음 = self.run_cli("novel", "check", self.path("원고"))
        self.assertIn("파일", 묶음)
        self.assertIn("장면", self.run_cli("novel", "outline", 원고, "--min", "20"))
        self.assertIn("리안", self.run_cli("novel", "find", "리안", 원고,
                                           "--min", "20"))
        self.assertIn("조사", self.run_cli("novel", "names", 원고, "--min", "2",
                                           expect=1))
        self.assertIn("시간", self.run_cli("novel", "timeline", 원고, "--min", "20"))
        self.assertIn("대사", self.run_cli("novel", "dialogue", 원고, "--min", "2"))
        # 짧아서 뺀 덩어리는 조용히 사라지지 않고 몇 개인지 말해야 한다
        장면원고 = Path(self.path("장면원고"))
        장면원고.mkdir(exist_ok=True)
        (장면원고 / "01화.txt").write_text(
            "가나다라마바사아자차카타파하" * 10 + "\n\n＊\n\n짧은 장면.\n",
            encoding="utf-8")
        장면 = self.run_cli("novel", "outline", str(장면원고), "--min", "100")
        self.assertIn("짧아 세지 않은 덩어리 1개", 장면)
        self.assertIn("어휘", self.run_cli("novel", "wordlist", 원고, "--min", "2"))
        self.run_cli("novel", "style", 원고)
        self.assertIn("화별", self.run_cli("novel", "cast", 원고, "--min", "2"))
        self.run_cli("novel", "tidy", 원고, "--scene-mark", "＊")
        self.assertIn("따옴표", self.run_cli("novel", "quote", 원고))

        # 문장 부호 고치기도 원고를 바꾸므로 따로 만든 원고에서 한다
        부호원고 = Path(self.path("부호원고"))
        부호원고.mkdir(exist_ok=True)
        (부호원고 / "01화.txt").write_text(
            "그는 말했다... 아니, 그게 아니라...\n갔다.그리고 잤다 . 끝\n",
            encoding="utf-8")
        본 = self.run_cli("novel", "punct", str(부호원고))
        self.assertIn("줄임표", 본)
        self.assertIn("미리보기", 본)
        self.run_cli("novel", "punct", str(부호원고), "--apply")
        고친글 = (부호원고 / "01화.txt").read_text(encoding="utf-8")
        self.assertIn("말했다……", 고친글)
        self.assertIn("갔다. 그리고 잤다. 끝", 고친글)

        # 이름 바꾸기는 원고를 고치므로 다른 시험이 쓰는 원고는 건드리지 않는다
        바꿀원고 = Path(self.path("이름바꿀원고"))
        바꿀원고.mkdir(exist_ok=True)
        (바꿀원고 / "01화.txt").write_text(
            "리안은 성문 앞에 섰다. 리안이 말했다.\n리안느는 다른 사람이다.\n",
            encoding="utf-8")
        이름바꿈 = self.run_cli("novel", "rename", "리안", "세하", str(바꿀원고))
        self.assertIn("리안은 -> 세하는", 이름바꿈)
        self.assertIn("미리보기", 이름바꿈)
        self.run_cli("novel", "rename", "리안", "세하", str(바꿀원고), "--apply")
        고친원고 = (바꿀원고 / "01화.txt").read_text(encoding="utf-8")
        self.assertIn("세하는", 고친원고)
        self.assertIn("리안느는", 고친원고)      # 다른 낱말은 그대로
        메모원고 = Path(self.path("원고")) / "메모화.md"
        메모원고.write_text("# 9화\n\n첫 문단. [[보강]]\n", encoding="utf-8")
        self.assertIn("보강", self.run_cli("novel", "notes", str(메모원고), expect=1))
        self.run_cli("novel", "notes", str(메모원고), "--remove", "--apply")
        self.assertNotIn("[[", 메모원고.read_text(encoding="utf-8"))

        대사 = self.run_cli("novel", "say", 원고, "--min", "1")
        self.assertIn("인물", 대사)

        통원고 = Path(self.path("통원고.txt"))
        통원고.write_text("들어가는 말.\n\n제1화 만남\n\n첫 문단.\n\n"
                          "2화 이별\n\n둘째 문단.\n", encoding="utf-8")
        화별 = self.path("화별")
        self.assertIn("--apply", self.run_cli("novel", "split", str(통원고),
                                              "-o", 화별))
        self.run_cli("novel", "split", str(통원고), "-o", 화별, "--apply")
        self.assertTrue((Path(화별) / "01-만남.md").is_file())
        self.run_cli("novel", "snap", 원고, "--note", "시험")
        out = self.run_cli("novel", "pace", 원고, "--goal", "100매")
        self.assertIn("스냅샷 1개", out)
        self.assertIn("속도를 계산할 수 없습니다", out)

    def test_novel_export_docx(self):
        import zipfile

        out = self.path("투고본.docx")
        self.run_cli("novel", "export", self.path("원고"), "-f", "docx",
                     "--title", "시험작", "-o", out)
        with zipfile.ZipFile(out) as z:
            self.assertIn("word/document.xml", z.namelist())

    def test_outputs_do_not_overwrite_silently(self):
        """-o 로 낼 때 있는 파일을 말없이 덮으면 원본이 사라진다."""
        soft = Path(self.path("소중한파일"))
        cases = [
            ("sheet", "to-json", self.path("명단.csv"), "-o", str(soft) + ".json"),
            ("sheet", "to-sql", self.path("명단.csv"), "-t", "t",
             "-o", str(soft) + ".sql"),
            ("sheet", "report", self.path("명단.csv"), "-o", str(soft) + ".html"),
        ]
        for args in cases:
            target = Path(args[-1])
            target.write_text("소중한 내용", encoding="utf-8")
            out = self.run_cli(*args, expect=1)
            self.assertIn("이미 있는 파일", out)
            self.assertEqual(target.read_text(encoding="utf-8"), "소중한 내용")
            self.run_cli(*args, "--overwrite")
            self.assertNotEqual(target.read_text(encoding="utf-8"), "소중한 내용")

    def test_fill_names_never_overwrite(self):
        """이름이 겹치면 덮어써서 한 건이 통째로 사라진다."""
        명단 = Path(self.path("겹친명단.csv"))
        명단.write_text("이름,값\n홍길동,1\n홍길동,2\n", encoding="utf-8")
        틀 = Path(self.path("짧은틀.md"))
        틀.write_text("{이름} 님 {값}\n", encoding="utf-8")
        나온 = Path(self.path("채운것"))
        out = self.run_cli("sheet", "fill", str(명단), "-t", str(틀),
                           "-o", str(나온), "--name", "{이름}.md", "--apply")
        self.assertIn("이름이 겹쳐", out)
        self.assertEqual(len(list(나온.glob("*.md"))), 2)

    def test_folder_output_does_not_replace_what_is_there(self):
        """앞서 만들어 고쳐 둔 초안을 말없이 지우면 사라진 줄 모른다."""
        명단 = Path(self.path("초안명단.csv"))
        명단.write_text("이름,메일\n홍길동,a@b.com\n", encoding="utf-8")
        틀 = Path(self.path("초안틀.md"))
        틀.write_text("{이름} 님\n", encoding="utf-8")
        나온 = Path(self.path("초안함"))
        self.run_cli("sheet", "mail", str(명단), "-t", str(틀), "--to", "메일",
                     "--subject", "{이름} 님", "-o", str(나온), "--apply")
        만든 = next(나온.glob("*.eml"))
        만든.write_text("사람이 고친 초안", encoding="utf-8")
        out = self.run_cli("sheet", "mail", str(명단), "-t", str(틀), "--to", "메일",
                           "--subject", "{이름} 님", "-o", str(나온), "--apply",
                           expect=1)
        self.assertIn("이미 있는 파일", out)
        self.assertEqual(만든.read_text(encoding="utf-8"), "사람이 고친 초안")

    def test_mail_names_never_overwrite(self):
        """받는 사람이 같으면 파일 이름도 같아진다 - 덮어쓰면 한 건이 사라진다."""
        명단 = Path(self.path("같은메일.csv"))
        명단.write_text("이름,메일\n홍길동,a@b.com\n김철수,a@b.com\n",
                      encoding="utf-8")
        틀 = Path(self.path("메일틀.md"))
        틀.write_text("{이름} 님\n", encoding="utf-8")
        나온 = Path(self.path("메일함"))
        out = self.run_cli("sheet", "mail", str(명단), "-t", str(틀),
                           "--to", "메일", "--subject", "{이름} 님",
                           "-o", str(나온), "--name", "{받는사람}.eml", "--apply")
        self.assertIn("이름이 겹쳐", out)
        self.assertEqual(len(list(나온.glob("*.eml"))), 2)

    def test_novel_export_epub(self):
        import zipfile

        out = self.path("투고본.epub")
        self.run_cli("novel", "export", self.path("원고"), "-f", "epub",
                     "--title", "시험작", "-o", out)
        with zipfile.ZipFile(out) as z:
            self.assertEqual(z.infolist()[0].filename, "mimetype")
            self.assertIn("OEBPS/content.opf", z.namelist())

    # -------------------------------------------------------------- ui

    def test_ui_group(self):
        out = self.run_cli("ui", "--list")
        self.assertIn("파일 정리", out)
        self.run_cli("ui", "없는화면", expect=1)

    def test_novel_export(self):
        out = self.path("투고본.html")
        self.run_cli("novel", "export", self.path("원고"), "--title", "제목",
                     "-o", out)
        html = Path(out).read_text(encoding="utf-8")
        self.assertIn("제목", html)
        self.assertIn("<h2", html)


if __name__ == "__main__":
    unittest.main()
