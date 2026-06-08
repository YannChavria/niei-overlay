"""Generate self-contained examples (pure Python, no NI, no third-party deps):

  * a synthetic base PNG (no overlay),
  * ``demo_overlay.png`` with one of every supported overlay primitive embedded as niEi,
  * ``demo_overlay.json`` round-tripped from it via the decoder.

Run:  python make_examples.py
"""
import os
import sys
import json
import zlib
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))   # import the modules from the repo root

import niei_overlay as ni
import niei_to_json as nj


def make_base_png(path, w=480, h=320):
    """Write a minimal 8-bit RGB PNG with a light gradient background."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)                         # filter: None
        v = 235 - (y * 45) // h
        row = bytes((v, v, min(v + 10, 255)))
        raw += row * w
    idat = zlib.compress(bytes(raw), 9)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ni.write_chunks(path, [(b"IHDR", ihdr), (b"IDAT", idat), (b"IEND", b"")])


def main():
    base = os.path.join(HERE, "_base.png")
    make_base_png(base)

    elements = [
        ni.rectangle(30, 30, 180, 90, (0, 170, 0)),                       # outline rect
        ni.rectangle(240, 30, 180, 90, (0, 120, 255), filled=True),       # filled rect
        ni.oval(30, 150, 180, 80, (255, 140, 0)),                         # oval
        ni.line((30, 150), (210, 230), (255, 0, 0)),                      # line
        ni.polyline([(245, 165), (300, 150), (335, 215), (415, 175)],     # polyline
                    (150, 0, 255)),
        ni.filled_polygon([(250, 235), (320, 235), (285, 295)],           # filled triangle
                          (0, 190, 190)),
        ni.arc((400, 255), 50, 0, 270, (255, 0, 255)),                    # arc
        ni.point_cross((120, 75), (255, 255, 255)),                       # cross point
        ni.point_pixel((330, 75), (0, 0, 0)),                             # pixel point
        ni.text((30, 305), "niEi overlay demo", (200, 0, 0), size=20),    # plain text
        ni.text((300, 305), "styled", (0, 0, 200), size=20,               # styled text
                bold=True, italic=True),
    ]

    out_png = os.path.join(HERE, "demo_overlay.png")
    ni.write_vision_png(base, out_png, elements)
    os.remove(base)

    out_json = os.path.join(HERE, "demo_overlay.json")
    data = nj.export_overlay(out_png)
    # store a repo-relative image path so the JSON is portable
    data["image"] = "examples/demo_overlay.png"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("wrote", os.path.relpath(out_png), "and", os.path.relpath(out_json))
    print("elements:", len(data["overlay"]))


if __name__ == "__main__":
    main()
