"""Dockerfile 훑기 - 흔히 사고 나는 자리만 짚는다.

린터를 새로 만드는 것이 아니라, 팀에서 되풀이해 지적하게 되는 몇 가지를
자동으로 본다. «이렇다» 까지만 적고 고치지 않는다 - 사정이 있어 그렇게
쓴 것일 수 있다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

INSTRUCTIONS = (
    "FROM", "RUN", "CMD", "LABEL", "MAINTAINER", "EXPOSE", "ENV", "ADD",
    "COPY", "ENTRYPOINT", "VOLUME", "USER", "WORKDIR", "ARG", "ONBUILD",
    "STOPSIGNAL", "HEALTHCHECK", "SHELL",
)
# 값이 이미지에 그대로 박히는 자리. 빌드 인자로 준 비밀값도 히스토리에 남는다
SECRET_NAME = re.compile(
    r"(?i)(pass(word)?|secret|token|api[_-]?key|private[_-]?key|credential)")
SECRET_VALUE = re.compile(r"""^["']?[^"'\s]{6,}["']?$""")
# 값이 아니라 «다른 데서 받아 온다» 는 표시. 이런 것은 비밀값이 아니다
PLACEHOLDER = re.compile(r"(?i)\$\{|\$[A-Za-z_]|change[_-]?me|your[_-]?|example|"
                         r"^\s*$|^<.+>$")


@dataclass
class Step:
    instruction: str
    value: str
    line: int                    # 시작 줄 (1부터)
    stage: int = 0               # 몇 번째 FROM 뒤인가 (멀티 스테이지)


@dataclass
class Note:
    line: int
    kind: str                    # 문제 / 권고
    what: str
    why: str


@dataclass
class Report:
    steps: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    stages: int = 0

    @property
    def problems(self) -> list:
        return [one for one in self.notes if one.kind == "문제"]


def parse(text: str) -> list[Step]:
    """Dockerfile 을 명령 단위로. 줄 끝의 «\\» 이어짐을 한 덩어리로 본다."""
    steps: list[Step] = []
    stage = 0
    buffer: list[str] = []
    start = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not buffer:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            head, _, tail = stripped.partition(" ")
            if head.upper() not in INSTRUCTIONS:
                continue          # 우리가 모르는 줄은 조용히 넘긴다
            start = number
            buffer = [head.upper(), tail]
        else:
            buffer.append(line.strip())
        if line.endswith("\\"):
            buffer[-1] = buffer[-1][:-1]
            continue
        instruction = buffer[0]
        value = " ".join(part for part in buffer[1:] if part).strip()
        if instruction == "FROM":
            stage += 1
        steps.append(Step(instruction, value, start, stage))
        buffer = []
    if buffer:                    # 마지막 줄이 «\» 로 끝난 파일
        steps.append(Step(buffer[0], " ".join(buffer[1:]).strip(), start, stage))
    return steps


def _image_of(value: str) -> str:
    return value.split(" AS ")[0].split(" as ")[0].strip()


def _tagless(image: str) -> bool:
    """태그도 다이제스트도 없는가. 레지스트리 주소의 포트와 헷갈리지 않게 본다."""
    if "@" in image:
        return False
    last = image.split("/")[-1]
    return ":" not in last


def check(text: str, *, has_dockerignore: bool | None = None) -> Report:
    """Dockerfile 에서 흔히 사고 나는 자리를 찾는다."""
    report = Report(parse(text))
    steps = report.steps
    report.stages = max([s.stage for s in steps], default=0)
    last_stage = report.stages

    if not steps:
        return report

    for step in steps:
        value = step.value
        if step.instruction == "FROM":
            image = _image_of(value)
            if image.endswith(":latest") or _tagless(image):
                report.notes.append(Note(
                    step.line, "문제", f"FROM {image}",
                    "태그가 latest 이거나 없습니다 - 어제 되던 빌드가 오늘 "
                    "다른 이미지로 만들어집니다. 판을 적어 고정하세요."))
        elif step.instruction == "ADD":
            if value.startswith(("http://", "https://")):
                report.notes.append(Note(
                    step.line, "권고", "ADD 로 내려받기",
                    "ADD 는 받은 파일이 바뀌어도 캐시를 그대로 씁니다. "
                    "RUN curl 로 받아 쓰거나 COPY 를 쓰세요."))
        elif step.instruction == "RUN":
            if re.search(r"apt-get\s+install", value):
                if "apt-get update" not in value:
                    report.notes.append(Note(
                        step.line, "문제", "apt-get install 만 따로",
                        "update 와 install 이 다른 RUN 이면 캐시된 낡은 "
                        "목록으로 설치합니다 - 한 RUN 에 이어 쓰세요."))
                if "rm -rf /var/lib/apt/lists" not in value:
                    report.notes.append(Note(
                        step.line, "권고", "apt 목록을 안 지움",
                        "설치 뒤 /var/lib/apt/lists 를 지우지 않으면 그만큼 "
                        "이미지가 커집니다."))
                if "--no-install-recommends" not in value:
                    report.notes.append(Note(
                        step.line, "권고", "권장 패키지까지 설치",
                        "--no-install-recommends 를 붙이면 안 쓰는 것이 "
                        "덜 들어갑니다."))
            if re.search(r"pip3?\s+install", value) and "--no-cache-dir" not in value:
                report.notes.append(Note(
                    step.line, "권고", "pip 캐시가 남음",
                    "--no-cache-dir 를 붙이면 이미지에 캐시가 안 남습니다."))
            if re.search(r"(?i)(curl|wget)\b.*\|\s*(sudo\s+)?(ba)?sh", value):
                report.notes.append(Note(
                    step.line, "권고", "받아서 바로 실행",
                    "받은 것을 그대로 실행하면 무엇이 도는지 빌드마다 "
                    "달라질 수 있습니다."))
        elif step.instruction in ("ENV", "ARG"):
            name, _, raw = value.partition("=")
            if (SECRET_NAME.search(name) and raw.strip()
                    and not PLACEHOLDER.search(raw.strip())
                    and SECRET_VALUE.match(raw.strip())):
                report.notes.append(Note(
                    step.line, "문제", f"{step.instruction} 에 비밀값",
                    f"«{name.strip()}» 값이 이미지에 그대로 박힙니다 "
                    "(ARG 도 빌드 기록에 남습니다). 실행할 때 넣으세요."))

    # 마지막 단계에 USER 가 없으면 root 로 돈다
    if not [s for s in steps if s.instruction == "USER" and s.stage == last_stage]:
        report.notes.append(Note(
            0, "문제", "USER 가 없음",
            "컨테이너가 root 로 돕니다. 마지막 단계에 USER 를 지정하세요."))

    # 의존성 설치보다 «전부 복사» 가 앞서면 캐시가 매번 깨진다
    deps = re.compile(r"(?i)\b(pip3?|npm|yarn|pnpm|poetry|bundle|go mod|"
                      r"apt-get|apk)\b.*\b(install|ci|download|add|sync)\b")
    copy_all = None
    for step in steps:
        if step.instruction in ("COPY", "ADD") and step.stage == last_stage:
            parts = [p for p in step.value.split() if not p.startswith("--")]
            if parts and parts[0] in (".", "./", "*"):
                copy_all = copy_all or step
        elif (step.instruction == "RUN" and copy_all is not None
              and step.stage == last_stage and deps.search(step.value)):
            report.notes.append(Note(
                copy_all.line, "권고", "전부 복사한 뒤 설치",
                f"{step.line}행의 설치가 소스 한 줄만 고쳐도 다시 돕니다. "
                "의존성 파일만 먼저 COPY 하고 설치한 뒤 나머지를 복사하세요."))
            break

    # 마지막에 적힌 것만 산다
    for name in ("CMD", "ENTRYPOINT"):
        same = [s for s in steps if s.instruction == name and s.stage == last_stage]
        if len(same) > 1:
            report.notes.append(Note(
                same[-2].line, "문제", f"{name} 가 여러 개",
                f"{name} 는 마지막 것만 씁니다 - 앞의 것은 아무 일도 "
                "하지 않습니다."))

    if has_dockerignore is False:
        report.notes.append(Note(
            0, "권고", ".dockerignore 가 없음",
            ".git 과 빌드 찌꺼기까지 빌드 컨텍스트로 올라갑니다."))
    report.notes.sort(key=lambda one: (one.line == 0, one.line))
    return report


def read(path: Path) -> Report:
    """파일을 읽어 훑는다. 옆에 .dockerignore 가 있는지도 함께 본다."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return check(text, has_dockerignore=(path.parent / ".dockerignore").is_file())
