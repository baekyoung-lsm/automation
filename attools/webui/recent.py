"""최근에 넣은 경로를 기억한다.

브라우저 localStorage 는 못 쓴다. 화면은 실행할 때마다 포트가 달라지고,
포트가 다르면 브라우저가 다른 곳으로 보기 때문이다. 그래서 사람이 눈으로
볼 수 있는 파일(~/.attools/ui-recent.json)에 둔다.
"""

from __future__ import annotations

import json
from pathlib import Path

KEEP = 5            # 칸마다 기억할 개수
MAX_VALUE = 300     # 경로 하나의 길이
MAX_FIELDS = 20     # 화면마다 기억할 칸 수


def store_path() -> Path:
    """홈은 부를 때마다 다시 본다."""
    return Path.home() / ".attools" / "ui-recent.json"


def load() -> dict:
    path = store_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}      # 망가진 기록 때문에 화면이 안 뜨면 안 된다
    return data if isinstance(data, dict) else {}


def recent(app: str) -> dict[str, list[str]]:
    fields = load().get(app)
    if not isinstance(fields, dict):
        return {}
    return {name: [v for v in values if isinstance(v, str)]
            for name, values in fields.items()
            if isinstance(values, list)}


def remember(app: str, field: str, value: str) -> list[str]:
    """가장 최근 것이 앞에 온다. 같은 값은 한 번만 남긴다."""
    value = value.strip()
    if not value or len(value) > MAX_VALUE:
        return recent(app).get(field, [])

    data = load()
    fields = data.get(app)
    if not isinstance(fields, dict):
        fields = {}
    values = [v for v in fields.get(field, []) if isinstance(v, str) and v != value]
    values.insert(0, value)
    fields[field] = values[:KEEP]

    if len(fields) > MAX_FIELDS:                  # 오래된 칸부터 버린다
        fields = dict(list(fields.items())[-MAX_FIELDS:])
    data[app] = fields

    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return fields[field]


def forget(app: str | None = None) -> None:
    """기억을 지운다. app 을 주면 그 화면 것만."""
    path = store_path()
    if app is None:
        path.unlink(missing_ok=True)
        return
    data = load()
    if data.pop(app, None) is not None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
