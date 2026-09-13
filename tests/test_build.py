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

    def test_module_entry_runs(self):
        """at.bat 이 소스 폴더에서 부르는 길. 여기서 막히면 .bat 도 막힌다."""
        done = subprocess.run([sys.executable, "-m", "attools.cli", "--version"],
                              capture_output=True, text=True, cwd=str(ROOT),
                              timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("attools", done.stdout)

    def test_windows_helpers_ship_next_to_the_archive(self):
        made = build.copy_windows(self.pyz)
        self.assertEqual([p.name for p in made], list(build.WINDOWS_FILES))
        for path in made:
            self.assertTrue(path.is_file(), path)

    def test_bat_files_are_utf8_and_crlf(self):
        """cp949 로 저장되거나 LF 로 바뀌면 윈도우에서 글자가 깨지거나 줄이 밀린다."""
        for name in build.WINDOWS_FILES:
            raw = (ROOT / name).read_bytes()
            text = raw.decode("utf-8")          # cp949 로 저장되면 여기서 터진다
            self.assertIn("chcp 65001", text, name)
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), name)

    def test_bat_knows_both_ways_to_run(self):
        """소스 폴더 옆에 둘 때와 .pyz 옆에 둘 때가 다르다. 둘 다 있어야 한다."""
        text = (ROOT / "at.bat").read_text(encoding="utf-8")
        self.assertIn("attools.cli", text)
        self.assertIn("at.pyz", text)


if __name__ == "__main__":
    unittest.main()
