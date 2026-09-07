"""새로 받은 저장소 훑기 시험 - 찾은 것만 말하는지."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import project


class InspectTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, name, body=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def find(self, report, name):
        return next((f for f in report.findings if f.name == name), None)

    def test_unknown_project_says_so(self):
        report = project.inspect(self.root)
        found = self.find(report, "알 수 없음")
        self.assertIsNotNone(found)
        self.assertIsNone(found.ok)          # 짐작하지 않는다
        self.assertEqual(report.steps, [])

    def test_python_marker(self):
        self.make("pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
        report = project.inspect(self.root)
        self.assertEqual(self.find(report, "파이썬").detail, "pyproject.toml")
        self.assertEqual(self.find(report, "파이썬 요구 판").detail, ">=3.10")
        self.assertTrue(report.steps)

    def test_node_engine_is_read(self):
        self.make("package.json", '{"engines": {"node": ">=20"}}')
        report = project.inspect(self.root)
        self.assertEqual(self.find(report, "노드 요구 판").detail, ">=20")

    def test_broken_package_json_does_not_raise(self):
        self.make("package.json", "{망가진 json")
        report = project.inspect(self.root)
        self.assertEqual(self.find(report, "노드").detail, "package.json")
        self.assertIsNone(self.find(report, "노드 요구 판"))

    def test_missing_env_is_reported_with_a_step(self):
        self.make(".env.example", "API_KEY=바꾸세요\n")
        report = project.inspect(self.root)
        found = self.find(report, ".env")
        self.assertFalse(found.ok)
        self.assertTrue(any("cp .env.example" in s for s in report.steps))

    def test_env_present_is_not_a_problem(self):
        self.make(".env.example", "A=1\n")
        self.make(".env", "A=2\n")
        self.assertTrue(self.find(project.inspect(self.root), ".env").ok)

    def test_npm_scripts_and_make_targets(self):
        self.make("package.json", '{"scripts": {"dev": "vite", "test": "vitest"}}')
        self.make("Makefile", "run:\n\tnpm run dev\n.PHONY: run\ntest:\n\techo\n")
        report = project.inspect(self.root)
        self.assertEqual(self.find(report, "npm 스크립트").detail, "dev, test")
        # .PHONY 는 목표가 아니다
        self.assertEqual(self.find(report, "Makefile").detail, "run, test")

    def test_install_traces(self):
        (self.root / "node_modules").mkdir()
        self.assertEqual(self.find(project.inspect(self.root), "노드 패키지").detail,
                         "node_modules/ 있음")

    def test_not_a_git_repo_is_unknown_not_a_failure(self):
        found = self.find(project.inspect(self.root), "저장소")
        self.assertIsNone(found.ok)

    def test_uncommitted_changes_are_not_a_missing_thing(self):
        import subprocess

        subprocess.run(["git", "init", "-q"], cwd=self.root,
                       capture_output=True, text=True)
        self.make("가.txt", "내용")
        report = project.inspect(self.root)
        changed = self.find(report, "커밋 안 된 변경")
        self.assertTrue(changed.ok)          # 그냥 지금 상태다
        self.assertIn("1개", changed.detail)


if __name__ == "__main__":
    unittest.main()
