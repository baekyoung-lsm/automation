"""PDF 만들기·읽기 시험.

만든 PDF 를 열어 볼 뷰어가 없으므로, 읽는 쪽에서 쓰는 방법 그대로
(startxref -> xref 표 -> 객체) 되짚어 본다. 구조가 어긋나면 여기서 걸린다.
"""

import re
import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attools import pdf


def _apply_filter(kind: int, line: bytearray, previous: bytearray,
                  step: int) -> bytes:
    """PNG 로 적을 때 줄 필터를 실제로 건다. 안 걸면 되돌리기를 시험하지 못한다."""
    out = bytearray()
    for x in range(len(line)):
        left = line[x - step] if x >= step else 0
        up = previous[x]
        upleft = previous[x - step] if x >= step else 0
        if kind == 0:
            value = line[x]
        elif kind == 1:
            value = line[x] - left
        elif kind == 2:
            value = line[x] - up
        elif kind == 3:
            value = line[x] - (left + up) // 2
        else:
            p = left + up - upleft
            pa, pb, pc = abs(p - left), abs(p - up), abs(p - upleft)
            best = left if (pa <= pb and pa <= pc) else (up if pb <= pc
                                                         else upleft)
            value = line[x] - best
        out.append(value & 0xFF)
    return bytes(out)


