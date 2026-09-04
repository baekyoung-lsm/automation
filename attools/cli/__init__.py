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


def _command_tree() -> dict[str, dict[str, list[str]]]:
    """{그룹: {하위명령: [옵션…]}}. 실제 파서에서 뽑는다."""
    tree: dict[str, dict[str, list[str]]] = {}
    for path, _help, parser in walk_commands(build_parser()):
        options = sorted({o for action in parser._actions
                          for o in action.option_strings if o.startswith("--")})
        if len(path) == 1:
            tree.setdefault(path[0], {})
            if not any(isinstance(a, argparse._SubParsersAction)
                       for a in parser._actions):
                tree[path[0]][""] = options
        elif len(path) == 2:
            tree.setdefault(path[0], {})[path[1]] = options
    return tree


def cmd_completion(a) -> int:
    tree = _command_tree()
    groups = " ".join(tree)

    if a.shell == "bash":
        lines = ["# attools 자동완성. 다음 줄을 ~/.bashrc 에 넣으세요:",
                 '#   eval "$(at completion bash)"',
                 "_at_complete() {",
                 '  local cur="${COMP_WORDS[COMP_CWORD]}" group="${COMP_WORDS[1]}"',
                 '  local sub="${COMP_WORDS[2]}" words=""',
                 "  if [ $COMP_CWORD -eq 1 ]; then",
                 f'    words="{groups}"',
                 "  elif [ $COMP_CWORD -eq 2 ]; then",
                 '    case "$group" in']
        for group, subs in tree.items():
            # 하위 명령이 없는 그룹(keys)은 그 자리에서 옵션을 완성한다
            names = " ".join(n for n in subs if n) or " ".join(subs.get("", []))
            lines.append(f'      {group}) words="{names}" ;;')
        lines += ['    esac', "  else", '    case "$group $sub" in']
        for group, subs in tree.items():
            for sub, options in subs.items():
                if sub and options:
                    lines.append(f'      "{group} {sub}") words="{" ".join(options)}" ;;')
        lines += ['    esac', "  fi",
                  '  COMPREPLY=($(compgen -W "$words" -- "$cur"))',
                  "}",
                  "complete -F _at_complete at"]
        _p("\n".join(lines))
        return 0

    # zsh
    lines = ["# attools 자동완성. 다음 줄을 ~/.zshrc 에 넣으세요:",
             '#   eval "$(at completion zsh)"',
             "_at_complete() {",
             "  local -a words",
             "  case $CURRENT in",
             f'    2) words=({groups}) ;;',
             "    3) case ${words[2]:-${(z)BUFFER}[2]} in"]
    for group, subs in tree.items():
        names = " ".join(n for n in subs if n) or " ".join(subs.get("", []))
        lines.append(f"      {group}) words=({names}) ;;")
    lines += ["      esac ;;", "  esac",
              "  compadd -- $words", "}",
              "compdef _at_complete at"]
    _p("\n".join(lines))
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

    cp = sub.add_parser("completion", help="셸 자동완성 스크립트 출력")
    cp.add_argument("shell", nargs="?", default="bash", choices=["bash", "zsh"])
    cp.set_defaults(func=cmd_completion)
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
