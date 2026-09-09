"""받은 메일 파일(.eml)에서 머리글·본문·첨부를 꺼낸다.

메일을 통째로 내려받거나 전달받으면 .eml 로 온다. 그 안의 첨부를 손으로
꺼내려면 메일 앱에 다시 넣어야 하는데, 그 자리를 없애려고 만든다.

표준 라이브러리 email 만 쓴다. 보내지는 않는다 - 읽기만 한다.
«보낸 사람» 은 메일에 적힌 값 그대로다. 진짜 보낸 사람인지는 알 수 없다
(메일 머리글은 누구나 적을 수 있다).
"""

from __future__ import annotations

import email
import email.policy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# .msg(아웃룩 전용)는 형식이 아예 달라 읽지 못한다. 메일 앱에서 .eml 로 저장한다.
MAIL_SUFFIXES = {".eml"}


class EmlError(Exception):
    pass


@dataclass
class Attachment:
    name: str
    size: int
    kind: str = ""                 # content type
    data: bytes = b""


@dataclass
class Mail:
    path: Path
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    date: datetime | None = None
    body: str = ""
    html_only: bool = False        # 글자 본문 없이 HTML 만 있던 메일인가
    attachments: list = field(default_factory=list)

    @property
    def when(self) -> str:
        return self.date.strftime("%Y-%m-%d %H:%M") if self.date else ""


def _header(message, name: str) -> str:
    """머리글 하나를 사람이 읽는 글자로. 한글 제목은 인코딩되어 온다."""
    value = message.get(name)
    if value is None:
        return ""
    text = str(value)
    return " ".join(text.split())


def read_mail(path: Path, *, keep_data: bool = False) -> Mail:
    """메일 하나를 읽는다. keep_data 면 첨부 내용까지 들고 있는다."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EmlError(str(exc)) from None
    if not raw.strip():
        raise EmlError(f"빈 파일입니다: {path.name}")

    try:
        message = email.message_from_bytes(raw, policy=email.policy.default)
    except Exception as exc:            # email 은 여러 예외를 낸다
        raise EmlError(f"메일로 읽지 못했습니다: {path.name} ({exc})") from None

    mail = Mail(path=path,
                subject=_header(message, "Subject"),
                sender=_header(message, "From"),
                to=_header(message, "To"),
                cc=_header(message, "Cc"))
    try:
        mail.date = message.get("Date").datetime if message.get("Date") else None
    except (AttributeError, ValueError, TypeError):
        mail.date = None

    body = message.get_body(preferencelist=("plain",))
    if body is None:
        body = message.get_body(preferencelist=("html",))
        mail.html_only = body is not None
    if body is not None:
        try:
            mail.body = body.get_content()
        except (LookupError, ValueError, UnicodeDecodeError):
            mail.body = ""

    for part in message.iter_attachments():
        name = part.get_filename() or "이름없는첨부"
        # 첨부는 «파일» 이므로 바이트 그대로 꺼낸다. get_content 로 받으면
        # 글자 파일(csv·txt)이 charset 해석을 거쳐 깨진 채로 나온다
        try:
            data = part.get_payload(decode=True)
        except (LookupError, ValueError, UnicodeDecodeError):
            data = None
        if data is None:
            try:
                data = part.get_content()
            except (LookupError, ValueError, UnicodeDecodeError):
                data = b""
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        elif not isinstance(data, bytes):
            data = bytes(data)
        mail.attachments.append(Attachment(
            name=" ".join(str(name).split()), size=len(data),
            kind=part.get_content_type(),
            data=data if keep_data else b""))
    return mail


def collect(root: Path) -> list[Path]:
    """폴더 안의 .eml 을 이름 순으로. 파일 하나를 주면 그 하나만."""
    root = Path(root)
    if root.is_file():
        return [root]
    return sorted(p for p in root.rglob("*")
                  if p.is_file() and p.suffix.lower() == ".eml")

