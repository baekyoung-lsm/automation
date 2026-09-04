"""단축키 데이터와 화면 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import keyhtml, keys
from attools.write import names
class KeysTest(unittest.TestCase):
    def setUp(self):
        self.groups, self.sources = keys.load_groups()
        self.state = keys.State()
        self.doc = keys.find_group(self.groups, "doc")

    def test_data_is_well_formed(self):
        self.assertTrue(self.groups)
        ids = [g.id for g in self.groups]
        self.assertEqual(len(ids), len(set(ids)))
        for g in self.groups:
            self.assertTrue(g.apps, g.id)
            names = [i.name for i in g.items]
            self.assertEqual(len(names), len(set(names)), f"{g.id} 항목 이름 중복")
            for item in g.items:
                self.assertTrue(item.cat, item.name)
                # 키 딕셔너리는 선언된 앱 id 만 쓴다
                self.assertLessEqual(set(item.keys), set(g.app_ids), item.name)
                self.assertTrue(any(item.keys.values()), f"{item.name}: 단축키가 하나도 없음")

    def test_three_cell_states(self):
        item = keys.Item("테스트", "편집", 3,
                         {"hwp": "Ctrl+K", "word": keys.NO_SHORTCUT, "gdocs": None},
                         group="doc")
        self.assertEqual(item.status("hwp"), "key")
        self.assertEqual(item.status("word"), "none")
        self.assertEqual(item.status("gdocs"), "unknown")
        self.assertEqual(item.status("없는앱"), "unknown")
        self.assertEqual(item.shortcut("hwp"), "Ctrl+K")
        self.assertEqual(item.shortcut("word"), keys.MARK_NONE)
        self.assertEqual(item.shortcut("gdocs"), keys.MARK_UNKNOWN)
        self.assertEqual(item.unknown_apps(["hwp", "word", "gdocs"]), ["gdocs"])

    def test_none_marker_is_not_searchable(self):
        # '없음'은 표시용 값이지 단축키가 아니므로 검색에 걸리면 안 된다
        group = keys.Group("t", "테스트", "", [{"id": "a", "name": "A"}])
        group.items = [keys.Item("기능", "편집", 3, {"a": keys.NO_SHORTCUT}, group="t")]
        self.assertEqual(keys.search(group, "없음"), [])
        self.assertEqual(len(keys.search(group, "기능")), 1)

    def test_gaps_lists_unknown_cells_only(self):
        group = keys.Group("t", "테스트", "", [{"id": "a", "name": "A"},
                                               {"id": "b", "name": "B"}])
        group.items = [
            keys.Item("있음", "편집", 3, {"a": "Ctrl+A", "b": keys.NO_SHORTCUT}, group="t"),
            keys.Item("모름", "편집", 3, {"a": "Ctrl+B", "b": None}, group="t"),
        ]
        rows = keys.gaps([group])
        self.assertEqual([(i.name, m) for _, i, m in rows], [("모름", ["b"])])

    def test_data_cell_values_are_valid(self):
        for g in self.groups:
            for item in g.items:
                for app, value in item.keys.items():
                    self.assertTrue(value is None or isinstance(value, str),
                                    f"{g.id}/{item.name}/{app}")
                    if isinstance(value, str):
                        self.assertTrue(value.strip(), f"{g.id}/{item.name}/{app} 빈 문자열")

    def test_search_by_function_name(self):
        found = [i.name for i in keys.search(self.doc, "붙여넣기")]
        self.assertIn("서식 없이 붙여넣기", found)

    def test_search_by_key_combo_ignores_separators(self):
        for query in ("Ctrl+Shift+V", "ctrl shift v", "ctrlshiftv"):
            found = [i.name for i in keys.search(self.doc, query)]
            self.assertIn("서식 없이 붙여넣기", found, query)

    def test_search_across_groups(self):
        hits = keys.search_all(self.groups, "Ctrl+K")
        self.assertGreater(len(hits), 1)
        self.assertTrue(all(isinstance(g, keys.Group) for g, _ in hits))

    def test_sort_abc_and_cat(self):
        names = [i.name for i in keys.sort_items(self.doc, self.state, "abc")]
        self.assertEqual(names, sorted(names))
        cats = [i.cat for i in keys.sort_items(self.doc, self.state, "cat")]
        self.assertEqual(cats, sorted(cats))
        with self.assertRaises(keys.KeysError):
            keys.sort_items(self.doc, self.state, "없는정렬")

    def test_hits_reorder_freq(self):
        target = self.doc.items[-1]
        self.assertNotEqual(keys.sort_items(self.doc, self.state, "freq")[0].name, target.name)
        self.state.hit(target.uid, 99)
        self.assertEqual(keys.sort_items(self.doc, self.state, "freq")[0].name, target.name)

    def test_pins_float_to_top(self):
        target = self.doc.items[-1]
        self.assertTrue(self.state.toggle_pin(target.uid))
        self.assertEqual(keys.sort_items(self.doc, self.state, "abc")[0].name, target.name)
        self.assertFalse(self.state.toggle_pin(target.uid))
        self.assertNotEqual(keys.sort_items(self.doc, self.state, "abc")[0].name, target.name)

    def test_custom_order_move(self):
        item = keys.sort_items(self.doc, self.state, "freq")[2]
        self.state.move(self.doc, item, -2)
        self.assertEqual(keys.sort_items(self.doc, self.state, "custom")[0].name, item.name)
        self.state.move(self.doc, item, 1)
        self.assertEqual(keys.sort_items(self.doc, self.state, "custom")[1].name, item.name)

    def test_sort_cycle_covers_every_mode(self):
        mode, seen = "freq", []
        for _ in range(len(keys.SORTS)):
            seen.append(mode)
            mode = keys.next_sort(mode)
        self.assertEqual(sorted(seen), sorted(keys.SORTS))
        self.assertEqual(mode, "freq")

    def test_unknown_group(self):
        with self.assertRaises(keys.KeysError):
            keys.find_group(self.groups, "없는그룹")

    def with_home(self):
        """홈을 임시 폴더로 돌린다. 실제 ~/.attools 를 건드리면 안 된다."""
        import os

        root = Path(tempfile.mkdtemp())
        previous = os.environ.get("HOME")
        os.environ["HOME"] = str(root)
        Path.home.cache_clear() if hasattr(Path.home, "cache_clear") else None
        return root, previous

    def restore_home(self, root, previous):
        import os

        if previous is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous
        shutil.rmtree(root, ignore_errors=True)

    def test_set_shortcut_writes_user_file(self):
        root, previous = self.with_home()
        try:
            path, is_new = keys.set_shortcut(self.doc, "표 만들기", "word", "Alt+N,T")
            self.assertTrue(path.is_file())
            self.assertTrue(str(path).startswith(str(root)))   # 실제 홈이 아니다
            self.assertFalse(is_new)          # 기본 데이터에 있는 항목

            groups, _ = keys.load_groups()
            item = next(i for i in keys.find_group(groups, "doc").items
                        if i.name == "표 만들기")
            self.assertEqual(item.shortcut("word"), "Alt+N,T")
            # 기본 데이터의 다른 칸이 사용자 항목에 덮여 사라지면 안 된다
            self.assertEqual(item.shortcut("hwp"), "Ctrl+N,T")
        finally:
            self.restore_home(root, previous)

    def test_set_shortcut_none_marks_no_shortcut(self):
        root, previous = self.with_home()
        try:
            keys.set_shortcut(self.doc, "편집 용지", "gdocs", None)
            groups, _ = keys.load_groups()
            item = next(i for i in keys.find_group(groups, "doc").items
                        if i.name == "편집 용지")
            self.assertEqual(item.status("gdocs"), "none")
            self.assertEqual(item.shortcut("gdocs"), keys.MARK_NONE)
        finally:
            self.restore_home(root, previous)

    def test_set_shortcut_new_item(self):
        root, previous = self.with_home()
        try:
            _, is_new = keys.set_shortcut(self.doc, "내가 만든 기능", "hwp", "Ctrl+Q")
            self.assertTrue(is_new)
            groups, _ = keys.load_groups()
            names_ = [i.name for i in keys.find_group(groups, "doc").items]
            self.assertIn("내가 만든 기능", names_)
        finally:
            self.restore_home(root, previous)

    def test_set_shortcut_rejects_unknown_app(self):
        with self.assertRaises(keys.KeysError):
            keys.set_shortcut(self.doc, "표 만들기", "없는앱", "x")

    def test_html_export_is_self_contained(self):
        html = keyhtml.build(self.groups, self.sources)
        self.assertNotIn("__DATA__", html)
        self.assertNotIn("<script src", html)   # 외부 의존 없음
        self.assertIn("서식 없이 붙여넣기", html)
        self.assertIn("localStorage", html)
        # 탭은 JS 가 그리므로 이름은 심어 둔 JSON 안에 있어야 한다
        for g in self.groups:
            self.assertIn(g.name, html)


if __name__ == "__main__":
    unittest.main()
