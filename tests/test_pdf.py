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


def simple_pdf(path: Path, *, pages: int = 3, text: str = "쪽",
               author: str = "") -> Path:
    """옛날 방식(고전 xref)으로 만든 작은 PDF. 쪽마다 다른 내용이 들어간다."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    kids, contents = [], []
    for i in range(1, pages + 1):
        stream = f"BT /F1 24 Tf 20 100 Td ({text}{i}) Tj ET".encode("utf-8")
        contents.append(add(b"<</Length " + str(len(stream)).encode() + b">>\n"
                            b"stream\n" + stream + b"\nendstream"))
    font = add(b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>")
    tree = len(objects) + pages + 1                 # 쪽 다음에 올 Pages 번호
    for i in range(pages):
        kids.append(add(
            f"<</Type/Page/Parent {tree} 0 R/Contents {contents[i]} 0 R"
            f"/Resources<</Font<</F1 {font} 0 R>>>>>>".encode()))
    add(("<</Type/Pages/Count %d/Kids[%s]/MediaBox[0 0 200 200]>>"
         % (pages, " ".join(f"{k} 0 R" for k in kids))).encode())
    root = add(b"<</Type/Catalog/Pages " + str(tree).encode() + b" 0 R>>")
    info = 0
    if author:
        info = add(b"<</Author<feff" + author.encode("utf-16-be").hex().encode()
                   + b">/Title(plan)>>")

    out = [b"%PDF-1.4\n"]
    places = [0]
    at = len(out[0])
    for i, body in enumerate(objects, 1):
        blob = f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        out.append(blob)
        places.append(at)
        at += len(blob)
    out.append(f"xref\n0 {len(objects) + 1}\n".encode())
    out.append(b"0000000000 65535 f \n")
    for i in range(1, len(objects) + 1):
        out.append(f"{places[i]:010d} 00000 n \n".encode())
    out.append((f"trailer\n<</Size {len(objects) + 1}/Root {root} 0 R"
                + (f"/Info {info} 0 R" if info else "")
                + f">>\nstartxref\n{at}\n%%EOF\n").encode())
    path.write_bytes(b"".join(out))
    return path


def modern_pdf(path: Path) -> Path:
    """요즘 방식으로 만든 PDF - 객체를 묶어 누르고(ObjStm) 표도 스트림이다."""
    stream = b"BT /F1 24 Tf 20 100 Td (modern) Tj ET"
    plain = (b"4 0 obj\n<</Length " + str(len(stream)).encode() + b">>\n"
             b"stream\n" + stream + b"\nendstream\nendobj\n")

    inner = [
        (1, b"<</Type/Catalog/Pages 2 0 R>>"),
        (2, b"<</Type/Pages/Count 1/Kids[3 0 R]/MediaBox[0 0 200 200]"
            b"/Resources<</Font<</F1<</Type/Font/Subtype/Type1"
            b"/BaseFont/Helvetica>>>>>>>>"),
        (3, b"<</Type/Page/Parent 2 0 R/Contents 4 0 R>>"),
    ]
    head, body = b"", b""
    for number, blob in inner:
        head += f"{number} {len(body)} ".encode()
        body += blob + b" "
    packed = zlib.compress(head + body)
    objstm = (b"5 0 obj\n<</Type/ObjStm/N 3/First " + str(len(head)).encode() +
              b"/Length " + str(len(packed)).encode() +
              b"/Filter/FlateDecode>>\nstream\n" + packed + b"\nendstream\nendobj\n")

    start = len(b"%PDF-1.5\n")
    rows = {4: start, 5: start + len(plain)}
    xref_at = start + len(plain) + len(objstm)
    rows[6] = xref_at

    table = bytearray()
    table += bytes([0]) + (0).to_bytes(4, "big") + (65535).to_bytes(2, "big")
    for number in (1, 2, 3):
        table += bytes([2]) + (5).to_bytes(4, "big") + (number - 1).to_bytes(2, "big")
    for number in (4, 5, 6):
        table += bytes([1]) + rows[number].to_bytes(4, "big") + (0).to_bytes(2, "big")
    squeezed = zlib.compress(bytes(table))
    xref = (b"6 0 obj\n<</Type/XRef/Size 7/W[1 4 2]/Root 1 0 R"
            b"/Filter/FlateDecode/Length " + str(len(squeezed)).encode() +
            b">>\nstream\n" + squeezed + b"\nendstream\nendobj\n")

    path.write_bytes(b"%PDF-1.5\n" + plain + objstm + xref +
                     f"startxref\n{xref_at}\n%%EOF\n".encode())
    return path


class InfoByObjectsTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_counts_pages_by_walking_the_tree(self):
        info = pdf.read_info(simple_pdf(self.root / "셋.pdf", pages=3,
                                        author="홍길동"))
        self.assertEqual(info.pages, 3)
        self.assertEqual(info.author, "홍길동")
        self.assertEqual(info.text_pages, 3)      # 글꼴이 걸린 쪽

    def test_scan_has_no_font(self):
        path = simple_pdf(self.root / "스캔.pdf", pages=1)
        raw = path.read_bytes().replace(b"/Resources<</Font<</F1 2 0 R>>>>",
                                        b"/Resources<<>>                  ")
        path.write_bytes(raw)
        self.assertEqual(pdf.read_info(path).text_pages, 0)

    def test_falls_back_when_the_file_is_too_broken(self):
        path = self.root / "망가진.pdf"
        path.write_bytes(b"%PDF-1.4\n1 0 obj\n<</Type/Page>>\nendobj\n")
        info = pdf.read_info(path)          # 훑어 세는 옛 방법으로 떨어진다
        self.assertEqual(info.pages, 1)
        self.assertIsNone(info.text_pages)

    def test_hangul_title_survives_a_rewrite(self):
        source = simple_pdf(self.root / "제목.pdf", pages=1)
        doc = pdf.open_pdf(source)
        out = self.root / "다시.pdf"
        pdf.join_pdfs([(doc, [1])], out, title="분기 보고서")
        self.assertEqual(pdf.read_info(out).title, "분기 보고서")


class PdfPagesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_reads_pages_and_inherits_size(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "셋.pdf", pages=3))
        pages = doc.pages()
        self.assertEqual([p.number for p in pages], [1, 2, 3])
        # MediaBox 는 Pages 에만 있다. 물려받지 못하면 쪽 크기를 잃는다
        self.assertEqual(doc.get(pages[0].data["MediaBox"]), [0, 0, 200, 200])

    def test_reads_packed_objects_and_xref_stream(self):
        doc = pdf.open_pdf(modern_pdf(self.root / "요즘.pdf"))
        self.assertEqual(len(doc.pages()), 1)
        page = doc.pages()[0]
        self.assertEqual(doc.get(page.data["MediaBox"]), [0, 0, 200, 200])

    def test_broken_xref_still_opens(self):
        path = simple_pdf(self.root / "망가진.pdf", pages=2)
        raw = path.read_bytes()
        # 표에 적힌 자리를 엉뚱하게 바꾼다 (고쳐 저장하다 깨진 파일 흉내)
        broken = re.sub(rb"(?m)^0000000(\d\d\d) 00000 n",
                        rb"0000009\1 00000 n", raw)
        path.write_bytes(broken)
        self.assertEqual(len(pdf.open_pdf(path).pages()), 2)

    def test_lying_xref_count_does_not_hang(self):
        path = simple_pdf(self.root / "거짓표.pdf", pages=1)
        path.write_bytes(path.read_bytes().replace(b"xref\n0 7",
                                                   b"xref\n0 999999999"))
        # 남은 길이보다 많이 적힌 표를 곧이곧대로 읽으면 멈추지 않는다
        self.assertEqual(len(pdf.open_pdf(path).pages()), 1)

    def test_encrypted_is_refused(self):
        path = simple_pdf(self.root / "잠긴.pdf", pages=1)
        raw = path.read_bytes().replace(b"/Root", b"/Encrypt 99 0 R/Root")
        path.write_bytes(raw)
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.open_pdf(path)
        self.assertIn("암호", str(ctx.exception))

    def test_not_a_pdf(self):
        path = self.root / "그냥.txt"
        path.write_text("안녕", encoding="utf-8")
        with self.assertRaises(pdf.PdfError):
            pdf.open_pdf(path)


class PageNumbersTest(unittest.TestCase):
    def test_ranges(self):
        self.assertEqual(pdf.page_numbers("1-3,7", 10), [1, 2, 3, 7])
        self.assertEqual(pdf.page_numbers("8-", 10), [8, 9, 10])
        self.assertEqual(pdf.page_numbers("-3", 10), [1, 2, 3])
        self.assertEqual(pdf.page_numbers("2", 10), [2])

    def test_out_of_range_is_refused(self):
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.page_numbers("9-12", 10)
        self.assertIn("10쪽", str(ctx.exception))

    def test_garbage_is_refused(self):
        with self.assertRaises(pdf.PdfError):
            pdf.page_numbers("둘째쪽", 10)


class JoinPdfTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def contents(self, doc, page):
        blob = doc.get(page.data.get("Contents"))
        parts = blob if isinstance(blob, list) else [blob]
        out = b""
        for one in parts:
            one = doc.get(one)
            if isinstance(one, pdf.Stream):
                out += pdf.stream_data(one, doc)
        return out

    def test_cut_keeps_the_right_pages(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "다섯.pdf", pages=5))
        out = self.root / "뽑은.pdf"
        result = pdf.join_pdfs([(doc, [2, 4])], out)
        self.assertEqual((result.pages, result.missing), (2, 0))

        made = pdf.open_pdf(out)
        self.assertEqual(len(made.pages()), 2)
        self.assertIn(b"(\xec\xaa\xbd2)", self.contents(made, made.pages()[0]))
        self.assertIn(b"(\xec\xaa\xbd4)", self.contents(made, made.pages()[1]))

    def test_join_keeps_order_and_font(self):
        one = pdf.open_pdf(simple_pdf(self.root / "가.pdf", pages=2, text="가"))
        two = pdf.open_pdf(simple_pdf(self.root / "나.pdf", pages=1, text="나"))
        out = self.root / "합본.pdf"
        result = pdf.join_pdfs([(two, [1]), (one, [1, 2])], out)
        self.assertEqual(result.pages, 3)

        made = pdf.open_pdf(out)
        bodies = [self.contents(made, p) for p in made.pages()]
        self.assertIn("나1".encode("utf-8"), bodies[0])
        self.assertIn("가1".encode("utf-8"), bodies[1])
        self.assertIn("가2".encode("utf-8"), bodies[2])
        # 글꼴까지 따라와야 한다. 안 따라오면 열리기는 하고 글자만 사라진다
        resources = made.get(made.pages()[0].data.get("Resources"))
        self.assertIn("F1", made.get(resources.get("Font")))

    def test_stream_bytes_are_copied_as_they_were(self):
        doc = pdf.open_pdf(modern_pdf(self.root / "요즘.pdf"))
        out = self.root / "옮긴.pdf"
        pdf.join_pdfs([(doc, [1])], out)
        made = pdf.open_pdf(out)
        self.assertEqual(self.contents(doc, doc.pages()[0]),
                         self.contents(made, made.pages()[0]))

    def test_rotate_adds_to_the_angle_already_there(self):
        path = simple_pdf(self.root / "누운.pdf", pages=1)
        raw = path.read_bytes().replace(b"/Type/Page/Parent",
                                        b"/Rotate 90/Type/Page/Parent")
        path.write_bytes(raw)
        doc = pdf.open_pdf(path)
        out = self.root / "세운.pdf"
        pdf.join_pdfs([(doc, [1])], out, rotate=270)
        made = pdf.open_pdf(out)
        self.assertEqual(made.get(made.pages()[0].data.get("Rotate")), 0)

    def test_catalog_can_be_carried_when_every_page_is_kept(self):
        path = simple_pdf(self.root / "설정.pdf", pages=2)
        path.write_bytes(path.read_bytes().replace(
            b"/Type/Catalog", b"/PageMode/UseThumbs/Type/Catalog"))
        doc = pdf.open_pdf(path)
        out = self.root / "그대로.pdf"
        pdf.join_pdfs([(doc, [1, 2])], out, catalog_from=doc)
        made = pdf.open_pdf(out)
        self.assertEqual(str(made.get(made.trailer["Root"]).get("PageMode")),
                         "UseThumbs")

    def test_rotate_must_be_a_right_angle(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "한쪽.pdf", pages=1))
        with self.assertRaises(pdf.PdfError):
            pdf.join_pdfs([(doc, [1])], self.root / "삐딱.pdf", rotate=45)

    def test_missing_object_is_counted_not_hidden(self):
        path = simple_pdf(self.root / "빠진.pdf", pages=1)
        raw = re.sub(rb"/F1 \d 0 R", b"/F1 9 0 R", path.read_bytes())
        path.write_bytes(raw)
        doc = pdf.open_pdf(path)
        result = pdf.join_pdfs([(doc, [1])], self.root / "빠진사본.pdf")
        self.assertEqual(result.missing, 1)

    def test_other_pages_are_not_dragged_along(self):
        # 쪽끼리 서로 가리키는 파일이라도 고르지 않은 쪽은 따라오면 안 된다
        path = simple_pdf(self.root / "링크.pdf", pages=3)
        raw = path.read_bytes().replace(
            b"/Type/Page/Parent", b"/Ex 7 0 R/Type/Page/Parent", 1)
        path.write_bytes(raw)
        doc = pdf.open_pdf(path)
        out = self.root / "하나만.pdf"
        pdf.join_pdfs([(doc, [1])], out)
        self.assertEqual(len(pdf.open_pdf(out).pages()), 1)

def xmp_pdf(path: Path, author: str = "김철수") -> Path:
    """XMP 메타데이터에 이름이 든 PDF. 요즘 프로그램은 여기에도 적는다."""
    simple_pdf(path, pages=1, author=author)
    raw = path.read_bytes()
    xmp = ("<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>"
           "<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF "
           "xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
           "<rdf:Description xmlns:dc='http://purl.org/dc/elements/1.1/'>"
           f"<dc:creator><rdf:Seq><rdf:li>{author}</rdf:li></rdf:Seq></dc:creator>"
           f"<dc:title>보고서</dc:title></rdf:Description></rdf:RDF>"
           "</x:xmpmeta><?xpacket end='w'?>").encode("utf-8")
    body = (b"\n90 0 obj\n<</Type/Metadata/Subtype/XML/Length "
            + str(len(xmp)).encode() + b">>\nstream\n" + xmp
            + b"\nendstream\nendobj\n")
    # 목차에 /Metadata 를 걸고 객체를 파일 끝에 붙인다 (자리는 훑어서 찾는다)
    raw = raw.replace(b"/Type/Catalog", b"/Metadata 90 0 R/Type/Catalog")
    path.write_bytes(raw + body)
    return path


class ScrubPdfTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_finds_the_author(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "이름.pdf", pages=1,
                                      author="홍길동"))
        self.assertEqual(pdf.scrub_names(doc), [("만든 사람", "홍길동")])

    def test_nothing_to_remove(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "깨끗.pdf", pages=1))
        self.assertEqual(pdf.scrub_names(doc), [])
        with self.assertRaises(pdf.PdfError):
            pdf.scrub_pdf(doc, self.root / "사본.pdf")

    def test_removed_name_is_really_gone(self):
        source = simple_pdf(self.root / "이름.pdf", pages=2, author="홍길동")
        out = self.root / "지운.pdf"
        result, names = pdf.scrub_pdf(pdf.open_pdf(source), out)
        self.assertEqual(result.pages, 2)
        self.assertEqual(names, [("만든 사람", "홍길동")])
        self.assertEqual(pdf.scrub_names(pdf.open_pdf(out)), [])
        # 덧붙이는 방식이었다면 옛 이름이 파일에 그대로 남는다
        blob = out.read_bytes().lower()
        self.assertNotIn("홍길동".encode("utf-16-be").hex().encode(), blob)
        self.assertNotIn("홍길동".encode("utf-8"), blob)
        self.assertTrue(source.is_file())            # 원본은 그대로

    def test_other_fields_stay(self):
        source = simple_pdf(self.root / "이름.pdf", pages=1, author="홍길동")
        out = self.root / "지운.pdf"
        pdf.scrub_pdf(pdf.open_pdf(source), out)
        self.assertEqual(pdf.read_info(out).title, "plan")

    def test_xmp_name_is_removed_too(self):
        source = xmp_pdf(self.root / "요즘.pdf", author="김철수")
        doc = pdf.open_pdf(source)
        self.assertIn(("만든 사람(XMP)", "김철수"), pdf.scrub_names(doc))

        out = self.root / "지운.pdf"
        pdf.scrub_pdf(doc, out)
        self.assertEqual(pdf.scrub_names(pdf.open_pdf(out)), [])
        self.assertNotIn("김철수".encode("utf-8"), out.read_bytes())
        # 이름이 아닌 XMP 항목은 남는다
        self.assertIn("보고서".encode("utf-8"), out.read_bytes())

    def test_catalog_extras_are_carried(self):
        source = simple_pdf(self.root / "설정.pdf", pages=1, author="홍길동")
        raw = source.read_bytes().replace(b"/Type/Catalog",
                                          b"/PageMode/UseOutlines/Type/Catalog")
        source.write_bytes(raw)
        out = self.root / "지운.pdf"
        pdf.scrub_pdf(pdf.open_pdf(source), out)
        made = pdf.open_pdf(out)
        root = made.get(made.trailer["Root"])
        self.assertEqual(str(root.get("PageMode")), "UseOutlines")

class StampTest(unittest.TestCase):
    box = [0, 0, 600, 800]

    def test_bottom_center(self):
        body = pdf.stamp_stream("3 / 10", self.box, 0)
        span = pdf.text_width("3 / 10", 9)
        self.assertIn("1 0 0 1", body)
        self.assertIn(f"{(600 - span) / 2:.2f} 12.00 Tm", body)

    def test_bottom_right(self):
        body = pdf.stamp_stream("7", self.box, 0, where="bottom-right", margin=20)
        span = pdf.text_width("7", 9)
        self.assertIn(f"{600 - 20 - span:.2f} 20.00 Tm", body)

    def test_top_right(self):
        body = pdf.stamp_stream("7", self.box, 0, where="top-right", size=10)
        self.assertIn(f"{800 - 12 - 10:.2f} Tm", body)

    def test_turned_page_is_drawn_the_way_it_is_seen(self):
        span = pdf.text_width("7", 9)
        turned = pdf.stamp_stream("7", self.box, 90)
        # 눕힌 쪽은 글자도 눕혀야 보는 사람에게 똑바로 보인다
        self.assertIn("0 1 -1 0", turned)
        self.assertIn(f"588.00 {(800 - span) / 2:.2f} Tm", turned)

        upside = pdf.stamp_stream("7", self.box, 180)
        self.assertIn("-1 0 0 -1", upside)
        self.assertIn(f"{600 - (600 - span) / 2:.2f} 788.00 Tm", upside)

        other = pdf.stamp_stream("7", self.box, 270)
        self.assertIn("0 -1 1 0", other)
        self.assertIn(f"12.00 {800 - (800 - span) / 2:.2f} Tm", other)

    def test_offset_mediabox(self):
        body = pdf.stamp_stream("7", [10, 20, 610, 820], 0, where="bottom-left")
        self.assertIn("22.00 32.00 Tm", body)      # 상자 왼쪽 아래에서 12pt

    def test_hangul_is_refused(self):
        with self.assertRaises(pdf.PdfError) as ctx:
            pdf.stamp_stream("대외비", self.box, 0)
        self.assertIn("한글", str(ctx.exception))

    def test_parentheses_are_escaped(self):
        body = pdf.stamp_stream("(3)", self.box, 0)
        self.assertIn(r"\(3\)", body)

    def test_unknown_place(self):
        with self.assertRaises(pdf.PdfError):
            pdf.stamp_stream("1", self.box, 0, where="middle")


class NumberPagesTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def stamped(self, doc, page):
        blob = doc.get(page.data.get("Contents"))
        self.assertIsInstance(blob, list)
        return pdf.stream_data(doc.get(blob[-1]), doc).decode("latin-1")

    def test_numbers_every_page(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "셋.pdf", pages=3))
        out = self.root / "번호.pdf"
        pdf.join_pdfs([(doc, [1, 2, 3])], out,
                      stamp=pdf.page_stamper("{쪽} / {전체}", 3))
        made = pdf.open_pdf(out)
        self.assertIn("(1 / 3)", self.stamped(made, made.pages()[0]))
        self.assertIn("(3 / 3)", self.stamped(made, made.pages()[2]))

    def test_skip_and_start(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "셋.pdf", pages=3))
        out = self.root / "번호.pdf"
        pdf.join_pdfs([(doc, [1, 2, 3])], out,
                      stamp=pdf.page_stamper("{쪽} / {전체}", 3, skip=1, start=5))
        made = pdf.open_pdf(out)
        first = made.get(made.pages()[0].data.get("Contents"))
        self.assertNotIsInstance(first, list)          # 표지에는 안 찍는다
        self.assertIn("(5 / 2)", self.stamped(made, made.pages()[1]))

    def test_font_is_added_next_to_the_old_ones(self):
        doc = pdf.open_pdf(simple_pdf(self.root / "하나.pdf", pages=1))
        out = self.root / "번호.pdf"
        pdf.join_pdfs([(doc, [1])], out, stamp=pdf.page_stamper("{쪽}", 1))
        made = pdf.open_pdf(out)
        fonts = made.get(made.get(made.pages()[0].data["Resources"])["Font"])
        self.assertIn("F1", fonts)                     # 원래 글꼴은 그대로
        self.assertIn("ATNUM", fonts)

    def test_original_content_is_kept(self):
        source = simple_pdf(self.root / "하나.pdf", pages=1, text="본문")
        doc = pdf.open_pdf(source)
        out = self.root / "번호.pdf"
        pdf.join_pdfs([(doc, [1])], out, stamp=pdf.page_stamper("{쪽}", 1))
        made = pdf.open_pdf(out)
        blob = made.get(made.pages()[0].data["Contents"])
        body = pdf.stream_data(made.get(blob[0]), made)
        self.assertIn("본문1".encode("utf-8"), body)

