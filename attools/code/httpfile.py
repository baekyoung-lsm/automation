"""«.http» 파일 읽기 - 여러 요청을 적어 두고 차례대로 부르기.

VS Code REST Client 나 IntelliJ 가 쓰는 그 형식이다. 개발하면서 부르는
순서(로그인 -> 목록 -> 상세)를 파일로 남겨 두면 다음 사람도 같은 순서로
확인할 수 있다.

여기서는 읽기만 한다. 부르는 것은 cli 쪽이 devkit.fetch 로 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# «{{이름}}» 자리. 이름에 공백이 섞여 오는 파일이 있어 양옆은 버린다.
SLOT = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
SETTING = re.compile(r"^@([A-Za-z_][\w.-]*)\s*=\s*(.*)$")
# 첫 줄: «GET https://…» 또는 «POST /path HTTP/1.1»
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE")
# 주소에는 띄어쓰기가 없지만 «{{ 검색어 }}» 처럼 자리 안에는 들어올 수 있다.
# \S+ 로만 받으면 그런 줄을 통째로 «모르겠습니다» 로 흘려보낸다
START = re.compile(r"^(" + "|".join(METHODS) +
                   r")\s+((?:\S|\{\{[^{}]*\}\})+)(?:\s+HTTP/[\d.]+)?\s*$",
                   re.IGNORECASE)
# 주석 줄에 적는 «@save 이름 = 자리» - 응답에서 값을 꺼내 다음 요청에 쓴다.
SAVE = re.compile(r"^@save\s+([A-Za-z_][\w.-]*)\s*=\s*(\S+)\s*$", re.IGNORECASE)
INDEX = re.compile(r"\[(\d+)\]")


@dataclass
class Request:
    number: int
    name: str = ""
    method: str = "GET"
    url: str = ""
    headers: list = field(default_factory=list)     # [(이름, 값)]
    body: str = ""
    line: int = 0                                   # 파일에서 시작한 줄
    saves: list = field(default_factory=list)       # [(이름, 응답 속 자리)]

    @property
    def writes(self) -> bool:
        """되돌릴 수 없는 메서드인가. 모르고 부르면 자료가 바뀐다."""
        return self.method.upper() in ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class HttpFile:
    requests: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)    # 못 읽은 줄

    @property
    def writes(self) -> list:
        return [one for one in self.requests if one.writes]


def parse(text: str) -> HttpFile:
    """.http 파일을 읽는다. 못 읽은 줄은 조용히 버리지 않고 적어 둔다."""
    out = HttpFile()
    current: Request | None = None
    in_body = False
    body: list[str] = []
    name = ""

    def close() -> None:
        nonlocal current, body, in_body
        if current is not None:
            current.body = "\n".join(body).strip("\n")
            out.requests.append(current)
        current, body, in_body = None, [], False

    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if line.startswith("###"):
            close()
            name = line.lstrip("#").strip()
            continue
        if current is not None and in_body:
            body.append(raw)
            continue
        if not line.strip():
            if current is not None:
                in_body = True          # 빈 줄 다음부터가 본문이다
            continue
        if line.lstrip().startswith(("#", "//")):
            note = line.lstrip().lstrip("#/").strip()
            keep = SAVE.match(note)
            if keep and current is not None:
                current.saves.append((keep.group(1), keep.group(2)))
            continue

        setting = SETTING.match(line.strip())
        if setting and current is None:
            out.variables[setting.group(1)] = setting.group(2).strip()
            continue

        found = START.match(line.strip())
        if found:
            close()
            current = Request(len(out.requests) + 1, name,
                              found.group(1).upper(), found.group(2), line=number)
            name = ""
            continue

        if current is not None and ":" in line:
            key, _, value = line.partition(":")
            current.headers.append((key.strip(), value.strip()))
            continue

        out.problems.append(f"{number}행: 무엇인지 모르겠습니다 - {line.strip()[:40]}")

    close()
    return out


def fill(text: str, values: dict) -> tuple[str, list]:
    """«{{이름}}» 을 채운다. (채운 글, 모르는 이름들)

    모르는 이름을 «{{이름}}» 인 채로 두고 부르면 주소가 이상한 채로 나가고,
    빈 칸으로 바꾸면 엉뚱한 곳을 부른다. 둘 다 하지 않고 이름을 돌려준다.
    """
    missing: list[str] = []

    def swap(found: re.Match) -> str:
        key = found.group(1)
        if key in values:
            return str(values[key])
        if key not in missing:
            missing.append(key)
        return found.group(0)

    return SLOT.sub(swap, text), missing


def resolve(request: Request, values: dict) -> tuple[Request, list]:
    """한 요청의 주소·머리글·본문을 채운다. (채운 요청, 모르는 이름들)"""
    missing: list[str] = []

    def take(text: str) -> str:
        filled, gone = fill(text, values)
        for one in gone:
            if one not in missing:
                missing.append(one)
        return filled

    made = Request(request.number, request.name, request.method,
                   take(request.url),
                   [(take(k), take(v)) for k, v in request.headers],
                   take(request.body), request.line, list(request.saves))
    return made, missing


def pick(data, path: str):
    """«data.items[0].id» 같은 자리에서 값 하나를 꺼낸다. (값, 못 찾은 이유)

    못 찾으면 None 을 값으로 주지 않는다 - 다음 요청이 «None» 을 달고 나가면
    무엇이 잘못됐는지 응답을 봐야 알게 된다. 어디서 끊겼는지 말로 돌려준다.
    """
    here = data
    walked = ""
    for step in path.replace("[", ".[").split("."):
        step = step.strip()
        if not step or step in ("$", "body"):
            continue
        found = INDEX.fullmatch(step)
        if found:
            if not isinstance(here, list):
                return None, f"{walked or '응답'} 은 목록이 아닙니다"
            spot = int(found.group(1))
            if spot >= len(here):
                return None, f"{walked or '응답'} 에 {spot}번째가 없습니다 ({len(here)}개)"
            here, walked = here[spot], f"{walked}[{spot}]"
            continue
        if not isinstance(here, dict) or step not in here:
            return None, f"응답에 «{walked + '.' if walked else ''}{step}» 이 없습니다"
        here, walked = here[step], f"{walked}.{step}" if walked else step
    return here, ""


def read_vars(pairs) -> dict:
    """«이름=값» 목록을 사전으로. 형태가 틀리면 그 자리를 알려 준다."""
    out: dict[str, str] = {}
    for one in pairs or []:
        key, sep, value = str(one).partition("=")
        if not sep or not key.strip():
            raise ValueError(f"«이름=값» 으로 주세요: {one}")
        out[key.strip()] = value
    return out
