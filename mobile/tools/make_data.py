"""폰 화면이 쓸 데이터를 attools 에서 뽑아 mobile/data.js 로 쓴다.

    python3 mobile/tools/make_data.py

명령 목록은 진짜 파서를 걸어 다니며 만든다 - 손으로 적으면 명령을 더할 때마다
어긋난다. 레시피와 단축키도 같은 파일에서 가져온다.
tests/test_mobile.py 가 이 파일이 지금 파서와 맞는지 본다.
"""

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from attools import cli, recipes                      # noqa: E402
from attools import keys                               # noqa: E402

SKIP = {"completion", "find", "how", "ui"}


def _subparsers(parser):
    return next((a for a in parser._actions
                 if isinstance(a, argparse._SubParsersAction)), None)


def commands() -> list:
    """(갈래, 이름, 하는 일). 진짜 파서를 걸어 다니며 모은다."""
    out = []
    top = _subparsers(cli.build_parser())
    도움 = {one.dest: (one.help or "").strip()
            for one in getattr(top, "_choices_actions", [])}
    for 갈래, sub in top.choices.items():
        if 갈래 in SKIP:
            continue
        inner = _subparsers(sub)
        if inner is None:
            out.append([갈래, "", 도움.get(갈래, "")])
            continue
        안쪽 = {one.dest: (one.help or "").strip()
                for one in getattr(inner, "_choices_actions", [])}
        for 이름 in inner.choices:
            out.append([갈래, 이름, 안쪽.get(이름, "")])
    return out


def cookbook() -> list:
    return [[one.topic, one.title, one.steps, one.note] for one in recipes.RECIPES]


def shortcuts() -> list:
    """(묶음, 프로그램들, 항목들). 모르는 칸(null)은 폰에서도 «?» 로 둔다."""
    groups, _meta = keys.load_groups()
    raw = json.loads(keys.read_data())
    앱 = {g["id"]: g.get("apps", []) for g in raw.get("groups", [])}
    return [
        {"id": one.id, "name": one.name,
         "apps": [{"id": a["id"], "name": a["name"]} for a in 앱.get(one.id, [])],
         "items": [{"name": i.name, "cat": i.cat, "keys": i.keys}
                   for i in one.items]}
        for one in groups
    ]


def main() -> None:
    body = {
        "명령": commands(),
        "레시피": cookbook(),
        "단축키": shortcuts(),
    }
    # 화면 파일 안에 바로 끼운다. 파일이 하나여야 한 벌만 관리한다.
    target = Path(__file__).resolve().parent.parent / "index.html"
    글 = target.read_text(encoding="utf-8")
    시작 = "// <데이터 시작>"
    끝 = "// <데이터 끝>"
    앞 = 글.index(시작)
    뒤 = 글.index(끝)
    새 = (시작 + " - python3 mobile/tools/make_data.py 가 쓴다. 손대지 마세요.\n"
          + "window.ATDATA = " + json.dumps(body, ensure_ascii=False) + ";\n")
    target.write_text(글[:앞] + 새 + 글[뒤:], encoding="utf-8")
    print(f"만들었습니다: {target}  "
          f"(명령 {len(body['명령'])}개, 레시피 {len(body['레시피'])}개, "
          f"단축키 묶음 {len(body['단축키'])}개)")


if __name__ == "__main__":
    main()
