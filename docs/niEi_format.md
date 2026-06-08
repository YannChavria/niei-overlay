# The `niEi` PNG chunk — NI Vision overlay format (reverse-engineered)

## Abstract

NI Vision (IMAQ / Vision Development Module) can save an image together with its
*vision information* to a PNG file via `imaqWriteVisionFile`
(LabVIEW: *IMAQ Write Image And Vision Info 2*). The overlay (non-destructive
annotations: lines, shapes, points, text) is stored in a private, ancillary PNG
chunk named **`niEi`** — it is **not** rendered by standard PNG viewers; only NI
tooling re-reads it.

This document describes the binary layout of that chunk, reverse-engineered by
diffing the output of `imaqWriteVisionFile` over single-primitive samples. A pure
Python encoder built from this spec reproduces NI's output **byte-for-byte** (the
decompressed payload is identical) for lines, filled polygons, cross points, text,
and multi-element overlays, and a decoder round-trips all samples losslessly.

> Status: community reverse-engineering, **not** official NI documentation. Verified
> against NI Vision 2018/2020-era output. Field names without a confirmed meaning are
> marked *(inferred)*. Only the primitives in §5 were exercised — **the format is NOT
> fully covered** (see the coverage table).

All integers are **little-endian** unless noted. Coordinates are stored as
**float64 rounded to integers** (NI rasterizes overlays at integer pixel coordinates).

---

## 1. Chunk wrapper

The `niEi` chunk is a standard ancillary PNG chunk (`length | "niEi" | data | CRC32`).
Its `data` field is:

| bytes | field | value |
|------|-------|-------|
| 4 | `u32` big-endian | length of the **decompressed** payload |
| 6 | ASCII | `"NIIMAQ"` |
| … | zlib stream | `zlib.compress(payload)` |

