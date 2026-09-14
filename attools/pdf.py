"""의존성 없는 PDF - 속성 읽기, 쪽 다루기, 이미지 묶기, 글자 꺼내기.

스캔한 사진을 제출용 PDF 한 장으로 묶고, 받은 PDF 의 제목·쪽 수를 보고,
쪽을 뽑거나 합치거나 번호를 찍고, 본문 글자를 꺼낸다.

글자는 글꼴에 ToUnicode 표가 있을 때만 꺼낸다. 표가 없는 글꼴(CID)은 번호가
무슨 글자인지 알 수 없으므로 그 부분을 빼고 어느 글꼴이 그랬는지 알린다 -
지어낸 글자가 섞여 나오는 것은 «안 나오는 것» 보다 나쁘다.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------- 속성 읽기

PDF_INFO_KEYS = {"Title": "title", "Author": "author", "Subject": "subject",
                 "Keywords": "keywords", "Producer": "program",
                 "CreationDate": "created", "ModDate": "modified"}
PAGE_RE = re.compile(rb"/Type\s*/Page(?![sC/\w])")
PAGES_COUNT_RE = re.compile(rb"/Type\s*/Pages\b[^>]{0,400}?/Count\s+(\d+)"
                            rb"|/Count\s+(\d+)[^>]{0,400}?/Type\s*/Pages\b", re.S)
OBJSTM_RE = re.compile(rb"<<[^<>]{0,500}/Type\s*/ObjStm.{0,500}?>>\s*stream\r?\n",
                       re.S)


class PdfError(Exception):
    pass


@dataclass
class PdfInfo:
    path: Path
    version: str = ""           # PDF-1.7
    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: str = ""
    program: str = ""
    created: str = ""
    modified: str = ""
    pages: int | None = None
    text_pages: int | None = None   # 글꼴이 걸린 쪽 수 (0 이면 스캔본으로 보인다)
    error: str = ""


def _info_by_objects(path: Path, info: "PdfInfo", *, look: int = 20) -> bool:
    """객체를 제대로 읽어 속성을 채운다. 못 읽으면 False (그때는 훑어 센다).

    정규식으로 «/Type /Page» 를 세면 압축 묶음 안의 옛 판까지 세어 쪽 수가
    부풀 때가 있다. 읽을 수 있으면 쪽 나무를 걸어가는 편이 정확하다.
    """
    try:
        doc = open_pdf(path)
        pages = doc.pages()
    except (PdfError, OSError, ValueError, RecursionError):
        return False

    info.pages = len(pages) or None
    meta = doc.get(doc.trailer.get("Info"))
    if isinstance(meta, dict):
        for key, field_name in PDF_INFO_KEYS.items():
            value = _string_text(doc.get(meta.get(key))).strip()
            if field_name in ("created", "modified"):
                value = _date(value)
            if value:
                setattr(info, field_name, value)

    with_text = 0
    for page in pages[:look]:
        resources = doc.get(page.data.get("Resources"))
        fonts = doc.get(resources.get("Font")) if isinstance(resources, dict) else None
        if isinstance(fonts, dict) and fonts:
            with_text += 1
    info.text_pages = with_text
    return True


def _text(raw: bytes) -> str:
    """PDF 문자열을 읽는다. (글자) 와 <16진수> 두 가지가 있다."""
    raw = raw.strip()
    if raw.startswith(b"<") and raw.endswith(b">"):
        try:
            data = bytes.fromhex(raw[1:-1].decode("ascii", "ignore").strip())
        except ValueError:
            return ""
    elif raw.startswith(b"(") and raw.endswith(b")"):
        body = raw[1:-1]
        out = bytearray()
        i = 0
        while i < len(body):
            ch = body[i]
            if ch == 0x5C and i + 1 < len(body):      # 역슬래시 이스케이프
                nxt = body[i + 1]
                out.append({0x6E: 10, 0x72: 13, 0x74: 9}.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        data = bytes(out)
    else:
        return ""

    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", "replace").strip()
    return data.decode("latin-1", "replace").strip()


def _date(value: str) -> str:
    """D:20260101120000+09'00' 을 사람이 읽는 꼴로. 못 읽으면 원문 그대로."""
    body = value[2:] if value.startswith("D:") else value
    digits = "".join(ch for ch in body if ch.isdigit())
    if len(digits) < 8:
        return value
    out = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
    if len(digits) >= 12:
        out += f" {digits[8:10]}:{digits[10:12]}"
    return out


def _slice(body: bytes, start: int) -> bytes:
    """그 자리에서 시작하는 값 하나를 잘라 낸다.

    (글자) 안에는 이스케이프한 괄호 «\\)» 도, 짝이 맞는 괄호도 들어간다.
    첫 «)» 에서 끊으면 «2026 \\(1\\) 계획» 이 «2026 (1» 로 잘린다.
    """
    if start >= len(body):
        return b""
    if body[start:start + 1] == b"<":
        end = body.find(b">", start)
        return body[start:end + 1] if end > 0 else b""

    depth = 0
    i = start
    while i < len(body):
        ch = body[i:i + 1]
        if ch == b"\\":
            i += 2
            continue
        if ch == b"(":
            depth += 1
        elif ch == b")":
            depth -= 1
            if depth == 0:
                return body[start:i + 1]
        i += 1
    return b""


def _flat(raw: bytes) -> bytes:
    """읽을 수 있는 만큼 편다. 압축된 객체 묶음(ObjStm)은 풀어서 붙인다."""
    out = [raw]
    for match in OBJSTM_RE.finditer(raw):
        chunk = raw[match.end():match.end() + (2 << 20)]
        end = chunk.find(b"endstream")
        try:
            out.append(zlib.decompress(chunk[:end] if end > 0 else chunk))
        except zlib.error:
            continue          # 다른 방식으로 눌린 것은 건너뛴다
    return b"\n".join(out)


def read_info(path: Path) -> PdfInfo:
    """PDF 의 제목·만든 사람·쪽 수를 읽는다. 못 읽으면 까닭을 적는다."""
    path = Path(path)
    info = PdfInfo(path=path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        info.error = str(e)
        return info

    if not raw.startswith(b"%PDF-"):
        info.error = "PDF 가 아닙니다 (%PDF- 로 시작하지 않습니다)"
        return info
    info.version = raw[1:8].decode("ascii", "replace")

    if b"/Encrypt" in raw:
        info.error = "암호가 걸려 있어 속성을 읽지 못했습니다"
        return info

    read = _info_by_objects(path, info)     # 제대로 읽을 수 있으면 그쪽이 정확하다
    if read:
        return info

    body = _flat(raw)
    pages = len(PAGE_RE.findall(body))
    if not pages:
        counts = [int(a or b) for a, b in PAGES_COUNT_RE.findall(body)]
        pages = max(counts) if counts else 0
    info.pages = pages or None
    if info.pages is None:
        info.error = "쪽 수를 읽지 못했습니다"

    for key, field_name in PDF_INFO_KEYS.items():
        match = re.search(rb"/" + key.encode() + rb"\s*(?=[(<])", body)
        if not match:
            continue
        value = _text(_slice(body, match.end()))
        if field_name in ("created", "modified"):
            value = _date(value)
        if value:
            setattr(info, field_name, value)
    return info


# ---------------------------------------------------------------- 이미지 묶기

PAGE_SIZES = {                    # 이름 -> (가로, 세로) 포인트 (72분의 1인치)
    "a4": (595.28, 841.89),
    "a5": (419.53, 595.28),
    "b5": (498.90, 708.66),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}
MM = 72 / 25.4                    # 밀리미터 -> 포인트
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}      # 넣을 수 있는 것만
JPEG_SOF = {0xC0, 0xC1, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}     # 0xC2(프로그레시브)는 뺀다
PNG_COLORS = {0: 1, 2: 3, 3: 1, 4: 1, 6: 3}         # 색 종류 -> 최종 성분 수


@dataclass
class PageImage:
    path: Path
    width: int                    # 픽셀
    height: int
    data: bytes                   # PDF 스트림에 그대로 넣을 바이트
    filter: str                   # DCTDecode 또는 FlateDecode
    colorspace: str               # DeviceGray 또는 DeviceRGB
    bits: int = 8


def _jpeg_page(raw: bytes, path: Path) -> PageImage:
    """JPEG 은 다시 눌지 않고 그대로 넣는다 (DCTDecode). 화질이 안 떨어진다."""
    i = 2
    while i + 9 < len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker == 0xC2:
            raise PdfError("프로그레시브 JPEG 이라 넣지 못합니다 "
                           "(일반(baseline) JPEG 으로 다시 저장하세요)")
        if marker in JPEG_SOF:
            height = int.from_bytes(raw[i + 5:i + 7], "big")
            width = int.from_bytes(raw[i + 7:i + 9], "big")
            components = raw[i + 9]
            if components == 3:
                space = "DeviceRGB"
            elif components == 1:
                space = "DeviceGray"
            else:
                raise PdfError(f"성분이 {components}개인 JPEG(CMYK 등)은 "
                               "넣지 못합니다")
            return PageImage(path, width, height, raw, "DCTDecode", space)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = int.from_bytes(raw[i + 2:i + 4], "big")
        if length < 2:
            break
        i += 2 + length
    raise PdfError("JPEG 의 크기를 읽지 못했습니다")


def _png_chunks(raw: bytes):
    i = 8
    while i + 8 <= len(raw):
        length = int.from_bytes(raw[i:i + 4], "big")
        kind = raw[i + 4:i + 8]
        yield kind, raw[i + 8:i + 8 + length]
        i += 8 + length + 4


def _unfilter(data: bytes, width: int, height: int, stride: int,
              step: int) -> bytearray:
    """PNG 의 줄별 필터를 되돌린다. 이걸 안 풀면 그림이 뭉개진다."""
    out = bytearray()
    previous = bytearray(stride)
    at = 0
    for _row in range(height):
        if at >= len(data):
            break
        kind = data[at]
        line = bytearray(data[at + 1:at + 1 + stride])
        if len(line) < stride:
            line += bytearray(stride - len(line))
        at += 1 + stride
        for x in range(stride):
            left = line[x - step] if x >= step else 0
            up = previous[x]
            upleft = previous[x - step] if x >= step else 0
            if kind == 0:
                value = line[x]
            elif kind == 1:
                value = line[x] + left
            elif kind == 2:
                value = line[x] + up
            elif kind == 3:
                value = line[x] + (left + up) // 2
            elif kind == 4:
                p = left + up - upleft
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
                best = left if (pa <= pb and pa <= pc) else (up if pb <= pc
                                                             else upleft)
                value = line[x] + best
            else:
                raise PdfError(f"모르는 PNG 줄 필터입니다: {kind}")
            line[x] = value & 0xFF
        out += line
        previous = line
    return out


def _png_page(raw: bytes, path: Path) -> PageImage:
    """PNG 은 픽셀을 풀었다가 다시 눌러 넣는다 (PDF 는 PNG 를 그대로 못 받는다)."""
    header = {}
    idat = bytearray()
    palette = b""
    for kind, body in _png_chunks(raw):
        if kind == b"IHDR":
            header = {
                "width": int.from_bytes(body[0:4], "big"),
                "height": int.from_bytes(body[4:8], "big"),
                "bits": body[8], "color": body[9], "interlace": body[12],
            }
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break

    if not header:
        raise PdfError("PNG 머리말(IHDR)을 찾지 못했습니다")
    if header["interlace"]:
        raise PdfError("인터레이스 PNG 는 넣지 못합니다 (그냥 PNG 로 다시 저장하세요)")
    if header["bits"] not in (8, 16):
        raise PdfError(f"{header['bits']}비트 PNG 는 넣지 못합니다 "
                       "(8비트로 다시 저장하세요)")
    color = header["color"]
    if color not in PNG_COLORS:
        raise PdfError(f"모르는 PNG 색 방식입니다: {color}")

    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
    depth = header["bits"] // 8
    width, height = header["width"], header["height"]
    stride = width * channels * depth
    try:
        flat = _unfilter(zlib.decompress(bytes(idat)), width, height, stride,
                         channels * depth)
    except zlib.error as exc:
        raise PdfError(f"PNG 를 풀지 못했습니다: {exc}") from None

    out = bytearray()
    keep = PNG_COLORS[color]
    for row in range(height):
        line = flat[row * stride:(row + 1) * stride]
        for x in range(width):
            at = x * channels * depth
            samples = [line[at + c * depth] for c in range(channels)]
            if color == 3:                      # 팔레트
                index = samples[0] * 3
                out += palette[index:index + 3] or b"\x00\x00\x00"
                continue
            if color in (4, 6):                 # 알파는 흰 바탕에 얹어 없앤다
                alpha = samples[-1]
                body = samples[:-1]
                samples = [(v * alpha + 255 * (255 - alpha)) // 255
                           for v in body]
            out += bytes(samples[:keep] if color != 3 else samples)

    space = "DeviceRGB" if (keep == 3 or color == 3) else "DeviceGray"
    return PageImage(path, width, height, zlib.compress(bytes(out), 6),
                     "FlateDecode", space)


def read_image(path: Path) -> PageImage:
    """이미지 한 장을 PDF 에 넣을 수 있는 꼴로 읽는다. 못 넣으면 까닭을 든다."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PdfError(str(exc)) from None

    if raw[:2] == b"\xff\xd8":
        return _jpeg_page(raw, path)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return _png_page(raw, path)
    raise PdfError("jpg 나 png 가 아닙니다 (gif·bmp·webp 는 jpg 로 "
                   "다시 저장하세요)")


def _obj(number: int, body: bytes) -> bytes:
    return f"{number} 0 obj\n".encode() + body + b"\nendobj\n"


def _stream(dictionary: str, data: bytes) -> bytes:
    return (f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode()
            + data + b"\nendstream")


def images_to_pdf(images: list[PageImage], out: Path, *, page: str = "a4",
                  margin_mm: float = 0.0, landscape: bool = False,
                  rotate: bool = True, title: str = "") -> Path:
    """이미지들을 한 장에 하나씩 담은 PDF 로 만든다.

    이미지는 다시 그리지 않고 쪽에 맞춰 «넣기만» 한다. 비율은 그대로 두고
    가운데에 놓는다 - 늘려 채우면 스캔한 서류가 찌그러진다.
    """
    if page not in PAGE_SIZES:
        raise PdfError(f"모르는 쪽 크기입니다: {page} "
                       f"({', '.join(sorted(PAGE_SIZES))})")
    if not images:
        raise PdfError("넣을 이미지가 없습니다")

    box = PAGE_SIZES[page]
    if landscape:
        box = (box[1], box[0])
    margin = max(0.0, margin_mm) * MM

    objects: list[bytes] = []      # 1번부터 차례로
    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    root_no = add(b"")             # 1: Catalog (나중에 채운다)
    pages_no = add(b"")            # 2: Pages
    page_numbers: list[int] = []

    for image in images:
        page_width, page_height = box
        wide = image.width > image.height
        turn = rotate and wide and page_height > page_width
        room_w = (page_height if turn else page_width) - 2 * margin
        room_h = (page_width if turn else page_height) - 2 * margin
        scale = min(room_w / image.width, room_h / image.height)
        draw_w, draw_h = image.width * scale, image.height * scale
        left = (room_w - draw_w) / 2 + margin
        bottom = (room_h - draw_h) / 2 + margin

        if turn:                    # 90도 돌려 눕힌다 (원본은 그대로 둔다)
            matrix = (f"0 {draw_w:.2f} {-draw_h:.2f} 0 "
                      f"{page_width - bottom:.2f} {left:.2f} cm")
        else:
            matrix = f"{draw_w:.2f} 0 0 {draw_h:.2f} {left:.2f} {bottom:.2f} cm"

        content = f"q {matrix} /Im0 Do Q".encode()
        image_no = add(_stream(
            f"/Type /XObject /Subtype /Image /Width {image.width} "
            f"/Height {image.height} /ColorSpace /{image.colorspace} "
            f"/BitsPerComponent {image.bits} /Filter /{image.filter}",
            image.data))
        content_no = add(_stream("", content))
        page_no = add(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
            f"{page_width:.2f} {page_height:.2f}] "
            f"/Resources << /XObject << /Im0 {image_no} 0 R >> >> "
            f"/Contents {content_no} 0 R >>".encode())
        page_numbers.append(page_no)

    kids = " ".join(f"{n} 0 R" for n in page_numbers)
    objects[pages_no - 1] = (f"<< /Type /Pages /Kids [{kids}] "
                             f"/Count {len(page_numbers)} >>").encode()
    info_no = 0
    if title:
        # 한글 제목은 16진수 UTF-16 으로 적는다. 괄호 escape 를 신경 쓸 일이 없다.
        packed = (b"\xfe\xff" + title.encode("utf-16-be")).hex()
        info_no = add(f"<< /Title <{packed}> /Producer (attools) >>".encode())
    objects[root_no - 1] = (f"<< /Type /Catalog /Pages {pages_no} 0 R "
                            f">>").encode()

    body = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, content in enumerate(objects, 1):
        offsets.append(len(body))
        body += _obj(number, content)

    start = len(body)
    body += f"xref\n0 {len(objects) + 1}\n".encode()
    body += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        body += f"{offset:010d} 00000 n \n".encode()
    trailer = f"<< /Size {len(objects) + 1} /Root {root_no} 0 R"
    if info_no:
        trailer += f" /Info {info_no} 0 R"
    body += (f"trailer\n{trailer} >>\nstartxref\n{start}\n%%EOF\n").encode()

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(body))
    return out


