"""파이썬 소스 훑기 시험 - 안 쓰는 import, 아무도 안 부르는 모듈."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import pyscan


class RedefinedTest(unittest.TestCase):
    """두 번 정의된 이름. 맞는 자리(property 짝·판 갈라 쓰기)는 세지 않는다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, body: str) -> Path:
        path = self.root / "겹침.py"
        path.write_text(body, encoding="utf-8")
        return path

    def test_function_defined_twice(self):
        path = self.write("def 일하다():\n    return 1\n\n\n"
                          "def 일하다():\n    return 2\n")
        found = pyscan.redefined(path)
        self.assertEqual([(f.name, f.kind, f.first, f.line) for f in found],
                         [("일하다", "함수", 1, 5)])

    def test_method_defined_twice(self):
        path = self.write("class 가:\n    def 보다(self):\n        pass\n\n"
                          "    def 보다(self):\n        pass\n")
        found = pyscan.redefined(path)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].kind, found[0].where), ("메서드", "가"))

    def test_property_pair_is_not_counted(self):
        path = self.write("class 가:\n"
                          "    @property\n"
                          "    def 값(self):\n        return self._v\n\n"
                          "    @값.setter\n"
                          "    def 값(self, v):\n        self._v = v\n")
        self.assertEqual(pyscan.redefined(path), [])

    def test_version_split_is_not_counted(self):
        """if/try 안에서 갈라 정의하는 것은 옳은 코드다."""
        path = self.write("import sys\n\n"
                          "if sys.version_info >= (3, 11):\n"
                          "    def 하다():\n        return 1\n"
                          "else:\n"
                          "    def 하다():\n        return 2\n")
        self.assertEqual(pyscan.redefined(path), [])

    def test_overload_is_not_counted(self):
        path = self.write("from typing import overload\n\n"
                          "@overload\n"
                          "def 하다(x: int) -> int: ...\n\n"
                          "@overload\n"
                          "def 하다(x: str) -> str: ...\n\n"
                          "def 하다(x):\n    return x\n")
        self.assertEqual(pyscan.redefined(path), [])

    def test_same_name_in_different_classes_is_fine(self):
        path = self.write("class 가:\n    def 보다(self):\n        pass\n\n"
                          "class 나:\n    def 보다(self):\n        pass\n")
        self.assertEqual(pyscan.redefined(path), [])

    def test_broken_file_is_skipped(self):
        path = self.write("def 하다(:\n")
        self.assertEqual(pyscan.redefined(path), [])

    def test_scan_counts_files(self):
        self.write("def 하다():\n    pass\n\n\ndef 하다():\n    pass\n")
        (self.root / "멀쩡.py").write_text("def 하나():\n    pass\n",
                                           encoding="utf-8")
        found, seen = pyscan.redefined_scan([self.root])
        self.assertEqual(seen, 2)
        self.assertEqual(len(found), 1)

    def test_our_own_repository_is_clean(self):
        """이 검사는 우리 저장소에서 실제로 한 번 사고가 나서 만들었다."""
        root = Path(__file__).resolve().parents[1]
        found, seen = pyscan.redefined_scan([root / "attools", root / "tests"])
        self.assertEqual(found, [], "\n".join(
            f"{f.path}:{f.line} {f.name}" for f in found))
        self.assertGreater(seen, 50)


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


class BranchCountTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def count(self, body: str) -> int:
        path = self.root / "a.py"
        path.write_text(body, encoding="utf-8")
        return pyscan.outline(path).symbols[0].branches

    def test_straight_line_function_is_one(self):
        self.assertEqual(self.count("def f():\n    return 1\n"), 1)

    def test_if_and_for_add_one_each(self):
        self.assertEqual(self.count("def f(a):\n    if a:\n        return 1\n"
                                    "    for x in a:\n        pass\n"), 3)

    def test_boolean_operators_count(self):
        self.assertEqual(self.count("def f(a, b, c):\n    return a and b and c\n"), 3)

    def test_except_and_comprehension_count(self):
        body = ("def f(items):\n"
                "    try:\n"
                "        return [x for x in items if x]\n"
                "    except ValueError:\n"
                "        return []\n")
        self.assertEqual(self.count(body), 4)     # 기본 1 + 컴프리헨션 + if + except

    def test_branchy_picks_the_worst_function(self):
        path = self.root / "b.py"
        path.write_text("def 단순():\n    return 1\n\n\n"
                        "def 복잡(a):\n    if a:\n        pass\n"
                        "    for x in a:\n        pass\n", encoding="utf-8")
        self.assertEqual(pyscan.outline(path).branchy.name, "복잡")


class ImportGraphTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "패키지"
        self.root.mkdir()
        (self.root / "__init__.py").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root.parent, ignore_errors=True)

    def make(self, name, body=""):
        (self.root / name).write_text(body, encoding="utf-8")

    def test_graph_points_the_other_way_than_module_uses(self):
        self.make("가.py", "from . import 나\n")
        self.make("나.py", "")
        graph = pyscan.import_graph(self.root)
        self.assertEqual(graph["패키지.가"], {"패키지.나"})
        self.assertEqual(graph["패키지.나"], set())

    def test_finds_a_two_module_cycle(self):
        self.make("가.py", "from . import 나\n")
        self.make("나.py", "from . import 가\n")
        cycles = pyscan.find_cycles(pyscan.import_graph(self.root))
        self.assertEqual(len(cycles), 1)
        self.assertEqual(sorted(cycles[0]), ["패키지.가", "패키지.나"])

    def test_finds_a_longer_cycle(self):
        self.make("가.py", "from . import 나\n")
        self.make("나.py", "from . import 다\n")
        self.make("다.py", "from . import 가\n")
        cycles = pyscan.find_cycles(pyscan.import_graph(self.root))
        self.assertEqual(len(cycles), 1)
        self.assertEqual(len(cycles[0]), 3)

    def test_the_same_cycle_is_reported_once(self):
        # 어디서 시작해도 같은 고리다
        self.make("가.py", "from . import 나\n")
        self.make("나.py", "from . import 가\n")
        self.make("다.py", "from . import 가\n")
        self.assertEqual(len(pyscan.find_cycles(pyscan.import_graph(self.root))), 1)

    def test_no_cycle(self):
        self.make("가.py", "from . import 나\n")
        self.make("나.py", "")
        self.assertEqual(pyscan.find_cycles(pyscan.import_graph(self.root)), [])

    def test_limit_stops_early(self):
        for i in range(6):
            self.make(f"가{i}.py", f"from . import 나{i}\n")
            self.make(f"나{i}.py", f"from . import 가{i}\n")
        cycles = pyscan.find_cycles(pyscan.import_graph(self.root), limit=2)
        self.assertEqual(len(cycles), 2)


class CompatTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, body: str) -> Path:
        path = self.root / name
        path.write_text(body, encoding="utf-8")
        return path

    def hits(self, body: str):
        return pyscan.compat_hits(self.write("a.py", body))

    def test_match_needs_3_10(self):
        got = self.hits("def f(x):\n    match x:\n        case 1:\n"
                        "            return 2\n")
        self.assertEqual([(h.version, h.kind) for h in got],
                         [((3, 10), "문법")])

    def test_new_stdlib_module(self):
        got = self.hits("import tomllib\n")
        self.assertEqual(got[0].version, (3, 11))
        self.assertTrue(got[0].sure)

    def test_new_typing_name(self):
        got = self.hits("from typing import Self\n")
        self.assertEqual(got[0].version, (3, 11))

    def test_guarded_import_is_not_blocking(self):
        # 없으면 없는 대로 도는 코드다. 이걸 막힌 자리로 세면 진짜가 묻힌다
        got = self.hits("try:\n    import tomllib\nexcept ImportError:\n"
                        "    tomllib = None\n")
        self.assertTrue(got[0].guarded)
        report = pyscan.CompatReport(files=1, hits=got)
        self.assertIsNone(report.needed)
        self.assertEqual(report.over((3, 10)), [])

    def test_pipe_annotation_needs_3_10(self):
        got = self.hits("def f(x: int | None) -> str | None:\n    return None\n")
        self.assertTrue(got)
        self.assertEqual(got[0].version, (3, 10))

    def test_future_import_makes_annotations_free(self):
        got = self.hits("from __future__ import annotations\n\n"
                        "def f(x: int | None) -> None:\n    return None\n")
        self.assertEqual(got, [])

    def test_pipe_outside_annotation_is_not_flagged(self):
        self.assertEqual(self.hits("a = 1 | 2\n"), [])

    def test_method_name_is_a_guess(self):
        got = self.hits("def f(s):\n    return s.removeprefix('가')\n")
        self.assertEqual(got[0].version, (3, 9))
        self.assertFalse(got[0].sure)      # 무엇의 메서드인지 알 수 없다

    def test_module_attribute_is_sure(self):
        got = self.hits("import itertools\n\nx = itertools.pairwise([1, 2])\n")
        self.assertTrue(got[0].sure)
        self.assertEqual(got[0].version, (3, 10))

    def test_same_name_on_another_module_is_skipped(self):
        self.assertEqual(self.hits("import os\n\nx = os.walk('.')\n"), [])

    def test_report_needed_ignores_guesses(self):
        report = pyscan.CompatReport(files=1, hits=[
            pyscan.CompatHit(Path("a.py"), 1, (3, 12), ".batched", "이름", False),
            pyscan.CompatHit(Path("a.py"), 2, (3, 10), "match 문", "문법", True)])
        self.assertEqual(report.needed, (3, 10))

    def test_scan_counts_files_and_keeps_broken_ones_aside(self):
        self.write("좋음.py", "import tomllib\n")
        self.write("깨짐.py", "def f(\n")
        report = pyscan.compat_scan([self.root])
        self.assertEqual(report.files, 2)
        self.assertEqual(len(report.failed), 1)
        self.assertEqual(report.needed, (3, 11))

    def test_parse_version(self):
        self.assertEqual(pyscan.parse_version("3.10"), (3, 10))
        with self.assertRaises(ValueError):
            pyscan.parse_version("3")


class ReadSourceTest(unittest.TestCase):
    """파이썬 소스로 읽을 수 없는 파일. 훑다가 멎으면 안 된다."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_non_utf8_file_raises_source_error(self):
        path = self.root / "그림.py"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(pyscan.SourceError):
            pyscan.read_source(path)

    def test_null_byte_file_raises_source_error(self):
        path = self.root / "널.py"
        path.write_bytes(b"x = 1\x00\n")
        with self.assertRaises(pyscan.SourceError):
            pyscan.read_source(path)

    def test_outline_reports_error_instead_of_raising(self):
        path = self.root / "그림.py"
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        result = pyscan.outline(path)
        self.assertTrue(result.error)
        self.assertEqual(result.symbols, [])

    def test_scans_skip_unreadable_file(self):
        bad = self.root / "널.py"
        bad.write_bytes(b"x = 1\x00\n")
        (self.root / "쓸만.py").write_text("import os\n", encoding="utf-8")
        self.assertEqual(pyscan.unused_imports(bad), [])
        self.assertEqual(pyscan.redefined(bad), [])
        found, seen = pyscan.redefined_scan([self.root])
        self.assertEqual(found, [])
        self.assertEqual(seen, 2)

    def test_compat_scan_counts_null_byte_file_as_failed(self):
        (self.root / "널.py").write_bytes(b"x = 1\x00\n")
        report = pyscan.compat_scan([self.root])
        self.assertEqual(len(report.failed), 1)


if __name__ == "__main__":
    unittest.main()