Only the *decompressed* payload must be exact; any valid zlib stream that inflates to
it is accepted (your compressor need not match NI's).

A complete NI vision PNG also contains these companion chunks (constant, reproduce
verbatim), in this order: `IHDR, bKGD, niEi, zTXt("Version"), tEXt("NI Image Type"="4"), … , IDAT, IEND`.

---

## 2. Payload

```
payload = HEADER(60) | b"\x00"*5 | u32(N) | record[0] | … | record[N-1] | TRAILER(28)
```

`N` = number of overlay elements.

### 2.1 Header (60 bytes)

| offset | size | field | value |
|-------:|-----:|-------|-------|
| 0  | 12 | magic | `10 10 06 00 00 00 09 00 04 00 00 00` |
| 12 | 4  | `u32` | `len(payload) - 60` (bytes after header) |
| 16 | 16 | signature | `22 9d c2 83 b0 03 31 4f cc a8 34 99 6c 14 34 99` *(constant)* |
| 32 | 9  | const | `01 00 00 00 01 00 00 00 01` |
| 41 | 4  | `u32` | `N` (element count) |
| 45 | 15 | zero padding | `00 …` |

Right after the header: 5 zero bytes, then `u32(N)` again, then the records.

### 2.2 Trailer (28 bytes) — overlay-group properties *(inferred)*

```
ff ff ff ff 04 00 00 00 ff ff ff ff   00 × 16
```

Emitted **once** after the last record (single default overlay group).

---

## 3. Records

Every record starts with a 1-byte marker `0x01`, then a `u32 kind`:
`0` = geometric shape, `1` = text.

### 3.1 Geometric record (`kind = 0`)

| size | field | notes |
|-----:|-------|-------|
| 1 | `0x01` | marker |
| 4 | `u32 = 0` | kind = geometric |
| 4 | `i32 type` | see type table below |
| 4 | `u32 coordCount` | `= 2 × numPoints` |
| 8·coordCount | `f64[]` | points as interleaved `x, y` (integer-valued) |
| 4 | `u32 = 1` | *(inferred)* |
| 4 | `u32 drawFlag` | `0` = outline, `1` = filled |
| 4 | `R, G, B, A` | colour, one byte each, `A = 0` |

Confirmed `type` codes:

| type | shape | points | notes |
|----:|-------|--------|-------|
| `0`  | line | 2 | |
| `1`  | rectangle | 2 | top-left & bottom-right corners; `drawFlag` = fill |
| `2`  | oval | 2 | bounding-box corners; `drawFlag` = fill |
| `3`  | point | 1 | **Pixel** symbol |
| `4`  | polygon | ≥3 | `drawFlag` 0 = outline, 1 = filled |
| `5`  | polyline | ≥2 | open contour |
| `-2` | arc | 3 | points 1–2 = bounding box, point 3 = `(startAngle×1000, endAngle×1000)` |
| `-3` | point | 1 | **Cross** symbol |

Multiple points from one `AddPoints` call serialize as **N separate point records**.
A `Roi` serializes as the geometric records of the shapes it contains.

### 3.2 Text record (`kind = 1`)

A third kind, `kind = 2`, is a **raster** element (used by `AddBitmap` and by point
symbol `UserDefined`): `marker | u32(2) | f64 originX | f64 originY | u32 width | u32 height
| pixel data…`. It embeds raw pixels and is not detailed here.

### Text record layout (`kind = 1`)

| size | field | notes |
|-----:|-------|-------|
| 1 | `0x01` | marker |
| 4 | `u32 = 1` | kind = text |
| 4 | `u32 textLen` | |
| textLen | bytes | text (ANSI / latin-1) |
| 4 | `u32 flag` | rendering flag: `0` from NI's .NET API, `1` from NI Vision Builder / VBAI. *Hypothesis:* `1` makes the overlay **scale with the image zoom** (so text grows when zoomed in) while `0` keeps a fixed pixel size. Independent of `fontSize` and the scale doubles — preserve it for faithful rendering. |
| 4 | `u32 fontLen` | e.g. 5 |
| fontLen | bytes | font name, e.g. `"Arial"` |
| 4 | `u32 fontSize` | e.g. 28 |
| 4 | `u32 decoration` | bitmask: `0x01` bold, `0x02` italic, `0x04` underline, `0x20` strikeout |
| 4 | `u32 hAlign` | 0 = left, 1 = centre, 2 = right |
| 4 | `u32 vAlign` | 0 = bottom, 1 = top |
| 4 | `R, G, B, A` | text colour |
| 4 | `R, G, B, A` | background colour (default `00 00 00 01` = transparent) |
| 8 | `f64 = 1.0` | scale X *(inferred)* |
| 8 | `f64 = 1.0` | scale Y *(inferred)* |
| 8 | `f64 originX` | |
| 8 | `f64 originY` | |
| 8 | `f64 angle` | rotation in degrees (default 0) |

---

## 4. Colour & coordinate notes

- Serialized overlay colour byte order is **R, G, B, A** with `A = 0` (note: the
  in-memory NI `RGBValue` is B,G,R,A with inverted alpha — the *serialized* form differs).
- Coordinates are `float64` but always integer-valued; NI rounds with banker's rounding.
- No field depends on image size, and there is no checksum/GUID tying the overlay to a
  specific image — the overlay is positionally self-contained.

---

## 5. Coverage — what is (not) mapped

All primitives below were validated **byte-exact** (encoder output == NI's, decoder
round-trips losslessly), except where noted.

| NI `Overlay.Add*` primitive | status | notes |
|---|---|---|
| `AddLine` | ✅ confirmed | `kind=0, type=0` |
| `AddRectangle` | ✅ confirmed | `type=1`, outline & filled |
| `AddOval` | ✅ confirmed | `type=2`, outline & filled |
| `AddPolygon` | ✅ confirmed | `type=4`, outline & filled |
| `AddPolyline` | ✅ confirmed | `type=5` |
| `AddArc` | ✅ confirmed | `type=-2`, angles ×1000 |
| `AddPoint` / `AddPoints` (Cross, Pixel) | ✅ confirmed | `type=-3` Cross, `type=3` Pixel; multi → N records |
| `AddText` | ✅ confirmed | full styling: bold/italic/underline/strikeout, H/V alignment, angle, background |
| `AddRoi` | ✅ confirmed | decomposes into the above geometric records |
| `AddPoint` (UserDefined symbol) | ◑ identified | `kind=2` raster (3×3 pattern), not encoded |
| `AddBitmap` | ◑ identified | `kind=2` raster (origin + W×H + pixels), not encoded |
| `AddMetafile` | ❌ unknown | not investigated (embeds an EMF) |
| **Named overlay groups** | ◑ identified | extended group framing; encoder emits the **default group only** |

Reference implementation covers everything marked ✅. The ◑ items are recognised but
not (yet) serialized by the encoder; contributions welcome.

**Real-world files** are richer than the minimal layout above: the overlay records are
organised into one or more groups and may be interleaved with non-overlay sections
(custom-data records of other `kind` values, calibration, pattern-matching templates),
and the header `u32(N)` counts only the first group — not the total. The decoder therefore
**walks the whole overlay region**, extracting every geometric and text record and
resyncing over unknown record kinds, rather than trusting `N`. Such files decode their full
overlay but will not re-encode byte-for-byte (the extra sections are out of scope).

## 6. Reference implementation

- [`niei_overlay.py`](../niei_overlay.py) — encoder (`line`, `rectangle`, `oval`, `polygon`,
  `polyline`, `arc`, `point_cross`, `point_pixel`, `text`, `write_vision_png`). Validated
  byte-exact vs `imaqWriteVisionFile`.
- [`niei_to_json.py`](../niei_to_json.py) — decoder, exports an image's overlay to JSON.
- [`examples/make_examples.py`](../examples/make_examples.py) — self-contained example generator.

### Minimal example

```python
import niei_overlay as ni
elements = [
    ni.line((100, 100), (200, 200), (255, 0, 0)),
    ni.text((210, 210), "label", (255, 0, 0), size=28),
]
ni.write_vision_png("in.png", "out.png", elements)   # out.png opens in NI overlay tools
```

JSON export:

```bash
python niei_to_json.py image.png overlay.json
```
