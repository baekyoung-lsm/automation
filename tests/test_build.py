"""한 파일로 묶기(build.py) 시험.

폴더로 두고 쓸 때는 되는데 묶으면 깨지는 자리가 있다 - data/ 를 Path 로 읽던
곳이 그랬다. 그것은 여기서만 잡힌다. 그래서 실제로 묶어 실제로 돌려 본다.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build

ROOT = Path(__file__).resolve().parents[1]


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pyz = build.build(Path(cls.tmp.name) / "at.pyz")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_pyz(self, *args, expect: int = 0) -> str:
        done = subprocess.run([sys.executable, str(self.pyz), *args],
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, expect,
                         f"at {' '.join(args)}\n{done.stdout}{done.stderr}")
        return done.stdout

    def test_archive_carries_data_and_no_cache(self):
        with zipfile.ZipFile(self.pyz) as zf:
            names = zf.namelist()
        self.assertIn("attools/data/shortcuts.json", names)
        self.assertIn("__main__.py", names)
        self.assertFalse([n for n in names if "__pycache__" in n])

    def test_runs_without_the_repo(self):
        """저장소 밖에서, 딴 폴더에서 돌아가야 나눠 줄 수 있다."""
        out = subprocess.run([sys.executable, str(self.pyz), "--version"],
                             capture_output=True, text=True, cwd=self.tmp.name,
                             timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("attools", out.stdout)

    def test_packaged_data_is_readable(self):
        """zip 안의 data/ 를 Path 로 읽으면 여기서 터진다."""
        self.assertIn("Ctrl+C", self.run_pyz("keys", "--group", "문서"))

    def test_real_work_runs(self):
        work = Path(self.tmp.name) / "일감" / "다운로드"
        work.mkdir(parents=True)
        (work / "Screenshot 1.png").write_bytes(b"\x89PNG" * 4)
        (work / "보고서.pdf").write_bytes(b"%PDF" * 4)
        out = self.run_pyz("file", "sweep", str(work))
        self.assertIn("스크린샷", out)

    def test_help_is_korean(self):
        self.assertIn("옮기기", self.run_pyz("file", expect=1))


if __name__ == "__main__":
    unittest.main()
