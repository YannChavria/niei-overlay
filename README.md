# niEi — NI Vision overlay in PNG (pure-Python read/write)

NI Vision (IMAQ / Vision Development Module) can save an image together with its
*vision information* to a PNG via `imaqWriteVisionFile` (LabVIEW: *IMAQ Write Image And
Vision Info 2*). The non-destructive **overlay** (lines, shapes, points, text) is stored
in a private PNG chunk named **`niEi`** — standard image viewers ignore it; only NI tools
re-read it.

This project documents that chunk's binary format (reverse-engineered) and provides a
small, dependency-free Python library to **write** overlays into a PNG and **read** them
back to JSON — without NI Vision installed.

> Reverse-engineered, **not** official NI documentation. Verified against NI Vision
> 2018/2020-era output; a pure-Python encoder built from the spec reproduces NI's output
> **byte-for-byte** for the supported primitives. See [`docs/niEi_format.md`](docs/niEi_format.md).

## Requirements

Python 3.x, standard library only (`zlib`, `struct`, `json`). No third-party packages, no NI runtime.

## Quick start

```python
import niei_overlay as ni

elements = [
    ni.rectangle(30, 30, 180, 90, (0, 170, 0)),
    ni.line((30, 150), (210, 230), (255, 0, 0)),
    ni.arc((400, 255), 50, 0, 270, (255, 0, 255)),
    ni.text((30, 305), "hello", (200, 0, 0), size=20, bold=True),
]
ni.write_vision_png("in.png", "out.png", elements)   # out.png opens in NI overlay tools
```

Read an image's overlay back to JSON:

```bash
python niei_to_json.py out.png overlay.json
```

```json
{
  "image": "out.png",
  "overlay": [
    { "type": "rectangle", "points": [[30,30],[210,120]], "color": [0,170,0], "filled": false },
    { "type": "line", "points": [[30,150],[210,230]], "color": [255,0,0] },
    { "type": "arc", "color": [255,0,255], "bbox": [[350,205],[450,305]], "start_angle": 0.0, "end_angle": 270.0 },
    { "type": "text", "text": "hello", "origin": [30,305], "color": [200,0,0], "font": "Arial", "size": 20, "style": {"bold": true} }
  ]
}
```

## Examples

```bash
python examples/make_examples.py
```

generates `examples/demo_overlay.png` (every supported primitive embedded as `niEi`) and
`examples/demo_overlay.json`. The base image is synthesized in pure Python, so the example
is fully self-contained.

## API (`niei_overlay`)

| function | overlay element |
|---|---|
| `line(p1, p2, rgb)` | line |
| `rectangle(left, top, w, h, rgb, filled=False)` | rectangle |
| `oval(left, top, w, h, rgb, filled=False)` | ellipse |
| `polygon(points, rgb, filled=False)` / `filled_polygon(points, rgb)` | polygon |
| `polyline(points, rgb)` | open polyline |
| `arc(center, radius, start_angle, end_angle, rgb)` | arc |
| `point_cross(p, rgb)` / `point_pixel(p, rgb)` | point (cross / single pixel) |
| `text(origin, s, rgb, size=28, *, font, bold, italic, underline, strikeout, h_align, v_align, bg, angle)` | text |
| `write_vision_png(in_png, out_png, elements)` | embed overlay into a PNG |

Colours are `(R, G, B)` tuples; coordinates are pixels (rounded to integers, as NI does).

## Coverage

Byte-exact for: line, rectangle, oval, polygon (outline/filled), polyline, arc, points
(cross/pixel), and text with full styling (bold/italic/underline/strikeout, H/V alignment,
rotation, background). `Roi` shapes decode as their geometric records.

Not (yet) supported: raster overlays (`AddBitmap` / user-defined point symbols), named
overlay groups, and metafiles. See the coverage table in the format spec.

## Files

```
niei_overlay.py        encoder (build overlays, write_vision_png)
niei_to_json.py        decoder (PNG -> JSON), runnable as a CLI
docs/niEi_format.md    binary format specification
examples/              self-contained example generator + outputs
```

## License

MIT — see [LICENSE](LICENSE).