# ------------------------------------------------------------ 쪽 뽑기·합치기
#
# 여기서부터는 PDF 를 «객체» 단위로 읽는다. 쪽 하나를 뽑으려면 그 쪽이 걸고 있는
# 글꼴·그림·색 정보까지 함께 옮겨야 하는데, 그 그물은 정규식으로 못 따라간다.
# 스트림(눌린 자료)은 풀지 않고 그대로 옮긴다 - 풀었다 다시 누르면 그림이
# 조용히 상한다.

_WS_BYTES = b"\x00\t\n\x0c\r "
_DELIM_BYTES = b"()<>[]{}/%"
_INT_RE = re.compile(rb"[+-]?\d+")
_REAL_RE = re.compile(rb"[+-]*(?:\d+\.\d*|\.\d+|\d+)")
_ESCAPES = {0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09, 0x62: 0x08, 0x66: 0x0C,
            0x28: 0x28, 0x29: 0x29, 0x5C: 0x5C}
_OBJ_RE = re.compile(rb"(?:^|[\s\x00])(\d+)\s+(\d+)\s+obj\b")
_INHERITED = ("Resources", "MediaBox", "CropBox", "Rotate")
_NAME_KEEP = re.compile(rb"[\x21-\x7e]")
_NAME_ESCAPE = set(b"()<>[]{}/%#")


class Name(str):
    """PDF 의 /이름. 글자열과 구분해야 다시 쓸 때 «/» 를 붙일 수 있다."""

    __slots__ = ()


class Ref(NamedTuple):
    """«12 0 R» - 다른 객체를 가리키는 번호."""

    num: int
    gen: int = 0


@dataclass
class Stream:
    """사전 + 눌린 자료. raw 는 파일에 있던 그대로다."""

    data: dict
    raw: bytes


class _Reader:
    """PDF 값 하나를 읽는다. 사전·배열·이름·글자열·번호·참조."""

    def __init__(self, raw: bytes, pos: int = 0, resolve=None):
        self.raw = raw
        self.pos = pos
        self.resolve = resolve or (lambda v: v)

    def skip(self) -> None:
        raw, end = self.raw, len(self.raw)
        while self.pos < end:
            ch = raw[self.pos]
            if ch in _WS_BYTES:
                self.pos += 1
            elif ch == 0x25:                      # % 주석은 줄 끝까지
                line = raw.find(b"\n", self.pos)
                self.pos = end if line < 0 else line + 1
            else:
                return

    def word(self) -> bytes:
        self.skip()
        raw, end = self.raw, len(self.raw)
        start = self.pos
        while (self.pos < end and raw[self.pos] not in _WS_BYTES
               and raw[self.pos] not in _DELIM_BYTES):
            self.pos += 1
        if self.pos == start:                     # 구분자는 한 글자로
            self.pos += 1
        return raw[start:self.pos]

    def value(self):
        self.skip()
        raw = self.raw
        if self.pos >= len(raw):
            raise PdfError("파일이 갑자기 끝났습니다")
        ch = raw[self.pos]
        if ch == 0x2F:                            # /이름
            return self._name()
        if ch == 0x28:                            # (글자열)
            return self._literal()
        if ch == 0x3C:                            # <<사전>> 또는 <16진수>
            return self._dict() if raw[self.pos + 1:self.pos + 2] == b"<" \
                else self._hex()
        if ch == 0x5B:                            # [배열]
            return self._array()
        word = self.word()
        if word == b"true":
            return True
        if word == b"false":
            return False
        if word == b"null":
            return None
        if _INT_RE.fullmatch(word):
            return self._maybe_ref(int(word))
        if _REAL_RE.fullmatch(word):
            return float(word.replace(b"--", b"-"))
        raise PdfError(f"읽지 못한 값입니다: {word[:20]!r}")

    def _maybe_ref(self, number: int):
        """«12 0 R» 인지 그냥 숫자 12 인지는 뒤를 봐야 안다."""
        save = self.pos
        gen = self.word()
        if _INT_RE.fullmatch(gen) and self.word() == b"R":
            return Ref(number, int(gen))
        self.pos = save
        return number

    def _name(self) -> Name:
        self.pos += 1
        raw, end = self.raw, len(self.raw)
        out = bytearray()
        while self.pos < end:
            ch = raw[self.pos]
            if ch in _WS_BYTES or ch in _DELIM_BYTES:
                break
            if ch == 0x23 and self.pos + 2 < end:          # #20 = 빈칸
                try:
                    out.append(int(raw[self.pos + 1:self.pos + 3], 16))
                    self.pos += 3
                    continue
                except ValueError:
                    pass
            out.append(ch)
            self.pos += 1
        return Name(out.decode("latin-1"))

    def _literal(self) -> bytes:
        raw, end = self.raw, len(self.raw)
        self.pos += 1
        depth, out = 1, bytearray()
        while self.pos < end:
            ch = raw[self.pos]
            if ch == 0x5C:                                  # 역슬래시
                nxt = raw[self.pos + 1] if self.pos + 1 < end else 0
                if nxt in _ESCAPES:
                    out.append(_ESCAPES[nxt])
                    self.pos += 2
                elif 0x30 <= nxt <= 0x37:                   # 8진수 세 자리까지
                    digits = ""
                    self.pos += 1
                    while len(digits) < 3 and self.pos < end and 0x30 <= raw[self.pos] <= 0x37:
                        digits += chr(raw[self.pos])
                        self.pos += 1
                    out.append(int(digits, 8) & 0xFF)
                elif nxt in (0x0A, 0x0D):                   # 줄 이어 쓰기
                    self.pos += 2
                    if nxt == 0x0D and raw[self.pos:self.pos + 1] == b"\n":
                        self.pos += 1
                else:
                    out.append(nxt)
                    self.pos += 2
                continue
            if ch == 0x28:
                depth += 1
            elif ch == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return bytes(out)
            out.append(ch)
            self.pos += 1
        raise PdfError("글자열이 닫히지 않았습니다")

    def _hex(self) -> bytes:
        end = self.raw.find(b">", self.pos)
        if end < 0:
            raise PdfError("16진수 글자열이 닫히지 않았습니다")
        digits = re.sub(rb"[^0-9A-Fa-f]", b"", self.raw[self.pos + 1:end])
        self.pos = end + 1
        if len(digits) % 2:
            digits += b"0"
        return bytes.fromhex(digits.decode("ascii"))

    def _array(self) -> list:
        self.pos += 1
        out = []
        while True:
            self.skip()
            if self.pos >= len(self.raw):
                raise PdfError("배열이 닫히지 않았습니다")
            if self.raw[self.pos] == 0x5D:
                self.pos += 1
                return out
            out.append(self.value())

    def _dict(self) -> dict:
        self.pos += 2
        out: dict = {}
        while True:
            self.skip()
            if self.pos >= len(self.raw):
                raise PdfError("사전이 닫히지 않았습니다")
            if self.raw[self.pos:self.pos + 2] == b">>":
                self.pos += 2
                return out
            key = self.value()
            if not isinstance(key, Name):
                raise PdfError(f"사전의 열쇠가 이름이 아닙니다: {key!r}")
            out[str(key)] = self.value()

    def object_at(self, offset: int, expect: int | None = None):
        """«12 0 obj ... endobj» 하나를 읽는다."""
        self.pos = offset
        number = self.word()
        self.word()
        if self.word() != b"obj" or not _INT_RE.fullmatch(number):
            raise PdfError(f"{offset} 자리에 객체가 없습니다")
        if expect is not None and int(number) != expect:
            raise PdfError(f"{offset} 자리는 {number.decode()}번 객체입니다 "
                           f"({expect}번을 찾고 있었습니다)")
        value = self.value()
        self.skip()
        if not isinstance(value, dict) or self.raw[self.pos:self.pos + 6] != b"stream":
            return value

        start = self.pos + 6
        if self.raw[start:start + 2] == b"\r\n":
            start += 2
        elif self.raw[start:start + 1] in (b"\n", b"\r"):
            start += 1

        data = None
        length = self.resolve(value.get("Length"))
        if isinstance(length, int) and 0 <= length <= len(self.raw) - start:
            data = self.raw[start:start + length]
            if b"endstream" not in self.raw[start + length:start + length + 20]:
                data = None                # /Length 가 틀렸다. 끝을 직접 찾는다
        if data is None:
            stop = self.raw.find(b"endstream", start)
            if stop < 0:
                raise PdfError("스트림이 닫히지 않았습니다")
            data = self.raw[start:stop]
            if data.endswith(b"\r\n"):
                data = data[:-2]
            elif data[-1:] in (b"\n", b"\r"):
                data = data[:-1]
        return Stream(value, data)


