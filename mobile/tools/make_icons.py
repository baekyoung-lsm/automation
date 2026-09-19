"""앱 아이콘(png)을 만든다. 표준 라이브러리만 쓴다 - zlib 과 struct 로 직접 쓴다.

    python3 mobile/tools/make_icons.py

장부 줄 세 개를 길이를 달리해 그린다. 글꼴을 쓰지 않으므로 어느 기기에서나
같게 나온다.
"""

import struct
import zlib
from pathlib import Path

GROUND = (27, 75, 107)          # 화면의 --accent 남색
LINE = (239, 241, 243)          # 화면의 --ground
SIZES = (192, 512)


def draw(size: int) -> bytes:
    px = [[GROUND] * size for _ in range(size)]
    margin = size // 6
    thick = max(size // 14, 2)
    for step, ratio in enumerate((1.0, 0.72, 0.45)):
        top = size // 2 - thick * 3 + step * thick * 3
        width = int((size - margin * 2) * ratio)
        for y in range(top, min(top + thick, size)):
            for x in range(margin, min(margin + width, size)):
                px[y][x] = LINE
    return b"".join(b"\x00" + b"".join(bytes(one) for one in row) for row in px)


def chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write(size: int, path: Path) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(draw(size), 9))
        + chunk(b"IEND", b""))


def main() -> None:
    here = Path(__file__).resolve().parent.parent
    for size in SIZES:
        target = here / f"icon-{size}.png"
        write(size, target)
        print(f"만들었습니다: {target}")


if __name__ == "__main__":
    main()
