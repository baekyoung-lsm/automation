"""Dockerfile 훑기 시험. 오탐이 나면 아무도 안 보게 되는 종류의 도구다."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import dockerkit

GOOD = """# 빌드 단계
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \\
 && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/lib /usr/local/lib
COPY . .
USER nobody
CMD ["python", "app.py"]
"""


def kinds(report) -> list[str]:
    return [one.what for one in report.notes]


class ParseTest(unittest.TestCase):
    def test_continued_lines_are_one_step(self):
        steps = dockerkit.parse("RUN apt-get update \\\n && apt-get install -y curl\n")
        self.assertEqual(len(steps), 1)
        self.assertIn("apt-get install", steps[0].value)
        self.assertEqual(steps[0].line, 1)

    def test_comments_and_blank_lines_are_skipped(self):
        steps = dockerkit.parse("# 주석\n\nFROM alpine:3.20\n")
        self.assertEqual([s.instruction for s in steps], ["FROM"])

    def test_stages_are_counted(self):
        steps = dockerkit.parse("FROM a:1 AS build\nRUN x\nFROM b:2\nRUN y\n")
        self.assertEqual([s.stage for s in steps], [1, 1, 2, 2])


class CheckTest(unittest.TestCase):
    def test_a_careful_dockerfile_gets_nothing(self):
        """오탐이 하나라도 나면 이 명령을 아무도 안 보게 된다."""
        report = dockerkit.check(GOOD, has_dockerignore=True)
        self.assertEqual(kinds(report), [])
        self.assertEqual(report.stages, 2)

    def test_latest_tag_and_no_tag(self):
        self.assertIn("FROM python:latest",
                      kinds(dockerkit.check("FROM python:latest\nUSER x\n")))
        self.assertIn("FROM python",
                      kinds(dockerkit.check("FROM python\nUSER x\n")))

    def test_a_registry_port_is_not_a_tag(self):
        """registry:5000/app:1.2 를 «태그 없음» 으로 세면 오탐이다."""
        report = dockerkit.check("FROM registry:5000/app:1.2\nUSER x\n")
        self.assertEqual(kinds(report), [])
        report = dockerkit.check("FROM registry:5000/app\nUSER x\n")
        self.assertEqual(kinds(report), ["FROM registry:5000/app"])

    def test_a_digest_is_fixed_enough(self):
        report = dockerkit.check("FROM python@sha256:abc123\nUSER x\n")
        self.assertEqual(kinds(report), [])

    def test_running_as_root(self):
        report = dockerkit.check("FROM python:3.12\n")
        self.assertIn("USER 가 없음", kinds(report))

    def test_user_in_an_earlier_stage_does_not_count(self):
        """앞 단계의 USER 는 마지막 이미지와 상관없다."""
        report = dockerkit.check(
            "FROM a:1 AS build\nUSER nobody\nFROM b:2\nCMD [\"x\"]\n")
        self.assertIn("USER 가 없음", kinds(report))

    def test_secret_in_env_but_not_a_placeholder(self):
        self.assertIn("ENV 에 비밀값",
                      kinds(dockerkit.check("FROM a:1\nENV DB_PASSWORD=hunter2secret\nUSER x\n")))
        # 값이 비었거나 다른 데서 받아 오는 것은 비밀값이 아니다
        for line in ("ENV DB_PASSWORD=", "ENV DB_PASSWORD=${DB_PASSWORD}",
                     "ENV DB_PASSWORD=changeme", "ARG TOKEN=$TOKEN"):
            self.assertEqual(
                kinds(dockerkit.check(f"FROM a:1\n{line}\nUSER x\n")), [], line)

    def test_apt_update_split_from_install(self):
        report = dockerkit.check(
            "FROM a:1\nRUN apt-get update\nRUN apt-get install -y curl\nUSER x\n")
        self.assertIn("apt-get install 만 따로", kinds(report))

    def test_copy_all_before_install_breaks_the_cache(self):
        report = dockerkit.check(
            "FROM a:1\nCOPY . .\nRUN npm ci\nUSER x\n")
        self.assertIn("전부 복사한 뒤 설치", kinds(report))

    def test_copying_only_the_manifest_first_is_fine(self):
        report = dockerkit.check(
            "FROM a:1\nCOPY package.json .\nRUN npm ci\nCOPY . .\nUSER x\n")
        self.assertEqual(kinds(report), [])

    def test_two_cmds(self):
        report = dockerkit.check(
            'FROM a:1\nUSER x\nCMD ["a"]\nCMD ["b"]\n')
        self.assertIn("CMD 가 여러 개", kinds(report))

    def test_cmd_in_each_stage_is_fine(self):
        report = dockerkit.check(
            'FROM a:1 AS build\nCMD ["a"]\nFROM b:2\nUSER x\nCMD ["b"]\n')
        self.assertEqual(kinds(report), [])

    def test_add_from_a_url(self):
        report = dockerkit.check(
            "FROM a:1\nADD https://example.com/x.tar.gz /tmp/\nUSER x\n")
        self.assertIn("ADD 로 내려받기", kinds(report))

    def test_problems_and_advice_are_told_apart(self):
        report = dockerkit.check("FROM python:latest\nRUN pip install x\nUSER y\n")
        self.assertEqual([one.what for one in report.problems],
                         ["FROM python:latest"])

    def test_an_empty_file_has_no_steps(self):
        self.assertEqual(dockerkit.check("").steps, [])
        self.assertEqual(dockerkit.check("").notes, [])


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_dockerignore_next_to_the_file_is_seen(self):
        path = self.root / "Dockerfile"
        path.write_text(GOOD, encoding="utf-8")
        self.assertIn(".dockerignore 가 없음", kinds(dockerkit.read(path)))
        (self.root / ".dockerignore").write_text(".git\n", encoding="utf-8")
        self.assertEqual(kinds(dockerkit.read(path)), [])


if __name__ == "__main__":
    unittest.main()