def stream_data(stream: Stream, doc: "Document | None" = None) -> bytes:
    """스트림을 푼다. 모르는 방식이면 짐작하지 않고 그만둔다."""
    get = doc.get if doc else (lambda v: v)
    filters = get(stream.data.get("Filter")) or []
    if isinstance(filters, (Name, str)):
        filters = [filters]
    parms = get(stream.data.get("DecodeParms"))
    if parms is None:
        parms = get(stream.data.get("DP"))
    if not isinstance(parms, list):
        parms = [parms]

    data = stream.raw
    for i, one in enumerate(filters):
        kind = str(get(one))
        if kind in ("FlateDecode", "Fl"):
            data = _inflate(data)
        elif kind in ("ASCII85Decode", "A85"):
            import base64
            body = re.sub(rb"\s", b"", data)
            if body.startswith(b"<~"):
                body = body[2:]
            data = base64.a85decode(body.split(b"~>")[0], adobe=False)
        elif kind in ("ASCIIHexDecode", "AHx"):
            body = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            data = bytes.fromhex((body + b"0" if len(body) % 2 else body).decode("ascii"))
        else:
            raise PdfError(f"이 방식으로 눌린 자료는 풀지 못합니다: {kind}")
        parm = get(parms[i]) if i < len(parms) else None
        if isinstance(parm, dict):
            data = _undo_predictor(data, parm, get)
    return data


def _inflate(data: bytes) -> bytes:
    """끝이 잘린 것도 읽을 수 있는 데까지 편다."""
    for wbits in (15, -15):
        try:
            return zlib.decompressobj(wbits).decompress(data)
        except zlib.error:
            continue
    raise PdfError("눌린 자료를 풀지 못했습니다")


