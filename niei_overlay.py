"""Pure-Python encoder for NI Vision overlays embedded in a PNG (the ``niEi`` chunk).

No NI dependency. Reproduces, byte-for-byte, the overlay payload written by NI Vision's
``imaqWriteVisionFile`` (LabVIEW: *IMAQ Write Image And Vision Info 2*). See
``docs/niEi_format.md`` for the format specification.

    niEi = u32_BE(decompressed_len) + b"NIIMAQ" + zlib(payload)
    payload = HEADER(60) + b"\\x00"*5 + u32(N) + records... + TRAILER(28)

All integers are little-endian. Colours are stored as R,G,B,A (A=0). Coordinates are
float64 rounded to integers (NI rasterizes overlays at integer pixel coordinates).
"""
import struct
import zlib

# ---- constants extracted verbatim from NI output ----
_HDR_PREFIX = bytes.fromhex("101006000000090004000000")          # [0:12]
_SIG        = bytes.fromhex("229dc283b003314fcca834996c143499")    # [16:32]
_HDR_MID    = bytes.fromhex("010000000100000001")                  # [32:41]
TRAILER     = bytes.fromhex("ffffffff04000000ffffffff") + b"\x00" * 16  # 28 bytes

# companion PNG chunks NI adds (verbatim)
BKGD_DATA    = bytes.fromhex("000000000000")
ZTXT_VERSION = bytes.fromhex(
    "56657273696f6e0000785ef34b2cc9cccf4bcc51f0cc2b2e292acd4dcd2b29"
    "56f0f4750c5408cb2c06ca2858e899e919000012790cfd")
TEXT_NI_TYPE = b"NI Image Type\x004"

# geometric type codes (i32)
T_LINE        = 0
T_RECT        = 1
T_OVAL        = 2
T_POINT_PIXEL = 3
T_POLYGON     = 4     # drawFlag 0 = outline, 1 = filled
T_POLYLINE    = 5     # open contour
T_ARC         = -2
T_POINT_CROSS = -3

# text decoration bitmask (@17)
DECO_BOLD, DECO_ITALIC, DECO_UNDERLINE, DECO_STRIKEOUT = 0x01, 0x02, 0x04, 0x20


def _color(rgb):
    r, g, b = rgb
    return bytes((r & 255, g & 255, b & 255, 0))


def _coord(v):
    return struct.pack("<d", float(round(v)))


# ---------------- element / record builders ----------------
def geom_record(gtype, points, rgb, draw_flag):
    out = b"\x01" + struct.pack("<I", 0) + struct.pack("<i", gtype)
    out += struct.pack("<I", len(points) * 2)
    for x, y in points:
        out += _coord(x) + _coord(y)
    out += struct.pack("<I", 1) + struct.pack("<I", draw_flag) + _color(rgb)
    return out


def line(p1, p2, rgb):
    return geom_record(T_LINE, [p1, p2], rgb, 0)


def polygon(points, rgb, filled=False):
    return geom_record(T_POLYGON, points, rgb, 1 if filled else 0)


def filled_polygon(points, rgb):
    return polygon(points, rgb, filled=True)


def polyline(points, rgb):
    """Open contour (not closed)."""
    return geom_record(T_POLYLINE, points, rgb, 0)


def rectangle(left, top, width, height, rgb, filled=False):
    """Stored as two corners: (left, top) and (left+width, top+height)."""
    return geom_record(T_RECT, [(left, top), (left + width, top + height)],
                       rgb, 1 if filled else 0)


def oval(left, top, width, height, rgb, filled=False):
    """Stored as the two corners of its bounding box (like a rectangle)."""
    return geom_record(T_OVAL, [(left, top), (left + width, top + height)],
                       rgb, 1 if filled else 0)


def arc(center, radius, start_angle, end_angle, rgb):
    """Bounding box (2 corners) + (start, end) angles stored x1000."""
    cx, cy = center
    return geom_record(T_ARC, [(cx - radius, cy - radius), (cx + radius, cy + radius),
                               (start_angle * 1000.0, end_angle * 1000.0)], rgb, 0)


def point_cross(p, rgb):
    return geom_record(T_POINT_CROSS, [p], rgb, 0)


def point_pixel(p, rgb):
    return geom_record(T_POINT_PIXEL, [p], rgb, 0)


