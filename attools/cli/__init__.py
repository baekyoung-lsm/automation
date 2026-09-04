"""attools CLI 진입점. 명령은 그룹마다 한 파일로 나눠 두었다."""

from __future__ import annotations

import argparse
import sys

from .. import __version__
from . import (dev_cmds, doc_cmds, file_cmds, git_cmds, json_cmds, keys_cmds,
               life_cmds, novel_cmds, sheet_cmds, text_cmds)
from .common import _cut, _grid, _p

# 도움말에 나오는 순서다.
GROUP_MODULES = (file_cmds, dev_cmds, git_cmds, life_cmds, sheet_cmds,
                 text_cmds, doc_cmds, json_cmds, keys_cmds, novel_cmds)


def walk_commands(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()):
    """(명령 경로, 한 줄 설명, 파서) 를 모두 돌려준다."""
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        helps = {a.dest: (a.help or "") for a in action._choices_actions}
        for name, sub in action.choices.items():
            here = path + (name,)
            yield here, helps.get(name, ""), sub
            yield from walk_commands(sub, here)


def cmd_find(a) -> int:
    needle = " ".join(a.words).strip().lower()
    if not needle:
        _p("찾을 말을 주세요. 예: at find 중복")
        return 1

    rows: list[tuple[str, str]] = []
    for path, help_text, parser in walk_commands(build_parser()):
        if any(isinstance(x, argparse._SubParsersAction) for x in parser._actions):
            continue                       # 그룹 자체는 건너뛴다
        haystack = " ".join(path) + " " + help_text
        if a.deep:
            haystack += " " + " ".join(
                (x.help or "") + " " + " ".join(x.option_strings)
                for x in parser._actions)
        if needle in haystack.lower():
            rows.append(("at " + " ".join(path), help_text))

    if not rows:
        _p(f"'{needle}' 에 걸리는 명령이 없습니다."
           + ("" if a.deep else " --deep 으로 옵션 설명까지 찾아보세요."))
        return 1

    _grid(["명령", "하는 일"], [[c, _cut(h, 60)] for c, h in rows], limit=60)
    _p(f"\n{len(rows)}개. 자세한 것은 <명령> --help 를 보세요.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="at", description="파일 / 텍스트 / JSON / 개발 / git / 엑셀 / 단축키 / 일상 / 소설 자동화 도구")
    ap.add_argument("-V", "--version", action="version", version=f"attools {__version__}")
    sub = ap.add_subparsers(dest="group", required=True)
    for module in GROUP_MODULES:
        module.add_commands(sub)

    fd = sub.add_parser("find", help="명령 찾기 - 하는 일로 검색")
    fd.add_argument("words", nargs="*", metavar="말")
    fd.add_argument("--deep", action="store_true", help="옵션 설명까지 찾는다")
    fd.set_defaults(func=cmd_find)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # '--' 뒤는 파싱하지 않고 그대로 하위 명령에 넘긴다 (at file watch ... -- pytest -q)
    tail: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, tail = argv[:cut], argv[cut + 1:]

    ap = build_parser()
    args = ap.parse_args(argv)
    if tail:
        args.command = tail
    try:
        return args.func(args)
    except KeyboardInterrupt:
        _p("\n중단했습니다.")
        return 130
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
