"""attools CLI 진입점. 명령은 그룹마다 한 파일로 나눠 두었다."""

from __future__ import annotations

import argparse
import sys

from .. import __version__
from . import (dev_cmds, doc_cmds, file_cmds, git_cmds, json_cmds, keys_cmds,
               life_cmds, novel_cmds, sheet_cmds, text_cmds)

# 도움말에 나오는 순서다.
GROUP_MODULES = (file_cmds, dev_cmds, git_cmds, life_cmds, sheet_cmds,
                 text_cmds, doc_cmds, json_cmds, keys_cmds, novel_cmds)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="at", description="파일 / 텍스트 / JSON / 개발 / git / 엑셀 / 단축키 / 일상 / 소설 자동화 도구")
    ap.add_argument("-V", "--version", action="version", version=f"attools {__version__}")
    sub = ap.add_subparsers(dest="group", required=True)
    for module in GROUP_MODULES:
        module.add_commands(sub)
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
