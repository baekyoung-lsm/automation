"""JSON 스키마·비교·합치기 시험."""

import shutil
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import jsonkit


class JsonkitTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name, content):
        p = self.root / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_load_reports_position_on_bad_json(self):
        p = self.write("bad.json", '{"a": }')
        with self.assertRaises(jsonkit.JsonError) as cm:
            jsonkit.load(p)
        self.assertIn("행", str(cm.exception))

    def test_load_falls_back_to_json_lines(self):
        p = self.write("a.jsonl", '{"a":1}\n{"a":2}\n')
        self.assertEqual(jsonkit.load(p), [{"a": 1}, {"a": 2}])

    def test_load_missing_file(self):
        with self.assertRaises(jsonkit.JsonError):
            jsonkit.load(self.root / "없음.json")

    def test_walk_paths(self):
        paths = [p for p, _ in jsonkit.walk({"a": {"b": [1, 2]}})]
        self.assertEqual(paths, ["a.b[0]", "a.b[1]"])

    def test_schema_collapses_arrays_and_marks_optional(self):
        data = {"users": [{"id": 1, "name": "가"}, {"id": 2, "name": "나", "nick": "x"}]}
        fields = {f.path: f for f in jsonkit.schema(data)}
        self.assertEqual(fields["users[].id"].types, {"int"})
        self.assertFalse(fields["users[].id"].optional)
        self.assertTrue(fields["users[].nick"].optional)

    def test_schema_records_mixed_types(self):
        fields = {f.path: f for f in jsonkit.schema({"a": [1, "x"]})}
        self.assertEqual(fields["a[]"].types, {"int", "string"})

    def test_diff_categories(self):
        d = jsonkit.diff({"keep": 1, "gone": 2, "t": 1, "v": "a"},
                         {"keep": 1, "new": 3, "t": "1", "v": "b"})
        self.assertEqual([p for p, _ in d.added], ["new"])
        self.assertEqual([p for p, _ in d.removed], ["gone"])
        self.assertEqual(d.type_changed, [("t", "int", "string")])
        self.assertEqual(d.value_changed, [("v", "a", "b")])
        self.assertFalse(d.empty)

    def test_diff_identical_is_empty(self):
        self.assertTrue(jsonkit.diff({"a": [1, {"b": 2}]}, {"a": [1, {"b": 2}]}).empty)

    def test_diff_by_key_ignores_array_order(self):
        before = {"u": [{"id": 1, "n": "가"}, {"id": 2, "n": "나"}]}
        after = {"u": [{"id": 2, "n": "나"}, {"id": 1, "n": "가"}]}
        self.assertFalse(jsonkit.diff(before, after).empty)          # 인덱스 기준이면 다르게 보이고
        self.assertTrue(jsonkit.diff(before, after, key="id").empty)  # id 로 짝지으면 같다

    def test_diff_by_key_finds_added_and_removed_items(self):
        d = jsonkit.diff({"u": [{"id": 1}]}, {"u": [{"id": 2}]}, key="id")
        self.assertEqual([p for p, _ in d.removed], ["u[id=1]"])
        self.assertEqual([p for p, _ in d.added], ["u[id=2]"])

    def test_breaking_covers_removed_and_type_changes(self):
        d = jsonkit.diff({"gone": 1, "t": 1, "v": 1}, {"t": "1", "v": 2})
        self.assertEqual(len(d.breaking), 2)

    def test_type_names(self):
        self.assertEqual(jsonkit.type_name(True), "bool")   # bool 이 int 로 잡히면 안 된다
        self.assertEqual(jsonkit.type_name(1), "int")
        self.assertEqual(jsonkit.type_name(None), "null")

    def test_parse_path(self):
        self.assertEqual(jsonkit.parse_path("users[0].name"), ["users", 0, "name"])
        self.assertEqual(jsonkit.parse_path("a"), ["a"])
        self.assertEqual(jsonkit.parse_path("a[2][3]"), ["a", 2, 3])
        for bad in ("", "   ", "a..b"):
            with self.assertRaises(jsonkit.JsonError):
                jsonkit.parse_path(bad)

    def test_get_path(self):
        data = {"users": [{"name": "홍길동"}], "config": {"port": 8080}}
        self.assertEqual(jsonkit.get_path(data, "users[0].name"), "홍길동")
        self.assertEqual(jsonkit.get_path(data, "config.port"), 8080)

    def test_get_path_errors_explain_where(self):
        data = {"config": {"debug": True}}
        with self.assertRaises(jsonkit.JsonError) as cm:
            jsonkit.get_path(data, "config.debug.더")
        self.assertIn("객체가 아니라", str(cm.exception))

        with self.assertRaises(jsonkit.JsonError):
            jsonkit.get_path(data, "없는키")
        with self.assertRaises(jsonkit.JsonError):
            jsonkit.get_path({"a": [1]}, "a[9]")

    def test_set_path_returns_before_and_after(self):
        data = {"version": "1.0.0", "list": [1, 2]}
        self.assertEqual(jsonkit.set_path(data, "version", "2.0.0"), ("1.0.0", "2.0.0"))
        self.assertEqual(data["version"], "2.0.0")

        self.assertEqual(jsonkit.set_path(data, "list[1]", 9), (2, 9))
        self.assertEqual(data["list"], [1, 9])

    def test_set_path_requires_create_for_new_keys(self):
        data = {"a": {}}
        with self.assertRaises(jsonkit.JsonError) as cm:
            jsonkit.set_path(data, "a.새키", 1)
        self.assertIn("--create", str(cm.exception))

        self.assertEqual(jsonkit.set_path(data, "a.새키", 1, create=True), (None, 1))
        self.assertEqual(data["a"]["새키"], 1)

    def test_set_path_creates_intermediate_objects(self):
        data = {}
        jsonkit.set_path(data, "a.b.c", 1, create=True)
        self.assertEqual(data, {"a": {"b": {"c": 1}}})

    def test_parse_value_json_then_string(self):
        self.assertEqual(jsonkit.parse_value("3"), 3)
        self.assertEqual(jsonkit.parse_value("true"), True)
        self.assertEqual(jsonkit.parse_value('"글자"'), "글자")
        self.assertEqual(jsonkit.parse_value("[1,2]"), [1, 2])
        self.assertEqual(jsonkit.parse_value("그냥 글자"), "그냥 글자")

    def test_preview_truncates(self):
        self.assertTrue(jsonkit.preview("가" * 100, 10).endswith("…"))


    def test_deep_merge_keeps_untouched_keys(self):
        merged, _ = jsonkit.merge_all([{"db": {"host": "local", "port": 5432}},
                                       {"db": {"host": "prod"}}])
        self.assertEqual(merged, {"db": {"host": "prod", "port": 5432}})

    def test_merge_records_what_changed(self):
        _, notes = jsonkit.merge_all([{"a": 1, "b": {"c": 2}}, {"a": 9, "b": {"d": 3}}])
        kinds = {(n.kind, n.path) for n in notes}
        self.assertIn(("덮어씀", "a"), kinds)
        self.assertIn(("추가", "b.d"), kinds)

    def test_merge_same_value_is_not_reported(self):
        _, notes = jsonkit.merge_all([{"a": 1}, {"a": 1}])
        self.assertEqual(notes, [])

    def test_merge_replaces_lists_by_default(self):
        merged, _ = jsonkit.merge_all([{"t": [1, 2]}, {"t": [3]}])
        self.assertEqual(merged["t"], [3])

    def test_merge_can_append_lists(self):
        merged, notes = jsonkit.merge_all([{"t": [1, 2]}, {"t": [3]}],
                                          list_mode="append")
        self.assertEqual(merged["t"], [1, 2, 3])
        self.assertEqual(notes[0].kind, "이어붙임")

    def test_merge_needs_something(self):
        with self.assertRaises(jsonkit.JsonError):
            jsonkit.merge_all([])


if __name__ == "__main__":
    unittest.main()