def png_bytes(width: int, height: int, pixel, *, color: int = 2,
              palette: bytes = b"", interlace: int = 0, bits: int = 8,
              filter_kind: int = 0) -> bytes:
    """시험용 PNG 를 손으로 만든다 (외부 라이브러리 없이)."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    step = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color] * (bits // 8)
    rows = []
    previous = bytearray()
    for y in range(height):
        line = bytearray()
        for x in range(width):
            line += bytes(pixel(x, y))
        if not previous:
            previous = bytearray(len(line))
        rows.append(bytes([filter_kind]) + _apply_filter(filter_kind, line,
                                                         previous, step))
        previous = line
    out = b"\x89PNG\r\n\x1a\n"
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bits, color,
                                      0, 0, interlace))
    if palette:
        out += chunk(b"PLTE", palette)
    out += chunk(b"IDAT", zlib.compress(b"".join(rows)))
    out += chunk(b"IEND", b"")
    return out


def jpeg_bytes(width: int, height: int, *, components: int = 3,
               marker: int = 0xC0) -> bytes:
    """SOF 만 제대로 든 최소 JPEG. 크기·성분 읽기를 보는 데 쓴다."""
    sof = struct.pack(">BBHBHHB", 0xFF, marker, 8 + 3 * components, 8,
                      height, width, components)
    sof += bytes([1, 0x11, 0]) * components
    return b"\xff\xd8" + sof + b"\xff\xd9"


class ReadInfoTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make(self, body: bytes) -> Path:
        path = self.root / "문서.pdf"
        path.write_bytes(b"%PDF-1.4\n" + body + b"\n%%EOF\n")
        return path

    def test_counts_pages(self):
        body = (b"1 0 obj<</Type/Pages/Kids[2 0 R]/Count 2>>endobj\n"
                b"2 0 obj<</Type/Page>>endobj\n3 0 obj<</Type/Page>>endobj\n")
        self.assertEqual(pdf.read_info(self.make(body)).pages, 2)

    def test_title_with_escaped_parens(self):
        body = b"1 0 obj<</Type/Page/Title (2026 \\(1\\) plan)>>endobj"
        self.assertEqual(pdf.read_info(self.make(body)).title, "2026 (1) plan")

    def test_encrypted(self):
        info = pdf.read_info(self.make(b"trailer<</Encrypt 9 0 R>>"))
        self.assertIn("암호", info.error)

    def test_not_a_pdf(self):
        path = self.root / "가짜.pdf"
        path.write_bytes("PDF 아님".encode("utf-8"))
        self.assertIn("PDF 가 아닙니다", pdf.read_info(path).error)


class ReadImageTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_jpeg_goes_in_as_is(self):
        raw = jpeg_bytes(120, 80)
        page = pdf.read_image(self.write("사진.jpg", raw))
        self.assertEqual((page.width, page.height), (120, 80))
        self.assertEqual(page.filter, "DCTDecode")
        self.assertEqual(page.colorspace, "DeviceRGB")
        self.assertEqual(page.data, raw)      # 다시 누르지 않는다

    def test_grayscale_jpeg(self):
        page = pdf.read_image(self.write("사진.jpg", jpeg_bytes(10, 10,
                                                               components=1)))
        self.assertEqual(page.colorspace, "DeviceGray")

    def test_progressive_jpeg_is_refused_with_a_reason(self):
        # PDF 의 DCTDecode 는 baseline 만 받는다. 넣어 두면 뷰어에서 빈 쪽이 된다
        raw = jpeg_bytes(10, 10, marker=0xC2)
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.read_image(self.write("사진.jpg", raw))
        self.assertIn("프로그레시브", str(ctx.exception))

    def test_cmyk_jpeg_is_refused(self):
        with self.assertRaises(pdf.PdfError):
            pdf.read_image(self.write("사진.jpg", jpeg_bytes(10, 10,
                                                            components=4)))

    def test_png_pixels_survive(self):
        def pixel(x, y):
            return (x * 10 % 256, y * 20 % 256, 7)

        page = pdf.read_image(self.write("그림.png", png_bytes(6, 4, pixel)))
        self.assertEqual(page.filter, "FlateDecode")
        raw = zlib.decompress(page.data)
        self.assertEqual(len(raw), 6 * 4 * 3)
        for y in range(4):
            for x in range(6):
                at = (y * 6 + x) * 3
                self.assertEqual(tuple(raw[at:at + 3]), pixel(x, y))

    def test_every_row_filter_is_undone(self):
        def pixel(x, y):
            return (x * 37 % 256, (x + y * 11) % 256, y * 5 % 256)

        want = zlib.decompress(
            pdf.read_image(self.write("민.png", png_bytes(7, 5, pixel))).data)
        for kind in (1, 2, 3, 4):      # Sub, Up, Average, Paeth
            page = pdf.read_image(self.write(f"필터{kind}.png",
                                             png_bytes(7, 5, pixel,
                                                       filter_kind=kind)))
            self.assertEqual(zlib.decompress(page.data), want,
                             f"{kind}번 줄 필터를 되돌리지 못했습니다")

    def test_palette_png(self):
        palette = bytes([255, 0, 0, 0, 255, 0])
        page = pdf.read_image(self.write("팔레트.png",
                                         png_bytes(2, 1, lambda x, y: (x,),
                                                   color=3, palette=palette)))
        self.assertEqual(zlib.decompress(page.data),
                         bytes([255, 0, 0, 0, 255, 0]))
        self.assertEqual(page.colorspace, "DeviceRGB")

    def test_interlaced_png_is_refused(self):
        raw = png_bytes(4, 4, lambda x, y: (1, 2, 3), interlace=1)
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.read_image(self.write("그림.png", raw))
        self.assertIn("인터레이스", str(ctx.exception))

    def test_other_formats_say_what_to_do(self):
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.read_image(self.write("그림.gif", b"GIF89a" + b"\x00" * 20))
        self.assertIn("jpg", str(ctx.exception))


class MakePdfTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.image = self.root / "그림.png"
        self.image.write_bytes(png_bytes(40, 30, lambda x, y: (x * 6, 100, y)))
        self.tall = self.root / "세로.png"
        self.tall.write_bytes(png_bytes(30, 40, lambda x, y: (10, 20, 30)))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def build(self, images=None, **kw) -> Path:
        pages = [pdf.read_image(p) for p in (images or [self.tall])]
        return pdf.images_to_pdf(pages, self.root / "묶음.pdf", **kw)

    # ---- 읽는 쪽 방법 그대로 되짚어 본다

    def objects(self, path: Path) -> dict[int, bytes]:
        """startxref -> xref 표 -> 객체. 자리가 틀리면 여기서 걸린다."""
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF-"))
        self.assertTrue(raw.rstrip().endswith(b"%%EOF"))
        start = int(raw.rsplit(b"startxref", 1)[1].split(b"%%EOF")[0].strip())
        table = raw[start:]
        self.assertTrue(table.startswith(b"xref"))
        count = int(table.split(b"\n")[1].split()[1])
        found: dict[int, bytes] = {}
        for number in range(1, count):
            line = table.split(b"\n")[2 + number]
            offset = int(line.split()[0])
            head = raw[offset:offset + 40]
            self.assertTrue(head.startswith(f"{number} 0 obj".encode()),
                            f"{number}번 객체 자리가 어긋납니다: {head[:20]!r}")
            found[number] = raw[offset:]
        return found

    def test_structure_can_be_walked_from_startxref(self):
        found = self.objects(self.build())
        self.assertIn(b"/Type /Catalog", found[1])
        self.assertIn(b"/Type /Pages", found[2])

    def test_one_page_per_image(self):
        path = self.build([self.image, self.tall, self.image])
        self.assertEqual(pdf.read_info(path).pages, 3)
        self.assertIn(b"/Count 3", path.read_bytes())

    def test_stream_length_matches(self):
        raw = self.build().read_bytes()
        for match in re.finditer(rb"/Length (\d+) >>\s*stream\r?\n", raw):
            length = int(match.group(1))
            body = raw[match.end():match.end() + length]
            self.assertEqual(raw[match.end() + length:match.end() + length + 10]
                             .strip()[:9], b"endstream")
            self.assertEqual(len(body), length)

    def test_image_bytes_are_the_ones_we_read(self):
        page = pdf.read_image(self.image)
        raw = self.build([self.image]).read_bytes()
        self.assertIn(page.data, raw)

    def test_page_box_follows_the_paper(self):
        raw = self.build(page="a4").read_bytes()
        self.assertIn(b"/MediaBox [0 0 595.28 841.89]", raw)
        wide = self.build(page="a4", landscape=True).read_bytes()
        self.assertIn(b"/MediaBox [0 0 841.89 595.28]", wide)

    def test_ratio_is_kept(self):
        # 40x30 그림을 A4 에 넣으면 4:3 이 그대로여야 한다 (눕히지 않을 때)
        raw = self.build([self.image], rotate=False).read_bytes()
        matrix = re.search(rb"q ([\d.]+) 0 0 ([\d.]+) ", raw)
        width, height = float(matrix.group(1)), float(matrix.group(2))
        self.assertAlmostEqual(width / height, 40 / 30, places=2)

    def test_wide_image_is_turned(self):
        turned = self.build([self.image], rotate=True).read_bytes()
        self.assertRegex(turned, rb"q 0 [\d.]+ -[\d.]+ 0 ")
        straight = self.build([self.image], rotate=False).read_bytes()
        self.assertNotRegex(straight, rb"q 0 [\d.]+ -[\d.]+ 0 ")

    def test_margin_shrinks_the_drawing(self):
        none = self.build([self.tall], margin_mm=0).read_bytes()
        wide = self.build([self.tall], margin_mm=20).read_bytes()
        first = float(re.search(rb"q ([\d.]+) 0 0 ", none).group(1))
        second = float(re.search(rb"q ([\d.]+) 0 0 ", wide).group(1))
        self.assertLess(second, first)

    def test_korean_title_is_readable_again(self):
        path = self.build(title="제출용 스캔")
        self.assertEqual(pdf.read_info(path).title, "제출용 스캔")

    def test_unknown_paper(self):
        with self.assertRaises(pdf.PdfError):
            self.build(page="가나다")

    def test_no_images(self):
        with self.assertRaises(pdf.PdfError):
            pdf.images_to_pdf([], self.root / "빈것.pdf")


if __name__ == "__main__":
    unittest.main()
