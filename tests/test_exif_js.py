"""Tests for web/static/exif.js (the in-browser EXIF reader), run under Node.

Builds small JPEG / PNG / WebP files with hand-made EXIF (including a GPS block
that must never be read) and checks what exifRead() returns. Skipped when
Node.js is not installed.

Run from the repo root:  .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

_REPO: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXIF_JS: str = os.path.join(_REPO, "web", "static", "exif.js")
_NODE: str | None = shutil.which("node")

# Loads exif.js into a sandbox and prints exifRead() for each file path given.
_HARNESS: str = """
const fs = require("fs");
const vm = require("vm");
const ctx = { TextDecoder, TextEncoder, DataView, Uint8Array, Math, Number, String, Array, Set, Object, JSON };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8") + "\\nthis.exifRead = exifRead; this.exifLabel = exifLabel;", ctx);
(async () => {
  const out = {};
  for (const path of process.argv.slice(3)) {
    const bytes = fs.readFileSync(path);
    const file = { arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) };
    out[path] = await ctx.exifRead(file);
  }
  out.labels = ["FocalLengthIn35mmFilm", "DateTimeOriginal", "ISO", "XResolution", "File name"].map(ctx.exifLabel);
  console.log(JSON.stringify(out));
})();
"""


def _tiff(little: bool, user_comment: bytes = b"ASCII\0\0\0Hello mesh") -> bytes:
    """A TIFF/EXIF block: IFD0 → Exif IFD and GPS IFD."""
    e: str = "<" if little else ">"
    # (tag, type, count, raw value bytes)
    def ascii_(s: str) -> bytes:
        return s.encode() + b"\0"

    def rational(*pairs: tuple[int, int]) -> bytes:
        return b"".join(struct.pack(e + "II", n, d) for n, d in pairs)

    def srational(n: int, d: int) -> bytes:
        return struct.pack(e + "ii", n, d)

    def short(v: int) -> bytes:
        return struct.pack(e + "H", v)

    ifd0 = [
        (0x010F, 2, ascii_("Canon")),
        (0x0110, 2, ascii_("EOS R6")),
        (0x0112, 3, short(6)),
        (0x0131, 2, ascii_("Firmware 1.8")),
        (0x0132, 2, ascii_("2026:11:26 10:15:30")),
        (0x0201, 4, struct.pack(e + "I", 978)),  # thumbnail offset: skipped
    ]
    exif = [
        (0x829A, 5, rational((1, 250))),
        (0x829D, 5, rational((28, 10))),
        (0x8827, 3, short(400)),
        (0x9000, 7, b"0232"),
        (0x9003, 2, ascii_("2026:11:26 10:15:30")),
        (0x9201, 10, srational(8, 1)),
        (0x9204, 10, srational(-2, 3)),
        (0x9209, 3, short(0x19)),
        (0x920A, 5, rational((50, 1))),
        (0x927C, 7, b"\x01" * 40),  # MakerNote: skipped
        (0xA000, 2, ascii_("0100")),  # some phones write versions as text
        (0xA405, 3, short(75)),
        (0xA432, 5, rational((24, 1), (70, 1), (28, 10), (4, 1))),
        (0xA434, 2, ascii_("RF24-70mm F2.8 L IS USM")),
        (0x9286, 7, user_comment),
    ]
    gps = [
        (0x0001, 2, ascii_("N")),
        (0x0002, 5, rational((39, 1), (45, 1), (0, 1))),
    ]
    header: bytes = (b"II" if little else b"MM") + struct.pack(e + "HI", 42, 8)
    # Layout: header | IFD0 | Exif IFD | GPS IFD | data area
    sizes = [2 + 12 * (len(ifd) + extra) + 4 for ifd, extra in ((ifd0, 2), (exif, 0), (gps, 0))]
    ifd0_off: int = 8
    exif_off: int = ifd0_off + sizes[0]
    gps_off: int = exif_off + sizes[1]
    data_off: int = gps_off + sizes[2]
    data = bytearray()
    type_size = {2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 10: 8}

    def build(entries: list, pointers: list) -> bytes:
        nonlocal data
        out = bytearray(struct.pack(e + "H", len(entries) + len(pointers)))
        for tag, typ, raw in sorted(entries + pointers):
            count: int = len(raw) // type_size[typ]
            if len(raw) <= 4:
                value: bytes = raw.ljust(4, b"\0")
            else:
                value = struct.pack(e + "I", data_off + len(data))
                data += raw
                if len(data) % 2:
                    data += b"\0"
            out += struct.pack(e + "HHI", tag, typ, count) + value
        return bytes(out + struct.pack(e + "I", 0))

    long_ = lambda v: struct.pack(e + "I", v)  # noqa: E731
    body: bytes = build(ifd0, [(0x8769, 4, long_(exif_off)), (0x8825, 4, long_(gps_off))])
    body += build(exif, [])
    body += build(gps, [])
    return header + body + bytes(data)


def _jpeg(tiff: bytes) -> bytes:
    app1: bytes = b"Exif\0\0" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xda\x00\x02" + b"\x00" * 8 + b"\xff\xd9"


def _png(tiff: bytes, after_idat: bool = False) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    ihdr: bytes = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat: bytes = chunk(b"IDAT", zlib.compress(b"\0\0\0\0"))
    exif: bytes = chunk(b"eXIf", tiff)
    middle: bytes = idat + exif if after_idat else exif + idat
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + middle + chunk(b"IEND", b"")


def _webp(tiff: bytes) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return kind + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"")

    body: bytes = b"WEBP" + chunk(b"VP8X", b"\x08" + b"\0" * 9) + chunk(b"EXIF", b"Exif\0\0" + tiff)
    return b"RIFF" + struct.pack("<I", len(body)) + body


@unittest.skipIf(_NODE is None, "Node.js is not installed")
class ExifJsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir: str = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def _run(self, files: dict[str, bytes]) -> dict:
        paths: list[str] = []
        for name, data in files.items():
            path: str = os.path.join(self.dir, name)
            with open(path, "wb") as f:
                f.write(data)
            paths.append(path)
        harness: str = os.path.join(self.dir, "harness.js")
        with open(harness, "w", encoding="utf-8") as f:
            f.write(_HARNESS)
        out = subprocess.run([str(_NODE), harness, _EXIF_JS, *paths], capture_output=True, text=True, timeout=30, check=True)
        result: dict = json.loads(out.stdout)
        return {os.path.basename(k): v for k, v in result.items()}

    def test_reads_exif_from_every_format_without_gps(self) -> None:
        files: dict[str, bytes] = {
            "le.jpg": _jpeg(_tiff(True)),
            "be.jpg": _jpeg(_tiff(False)),
            "p.png": _png(_tiff(True)),
            "w.webp": _webp(_tiff(False)),
        }
        result: dict = self._run(files)
        expected: dict = {
            "Make": "Canon",
            "Model": "EOS R6",
            "Orientation": "Rotated 90° CW",
            "Software": "Firmware 1.8",
            "DateTime": "2026-11-26 10:15:30",
            "ExposureTime": "1/250 s",
            "FNumber": "f/2.8",
            "ISO": "400",
            "ExifVersion": "2.32",
            "DateTimeOriginal": "2026-11-26 10:15:30",
            "ShutterSpeedValue": "8 APEX (1/256 s)",
            "ExposureBiasValue": "-0.67 EV",
            "FlashpixVersion": "1.00",
            "Flash": "Fired, auto",
            "FocalLength": "50 mm",
            "FocalLengthIn35mmFilm": "75 mm",
            "LensSpecification": "24–70 mm f/2.8–4",
            "LensModel": "RF24-70mm F2.8 L IS USM",
            "UserComment": "Hello mesh",
        }
        for name in files:
            self.assertEqual(result[name], expected, name)
            self.assertFalse(any(k.lower().startswith("gps") or "0x000" in k for k in result[name]), name)
        self.assertEqual(result["labels"], ["Focal length in 35mm film", "Date time original", "ISO", "X resolution", "File name"])

    def test_png_exif_after_image_data(self) -> None:
        result: dict = self._run({"late.png": _png(_tiff(True), after_idat=True)})
        self.assertEqual(result["late.png"]["Model"], "EOS R6")

    def test_unicode_user_comment_byte_order(self) -> None:
        text: str = "Héllo mesh"
        result: dict = self._run({
            "le.jpg": _jpeg(_tiff(True, b"UNICODE\0" + text.encode("utf-16-le"))),
            "be.jpg": _jpeg(_tiff(False, b"UNICODE\0" + text.encode("utf-16-be"))),
            "bom_be_in_le.jpg": _jpeg(_tiff(True, b"UNICODE\0" + b"\xfe\xff" + text.encode("utf-16-be"))),
            "bom_le_in_be.jpg": _jpeg(_tiff(False, b"UNICODE\0" + b"\xff\xfe" + text.encode("utf-16-le"))),
        })
        for name in ("le.jpg", "be.jpg", "bom_be_in_le.jpg", "bom_le_in_be.jpg"):
            self.assertEqual(result[name]["UserComment"], text, name)

    def test_files_without_exif_or_garbage(self) -> None:
        truncated: bytes = _jpeg(_tiff(True))[:60]
        result: dict = self._run({
            "none.jpg": b"\xff\xd8\xff\xdb\x00\x04\x00\x00\xff\xd9",
            "text.txt": b"hello",
            "cut.jpg": truncated,
            "empty.png": _png(b""),
        })
        self.assertEqual(result["none.jpg"], {})
        self.assertEqual(result["text.txt"], {})
        self.assertIsInstance(result["cut.jpg"], dict)
        self.assertEqual(result["empty.png"], {})


if __name__ == "__main__":
    unittest.main()
