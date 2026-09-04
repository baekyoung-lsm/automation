"""sqlite 훑기 시험."""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools.code import dbkit
class DbkitTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.path = self.root / "시험.db"
        conn = sqlite3.connect(self.path)
        conn.execute("CREATE TABLE 사원(사번 INTEGER PRIMARY KEY, "
                     "이름 TEXT NOT NULL, 부서 TEXT DEFAULT '미정')")
        conn.executemany("INSERT INTO 사원(이름, 부서) VALUES (?,?)",
                         [("가", "영업"), ("나", "개발"), ("다", "개발")])
        conn.execute("CREATE VIEW 영업 AS SELECT * FROM 사원 WHERE 부서='영업'")
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_header_check_beats_extension(self):
        fake = self.root / "가짜.db"
        fake.write_text("이건 데이터베이스가 아니다", encoding="utf-8")
        self.assertTrue(dbkit.is_sqlite(self.path))
        self.assertFalse(dbkit.is_sqlite(fake))
        with self.assertRaises(dbkit.DbError):
            dbkit.connect(fake)

    def test_missing_file_is_reported(self):
        with self.assertRaises(dbkit.DbError):
            dbkit.connect(self.root / "없는파일.db")

    def test_tables_include_views_and_row_counts(self):
        with dbkit.connect(self.path) as conn:
            found = {t.name: t for t in dbkit.tables(conn)}
        self.assertEqual(found["사원"].kind, "table")
        self.assertEqual(found["사원"].rows, 3)
        self.assertEqual(found["사원"].columns, 3)
        self.assertEqual(found["영업"].kind, "view")
        self.assertEqual(found["영업"].rows, 1)

    def test_columns_report_null_default_and_key(self):
        with dbkit.connect(self.path) as conn:
            cols = {c.name: c for c in dbkit.columns(conn, "사원")}
        self.assertTrue(cols["사번"].pk)
        self.assertTrue(cols["이름"].notnull)
        self.assertEqual(cols["부서"].default, "'미정'")
        self.assertEqual(cols["이름"].type, "TEXT")

    def test_unknown_table_is_reported(self):
        with dbkit.connect(self.path) as conn:
            with self.assertRaises(dbkit.DbError):
                dbkit.columns(conn, "없는표")

    def test_query_returns_headers_and_marks_truncation(self):
        with dbkit.connect(self.path) as conn:
            headers, rows, more = dbkit.query(conn, "SELECT 이름 FROM 사원", limit=2)
        self.assertEqual(headers, ["이름"])
        self.assertEqual(len(rows), 2)
        self.assertTrue(more)          # 잘렸다는 것을 알려야 한다

    def test_query_is_read_only(self):
        with dbkit.connect(self.path) as conn:
            with self.assertRaises(dbkit.DbError):
                dbkit.query(conn, "DELETE FROM 사원")
        conn2 = sqlite3.connect(self.path)
        self.assertEqual(conn2.execute("SELECT COUNT(*) FROM 사원").fetchone()[0], 3)
        conn2.close()

    def test_write_words_are_recognised(self):
        self.assertTrue(dbkit.looks_like_write("  insert into a values(1)"))
        self.assertTrue(dbkit.looks_like_write("DROP TABLE a"))
        self.assertFalse(dbkit.looks_like_write("select * from a"))
        self.assertFalse(dbkit.looks_like_write("WITH x AS (SELECT 1) SELECT * FROM x"))

    def test_broken_sql_is_reported(self):
        with dbkit.connect(self.path) as conn:
            with self.assertRaises(dbkit.DbError):
                dbkit.query(conn, "SELECT 없는열 FROM 사원")


if __name__ == "__main__":
    unittest.main()
