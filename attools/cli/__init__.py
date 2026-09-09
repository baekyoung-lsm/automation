"""attools CLI 진입점. 명령은 그룹마다 한 파일로 나눠 두었다."""

from __future__ import annotations

import argparse
import re
import sys

from .. import __version__
from . import (dev_cmds, doc_cmds, file_cmds, git_cmds, json_cmds, keys_cmds,
               life_cmds, novel_cmds, sheet_cmds, text_cmds, ui_cmds)
from .common import _cut, _grid, _p

# 도움말에 나오는 순서다.
GROUP_MODULES = (file_cmds, dev_cmds, git_cmds, life_cmds, sheet_cmds,
                 text_cmds, doc_cmds, json_cmds, keys_cmds, novel_cmds,
                 ui_cmds)


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


# 사람이 치는 말과 도움말에 적힌 말이 다르다. 찾기에서만 쓰는 짝이다.
FIND_ALIASES = {
    "압축": ["zip", "보관", "묶"],
    "글자수": ["글자 수"],
    "폰트": ["글꼴"],
    "사진": ["이미지", "그림"],
    "엑셀": ["xlsx", "csv", "표"],
    "한글": ["hwpx"],
    "워드": ["docx"],
    "메일": ["eml", "첨부"],
    "일정": ["ics", "캘린더", "마감"],
    "연락처": ["vcf", "주소록"],
    "백업": ["sync", "보관"],
    "번역": [],
    "암호": ["시크릿", "비밀번호"],
    "로그": ["log"],
    "속도": ["시간", "벤치"],
    "맞춤법": ["표기 오류", "typo"],
    "담당자": ["주로 만진 사람", "누가"],
    "주인": ["주로 만진 사람", "누가"],
    "누구": ["주로 만진 사람", "누가"],
    "급여": ["시급", "수당", "임금", "근무 시간"],
    "월급": ["시급", "수당", "통상임금"],
    "임금": ["시급", "수당"],
    "알바": ["시급", "주휴", "근무 시간"],
    "통계": ["집계", "요약"],
    "차트": ["그림", "그래프"],
    "도표": ["표"],
    "워터마크": ["쪽 번호"],
    "견적서": ["표", "틀"],
    "텍스트": ["글자"],
    "발표자료": ["pptx", "슬라이드"],
    "ppt": ["pptx", "슬라이드"],
    "본문": ["글자", "문단"],
    "복사": ["글자 꺼내"],
}


def _find_needles(text: str) -> list[str]:
    """찾을 말과, 같은 뜻으로 도움말에 적혔을 만한 말들."""
    needle = text.strip().lower()
    out = [needle, needle.replace(" ", "")]
    for word, others in FIND_ALIASES.items():
        if word in needle or needle in word:
            out += [word] + others
    return [n for n in dict.fromkeys(out) if n]


def cmd_find(a) -> int:
    needle = " ".join(a.words).strip().lower()
    if not needle:
        _p("찾을 말을 주세요. 예: at find 중복")
        return 1

    needles = _find_needles(needle)
    rows: list[tuple[str, str]] = []
    for path, help_text, parser in walk_commands(build_parser()):
        if any(isinstance(x, argparse._SubParsersAction) for x in parser._actions):
            continue                       # 그룹 자체는 건너뛴다
        haystack = " ".join(path) + " " + help_text
        if a.deep:
            haystack += " " + " ".join(
                (x.help or "") + " " + " ".join(x.option_strings)
                for x in parser._actions)
        flat = haystack.lower()
        # 띄어쓰기를 지운 꼴도 본다. «글자수» 로 쳐도 «글자 수» 가 걸리게
        if any(n in flat or n in flat.replace(" ", "") for n in needles):
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


