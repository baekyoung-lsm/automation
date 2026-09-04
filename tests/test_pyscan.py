"""파이썬 소스 훑기 시험 - 안 쓰는 import, 아무도 안 부르는 모듈."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import pyscan


class UnusedImportTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, body: str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_finds_unused_import(self):
        path = self.write("a.py", "import os\nimport sys\n\nprint(sys.argv)\n")
        found = pyscan.unused_imports(path)
        self.assertEqual([(u.name, u.line) for u in found], [("os", 1)])

    def test_attribute_use_counts(self):
        path = self.write("a.py", "import os.path\n\nprint(os.path.join('a'))\n")
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_alias_is_tracked(self):
        path = self.write("a.py", "import numpy as np\nimport json as j\n\nnp.array\n")
        self.assertEqual([u.name for u in pyscan.unused_imports(path)], ["j"])

    def test_name_in_dunder_all_counts_as_used(self):
        path = self.write("a.py", 'from x import 가\n\n__all__ = ["가"]\n')
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_string_annotation_counts_as_used(self):
        path = self.write("a.py", 'from x import Thing\n\ndef f(a: "Thing"): ...\n')
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_future_import_is_never_reported(self):
        path = self.write("a.py", "from __future__ import annotations\n")
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_star_import_is_not_judged(self):
        path = self.write("a.py", "from x import *\n")
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_ignore_mark_silences_a_line(self):
        path = self.write("a.py", "import os  # attools:ignore\n")
        self.assertEqual(pyscan.unused_imports(path), [])

    def test_init_is_skipped_by_default(self):
        path = self.write("pkg/__init__.py", "from .a import 가\n")
        self.assertEqual(pyscan.unused_imports(path), [])
        self.assertEqual(len(pyscan.unused_imports(path, skip_init=False)), 1)

    def test_broken_file_is_skipped_quietly(self):
        path = self.write("a.py", "def (:\n")
        self.assertEqual(pyscan.unused_imports(path), [])


class ModuleUseTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "pkg"
        self.root.mkdir(parents=True)
        (self.root / "__init__.py").write_text("", encoding="utf-8")
        (self.root / "core.py").write_text("값 = 1\n", encoding="utf-8")
        (self.root / "user.py").write_text("from .core import 값\n\nprint(값)\n",
                                           encoding="utf-8")
        (self.root / "혼자.py").write_text("값 = 2\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def test_imported_module_is_not_orphan(self):
        uses = {m.module: m for m in pyscan.module_uses(self.root)}
        self.assertFalse(uses["pkg.core"].orphan)
        self.assertIn("pkg.user", uses["pkg.core"].imported_by)

    def test_module_nobody_imports_is_orphan(self):
        uses = {m.module: m for m in pyscan.module_uses(self.root)}
        self.assertTrue(uses["pkg.혼자"].orphan)

    def test_skips_cache_directories(self):
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "x.py").write_text("import os\n", encoding="utf-8")
        self.assertNotIn("x", [p.stem for p in pyscan.iter_python(self.root)])


class OutlineTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / "a.py"
        body = [
            '"""모듈 설명."""',
            "",
            "import os",
            "",
            "",
            "class 가게:",
            '    """설명 있는 클래스."""',
            "",
            "    def 열다(self):",
            '        """설명."""',
            "        return 1",
            "",
            "    def _닫다(self):",
            "        return 2",
            "",
            "",
            "def 긴함수():",
            "    x = 0",
        ] + ["    x += 1"] * 6 + [
            "    return x",
            "",
            "",
            "def _숨은함수():",
            "    return 0",
            "",
        ]
        self.path.write_text("\n".join(body), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_lists_classes_methods_and_functions(self):
        result = pyscan.outline(self.path)
        kinds = {(s.name, s.kind) for s in result.symbols}
        self.assertIn(("가게", "클래스"), kinds)
        self.assertIn(("열다", "메서드"), kinds)
        self.assertIn(("긴함수", "함수"), kinds)

    def test_method_knows_its_class(self):
        열다 = next(s for s in pyscan.outline(self.path).symbols if s.name == "열다")
        self.assertEqual(열다.parent, "가게")

    def test_docstring_presence(self):
        found = {s.name: s.doc for s in pyscan.outline(self.path).symbols}
        self.assertTrue(found["가게"])
        self.assertTrue(found["열다"])
        self.assertFalse(found["긴함수"])

    def test_undocumented_lists_public_only(self):
        names = [s.name for s in pyscan.outline(self.path).undocumented]
        self.assertIn("긴함수", names)
        self.assertNotIn("_숨은함수", names)

    def test_longest_function(self):
        longest = pyscan.outline(self.path).longest
        self.assertEqual(longest.name, "긴함수")
        self.assertGreater(longest.lines, 5)

    def test_broken_file_keeps_the_error(self):
        bad = self.root / "b.py"
        bad.write_text("def (:\n", encoding="utf-8")
        result = pyscan.outline(bad)
        self.assertTrue(result.error)
        self.assertEqual(result.symbols, [])

    def test_outlines_walks_directories_and_files(self):
        rows = pyscan.outlines([self.root])
        self.assertEqual([r.path.name for r in rows], ["a.py"])
        self.assertEqual(len(pyscan.outlines([self.path])), 1)


if __name__ == "__main__":
    unittest.main()
