"""의존성 없는 PDF - 속성 읽기와 이미지 묶기.

스캔한 사진을 제출용 PDF 한 장으로 묶는 일과, 받은 PDF 의 제목·쪽 수를
보는 일만 한다. 본문 글자는 꺼내지 않는다 - 글꼴(CID)에 따라 조용히 틀린
글자가 나오는데, 그건 «안 되는 것» 보다 나쁘다.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

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
    error: str = ""


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