class _Parser(argparse.ArgumentParser):
    """argparse 의 영어 오류를 한국어로 바꾸고, 오타는 비슷한 이름을 짚어 준다.

    명령이 이백 개가 넘어서 «invalid choice» 한 줄에 이름 쉰 개가 딸려 나온다.
    사람이 읽을 수 있는 것은 «혹시 이것인가요» 쪽이다.

    예시(epilog)는 줄을 그대로 둔다. argparse 기본값은 한 문단으로 이어 붙여
    서, 명령 예 서너 줄이 한 덩어리가 되어 어디까지가 한 줄인지 알 수 없다.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message: str):
        import difflib

        lines = []
        choice = re.match(r"argument (\S+): invalid choice: '([^']*)'"
                          r"(?: \(choose from (.*)\))?", message)
        required = re.match(r"the following arguments are required: (.+)", message)
        unknown = re.match(r"unrecognized arguments: (.+)", message)
        wants = re.match(r"argument (\S+): expected (?:one|at least one) argument",
                         message)
        bad_value = re.match(r"argument (\S+): invalid (\w+) value: '([^']*)'",
                             message)

        if choice:
            _name, given, raw = choice.groups()
            names = re.findall(r"'([^']+)'", raw or "")
            near = difflib.get_close_matches(given, names, n=3, cutoff=0.4)
            lines.append(f"없는 이름입니다: {given}")
            if near:
                lines.append("혹시 이것인가요: " + ", ".join(near))
            lines.append(f"{self.prog} 를 인자 없이 치면 있는 것을 보여 줍니다.")
        elif required:
            lines.append(f"빠진 것이 있습니다: {required.group(1)}")
            lines.append(f"{self.prog} --help 로 쓰는 법을 봅니다.")
        elif unknown:
            lines.append(f"모르는 인자입니다: {unknown.group(1)}")
            lines.append(f"{self.prog} --help 로 쓸 수 있는 것을 봅니다.")
        elif wants:
            lines.append(f"«{wants.group(1)}» 에는 값이 있어야 합니다.")
        elif bad_value:
            name, kind, given = bad_value.groups()
            korean = {"int": "정수", "float": "숫자"}.get(kind, kind)
            lines.append(f"«{name}» 에 {korean}가 아닌 값을 줬습니다: {given}")
        else:
            lines.append(message)

        sys.stderr.write("\n".join(lines) + "\n")
        raise SystemExit(2)


def _subparsers(parser: argparse.ArgumentParser):
    """그 파서에 달린 하위 명령 목록 동작. 없으면 None."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _list_group(parser: argparse.ArgumentParser, name: str) -> int:
    """«at sheet» 처럼 하위 명령 없이 부르면 무엇이 있는지 보여 준다.

    argparse 가 내는 사용법은 이름 쉰 개가 한 줄로 이어져 읽을 수가 없다.
    처음 쓰는 사람이 제일 먼저 치는 것이 그 형태라 표로 보여 준다.
    """
    action = _subparsers(parser)
    helps = {choice.dest: (choice.help or "")
             for choice in getattr(action, "_choices_actions", [])}
    rows = [[f"at {name} {key}", _cut(helps.get(key, ""), 60)]
            for key in (action.choices if action else {})]
    _p(f"at {name} 에는 명령이 {len(rows)}개 있습니다.")
    _grid(["명령", "하는 일"], rows, limit=60)
    _p(f"\n자세한 것은 at {name} <명령> --help 를 보세요. "
       "찾는 말이 있으면 at find <말> 도 됩니다.")
    return 1


def _list_groups(parser: argparse.ArgumentParser) -> int:
    """«at» 만 쳤을 때. 갈래와 그 안에 명령이 몇 개인지 보여 준다."""
    action = _subparsers(parser)
    helps = {choice.dest: (choice.help or "")
             for choice in getattr(action, "_choices_actions", [])}
    rows = []
    for name, group in (action.choices if action else {}).items():
        inner = _subparsers(group)
        count = f"{len(inner.choices):,}개" if inner else "-"
        rows.append([f"at {name}", count, _cut(helps.get(name, ""), 50)])
    _p(f"attools {__version__} - 갈래 {len(rows)}개")
    _grid(["갈래", "명령", "하는 일"], rows, limit=50)
    _p("\n갈래를 치면 그 안의 명령이 나옵니다 (예: at sheet). "
       "찾는 말이 있으면 at find <말>.")
    return 1


def build_parser() -> argparse.ArgumentParser:
    ap = _Parser(
        prog="at", description="파일 / 텍스트 / JSON / 개발 / git / 엑셀 / 단축키 / 일상 / 소설 자동화 도구")
    ap.add_argument("-V", "--version", action="version", version=f"attools {__version__}")
    sub = ap.add_subparsers(dest="group", required=False)
    for module in GROUP_MODULES:
        module.add_commands(sub)

    # 하위 명령 없이 «at sheet» 만 쳤을 때 목록을 보여 준다
    for name, parser in sub.choices.items():
        action = _subparsers(parser)
        if action is None:
            continue
        action.required = False
        parser.set_defaults(func=lambda a, p=parser, n=name: _list_group(p, n))

    fd = sub.add_parser("find", help="명령 찾기 - 하는 일로 검색")
    fd.add_argument("words", nargs="*", metavar="말")
    fd.add_argument("--deep", action="store_true", help="옵션 설명까지 찾는다")
    fd.set_defaults(func=cmd_find)

    cp = sub.add_parser("completion", help="셸 자동완성 스크립트 출력")
    cp.add_argument("shell", nargs="?", default="bash", choices=["bash", "zsh"])
    cp.set_defaults(func=cmd_completion)

    ap.set_defaults(func=lambda a, p=ap: _list_groups(p))
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