def text(origin, s, rgb, size=28, *, font="Arial", flag=0,
         bold=False, italic=False, underline=False, strikeout=False,
         h_align=0, v_align=0, bg=b"\x00\x00\x00\x01", angle=0.0):
    """Overlay text.

    h_align: 0 left, 1 centre, 2 right. v_align: 0 bottom, 1 top.
    bg: 4-byte R,G,B,A background colour (default = transparent). angle: degrees.
    flag: rendering flag stored right after the string (NI's .NET API writes 0;
    NI Vision Builder / ProTime writes 1). Hypothesis: 1 = overlay scales with the image
    zoom (text grows when zoomed in), 0 = fixed pixel size. Preserve it for faithful rendering.
    """
    deco = ((DECO_BOLD if bold else 0) | (DECO_ITALIC if italic else 0)
            | (DECO_UNDERLINE if underline else 0) | (DECO_STRIKEOUT if strikeout else 0))
    sb = s.encode("latin-1", "replace")
    fb = font.encode("latin-1", "replace")
    out = b"\x01" + struct.pack("<I", 1) + struct.pack("<I", len(sb)) + sb
    out += struct.pack("<I", flag)                    # rendering flag (0 = .NET API, 1 = VBAI/ProTime)
    out += struct.pack("<I", len(fb)) + fb            # font name
    out += struct.pack("<I", size)                    # font size
    out += struct.pack("<I", deco)                    # @17 decoration bitmask
    out += struct.pack("<I", h_align)                 # @21 horizontal alignment
    out += struct.pack("<I", v_align)                 # @25 vertical alignment
    out += _color(rgb)                                # @29 text colour
    out += bytes(bg)                                  # @33 background colour (RGBA)
    out += struct.pack("<d", 1.0) + struct.pack("<d", 1.0)   # @37/@45 scale
    out += _coord(origin[0]) + _coord(origin[1])      # @53/@61 origin
    out += struct.pack("<d", float(angle))            # @69 angle (degrees)
    return out


# ---------------- payload / chunk assembly ----------------
def build_payload(records):
    body = b"\x00" * 5 + struct.pack("<I", len(records)) + b"".join(records) + TRAILER
    header = (_HDR_PREFIX + struct.pack("<I", len(body))
              + _SIG + _HDR_MID + struct.pack("<I", len(records)) + b"\x00" * 15)
    return header + body


def build_niei_chunk_data(payload):
    return struct.pack(">I", len(payload)) + b"NIIMAQ" + zlib.compress(payload)


# ---------------- PNG chunk I/O ----------------
def read_chunks(path):
    d = open(path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG: " + path
    i, out = 8, []
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        out.append((d[i + 4:i + 8], d[i + 8:i + 8 + ln]))
        i += 12 + ln
    return out


def _chunk_bytes(typ, data):
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def write_chunks(path, chunks):
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        for typ, data in chunks:
            f.write(_chunk_bytes(typ, data))


def write_vision_png(in_png, out_png, elements):
    """Read ``in_png``, embed the overlay built from ``elements`` (a list of records
    produced by line()/rectangle()/.../text()) into a fresh ``niEi`` chunk, and write
    ``out_png``. Image pixels and existing metadata are preserved; any pre-existing
    ``niEi`` is replaced. Chunk order: IHDR, bKGD, niEi, zTXt(Version), tEXt, ..., IDAT, IEND.
    """
    src = [(t, d) for t, d in read_chunks(in_png) if t != b"niEi"]
    have = {t for t, _ in src}
    niei = build_niei_chunk_data(build_payload(elements))

    final = []
    for typ, data in src:
        final.append((typ, data))
        if typ == b"IHDR" and b"bKGD" not in have:
            final.append((b"bKGD", BKGD_DATA))
        anchor = b"bKGD" if b"bKGD" in have else b"IHDR"
        if typ == anchor:
            final.append((b"niEi", niei))
            if not any(t == b"zTXt" and d.startswith(b"Version\x00") for t, d in src):
                final.append((b"zTXt", ZTXT_VERSION))
            if not any(t == b"tEXt" and d.startswith(b"NI Image Type\x00") for t, d in src):
                final.append((b"tEXt", TEXT_NI_TYPE))
    write_chunks(out_png, final)
