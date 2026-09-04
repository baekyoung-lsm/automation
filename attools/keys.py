"""단축키 모음: 앱 그룹별 비교표, 검색, 정렬, 사용 기록."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_FILE = Path(__file__).parent / "data" / "shortcuts.json"
def user_dir() -> Path:
    """설정과 기록이 쌓이는 곳. 홈은 부를 때마다 다시 본다."""
    return Path.home() / ".attools"


def user_data_path() -> Path:
    """사용자가 추가·수정한 단축키."""
    return user_dir() / "shortcuts.json"


def state_path() -> Path:
    """조회 횟수, 사용자 순서, 고정."""
    return user_dir() / "keys.json"

# 값이 없는 칸은 두 가지다. 이 둘을 구분하지 않으면 "찾아봐야 할 것"을 알 수 없다.
NO_SHORTCUT = "없음"      # 확인했고, 기본 단축키가 없는 기능
UNKNOWN = None            # 아직 확인하지 못한 칸
MARK_NONE = "—"
MARK_UNKNOWN = "?"

SORTS = {
    "freq": "자주 찾는 순",
    "abc": "가나다 순",
    "custom": "사용자 순",
    "cat": "분류 순",
}
SORT_ORDER = ["freq", "abc", "custom", "cat"]


class KeysError(Exception):
    pass


@dataclass
class Item:
    name: str
    cat: str
    freq: int
    keys: dict[str, str | None]
    group: str = ""

    @property
    def uid(self) -> str:
        return f"{self.group}:{self.name}"

    def status(self, app: str) -> str:
        """key = 단축키 있음, none = 기본 단축키 없음, unknown = 확인 못 함"""
        value = self.keys.get(app, UNKNOWN)
        if value == NO_SHORTCUT:
            return "none"
        return "key" if value else "unknown"

    def shortcut(self, app: str) -> str:
        state = self.status(app)
        if state == "key":
            return self.keys[app]
        return MARK_NONE if state == "none" else MARK_UNKNOWN

    def haystack(self, apps: list[str]) -> str:
        # 표시용 기호와 '없음' 자체는 검색에 걸리지 않게 뺀다
        parts = [self.name, self.cat] + [self.keys.get(a) or "" for a in apps
                                         if self.keys.get(a) != NO_SHORTCUT]
        return normalize(" ".join(parts))

    def unknown_apps(self, apps: list[str]) -> list[str]:
        return [a for a in apps if self.status(a) == "unknown"]


@dataclass
class Group:
    id: str
    name: str
    desc: str
    apps: list[dict]
    items: list[Item] = field(default_factory=list)

    @property
    def app_ids(self) -> list[str]:
        return [a["id"] for a in self.apps]

    def app_name(self, app_id: str) -> str:
        for a in self.apps:
            if a["id"] == app_id:
                return a["name"]
        raise KeysError(f"'{app_id}' 앱이 {self.name} 그룹에 없습니다.")


def normalize(text: str) -> str:
    """검색 비교용. 공백과 구분 기호를 없애고 소문자로."""
    return re.sub(r"[\s\-_+·,]", "", text).lower()


# ------------------------------------------------------------------ 데이터

def load_groups() -> tuple[list[Group], dict]:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    groups = {g["id"]: g for g in raw["groups"]}

    if user_data_path().is_file():
        try:
            extra = json.loads(user_data_path().read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise KeysError(f"{user_data_path()} 를 읽지 못했습니다: {e}") from None
        for g in extra.get("groups", []):
            base = groups.get(g["id"])
            if base is None:
                groups[g["id"]] = g
                continue
            # 같은 그룹이면 앱과 항목을 덧붙이고, 이름이 겹치면 사용자 값이 이긴다
            names = {i["name"] for i in g.get("items", [])}
            base["items"] = [i for i in base["items"] if i["name"] not in names]
            base["items"] += g.get("items", [])
            known = {a["id"] for a in base["apps"]}
            base["apps"] += [a for a in g.get("apps", []) if a["id"] not in known]

    out = []
    for g in groups.values():
        group = Group(g["id"], g["name"], g.get("desc", ""), g["apps"])
        group.items = [Item(i["name"], i.get("cat", ""), i.get("freq", 1),
                            i.get("keys", {}), group=g["id"])
                       for i in g["items"]]
        out.append(group)
    return out, raw.get("sources", {})


# -------------------------------------------------------------------- 상태

@dataclass
class State:
    hits: dict[str, int] = field(default_factory=dict)
    order: dict[str, list[str]] = field(default_factory=dict)
    pins: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> State:
        if not state_path().is_file():
            return cls()
        try:
            raw = json.loads(state_path().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        return cls(hits=raw.get("hits", {}), order=raw.get("order", {}),
                   pins=raw.get("pins", []))

    def save(self) -> None:
        state_path().parent.mkdir(parents=True, exist_ok=True)
        state_path().write_text(
            json.dumps({"hits": self.hits, "order": self.order, "pins": self.pins},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    def hit(self, uid: str, n: int = 1) -> None:
        self.hits[uid] = self.hits.get(uid, 0) + n

    def toggle_pin(self, uid: str) -> bool:
        if uid in self.pins:
            self.pins.remove(uid)
            return False
        self.pins.append(uid)
        return True

    def move(self, group: Group, item: Item, delta: int) -> None:
        """사용자 순서에서 항목을 위아래로 옮긴다."""
        names = self.order.get(group.id) or [i.name for i in sort_items(
            group, self, "freq")]
        if item.name not in names:
            names.append(item.name)
        i = names.index(item.name)
        j = max(0, min(len(names) - 1, i + delta))
        names.insert(j, names.pop(i))
        self.order[group.id] = names


# ----------------------------------------------------------- 검색 · 정렬

def search(group: Group, query: str) -> list[Item]:
    if not query.strip():
        return list(group.items)
    needle = normalize(query)
    apps = group.app_ids
    return [i for i in group.items if needle in i.haystack(apps)]


def sort_items(group: Group, state: State, mode: str,
               items: list[Item] | None = None) -> list[Item]:
    items = list(group.items if items is None else items)
    if mode not in SORTS:
        raise KeysError(f"알 수 없는 정렬: {mode} ({', '.join(SORTS)})")

    if mode == "freq":
        items.sort(key=lambda i: (-state.hits.get(i.uid, 0), -i.freq, i.name))
    elif mode == "abc":
        items.sort(key=lambda i: i.name)
    elif mode == "cat":
        items.sort(key=lambda i: (i.cat, -i.freq, i.name))
    else:  # custom
        order = state.order.get(group.id, [])
        rank = {name: n for n, name in enumerate(order)}
        items.sort(key=lambda i: (rank.get(i.name, len(order)),
                                  -state.hits.get(i.uid, 0), -i.freq, i.name))

    pinned = [i for i in items if i.uid in state.pins]
    return pinned + [i for i in items if i.uid not in state.pins] if pinned else items


def next_sort(mode: str) -> str:
    return SORT_ORDER[(SORT_ORDER.index(mode) + 1) % len(SORT_ORDER)]


def find_group(groups: list[Group], name: str) -> Group:
    for g in groups:
        if g.id == name or g.name == name:
            return g
    known = ", ".join(f"{g.id}({g.name})" for g in groups)
    raise KeysError(f"'{name}' 그룹이 없습니다. 있는 그룹: {known}")


def gaps(groups: list[Group]) -> list[tuple[Group, Item, list[str]]]:
    """아직 확인하지 못한 칸을 모은다."""
    out = []
    for g in groups:
        for item in g.items:
            missing = item.unknown_apps(g.app_ids)
            if missing:
                out.append((g, item, missing))
    return out


def search_all(groups: list[Group], query: str) -> list[tuple[Group, Item]]:
    out = []
    for g in groups:
        out.extend((g, i) for i in search(g, query))
    return out


def load_user_file() -> dict:
    if not user_data_path().is_file():
        return {"groups": []}
    try:
        data = json.loads(user_data_path().read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise KeysError(f"{user_data_path()} 를 읽지 못했습니다: {e}") from None
    data.setdefault("groups", [])
    return data


def save_user_file(data: dict) -> Path:
    user_data_path().parent.mkdir(parents=True, exist_ok=True)
    user_data_path().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    return user_data_path()


def set_shortcut(group: Group, item_name: str, app_id: str, value: str | None, *,
                 cat: str = "", freq: int = 3) -> tuple[Path, bool]:
    """사용자 파일에 단축키 한 칸을 적는다. (파일 경로, 새 항목인지)

    value 가 None 이면 '없음'(기본 단축키가 없는 기능)으로 적는다.
    기본 데이터는 건드리지 않는다. 갱신될 때 덮어써지지 않게 하기 위해서다.
    """
    if app_id not in group.app_ids:
        raise KeysError(f"'{app_id}' 앱이 {group.name} 그룹에 없습니다. "
                        f"있는 앱: {', '.join(group.app_ids)}")

    data = load_user_file()
    block = next((g for g in data["groups"] if g.get("id") == group.id), None)
    if block is None:
        block = {"id": group.id, "items": []}
        data["groups"].append(block)
    block.setdefault("items", [])

    existing = next((i for i in block["items"] if i.get("name") == item_name), None)
    is_new = existing is None
    if existing is None:
        base = next((i for i in group.items if i.name == item_name), None)
        existing = {
            "name": item_name,
            "cat": cat or (base.cat if base else "기타"),
            "freq": base.freq if base else freq,
            # 기본 데이터의 다른 칸도 함께 옮겨 둬야 사용자 항목이 그것을 덮지 않는다
            "keys": dict(base.keys) if base else {},
        }
        block["items"].append(existing)
        is_new = base is None

    existing.setdefault("keys", {})[app_id] = NO_SHORTCUT if value is None else value
    return save_user_file(data), is_new
