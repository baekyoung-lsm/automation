"""시험용 가짜 자료 만들기. 전부 무작위이고 실제 사람·회사와 관계없다."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
            "한", "오", "서", "신", "권", "황", "안", "송", "류", "홍"]
GIVEN_FIRST = ["민", "서", "지", "현", "예", "수", "준", "하", "유", "도",
               "은", "재", "다", "채", "시", "우"]
GIVEN_LAST = ["준", "연", "우", "은", "호", "빈", "찬", "율", "아", "린",
              "성", "진", "희", "원", "영", "훈"]
DEPARTMENTS = ["영업", "개발", "인사", "재무", "마케팅", "고객지원", "물류", "기획"]
CITIES = {"서울시": ["강남구", "송파구", "마포구", "종로구", "성동구"],
          "부산시": ["해운대구", "수영구", "동래구"],
          "대구시": ["수성구", "달서구"],
          "인천시": ["연수구", "부평구"],
          "경기도": ["성남시", "수원시", "고양시", "용인시"]}
DOMAINS = ["example.com", "example.net", "test.co.kr", "mail.example.org"]
PRODUCTS = ["의자", "책상", "모니터", "키보드", "노트북", "가방", "우산", "컵"]
STATUSES = ["대기", "처리중", "완료", "취소"]

# 열 이름에 쓰는 종류. 모르는 종류를 조용히 문자열로 만들지 않으려고 목록을 둔다.
KINDS = ("이름", "전화", "이메일", "부서", "주소", "사업자번호", "날짜", "정수",
         "금액", "상품", "상태", "참거짓", "uuid")


class FakeError(Exception):
    pass


@dataclass
class Field:
    name: str
    kind: str
    low: float = 0
    high: float = 0

    @property
    def label(self) -> str:
        return self.name or self.kind


def parse_field(spec: str) -> Field:
    """'이름=이름', '금액=정수:1000:9000' 형태를 읽는다."""
    name, _, rest = spec.partition("=")
    body = rest or name
    parts = body.split(":")
    kind = parts[0].strip()
    if kind not in KINDS:
        raise FakeError(f"모르는 종류입니다: {kind} ({', '.join(KINDS)})")
    low = high = 0.0
    if len(parts) > 1:
        try:
            low = float(parts[1])
            high = float(parts[2]) if len(parts) > 2 else low
        except ValueError:
            raise FakeError(f"범위는 숫자로 적으세요: {spec}") from None
        if high < low:
            raise FakeError(f"범위가 뒤집혔습니다: {spec}")
    return Field(name.strip() if rest else kind, kind, low, high)


def bizno(rng: random.Random) -> str:
    """검증번호까지 맞는 가짜 사업자등록번호. 실제 등록 여부와는 무관하다."""
    digits = [rng.randrange(10) for _ in range(9)]
    weights = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    total = sum(d * w for d, w in zip(digits, weights)) + (digits[8] * 5) // 10
    digits.append((10 - total % 10) % 10)
    body = "".join(str(d) for d in digits)
    return f"{body[:3]}-{body[3:5]}-{body[5:]}"


def person(rng: random.Random) -> str:
    return (rng.choice(SURNAMES) + rng.choice(GIVEN_FIRST) + rng.choice(GIVEN_LAST))


def value(field: Field, rng: random.Random, *, today: date | None = None):
    kind = field.kind
    if kind == "이름":
        return person(rng)
    if kind == "전화":
        return f"010-{rng.randrange(1000, 10000)}-{rng.randrange(1000, 10000)}"
    if kind == "이메일":
        return (f"user{rng.randrange(1000, 9999)}@{rng.choice(DOMAINS)}")
    if kind == "부서":
        return rng.choice(DEPARTMENTS)
    if kind == "주소":
        city = rng.choice(list(CITIES))
        return f"{city} {rng.choice(CITIES[city])} {rng.randrange(1, 200)}-{rng.randrange(1, 40)}"
    if kind == "사업자번호":
        return bizno(rng)
    if kind == "날짜":
        base = today or date.today()
        span = int(field.high or field.low or 365)
        return base - timedelta(days=rng.randrange(span + 1))
    if kind == "정수":
        low, high = int(field.low or 0), int(field.high or field.low or 100)
        return rng.randrange(low, high + 1)
    if kind == "금액":
        low, high = int(field.low or 1000), int(field.high or field.low or 1_000_000)
        return rng.randrange(low // 100, high // 100 + 1) * 100
    if kind == "상품":
        return rng.choice(PRODUCTS)
    if kind == "상태":
        return rng.choice(STATUSES)
    if kind == "참거짓":
        return rng.random() < 0.5
    if kind == "uuid":
        import uuid

        return str(uuid.UUID(int=rng.getrandbits(128), version=4))
    raise FakeError(f"모르는 종류입니다: {kind}")


def make_rows(fields: list[Field], rows: int, *, seed: int | None = None,
              today: date | None = None) -> tuple[list[str], list[list]]:
    """(열 이름, 행들). seed 를 주면 같은 자료가 다시 나온다."""
    if not fields:
        raise FakeError("만들 열을 주세요.")
    if rows < 1:
        raise FakeError("행 수는 1 이상이어야 합니다.")
    rng = random.Random(seed)
    headers = [f.label for f in fields]
    body = [[value(f, rng, today=today) for f in fields] for _ in range(rows)]
    return headers, body
