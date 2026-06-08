"""Decode the NI Vision overlay (``niEi`` chunk) of a PNG and export it to JSON.

Pure Python, no NI dependency. Inverse of ``niei_overlay`` (encoder).
See ``docs/niEi_format.md`` for the format specification.

Usage:
    python niei_to_json.py <image.png> [out.json]
"""
import struct
import zlib
import json
import sys

GEOM_TYPE = {0: "line", 1: "rectangle", 2: "oval", 3: "point",
             4: "polygon", 5: "polyline", -2: "arc", -3: "point"}


class _Reader:
    def __init__(self, b, off=0):
        self.b = b
        self.o = off

    def u32(self):
        v = struct.unpack_from("<I", self.b, self.o)[0]; self.o += 4; return v

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.o)[0]; self.o += 4; return v

    def f64(self):
        v = struct.unpack_from("<d", self.b, self.o)[0]; self.o += 8; return v

    def raw(self, n):
        v = self.b[self.o:self.o + n]; self.o += n; return v

    def u8(self):
        v = self.b[self.o]; self.o += 1; return v


def get_niei_payload(png_path):
    """Return the decompressed niEi payload of a PNG, or None if there is no niEi."""
    d = open(png_path, "rb").read()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG: " + png_path
    i = 8
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        if d[i + 4:i + 8] == b"niEi":
            data = d[i + 8:i + 8 + ln]
            assert data[4:10] == b"NIIMAQ", "unexpected niEi chunk"
            payload = zlib.decompress(data[10:])
            assert len(payload) == struct.unpack(">I", data[:4])[0]
            return payload
        i += 12 + ln
    return None


def _rgb(rgba):
    r, g, b, _a = rgba
    return [r, g, b]


_TRAILER_MARK = bytes.fromhex("ffffffff04000000ffffffff")


def _parse_geom(p, o):
    """Try to parse a geometric record (kind=0) at offset o. Returns (element, end) or None."""
    if o + 13 > len(p) or p[o] != 1 or struct.unpack_from("<I", p, o + 1)[0] != 0:
        return None
    gtype = struct.unpack_from("<i", p, o + 5)[0]
    ncoord = struct.unpack_from("<I", p, o + 9)[0]
    if gtype not in GEOM_TYPE or ncoord < 2 or ncoord > 64 or ncoord % 2:
        return None
    base = o + 13
    end = base + 8 * ncoord + 12
    if end > len(p):
        return None
    pts = []
    for k in range(ncoord // 2):
        x = struct.unpack_from("<d", p, base + 16 * k)[0]
        y = struct.unpack_from("<d", p, base + 16 * k + 8)[0]
        if gtype != -2 and not (-100 <= x <= 20000 and -100 <= y <= 20000):
            return None
        pts.append([x, y])
    off = base + 8 * ncoord
    if struct.unpack_from("<I", p, off)[0] != 1:
        return None
    draw = struct.unpack_from("<I", p, off + 4)[0]
    if draw > 1 or p[off + 11] != 0:        # drawFlag sane, colour alpha == 0
        return None
    color = _rgb(p[off + 8:off + 12])
    el = {"type": GEOM_TYPE[gtype], "points": pts, "color": color}
    if gtype in (1, 2, 4):
        el["filled"] = bool(draw)
    if gtype == -3:
        el["symbol"] = "cross"
    if gtype == 3:
        el["symbol"] = "pixel"
    if gtype == -2:
        el["bbox"] = [pts[0], pts[1]]
        el["start_angle"] = pts[2][0] / 1000.0
        el["end_angle"] = pts[2][1] / 1000.0
        del el["points"]
    return el, end


def _parse_text(p, o):
    """Try to parse a text record (kind=1) at offset o. Returns (element, end) or None."""
    if o + 9 > len(p) or p[o] != 1 or struct.unpack_from("<I", p, o + 1)[0] != 1:
        return None
    tlen = struct.unpack_from("<I", p, o + 5)[0]
    if tlen > 4096 or o + 9 + tlen > len(p):
        return None
    txt = p[o + 9:o + 9 + tlen].decode("latin-1")
    if any(ord(c) < 9 for c in txt):
        return None
    r = _Reader(p, o + 9 + tlen)
    try:
        flag = r.u32()                       # rendering flag (0 = .NET API, 1 = VBAI/ProTime)
        flen = r.u32()
        if flen > 256:
            return None
        font = r.raw(flen).decode("latin-1")
        size = r.u32()
        deco = r.u32(); h_align = r.u32(); v_align = r.u32()
        color = _rgb(r.raw(4))
        bg = list(r.raw(4))
        r.f64(); r.f64()
        origin = [r.f64(), r.f64()]
        angle = r.f64()
    except struct.error:
        return None
    el = {"type": "text", "text": txt, "origin": origin,
          "color": color, "font": font, "size": size}
    if flag:
        el["flag"] = flag
    style = {}
    if deco & 0x01: style["bold"] = True
    if deco & 0x02: style["italic"] = True
    if deco & 0x04: style["underline"] = True
    if deco & 0x20: style["strikeout"] = True
    if h_align: style["h_align"] = h_align
    if v_align: style["v_align"] = v_align
    if angle: style["angle"] = angle
    if bg != [0, 0, 0, 1]: style["background"] = bg
    if style:
        el["style"] = style
    return el, r.o


def decode_payload(payload):
    """Decompressed niEi payload -> list of overlay elements (dicts).

    Walks the whole overlay region and extracts every geometric/text record, resyncing
    over unknown record kinds and nested framing (real NI files group records and may
    interleave non-overlay data). Returns [] if no overlay records are found.
    """
    end = payload.rfind(_TRAILER_MARK)
    region = end if end > 60 else len(payload)
    elements = []
    o = 60
    while o < region:
        hit = _parse_geom(payload, o) or _parse_text(payload, o)
        if hit:
            el, nxt = hit
            elements.append(el)
            o = nxt
        else:
            o += 1
    return elements


def export_overlay(png_path):
    payload = get_niei_payload(png_path)
    if payload is None:
        return {"image": png_path, "overlay": []}
    return {"image": png_path, "overlay": decode_payload(payload)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    result = export_overlay(sys.argv[1])
    out = json.dumps(result, indent=2, ensure_ascii=False)
    if len(sys.argv) >= 3:
        open(sys.argv[2], "w", encoding="utf-8").write(out)
        print("wrote", sys.argv[2])
    else:
        print(out)