def _undo_predictor(data: bytes, parm: dict, get) -> bytes:
    predictor = int(get(parm.get("Predictor")) or 1)
    if predictor < 10:
        return data
    columns = int(get(parm.get("Columns")) or 1)
    colors = int(get(parm.get("Colors")) or 1)
    bits = int(get(parm.get("BitsPerComponent")) or 8)
    stride = (columns * colors * bits + 7) // 8
    step = max(1, colors * bits // 8)
    return bytes(_unfilter(data, columns, len(data) // (stride + 1), stride, step))


@dataclass
class PdfPage:
    number: int              # 몇 번째 쪽인가 (1부터)
    obj: int | None          # 파일 안의 객체 번호
    data: dict               # 물려받은 것(글꼴·크기)까지 채운 쪽 사전


class Document:
    """열어 둔 PDF 하나. 객체는 부를 때 읽는다."""

    def __init__(self, path: Path, raw: bytes):
        self.path = Path(path)
        self.raw = raw
        self.offsets: dict[int, int] = {}
        self.packed: dict[int, tuple[int, int]] = {}   # 번호 -> (담은 스트림, 차례)
        self.entries: set[int] = set()
        self.trailer: dict = {}
        self._cache: dict[int, object] = {}
        self._objstm: dict[int, dict] = {}
        self._scan: dict[int, int] | None = None
        self._pages: list[PdfPage] | None = None

    # ---- 객체 읽기

    def get(self, value, depth: int = 0):
        """참조면 따라간다. 고리에 빠지지 않게 깊이를 막는다."""
        while isinstance(value, Ref) and depth < 32:
            value = self.object(value.num)
            depth += 1
        return value

    def object(self, num: int):
        if num in self._cache:
            return self._cache[num]
        self._cache[num] = None                   # 스스로를 다시 부르는 고리 끊기
        value = self._read(num, self.offsets.get(num))
        if value is None and num in self.packed:
            value = self._from_packed(num)
        if value is None:
            value = self._read(num, self._scanned().get(num))
        self._cache[num] = value
        return value

    def _read(self, num: int, offset: int | None):
        if offset is None or not 0 <= offset < len(self.raw):
            return None
        try:
            return _Reader(self.raw, resolve=self.get).object_at(offset, num)
        except (PdfError, ValueError):
            return None

    def _scanned(self) -> dict[int, int]:
        """교차 참조표가 틀린 파일도 있다. 그때는 파일을 훑어 자리를 찾는다."""
        if self._scan is None:
            self._scan = {int(m.group(1)): m.start(1)
                          for m in _OBJ_RE.finditer(self.raw)}
        return self._scan

    def _from_packed(self, num: int):
        holder, _index = self.packed[num]
        table = self._objstm.get(holder)
        if table is None:
            table = {}
            stream = self.get(Ref(holder))
            if isinstance(stream, Stream):
                try:
                    body = stream_data(stream, self)
                    count = int(self.get(stream.data.get("N")) or 0)
                    first = int(self.get(stream.data.get("First")) or 0)
                    head = _Reader(body[:first])
                    pairs = [(int(head.value()), int(head.value()))
                             for _ in range(count)]
                    for number, offset in pairs:
                        table[number] = _Reader(body, first + offset,
                                                resolve=self.get).value()
                except (PdfError, ValueError, IndexError):
                    table = {}
            self._objstm[holder] = table
        return table.get(num)

    # ---- 쪽 차례

    def pages(self) -> list[PdfPage]:
        if self._pages is not None:
            return self._pages
        root = self.get(self.trailer.get("Root"))
        node = self.get(root.get("Pages")) if isinstance(root, dict) else None
        found: list[PdfPage] = []
        if isinstance(node, dict):
            self._collect(node, {}, found, set(), 0)
        if not found:
            raise PdfError(f"쪽 차례를 읽지 못했습니다: {self.path.name} "
                           "(망가졌거나 이 프로그램이 모르는 짜임입니다)")
        self._pages = found
        return found

    def _collect(self, node: dict, inherited: dict, out: list,
                 seen: set, depth: int, obj: int | None = None) -> None:
        inherited = dict(inherited)
        for key in _INHERITED:
            if key in node:
                inherited[key] = node[key]
        kids = self.get(node.get("Kids"))
        if isinstance(kids, list) and str(node.get("Type", "")) != "Page":
            if depth > 64:
                raise PdfError("쪽 나무가 너무 깊습니다")
            for kid in kids:
                number = kid.num if isinstance(kid, Ref) else None
                if number is not None:
                    if number in seen:
                        continue              # 같은 곳을 두 번 도는 파일도 있다
                    seen.add(number)
                child = self.get(kid)
                if isinstance(child, dict):
                    self._collect(child, inherited, out, seen, depth + 1, number)
            return
        page = dict(node)
        for key, value in inherited.items():
            page.setdefault(key, value)
        out.append(PdfPage(number=len(out) + 1, obj=obj, data=page))


def open_pdf(path) -> Document:
    """PDF 를 연다. 암호가 걸렸거나 PDF 가 아니면 까닭을 말하고 그만둔다."""
    path = Path(path)
    raw = path.read_bytes()
    if not raw.startswith(b"%PDF-"):
        raise PdfError(f"PDF 가 아닙니다: {path.name}")

    doc = Document(path, raw)
    start = raw.rfind(b"startxref")
    if start >= 0:
        reader = _Reader(raw, start + len(b"startxref"))
        try:
            offset = reader.value()
        except PdfError:
            offset = None
        if isinstance(offset, int):
            _load_xref(doc, offset, set())

    if "Root" not in doc.trailer:
        _find_trailer(doc)
    if "Encrypt" in doc.trailer:          # 값을 못 읽어도 잠긴 건 잠긴 것이다
        raise PdfError(f"암호가 걸려 있습니다: {path.name} "
                       "(암호를 풀어 저장한 사본으로 다시 해 보세요)")
    if "Root" not in doc.trailer:
        raise PdfError(f"목차(Root)를 찾지 못했습니다: {path.name}")
    return doc


def _load_xref(doc: Document, offset: int | None, seen: set) -> None:
    """교차 참조표를 따라간다. 고쳐 저장한 파일은 표가 여러 겹이다."""
    depth = 0
    while (isinstance(offset, int) and offset not in seen
           and 0 <= offset < len(doc.raw) and depth < 64):
        seen.add(offset)
        depth += 1
        reader = _Reader(doc.raw, offset, resolve=doc.get)
        reader.skip()
        try:
            if doc.raw[reader.pos:reader.pos + 4] == b"xref":
                trailer = _classic_xref(doc, reader)
            else:
                trailer = _xref_stream(doc, reader)
        except (PdfError, ValueError):
            return
        for key, value in trailer.items():
            doc.trailer.setdefault(key, value)
        hybrid = trailer.get("XRefStm")            # 두 가지를 다 넣은 파일
        if isinstance(hybrid, int):
            _load_xref(doc, hybrid, seen)
        offset = trailer.get("Prev")


def _classic_xref(doc: Document, reader: _Reader) -> dict:
    reader.word()                                   # xref
    while True:
        save = reader.pos
        word = reader.word()
        if word == b"trailer":
            value = reader.value()
            return value if isinstance(value, dict) else {}
        if not _INT_RE.fullmatch(word):
            reader.pos = save
            return {}
        start = int(word)
        count_word = reader.word()
        if not _INT_RE.fullmatch(count_word):
            return {}
        count = int(count_word)
        # 한 줄이 20 바이트다. 남은 길이보다 많이 적혀 있으면 그만큼만 읽는다
        count = min(count, (len(doc.raw) - reader.pos) // 18 + 1)
        for i in range(count):
            place, _gen, kind = reader.word(), reader.word(), reader.word()
            if not place:                      # 파일이 먼저 끝났다
                break
            num = start + i
            if num in doc.entries:
                continue                # 새 표가 이미 정한 것은 덮지 않는다
            doc.entries.add(num)
            if kind == b"n" and _INT_RE.fullmatch(place):
                doc.offsets[num] = int(place)


def _xref_stream(doc: Document, reader: _Reader) -> dict:
    obj = reader.object_at(reader.pos)
    if not isinstance(obj, Stream):
        raise PdfError("교차 참조표를 찾지 못했습니다")
    data = stream_data(obj, doc)
    widths = [int(doc.get(w)) for w in (doc.get(obj.data.get("W")) or [])]
    if len(widths) < 3:
        raise PdfError("교차 참조 스트림의 /W 를 읽지 못했습니다")
    size = int(doc.get(obj.data.get("Size")) or 0)
    index = doc.get(obj.data.get("Index")) or [0, size]
    row = sum(widths)
    at = 0
    for i in range(0, len(index) - 1, 2):
        start, count = int(doc.get(index[i])), int(doc.get(index[i + 1]))
        for step in range(count):
            chunk = data[at:at + row]
            at += row
            if len(chunk) < row:
                break
            fields, place = [], 0
            for size_of in widths:
                fields.append(int.from_bytes(chunk[place:place + size_of], "big")
                              if size_of else None)
                place += size_of
            kind = fields[0] if widths[0] else 1
            num = start + step
            if num in doc.entries:
                continue
            doc.entries.add(num)
            if kind == 1:
                doc.offsets[num] = fields[1]
            elif kind == 2:
                doc.packed[num] = (fields[1], fields[2] or 0)
    return obj.data


def _find_trailer(doc: Document) -> None:
    """교차 참조표가 망가졌을 때. 파일에 있는 trailer 와 /Type /Catalog 를 찾는다."""
    for match in re.finditer(rb"trailer", doc.raw):
        try:
            value = _Reader(doc.raw, match.end(), resolve=doc.get).value()
        except PdfError:
            continue
        if isinstance(value, dict) and "Root" in value:
            for key, item in value.items():        # Info·ID 도 함께 챙긴다
                doc.trailer.setdefault(key, item)
    if "Root" in doc.trailer:
        return
    for num in sorted(doc._scanned()):
        value = doc.object(num)
        data = value.data if isinstance(value, Stream) else value
        if isinstance(data, dict) and str(data.get("Type", "")) == "Catalog":
            doc.trailer["Root"] = Ref(num)
            return


# ---- 다시 쓰기

def _name_bytes(name: str) -> bytes:
    out = bytearray(b"/")
    for ch in name.encode("latin-1", "replace"):
        if ch in _NAME_ESCAPE or not _NAME_KEEP.match(bytes([ch])):
            out += f"#{ch:02X}".encode("ascii")
        else:
            out.append(ch)
    return bytes(out)


def _serialize(value) -> bytes:
    """읽어 둔 값을 다시 PDF 글로. 글자열은 언제나 16진수로 쓴다(따옴표 사고 방지)."""
    if isinstance(value, Stream):
        data = dict(value.data)
        data["Length"] = len(value.raw)
        return (_serialize(data) + b"\nstream\n" + value.raw + b"\nendstream")
    if isinstance(value, Name):
        return _name_bytes(str(value))
    if isinstance(value, Ref):
        return f"{value.num} 0 R".encode("ascii")
    if value is True:
        return b"true"
    if value is False:
        return b"false"
    if value is None:
        return b"null"
    if isinstance(value, int):
        return str(value).encode("ascii")
    if isinstance(value, float):
        return (f"{value:.6f}".rstrip("0").rstrip(".") or "0").encode("ascii")
    if isinstance(value, (bytes, bytearray)):
        return b"<" + bytes(value).hex().encode("ascii") + b">"
    if isinstance(value, str):
        try:                       # 로마자면 그대로, 아니면 UTF-16 (BOM 을 꼭 붙인다)
            return b"<" + value.encode("latin-1").hex().encode("ascii") + b">"
        except UnicodeEncodeError:
            return (b"<feff" + value.encode("utf-16-be").hex().encode("ascii")
                    + b">")
    if isinstance(value, list):
        return b"[" + b" ".join(_serialize(v) for v in value) + b"]"
    if isinstance(value, dict):
        parts = [_name_bytes(k) + b" " + _serialize(v) for k, v in value.items()]
        return b"<<" + b"".join(parts) + b">>"
    raise PdfError(f"쓸 수 없는 값입니다: {type(value).__name__}")


class _Copier:
    """고른 쪽이 걸고 있는 객체를 새 파일로 옮겨 담는다."""

    def __init__(self):
        self.slots: list = []                       # 새 번호(1부터) 순서대로
        self.map: dict[tuple[int, int], int] = {}
        self.queue: list = []
        self.missing: list[int] = []                # 가리키는데 없던 객체

    def reserve(self, key) -> int:
        if key not in self.map:
            self.slots.append(None)
            self.map[key] = len(self.slots)
        return self.map[key]

    def ref(self, doc: Document, num: int) -> Ref:
        key = (id(doc), num)
        if key in self.map:
            return Ref(self.map[key])
        new = self.reserve(key)
        self.queue.append((doc, num, new))
        return Ref(new)

    def convert(self, doc: Document, value, depth: int = 0):
        if depth > 64:
            return None
        if isinstance(value, Ref):
            return self.ref(doc, value.num)
        if isinstance(value, Stream):
            data = {k: self.convert(doc, v, depth + 1)
                    for k, v in value.data.items() if k != "Length"}
            data["Length"] = len(value.raw)
            return Stream(data, value.raw)
        if isinstance(value, dict):
            return {k: self.convert(doc, v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [self.convert(doc, v, depth + 1) for v in value]
        return value

    def drain(self, keep: set) -> None:
        while self.queue:
            doc, num, new = self.queue.pop()
            value = doc.object(num)
            data = value.data if isinstance(value, Stream) else value
            if (isinstance(data, dict) and str(data.get("Type", "")) == "Page"
                    and (id(doc), num) not in keep):
                self.slots[new - 1] = None   # 안 고른 쪽을 가리키는 자리는 비운다
                continue
            if value is None:
                self.missing.append(num)     # 없는 것을 있는 척하지 않는다
            self.slots[new - 1] = self.convert(doc, value)


def page_numbers(spec: str, total: int) -> list[int]:
    """«1-3,7» «5-» «-3» 을 쪽 번호 목록으로. 차례와 겹침은 적은 대로 둔다."""
    out: list[int] = []
    for piece in str(spec).replace(" ", "").split(","):
        if not piece:
            continue
        if "-" in piece[1:] or piece.startswith("-"):
            first, _, last = piece.partition("-") if not piece.startswith("-") \
                else ("1", "-", piece[1:])
            start = int(first) if first.isdigit() else 1
            stop = int(last) if last.isdigit() else total
        elif piece.isdigit():
            start = stop = int(piece)
        else:
            raise PdfError(f"쪽 지정을 읽지 못했습니다: {piece}")
        if start < 1 or stop > total or start > stop:
            raise PdfError(f"{start}-{stop} 은 없는 쪽입니다 (이 문서는 {total}쪽)")
        out.extend(range(start, stop + 1))
    if not out:
        raise PdfError("고른 쪽이 없습니다")
    return out


@dataclass
class JoinResult:
    pages: int               # 새 파일의 쪽 수
    objects: int             # 옮긴 객체 수
    missing: int             # 원본이 가리키는데 없던 객체 수 (0 이어야 한다)


def rotation_plan(order: list[int], pages: list[int] | None,
                  angle: int) -> dict[int, int]:
    """«출력 차례 -> 더할 각도». pages 가 없으면 전부 돌린다.

    스캐너가 낱장을 뒤집어 넣으면 짝수 쪽만 거꾸로 들어온다. 그래서 쪽마다
    따로 돌릴 수 있어야 한다. 고르는 기준은 «원본 쪽 번호» 다 - 사람은
    원본을 보고 «2, 4쪽이 거꾸로다» 라고 세기 때문이다.
    """
    if angle % 90:
        raise PdfError(f"돌릴 각도는 90 의 배수여야 합니다: {angle}")
    wanted = None if pages is None else set(pages)
    return {spot: angle for spot, number in enumerate(order, 1)
            if wanted is None or number in wanted}


def join_pdfs(picks: list[tuple[Document, list[int]]], out: Path,
              *, title: str = "", rotate: int = 0,
              turns: dict | None = None,
              catalog_from: Document | None = None,
              info: dict | None = None,
              metadata: bytes | None = None,
              stamp=None, stamp_image: "StampImage | None" = None) -> JoinResult:
    """문서마다 고른 쪽을 차례대로 이어 붙여 새 PDF 로.

    rotate 는 90 의 배수. 원래 돌아가 있던 각도에 더한다 - 스캔한 것이
    이미 눕혀져 있으면 «90 도 더»가 맞지 «90 도로» 는 틀리기 때문이다.
    turns 는 «출력 차례 -> 더할 각도» 로, 쪽마다 다르게 돌릴 때 쓴다
    (rotation_plan 으로 만든다). rotate 와 함께 주면 더해진다.

    catalog_from 을 주면 그 문서의 목차(책갈피·양식·쪽 번호 표시·구조 태그)를
    함께 옮긴다. 쪽을 다 옮길 때만 뜻이 있다 - 안 옮긴 쪽을 가리키는 책갈피는
    빈 자리가 되기 때문이다.

    stamp(차례, 쪽, 문서) 를 주면 그 쪽 위에 덧그릴 내용 스트림을 받아 붙인다
    (쪽 번호). 원래 내용은 건드리지 않고 뒤에 한 겹 더 얹는다.
    """
    if rotate % 90:
        raise PdfError(f"돌릴 각도는 90 의 배수여야 합니다: {rotate}")
    out = Path(out)
    copier = _Copier()
    chosen = []
    taken: set = set()
    for doc, numbers in picks:
        pages = doc.pages()
        for number in numbers:
            page = pages[number - 1]
            key = (id(doc), page.obj) if page.obj is not None \
                else (id(doc), -(len(chosen) + 1))
            # 같은 쪽을 두 번 넣는 일이 있다(표지를 앞뒤로, --order 1,1).
            # 같은 열쇠로 자리를 잡으면 둘이 한 자리를 나눠 쪽이 하나로 준다
            again = 0
            while key in taken:
                again += 1
                key = (*key, again)
            taken.add(key)
            chosen.append((doc, page, copier.reserve(key), key))
    if not chosen:
        raise PdfError("고른 쪽이 없습니다")

    keep = {key[:2] for _doc, _page, _new, key in chosen}
    tree = copier.reserve(("root", "pages"))
    catalog = copier.reserve(("root", "catalog"))
    info_slot = copier.reserve(("root", "info"))

    # 글자 도장은 글꼴이, 그림 도장은 이미지 객체가 있어야 한다
    stamp_font = copier.reserve(("root", "stampfont")) \
        if (stamp and stamp_image is None) else 0
    stamp_mask = copier.reserve(("root", "stampmask")) \
        if (stamp_image is not None and stamp_image.alpha) else 0
    stamp_slot = copier.reserve(("root", "stampimage")) \
        if stamp_image is not None else 0
    for order, (doc, page, new, _key) in enumerate(chosen, 1):
        data = {k: v for k, v in page.data.items() if k != "Parent"}
        copied = copier.convert(doc, data)
        copied["Type"] = Name("Page")
        copied["Parent"] = Ref(tree)
        extra = (rotate + (turns or {}).get(order, 0)) % 360
        if extra:
            was = doc.get(page.data.get("Rotate"))
            copied["Rotate"] = (int(was or 0) + extra) % 360
        if stamp:
            body = stamp(order, page, doc)
            if body:
                _add_stamp(copier, doc, page, copied, body, stamp_font,
                           image=stamp_slot)
        copier.slots[new - 1] = copied

    made_catalog: dict = {"Type": Name("Catalog"), "Pages": Ref(tree)}
    if catalog_from is not None:
        root = catalog_from.get(catalog_from.trailer.get("Root"))
        if isinstance(root, dict):
            # /Pages 와 /Metadata 는 우리가 다시 만든다. 나머지는 그대로 옮긴다
            carry = {k: v for k, v in root.items()
                     if k not in ("Type", "Pages", "Metadata")}
            made_catalog = {**copier.convert(catalog_from, carry),
                            "Type": Name("Catalog"), "Pages": Ref(tree)}
    if metadata is not None:
        xmp = copier.reserve(("root", "xmp"))
        copier.slots[xmp - 1] = Stream(
            {"Type": Name("Metadata"), "Subtype": Name("XML")}, metadata)
        made_catalog["Metadata"] = Ref(xmp)
    copier.drain(keep)               # 목차까지 걸어 둔 뒤에 한 번에 옮긴다

    copier.slots[tree - 1] = {
        "Type": Name("Pages"),
        "Kids": [Ref(new) for _doc, _page, new, _key in chosen],
        "Count": len(chosen),
    }
    if stamp_font:
        copier.slots[stamp_font - 1] = {
            "Type": Name("Font"), "Subtype": Name("Type1"),
            "BaseFont": Name("Helvetica"), "Encoding": Name("WinAnsiEncoding")}
    if stamp_image is not None:
        if stamp_mask:
            copier.slots[stamp_mask - 1] = Stream(
                {"Type": Name("XObject"), "Subtype": Name("Image"),
                 "Width": stamp_image.width, "Height": stamp_image.height,
                 "ColorSpace": Name("DeviceGray"), "BitsPerComponent": 8,
                 "Filter": Name("FlateDecode")}, stamp_image.alpha)
        data = {"Type": Name("XObject"), "Subtype": Name("Image"),
                "Width": stamp_image.width, "Height": stamp_image.height,
                "ColorSpace": Name(stamp_image.space), "BitsPerComponent": 8,
                "Filter": Name(stamp_image.filter)}
        if stamp_mask:
            # 도장은 대개 배경이 비어 있다. 알파를 SMask 로 넣지 않으면
            # 하얀 네모가 글자를 덮는다.
            data["SMask"] = Ref(stamp_mask)
        copier.slots[stamp_slot - 1] = Stream(data, stamp_image.data)
    copier.slots[catalog - 1] = made_catalog
    if info is None and catalog_from is not None:
        # 문서를 통째로 다시 쓰는 것이므로 제목·만든 날짜 같은 속성도 그대로 둔다
        was = catalog_from.get(catalog_from.trailer.get("Info"))
        info = {k: catalog_from.get(v) for k, v in was.items()} \
            if isinstance(was, dict) else None
    made = dict(info) if info is not None else {"Producer": "attools"}
    if title:
        made["Title"] = title
    copier.slots[info_slot - 1] = made

    _write_objects(copier.slots, out, root=catalog, info=info_slot)

    check = open_pdf(out)          # 쓴 것을 다시 열어 본다
    if len(check.pages()) != len(chosen):
        out.unlink(missing_ok=True)
        raise PdfError("만든 PDF 를 다시 읽어 보니 쪽 수가 맞지 않아 지웠습니다")
    return JoinResult(pages=len(chosen), objects=len(copier.slots),
                      missing=len(copier.missing))


def _add_stamp(copier: "_Copier", doc: Document, page: PdfPage, copied: dict,
               body: str, font: int, image: int = 0) -> None:
    """쪽 위에 한 겹 더 얹는다. 원래 내용 스트림은 그대로 두고 뒤에 붙인다."""
    # 자원 사전은 여러 쪽이 함께 쓰기도 한다. 그 자리에 글꼴을 밀어 넣지 않고
    # 이 쪽만의 사전으로 풀어서 넣는다.
    resources = doc.get(page.data.get("Resources"))
    resources = dict(resources) if isinstance(resources, dict) else {}
    made = copier.convert(doc, resources)
    fonts = doc.get(resources.get("Font"))
    fonts = copier.convert(doc, dict(fonts)) if isinstance(fonts, dict) else {}
    name = "ATNUM"
    while name in fonts:                     # 이름이 겹치면 다른 이름을 쓴다
        name += "1"
    if font:
        fonts[name] = Ref(font)
        made["Font"] = fonts

    image_name = "ATIMG"
    if image:
        holder = doc.get(resources.get("XObject"))
        holder = copier.convert(doc, dict(holder)) if isinstance(holder, dict) else {}
        while image_name in holder:
            image_name += "1"
        holder[image_name] = Ref(image)
        made["XObject"] = holder
    copied["Resources"] = made

    number = copier.reserve(("stamp", len(copier.slots)))
    copier.slots[number - 1] = Stream(
        {}, body.replace("/ATNUM", f"/{name}")
                .replace("/ATIMG", f"/{image_name}").encode("latin-1"))
    was = copied.get("Contents")
    items = was if isinstance(was, list) else ([] if was is None else [was])
    copied["Contents"] = [*items, Ref(number)]


def _write_objects(slots: list, out: Path, *, root: int, info: int) -> None:
    head = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    chunks = [head]
    places = [0] * (len(slots) + 1)
    at = len(head)
    for i, value in enumerate(slots, 1):
        places[i] = at
        blob = f"{i} 0 obj\n".encode("ascii") + _serialize(value) + b"\nendobj\n"
        chunks.append(blob)
        at += len(blob)

    table = [f"xref\n0 {len(slots) + 1}\n".encode("ascii"),
             b"0000000000 65535 f \n"]
    for i in range(1, len(slots) + 1):
        table.append(f"{places[i]:010d} 00000 n \n".encode("ascii"))
    chunks.extend(table)
    trailer = (f"trailer\n<</Size {len(slots) + 1}/Root {root} 0 R"
               f"/Info {info} 0 R>>\nstartxref\n{at}\n%%EOF\n").encode("ascii")
    chunks.append(trailer)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(b"".join(chunks))


# ---- 문서에 남은 이름 지우기

PDF_SCRUB_KEYS = {"Author": "만든 사람", "Company": "회사"}
XMP_TAGS = {"dc:creator": "만든 사람(XMP)", "pdf:Author": "만든 사람(XMP)",
            "xmp:Author": "만든 사람(XMP)"}
_XMP_TEXT = re.compile(rb"<[^<>]+>")


def _xmp_stream(doc: Document):
    """목차에 걸린 XMP 메타데이터 스트림. 없으면 None."""
    root = doc.get(doc.trailer.get("Root"))
    if not isinstance(root, dict):
        return None
    found = doc.get(root.get("Metadata"))
    return found if isinstance(found, Stream) else None


def _xmp_text(doc: Document) -> bytes:
    stream = _xmp_stream(doc)
    if stream is None:
        return b""
    try:
        return stream_data(stream, doc)
    except (PdfError, zlib.error):
        return b""


def _xmp_value(body: bytes, tag: str) -> str:
    """<dc:creator> 안의 글자만. 안쪽 rdf:Seq·li 태그는 걷어 낸다."""
    match = re.search(tag.encode("ascii") + rb"[^>]*>(.*?)</" + tag.encode("ascii"),
                      body, re.S)
    if not match:
        return ""
    return _XMP_TEXT.sub(b" ", match.group(1)).decode("utf-8", "replace").strip()


def _blank_xmp(body: bytes) -> bytes:
    for tag in XMP_TAGS:
        name = tag.encode("ascii")
        body = re.sub(name + rb"([^>]*)>.*?</" + name + rb">",
                      name + rb"\1></" + name + rb">", body, flags=re.S)
        body = re.sub(rb"\b" + name + rb'="[^"]*"', name + b'=""', body)
    return body


def _string_text(value) -> str:
    """PDF 글자열을 사람이 읽는 글로. 앞에 BOM 이 있으면 UTF-16 이다."""
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if raw[:2] == b"\xfe\xff":
            return raw[2:].decode("utf-16-be", "replace")
        if raw[:2] == b"\xff\xfe":
            return raw[2:].decode("utf-16-le", "replace")
        return raw.decode("latin-1", "replace")
    return "" if value is None else str(value)


def scrub_names(doc: Document) -> list[tuple[str, str]]:
    """이 PDF 에서 지울 수 있는 이름. (사람이 읽는 이름, 값)"""
    found: list[tuple[str, str]] = []
    info = doc.get(doc.trailer.get("Info"))
    if isinstance(info, dict):
        for key, label in PDF_SCRUB_KEYS.items():
            text = _string_text(doc.get(info.get(key))).strip()
            if text:
                found.append((label, text))
    body = _xmp_text(doc)
    for tag, label in XMP_TAGS.items():
        value = _xmp_value(body, tag)
        if value and (label, value) not in found:
            found.append((label, value))
    return found


def scrub_pdf(doc: Document, out: Path) -> tuple[JoinResult, list[tuple[str, str]]]:
    """이름을 지운 새 PDF 를 만든다. 원본은 건드리지 않는다.

    고친 자리만 덧붙이는 방식(증분 갱신)은 쓰지 않는다 - 옛 이름이 파일에
    그대로 남아 꺼내 볼 수 있기 때문이다. 다시 써야 정말로 지워진다.
    """
    names = scrub_names(doc)
    if not names:
        raise PdfError("지울 이름이 없습니다")

    info = doc.get(doc.trailer.get("Info"))
    clean = {}
    if isinstance(info, dict):
        clean = {k: doc.get(v) for k, v in info.items()
                 if k not in PDF_SCRUB_KEYS}
    body = _xmp_text(doc)
    xmp = _blank_xmp(body) if body else None

    result = join_pdfs([(doc, [p.number for p in doc.pages()])], out,
                       catalog_from=doc, info=clean, metadata=xmp)

    left = scrub_names(open_pdf(out))     # 정말 지워졌는지 다시 열어 본다
    if left:
        out.unlink(missing_ok=True)
        raise PdfError("이름이 그대로 남아 있어 만든 파일을 지웠습니다: "
                       + ", ".join(f"{label} {value}" for label, value in left))
    return result, names


# ---- 쪽 번호 찍기

STAMP_WHERE = {"bottom-center": "아래 가운데", "bottom-right": "아래 오른쪽",
               "bottom-left": "아래 왼쪽", "top-right": "위 오른쪽",
               "top-center": "위 가운데"}
# 헬베티카의 실제 글자 폭(1000 분의 1). 쪽 번호에 쓰는 글자만 정확히 적는다.
HELVETICA_WIDTH = {" ": 278, "/": 278, "-": 333, ".": 278, ",": 278, "(": 333,
                   ")": 333, ":": 278}
HELVETICA_DIGIT = 556
HELVETICA_OTHER = 556        # 나머지는 어림잡는다 (가운데 맞춤이 조금 흔들린다)


def text_width(text: str, size: float) -> float:
    """헬베티카로 찍었을 때의 글자 너비(포인트)."""
    total = 0
    for ch in text:
        if ch.isdigit():
            total += HELVETICA_DIGIT
        else:
            total += HELVETICA_WIDTH.get(ch, HELVETICA_OTHER)
    return total * size / 1000


def _pdf_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def stamp_stream(text: str, box: list, rotate: int, *, where: str = "bottom-center",
                 size: float = 9.0, margin: float = 12.0, font: str = "ATNUM") -> str:
    """쪽 번호 한 줄을 그리는 내용 스트림.

    돌아간 쪽(/Rotate)은 보는 사람 기준으로 아래가 달라진다. 그대로 찍으면
    옆으로 누운 번호가 나오므로, 글자를 반대로 돌려 놓는다.
    """
    if where not in STAMP_WHERE:
        raise PdfError(f"모르는 자리입니다: {where} ({', '.join(STAMP_WHERE)})")
    try:
        text.encode("latin-1")
    except UnicodeEncodeError:
        raise PdfError("쪽 번호에는 한글을 넣지 못합니다 "
                       "(글꼴을 파일에 심어야 하는데 그러지 않습니다). "
                       "숫자와 로마자만 쓰세요.") from None

    x0, y0, x1, y1 = (float(v) for v in (box + [0, 0, 612, 792])[:4])
    width, height = abs(x1 - x0), abs(y1 - y0)
    rotate %= 360
    if rotate in (90, 270):
        shown_w, shown_h = height, width
    else:
        shown_w, shown_h = width, height

    span = text_width(text, size)
    if where.endswith("right"):
        shown_x = shown_w - margin - span
    elif where.endswith("left"):
        shown_x = margin
    else:
        shown_x = (shown_w - span) / 2
    shown_y = (shown_h - margin - size) if where.startswith("top") else margin

    # 보는 사람 자리 -> 파일 안의 자리
    if rotate == 90:
        matrix, x, y = "0 1 -1 0", width - shown_y, shown_x
    elif rotate == 180:
        matrix, x, y = "-1 0 0 -1", width - shown_x, height - shown_y
    elif rotate == 270:
        matrix, x, y = "0 -1 1 0", shown_y, height - shown_x
    else:
        matrix, x, y = "1 0 0 1", shown_x, shown_y

    return (f"q 0 g BT /{font} {size:g} Tf "
            f"{matrix} {min(x0, x1) + x:.2f} {min(y0, y1) + y:.2f} Tm "
            f"({_pdf_text(text)}) Tj ET Q\n")


def page_stamper(template: str, total: int, *, start: int = 1, skip: int = 0,
                 where: str = "bottom-center", size: float = 9.0,
                 margin: float = 12.0):
    """쪽마다 무엇을 찍을지 정하는 함수를 만든다. {쪽} 과 {전체} 를 쓴다."""
    def stamp(index: int, page: "PdfPage", doc: "Document") -> str:
        if index <= skip:
            return ""                      # 표지처럼 건너뛸 쪽
        text = template.replace("{쪽}", str(index - skip + start - 1)) \
                       .replace("{전체}", str(max(total - skip, 0)))
        box = doc.get(page.data.get("MediaBox")) or [0, 0, 612, 792]
        box = [float(doc.get(v) or 0) for v in box]
        turn = doc.get(page.data.get("Rotate")) or 0
        return stamp_stream(text, box, int(turn), where=where, size=size,
                            margin=margin)
    return stamp


# ------------------------------------------------------- 쪽에서 글자 꺼내기
#
# PDF 는 «글자» 가 아니라 «어느 글꼴의 몇 번 글리프» 를 적어 둔 형식이다.
# 그 번호가 어떤 글자인지는 글꼴이 ToUnicode 표를 달고 있을 때만 알 수 있다.
# 표가 없으면 지어내지 않고 그 부분을 빼고, 어느 글꼴이 그랬는지 알려 준다 -
# 아무 값이나 채우면 «꺼냈는데 글자가 뒤죽박죽» 이 되어 더 나쁘다.

_BF_CHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BF_RANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_HEX_ITEM = re.compile(rb"<([0-9A-Fa-f\s]*)>")
_RANGE_ITEM = re.compile(
    rb"<([0-9A-Fa-f\s]*)>\s*<([0-9A-Fa-f\s]*)>\s*(\[[^\]]*\]|<[0-9A-Fa-f\s]*>)", re.S)
_RANGE_LIMIT = 65536          # 한 구간이 이보다 넓으면 건너뛴다
# 글자 사이를 이만큼 벌리면 빈칸으로 본다 (TJ 의 값은 1/1000 em 이고 음수가 벌림)
_SPACE_GAP = 200.0
SIMPLE_ENCODINGS = {"WinAnsiEncoding": "cp1252", "MacRomanEncoding": "mac_roman",
                    "StandardEncoding": "latin-1", "PDFDocEncoding": "latin-1"}


def _hex_bytes(raw: bytes) -> bytes:
    # 16진수 아닌 것은 다 버린다. 구간의 목적지는 «<0041>» 처럼 괄호째 잡힌다
    body = re.sub(rb"[^0-9A-Fa-f]", b"", raw)
    if len(body) % 2:
        body += b"0"
    try:
        return bytes.fromhex(body.decode("ascii"))
    except ValueError:
        return b""


def _utf16_text(raw: bytes) -> str:
    """ToUnicode 의 목적지 값은 UTF-16BE 다."""
    body = _hex_bytes(raw)
    if not body:
        return ""
    if len(body) % 2:
        return body.decode("latin-1", "replace")
    return body.decode("utf-16-be", "replace")


def parse_tounicode(data: bytes) -> tuple[dict[int, str], int]:
    """ToUnicode CMap 을 (코드 -> 글자, 코드 바이트 수)로 읽는다."""
    table: dict[int, str] = {}
    width = 1
    for block in _BF_CHAR.findall(data):
        items = _HEX_ITEM.findall(block)
        for i in range(0, len(items) - 1, 2):
            source = _hex_bytes(items[i])
            if not source:
                continue
            width = max(width, len(source))
            table[int.from_bytes(source, "big")] = _utf16_text(items[i + 1])
    for block in _BF_RANGE.findall(data):
        for low, high, target in _RANGE_ITEM.findall(block):
            start, stop = _hex_bytes(low), _hex_bytes(high)
            if not start or not stop:
                continue
            width = max(width, len(start))
            first, last = int.from_bytes(start, "big"), int.from_bytes(stop, "big")
            if last < first or last - first > _RANGE_LIMIT:
                continue
            if target.startswith(b"["):
                for step, item in enumerate(_HEX_ITEM.findall(target)):
                    if first + step <= last:
                        table[first + step] = _utf16_text(item)
                continue
            base = _utf16_text(target)
            if not base:
                continue
            for code in range(first, last + 1):
                # 마지막 코드 단위만 늘린다 (CMap 규칙)
                table[code] = base[:-1] + chr(ord(base[-1]) + code - first)
    return table, min(width, 2)


@dataclass
class PdfFont:
    name: str                       # /F1 같은 자원 이름
    base: str = ""                  # 글꼴 이름 (BaseFont)
    table: dict = field(default_factory=dict)
    width: int = 1                  # 코드 한 개가 몇 바이트인가
    encoding: str = ""              # ToUnicode 가 없을 때 쓸 인코딩

    @property
    def readable(self) -> bool:
        return bool(self.table or self.encoding)

    def decode(self, raw: bytes) -> str:
        if self.table:
            out = []
            step = self.width
            for i in range(0, len(raw) - step + 1, step):
                code = int.from_bytes(raw[i:i + step], "big")
                out.append(self.table.get(code, ""))
            return "".join(out)
        if self.encoding:
            return raw.decode(self.encoding, "replace")
        return ""


def page_fonts(doc: "Document", page: PdfPage) -> dict[str, PdfFont]:
    """쪽이 쓰는 글꼴마다 코드 -> 글자 표를 만든다."""
    resources = doc.get(page.data.get("Resources"))
    fonts = doc.get(resources.get("Font")) if isinstance(resources, dict) else None
    out: dict[str, PdfFont] = {}
    if not isinstance(fonts, dict):
        return out

    for key, value in fonts.items():
        entry = doc.get(value)
        if not isinstance(entry, dict):
            continue
        font = PdfFont(str(key), str(doc.get(entry.get("BaseFont")) or ""))
        stream = doc.get(entry.get("ToUnicode"))
        if isinstance(stream, Stream):
            try:
                font.table, font.width = parse_tounicode(stream_data(stream, doc))
            except (PdfError, ValueError):
                font.table = {}
        if not font.table:
            # 표가 없으면 라틴 글꼴일 때만 바이트를 그대로 글자로 본다.
            # 한글은 이 길로 오면 통째로 깨지므로 못 읽은 것으로 둔다.
            kind = str(doc.get(entry.get("Subtype")) or "")
            code = doc.get(entry.get("Encoding"))
            name = str(code) if isinstance(code, Name) else ""
            if kind != "Type0":
                font.encoding = SIMPLE_ENCODINGS.get(name, "cp1252")
        elif str(doc.get(entry.get("Subtype")) or "") == "Type0":
            font.width = max(font.width, 2)
        out[str(key)] = font
    return out


def _content_ops(data: bytes):
    """내용 스트림을 (피연산자들, 연산자)로 하나씩 넘긴다."""
    reader = _Reader(data)
    operands: list = []
    end = len(data)
    while True:
        reader.skip()
        if reader.pos >= end:
            return
        ch = data[reader.pos]
        if ch in b"/([<" or ch in b"+-." or 0x30 <= ch <= 0x39:
            save = reader.pos
            try:
                operands.append(reader.value())
                continue
            except (PdfError, ValueError, IndexError):
                reader.pos = save + 1
                continue
        word = reader.word()
        if word in (b"]", b">>", b"}", b"{"):
            continue
        if word == b"BI":
            # 그림이 스트림 한가운데 박힌 자리. 이진 자료를 값으로 읽으면
            # 그다음이 통째로 어긋나므로 EI 까지 건너뛴다
            stop = data.find(b"EI", reader.pos)
            reader.pos = end if stop < 0 else stop + 2
            operands = []
            continue
        yield operands, word
        operands = []


def page_text(doc: "Document", page: PdfPage) -> tuple[str, list[str]]:
    """쪽의 글자와, 글자 정보가 없어 못 읽은 글꼴 이름들. (글, 못 읽은 글꼴)"""
    try:
        fonts = page_fonts(doc, page)
    except (PdfError, ValueError):
        fonts = {}

    chunks: list[bytes] = []
    for ref in _content_streams(doc, page):
        try:
            chunks.append(stream_data(ref, doc))
        except (PdfError, ValueError):
            continue
    if not chunks:
        return "", []

    lines: list[str] = []
    line: list[str] = []
    missing: list[str] = []
    font: PdfFont | None = None

    def show(raw) -> None:
        if isinstance(raw, bytes) and font is not None:
            piece = font.decode(raw)
            if piece:
                line.append(piece)
            elif not font.readable and font.base not in missing:
                missing.append(font.base or font.name)

    def newline() -> None:
        text = "".join(line).strip()
        line.clear()
        if text:
            lines.append(text)

    # 글자를 찍는 자리(y)가 바뀔 때만 줄을 나눈다. 자리를 옮길 때마다 나누면
    # 낱말마다 Td 를 쓰는 문서가 «한 줄에 한 낱말» 로 나온다
    where = [0.0, 0.0]          # 지금 줄의 (x, y)

    def move(x: float, y: float) -> None:
        if abs(y - where[1]) > 0.5:
            newline()
        elif line and not "".join(line).endswith(" ") and x > where[0]:
            line.append(" ")    # 같은 줄에서 자리를 옮겼으면 띄어 쓴 것으로 본다
        where[0], where[1] = x, y

    def numbers(items, count: int) -> list:
        got = [v for v in items if isinstance(v, (int, float))]
        return got[-count:] if len(got) >= count else []

    for operands, op in _content_ops(b"\n".join(chunks)):
        if op == b"Tf" and len(operands) >= 2:
            font = fonts.get(str(operands[-2]))
        elif op == b"Tj" and operands:
            show(operands[-1])
        elif op == b"'" and operands:
            newline()
            show(operands[-1])
        elif op == b'"' and operands:
            newline()
            show(operands[-1])
        elif op == b"TJ" and operands and isinstance(operands[-1], list):
            for item in operands[-1]:
                if isinstance(item, bytes):
                    show(item)
                elif isinstance(item, (int, float)) and -item >= _SPACE_GAP:
                    line.append(" ")
        elif op in (b"Td", b"TD") and (pair := numbers(operands, 2)):
            move(where[0] + pair[0], where[1] + pair[1])
        elif op == b"Tm" and (six := numbers(operands, 6)):
            move(six[4], six[5])
        elif op in (b"T*", b"BT", b"ET"):
            newline()
            if op == b"BT":
                where[0], where[1] = 0.0, 0.0
    newline()
    return "\n".join(lines), missing


def _content_streams(doc: "Document", page: PdfPage) -> list[Stream]:
    """쪽의 내용 스트림들. 여러 개로 쪼개 둔 파일이 흔하다."""
    body = doc.get(page.data.get("Contents"))
    found = []
    for item in (body if isinstance(body, list) else [body]):
        value = doc.get(item)
        if isinstance(value, Stream):
            found.append(value)
    return found


@dataclass
class TextResult:
    pages: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)   # 못 읽은 글꼴 이름

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages)

    @property
    def empty_pages(self) -> list[int]:
        return [i + 1 for i, body in enumerate(self.pages) if not body.strip()]


def read_text(doc: "Document", *, pages: list[int] | None = None) -> TextResult:
    """PDF 에서 글자를 꺼낸다. pages 는 1부터 센 쪽 번호."""
    result = TextResult()
    all_pages = doc.pages()
    picked = pages or list(range(1, len(all_pages) + 1))
    for number in picked:
        if not 1 <= number <= len(all_pages):
            continue
        body, missing = page_text(doc, all_pages[number - 1])
        result.pages.append(body)
        for name in missing:
            if name not in result.missing:
                result.missing.append(name)
    return result


# ------------------------------------------------ PDF 안의 그림 꺼내기

# 이미지 자체가 눌린 방식. 이것은 풀지 않고 그대로 파일로 낸다 - jpg 는
# 이미 jpg 다. 다시 눌러 봐야 화질만 깎인다.
IMAGE_CODECS = {"DCTDecode": "jpg", "DCT": "jpg", "JPXDecode": "jp2"}

# 우리가 풀 수 있는 앞단 필터. 여기 없는 것은 못 꺼낸다고 말한다.
PLAIN_FILTERS = {"FlateDecode", "Fl", "ASCII85Decode", "A85",
                 "ASCIIHexDecode", "AHx", "RunLengthDecode", "RL"}

MAX_PIXELS = 80_000_000        # 8천만 화소. 이보다 크면 깨진 값으로 본다


@dataclass
class PdfImage:
    """PDF 안에 들어 있던 그림 하나."""

    page: int
    name: str                  # 문서 안에서의 이름 (Im0)
    width: int
    height: int
    kind: str = ""             # jpg · jp2 · png. 빈 값이면 못 꺼낸 것
    data: bytes = b""
    colors: str = ""           # 무슨 색으로 적혀 있었나 (사람이 보고 판단하게)
    why: str = ""              # 못 꺼낸 이유

    @property
    def ok(self) -> bool:
        return bool(self.data)

    @property
    def size(self) -> int:
        return len(self.data)


def _run_length(data: bytes) -> bytes:
    """PDF 의 RunLengthDecode. 길이 바이트 하나에 128 을 기준으로 갈린다."""
    out = bytearray()
    i = 0
    while i < len(data):
        length = data[i]
        i += 1
        if length == 128:
            break
        if length < 128:
            out += data[i:i + length + 1]
            i += length + 1
        else:
            if i >= len(data):
                break
            out += bytes([data[i]]) * (257 - length)
            i += 1
    return bytes(out)


def _image_stream(doc: "Document", stream: Stream) -> tuple[bytes, str]:
    """이미지 코덱 앞까지만 푼다. (자료, 남은 코덱). 코덱이 없으면 («», 생자료).

    stream_data 는 DCTDecode 를 만나면 그만둔다 - 맞는 동작이다. 여기서는
    그 앞단(Flate·A85)만 풀고 jpg 는 눌린 채로 받아야 한다.
    """
    get = doc.get
    filters = get(stream.data.get("Filter")) or []
    if isinstance(filters, (Name, str)):
        filters = [filters]
    parms = get(stream.data.get("DecodeParms"))
    if parms is None:
        parms = get(stream.data.get("DP"))
    if not isinstance(parms, list):
        parms = [parms]

    data = stream.raw
    for i, one in enumerate(filters):
        kind = str(get(one))
        if kind in IMAGE_CODECS:
            return data, kind
        if kind in ("FlateDecode", "Fl"):
            data = _inflate(data)
        elif kind in ("RunLengthDecode", "RL"):
            data = _run_length(data)
        elif kind in ("ASCII85Decode", "A85"):
            import base64
            body = re.sub(rb"\s", b"", data)
            if body.startswith(b"<~"):
                body = body[2:]
            data = base64.a85decode(body.split(b"~>")[0], adobe=False)
        elif kind in ("ASCIIHexDecode", "AHx"):
            body = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
            data = bytes.fromhex((body + b"0" if len(body) % 2 else body).decode("ascii"))
        else:
            raise PdfError(kind)
        parm = get(parms[i]) if i < len(parms) else None
        if isinstance(parm, dict):
            data = _undo_predictor(data, parm, get)
    return data, ""


def _space_name(doc: "Document", space) -> str:
    """색 공간의 이름. 모르면 빈 값."""
    space = doc.get(space)
    if isinstance(space, (Name, str)):
        return str(space)
    if isinstance(space, list) and space:
        return str(doc.get(space[0]))
    return ""


def _channels(doc: "Document", space) -> tuple[int, str]:
    """(성분 수, 사람이 읽는 이름). 모르는 색 공간은 0 을 준다."""
    name = _space_name(doc, space)
    if name in ("DeviceGray", "CalGray", "G"):
        return 1, "회색"
    if name in ("DeviceRGB", "CalRGB", "Lab", "RGB"):
        return 3, "RGB"
    if name in ("DeviceCMYK", "CMYK"):
        return 4, "CMYK"
    if name == "ICCBased":
        space = doc.get(space)
        target = doc.get(space[1]) if len(space) > 1 else None
        count = int(doc.get(target.data.get("N")) or 0) if isinstance(target, Stream) else 0
        return count, {1: "회색", 3: "RGB", 4: "CMYK"}.get(count, "ICC")
    if name in ("Indexed", "I"):
        return 1, "색표(Indexed)"
    return 0, name or "알 수 없음"


def _palette(doc: "Document", space) -> tuple[bytes, int]:
    """색표(Indexed)의 표와 바탕 색의 성분 수. 못 읽으면 (b"", 0)."""
    space = doc.get(space)
    if not isinstance(space, list) or len(space) < 4:
        return b"", 0
    base, _hival, lookup = doc.get(space[1]), doc.get(space[2]), doc.get(space[3])
    count, _ = _channels(doc, base)
    if count != 3:                     # RGB 바탕만 편다. 나머지는 짐작하지 않는다
        return b"", 0
    if isinstance(lookup, Stream):
        try:
            lookup = stream_data(lookup, doc)
        except PdfError:
            return b"", 0
    if isinstance(lookup, str):
        lookup = lookup.encode("latin-1", "replace")
    return (lookup if isinstance(lookup, bytes) else b""), count


def _png(data: bytes, width: int, height: int, *, bits: int, gray: bool) -> bytes:
    """생 화소를 PNG 로 싼다. 줄마다 필터 바이트(0)를 앞에 붙인다."""
    import struct

    channels = 1 if gray else 3
    stride = (width * channels * bits + 7) // 8
    rows = bytearray()
    for y in range(height):
        line = data[y * stride:(y + 1) * stride]
        rows += b"\x00" + line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    head = struct.pack(">IIBBBBB", width, height, bits, 0 if gray else 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def _as_png(doc: "Document", stream: Stream, data: bytes,
            width: int, height: int) -> tuple[bytes, str, str]:
    """눌리지 않은 화소를 PNG 로. (자료, 색 이름, 못 한 이유)."""
    get = doc.get
    # «or 8» 로 적으면 BitsPerComponent 0 인 망가진 문서를 8비트로 읽어
    # 그럴듯한 그림을 내게 된다. 없는 것과 0 은 다르다.
    raw_bits = get(stream.data.get("BitsPerComponent"))
    if raw_bits is None:
        raw_bits = get(stream.data.get("BPC"))
    try:
        bits = 8 if raw_bits is None else int(raw_bits)
    except (TypeError, ValueError):
        return b"", _channels(doc, stream.data.get("ColorSpace")
                              or stream.data.get("CS"))[1], \
               f"비트 수를 읽지 못했습니다 ({raw_bits})"
    space = stream.data.get("ColorSpace") or stream.data.get("CS")
    mask = bool(get(stream.data.get("ImageMask")) or get(stream.data.get("IM")))

    if mask:
        # 도장·글자 모양으로 쓰는 1비트 그림. PNG 에 1비트 회색이 있다.
        stride = (width + 7) // 8
        if len(data) < stride * height:
            return b"", "흑백(1비트)", "자료가 모자랍니다"
        return _png(data, width, height, bits=1, gray=True), "흑백(1비트)", ""

    count, colors = _channels(doc, space)
    if colors == "색표(Indexed)":
        table, _ = _palette(doc, space)
        if not table or bits != 8:
            return b"", colors, "색표를 펴지 못했습니다"
        out = bytearray()
        for value in data[:width * height]:
            out += table[value * 3:value * 3 + 3].ljust(3, b"\x00")
        if len(out) < width * height * 3:
            return b"", colors, "자료가 모자랍니다"
        return _png(bytes(out), width, height, bits=8, gray=False), colors, ""

    if count not in (1, 3):
        return b"", colors, f"{colors} 색은 다루지 못합니다"
    if count == 3 and bits not in (8, 16):
        return b"", colors, f"{bits}비트 RGB 는 다루지 못합니다"
    if count == 1 and bits not in (1, 2, 4, 8, 16):
        return b"", colors, f"{bits}비트 회색은 다루지 못합니다"

    stride = (width * count * bits + 7) // 8
    if len(data) < stride * height:
        # 모자란 것을 채워 내면 그럴듯한 그림이 나오지만 그 그림은 거짓이다.
        return b"", colors, "자료가 모자랍니다"
    return _png(data, width, height, bits=bits, gray=count == 1), colors, ""


def _image_of(doc: "Document", number: int, name: str,
              stream: Stream) -> PdfImage:
    get = doc.get
    width = int(get(stream.data.get("Width")) or get(stream.data.get("W")) or 0)
    height = int(get(stream.data.get("Height")) or get(stream.data.get("H")) or 0)
    found = PdfImage(number, name, width, height)
    if width <= 0 or height <= 0:
        found.why = "크기를 읽지 못했습니다"
        return found
    if width * height > MAX_PIXELS:
        found.why = "크기가 이상합니다"
        return found

    try:
        data, codec = _image_stream(doc, stream)
    except PdfError as exc:
        found.why = f"{exc} 방식은 풀지 못합니다"
        return found

    if codec:
        found.kind = IMAGE_CODECS[codec]
        found.data = data
        found.colors = _channels(doc, stream.data.get("ColorSpace")
                                 or stream.data.get("CS"))[1]
        return found

    body, colors, why = _as_png(doc, stream, data, width, height)
    found.colors = colors
    if not body:
        found.why = why
        return found
    found.kind = "png"
    found.data = body
    return found


def _xobjects(doc: "Document", data: dict, number: int, *,
              depth: int = 0, seen: set | None = None) -> list[PdfImage]:
    """쪽(또는 Form) 안의 그림. Form 안에 또 들어 있는 것도 따라간다."""
    seen = seen if seen is not None else set()
    out: list[PdfImage] = []
    if depth > 4:
        return out
    resources = doc.get(data.get("Resources")) or {}
    if not isinstance(resources, dict):
        return out
    holder = doc.get(resources.get("XObject")) or {}
    if not isinstance(holder, dict):
        return out

    for name in sorted(holder):
        ref = holder[name]
        key = (number, ref.num) if isinstance(ref, Ref) else (number, name)
        if key in seen:
            continue
        seen.add(key)
        stream = doc.get(ref)
        if not isinstance(stream, Stream):
            continue
        kind = str(doc.get(stream.data.get("Subtype")) or "")
        if kind == "Image":
            out.append(_image_of(doc, number, name, stream))
        elif kind == "Form":
            out += _xobjects(doc, stream.data, number, depth=depth + 1, seen=seen)
    return out


def read_images(doc: "Document", *,
                pages: list[int] | None = None) -> list[PdfImage]:
    """PDF 안의 그림을 꺼낸다. 못 꺼낸 것도 이유와 함께 목록에 남긴다.

    jpg 는 눌린 그대로 낸다. 다시 눌러 내면 화질만 깎인다. 눌리지 않은
    화소는 PNG 로 싸고, 우리가 모르는 색 공간·압축은 «못 꺼냈다» 고 적는다.
    조용히 빼면 그림이 몇 장 없는 문서로 보인다.
    """
    all_pages = doc.pages()
    picked = pages or list(range(1, len(all_pages) + 1))
    out: list[PdfImage] = []
    for number in picked:
        if not 1 <= number <= len(all_pages):
            continue
        out += _xobjects(doc, all_pages[number - 1].data, number)
    return out


# ---------------------------------------------------- 쪽마다 무엇이 들어 있나

@dataclass
class PageFacts:
    """쪽 하나에 무엇이 들어 있는지. 판단은 부르는 쪽이 한다."""

    number: int
    chars: int = 0             # 꺼낸 글자 수 (공백 제외)
    images: int = 0            # 그림 수
    image_bytes: int = 0       # 그림 자료의 크기 합
    unreadable: int = 0        # 꺼내지 못한 그림 수
    missing_fonts: list = field(default_factory=list)

    @property
    def empty(self) -> bool:
        """글자도 그림도 없는 쪽. 이것만이 «확실히 빈 쪽» 이다."""
        return self.chars == 0 and self.images == 0 and self.unreadable == 0


def page_facts(doc: "Document", *, pages: list[int] | None = None) -> list[PageFacts]:
    """쪽마다 글자 수와 그림을 센다.

    스캔한 백지는 «그림 한 장» 으로 들어 있어 글자만 봐서는 빈 쪽인지 알 수
    없다. 그래서 세기만 하고 «백지다» 라고 말하지 않는다 - 그 판단에 필요한
    것(글자 수·그림 수·그림 용량)을 그대로 돌려준다.
    """
    all_pages = doc.pages()
    picked = pages or list(range(1, len(all_pages) + 1))
    out: list[PageFacts] = []
    for number in picked:
        if not 1 <= number <= len(all_pages):
            continue
        page = all_pages[number - 1]
        facts = PageFacts(number)
        try:
            body, missing = page_text(doc, page)
        except (PdfError, ValueError, RecursionError):
            body, missing = "", []
        facts.chars = len("".join(body.split()))
        facts.missing_fonts = list(missing)
        for image in _xobjects(doc, page.data, number):
            if image.ok:
                facts.images += 1
                facts.image_bytes += image.size
            else:
                facts.unreadable += 1
        out.append(facts)
    return out


# ------------------------------------------------------------ 그림 도장 찍기
#
# 계약서에 도장을 찍으려고 인쇄해서 찍고 다시 스캔하는 일을 없애려는 것이다.
# 원래 내용은 건드리지 않고 그림 한 겹을 위에 얹는다.

@dataclass
class StampImage:
    """도장으로 얹을 그림. 자료는 이미 눌린 채로 들고 있는다."""

    width: int
    height: int
    data: bytes
    filter: str = "FlateDecode"
    space: str = "DeviceRGB"
    alpha: bytes | None = None     # 8비트 투명도 (FlateDecode 로 눌러 둔 것)
    source: str = ""


def read_stamp(path: Path) -> StampImage:
    """도장 그림을 읽는다. PNG 의 투명도는 살려서 가져온다.

    jpg 는 투명도가 없어 네모가 그대로 얹힌다. 도장은 PNG 로 만드는 편이 낫다.
    """
    path = Path(path)
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        page = read_image(path)                 # jpg 는 눌린 채로 그대로 쓴다
        return StampImage(page.width, page.height, page.data, page.filter,
                          page.colorspace, None, str(path))

    header: dict = {}
    idat = bytearray()
    palette = b""
    for kind, body in _png_chunks(raw):
        if kind == b"IHDR":
            header = {"width": int.from_bytes(body[0:4], "big"),
                      "height": int.from_bytes(body[4:8], "big"),
                      "bits": body[8], "color": body[9], "interlace": body[12]}
        elif kind == b"PLTE":
            palette = body
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if not header:
        raise PdfError("PNG 머리말(IHDR)을 찾지 못했습니다")
    if header["interlace"]:
        raise PdfError("인터레이스 PNG 는 못 씁니다 (그냥 PNG 로 다시 저장하세요)")
    if header["bits"] != 8:
        raise PdfError(f"{header['bits']}비트 PNG 는 못 씁니다 "
                       "(8비트로 다시 저장하세요)")

    color = header["color"]
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    if channels is None:
        raise PdfError(f"모르는 PNG 색 방식입니다: {color}")
    width, height = header["width"], header["height"]
    stride = width * channels
    try:
        flat = _unfilter(zlib.decompress(bytes(idat)), width, height, stride,
                         channels)
    except zlib.error as exc:
        raise PdfError(f"PNG 를 풀지 못했습니다: {exc}") from None

    body = bytearray()
    alpha = bytearray()
    for row in range(height):
        line = flat[row * stride:(row + 1) * stride]
        for x in range(width):
            at = x * channels
            if color == 3:                       # 팔레트
                index = line[at] * 3
                body += palette[index:index + 3] or b"\x00\x00\x00"
            elif color in (0, 4):                # 회색 (+알파)
                body.append(line[at])
            else:                                # RGB (+알파)
                body += line[at:at + 3]
            if color == 4:
                alpha.append(line[at + 1])
            elif color == 6:
                alpha.append(line[at + 3])

    space = "DeviceGray" if color in (0, 4) else "DeviceRGB"
    return StampImage(width, height, zlib.compress(bytes(body), 6),
                      "FlateDecode", space,
                      zlib.compress(bytes(alpha), 6) if alpha else None,
                      str(path))


def image_stamp_stream(box: list, rotate: int, *, where: str = "bottom-right",
                       width: float = 85.0, height: float = 85.0,
                       margin: float = 12.0, name: str = "ATIMG") -> str:
    """그림 한 장을 쪽 위에 얹는 내용 스트림. 자리 셈은 쪽 번호와 같은 규칙이다."""
    if where not in STAMP_WHERE:
        raise PdfError(f"모르는 자리입니다: {where} ({', '.join(STAMP_WHERE)})")

    x0, y0, x1, y1 = (float(v) for v in (box + [0, 0, 612, 792])[:4])
    page_w, page_h = abs(x1 - x0), abs(y1 - y0)
    rotate %= 360
    shown_w, shown_h = (page_h, page_w) if rotate in (90, 270) else (page_w, page_h)

    if where.endswith("right"):
        shown_x = shown_w - margin - width
    elif where.endswith("left"):
        shown_x = margin
    else:
        shown_x = (shown_w - width) / 2
    shown_y = (shown_h - margin - height) if where.startswith("top") else margin

    # 보는 사람 자리 -> 파일 안의 자리. 돌아간 쪽이면 그림도 같이 돌린다
    if rotate == 90:
        matrix = f"0 {width:.2f} {-height:.2f} 0"
        x, y = page_w - shown_y, shown_x
    elif rotate == 180:
        matrix = f"{-width:.2f} 0 0 {-height:.2f}"
        x, y = page_w - shown_x, page_h - shown_y
    elif rotate == 270:
        matrix = f"0 {-width:.2f} {height:.2f} 0"
        x, y = shown_y, page_h - shown_x
    else:
        matrix = f"{width:.2f} 0 0 {height:.2f}"
        x, y = shown_x, shown_y

    return (f"q {matrix} {min(x0, x1) + x:.2f} {min(y0, y1) + y:.2f} cm "
            f"/{name} Do Q\n")


def image_stamper(image: StampImage, *, pages: list[int] | None = None,
                  where: str = "bottom-right", width_mm: float = 30.0,
                  margin_mm: float = 10.0):
    """어느 쪽에 얼마만 하게 찍을지 정하는 함수를 만든다."""
    width = width_mm * 72.0 / 25.4
    height = width * image.height / image.width if image.width else width
    margin = margin_mm * 72.0 / 25.4
    wanted = set(pages) if pages else None

    def stamp(index: int, page: "PdfPage", doc: "Document") -> str:
        if wanted is not None and index not in wanted:
            return ""
        box = doc.get(page.data.get("MediaBox")) or [0, 0, 612, 792]
        box = [float(doc.get(v) or 0) for v in box]
        turn = doc.get(page.data.get("Rotate")) or 0
        return image_stamp_stream(box, int(turn), where=where, width=width,
                                  height=height, margin=margin)
    return stamp
