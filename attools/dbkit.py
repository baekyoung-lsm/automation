"""sqlite 파일 훑기. 표준 라이브러리 sqlite3 만 쓰고, 읽기 전용으로 연다."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

SQLITE_MAGIC = b"SQLite format 3\x00"
WRITE_WORDS = ("insert", "update", "delete", "drop", "alter", "create",
               "replace", "truncate", "attach", "pragma", "vacuum", "begin")


class DbError(Exception):
    pass


@dataclass
class Column:
    name: str
    type: str
    notnull: bool
    default: str
    pk: bool


@dataclass
class TableInfo:
    name: str
    kind: str          # table | view
    rows: int
    columns: int


def is_sqlite(path: Path) -> bool:
    """헤더로 판단한다. 확장자는 .db, .sqlite, .sqlite3 제각각이다."""
    try:
        with path.open("rb") as fh:
            return fh.read(16) == SQLITE_MAGIC
    except OSError:
        return False


def connect(path: Path) -> sqlite3.Connection:
    """읽기 전용으로 연다. 훑어보다가 원본을 고치는 일은 없어야 한다."""
    if not path.is_file():
        raise DbError(f"파일이 없습니다: {path}")
    if not is_sqlite(path):
        raise DbError(f"sqlite 파일이 아닙니다: {path}")
    uri = f"file:{path.resolve().as_uri()[7:]}?mode=ro"
    try:
        return sqlite3.connect(uri, uri=True)
    except sqlite3.Error as e:
        raise DbError(str(e)) from None


def tables(conn: sqlite3.Connection) -> list[TableInfo]:
    rows = conn.execute(
        "SELECT name, type FROM sqlite_master "
        "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
        "ORDER BY type, name").fetchall()
    out: list[TableInfo] = []
    for name, kind in rows:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        except sqlite3.Error:
            count = -1           # 깨진 뷰 등. 0 과 구분해 둔다
        width = len(conn.execute(f'PRAGMA table_info("{name}")').fetchall())
        out.append(TableInfo(name, kind, count, width))
    return out


def columns(conn: sqlite3.Connection, table: str) -> list[Column]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    if not rows:
        raise DbError(f"'{table}' 표가 없습니다.")
    return [Column(r[1], r[2] or "", bool(r[3]), "" if r[4] is None else str(r[4]),
                   bool(r[5])) for r in rows]


def looks_like_write(sql: str) -> bool:
    """읽기 전용으로 열지만, 무엇이 막혔는지 미리 알려 주려고 본다."""
    head = sql.strip().lstrip("(").split(None, 1)
    return bool(head) and head[0].lower() in WRITE_WORDS


def query(conn: sqlite3.Connection, sql: str, *,
          limit: int = 200) -> tuple[list[str], list[list], bool]:
    """(열 이름, 행, 더 있는지). limit 보다 한 줄 더 읽어 잘렸는지 안다."""
    try:
        cur = conn.execute(sql)
        rows = cur.fetchmany(limit + 1)
    except sqlite3.Error as e:
        raise DbError(str(e)) from None
    headers = [d[0] for d in cur.description] if cur.description else []
    return headers, [list(r) for r in rows[:limit]], len(rows) > limit


def sample(conn: sqlite3.Connection, table: str, *,
           limit: int = 5) -> tuple[list[str], list[list], bool]:
    return query(conn, f'SELECT * FROM "{table}"', limit=limit)
