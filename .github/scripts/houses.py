"""House-number add-ons from the zoom-15 region maps (plan item 45, run by the house-addons workflow).

    python3 houses.py tiles <in.pmtiles> <out.pmtiles>        keep only the address points of zoom 15
    python3 houses.py catalog <maps.json> <dir> <tag> > new   houseUrl / houseSizeBytes / houseSha256 per region

A Protomaps v4 tile is a protobuf of layers (field 3); the address points are point features (geometry type 1) of the
"buildings" layer, with kind=address. Only that layer is kept and in it only point features; the keys / values tables stay
as they are (indices into them stay valid). Tiles without any address point are dropped. The app overzooms them from 16 on.
"""
import gzip
import hashlib
import json
import sys
from pathlib import Path

from pmtiles.reader import MmapSource, Reader, all_tiles
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

REPO = "ktnik-prog/rutanav-beta"
ZOOM = 15


def varint(b, i):
    r = s = 0
    while True:
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if c < 0x80:
            return r, i
        s += 7


def put_varint(n):
    out = bytearray()
    while True:
        c = n & 0x7F
        n >>= 7
        if n:
            out.append(c | 0x80)
        else:
            out.append(c)
            return bytes(out)


def fields(b):
    """(field number, wire type, raw bytes of the whole field incl. its key, payload for length-delimited)."""
    i = 0
    while i < len(b):
        start = i
        key, i = varint(b, i)
        f, wt = key >> 3, key & 7
        payload = None
        if wt == 0:
            _, i = varint(b, i)
        elif wt == 1:
            i += 8
        elif wt == 2:
            n, i = varint(b, i)
            payload = b[i:i + n]
            i += n
        elif wt == 5:
            i += 4
        else:
            raise ValueError(f"wire type {wt}")
        yield f, wt, b[start:i], payload


def feature_type(feat):
    for f, wt, raw, _ in fields(feat):
        if f == 3 and wt == 0:
            return varint(raw, 1)[0] if raw[0] == 0x18 else None
    return 0


def addresses_only(tile):
    out = bytearray()
    for f, wt, raw, layer in fields(tile):
        if f != 3 or wt != 2:
            continue
        name = None
        for lf, lwt, _, lp in fields(layer):
            if lf == 1 and lwt == 2:
                name = lp.decode()
                break
        if name != "buildings":
            continue
        kept = bytearray()
        points = 0
        for lf, lwt, lraw, lp in fields(layer):
            if lf == 2 and lwt == 2:  # a feature: keep points only
                if feature_type(lp) == 1:
                    kept += lraw
                    points += 1
            else:
                kept += lraw
        if points:
            out += b"\x1a" + put_varint(len(kept)) + kept
    return bytes(out)


def tiles(src, dst):
    with open(src, "rb") as f:
        get = MmapSource(f)
        reader = Reader(get)
        header = reader.header()
        meta = reader.metadata()
        gz = header["tile_compression"] == Compression.GZIP
        kept = []
        total = 0
        for (z, x, y), data in all_tiles(get):
            if z != ZOOM:
                continue
            total += 1
            raw = gzip.decompress(data) if gz else data
            if b"addr_housenumber" not in raw:
                continue
            small = addresses_only(raw)
            if small:
                kept.append((zxy_to_tileid(z, x, y), gzip.compress(small, 9)))
    kept.sort()
    with open(dst, "wb") as out:
        w = Writer(out)
        for tid, data in kept:
            w.write_tile(tid, data)
        h = dict(header)
        h.update(tile_type=TileType.MVT, tile_compression=Compression.GZIP, min_zoom=ZOOM, max_zoom=ZOOM, center_zoom=ZOOM)
        meta = dict(meta) if isinstance(meta, dict) else {}
        meta["vector_layers"] = [{"id": "buildings", "fields": {"kind": "String", "addr_housenumber": "String"},
                                  "minzoom": ZOOM, "maxzoom": ZOOM}]
        meta["description"] = "Ruta house numbers (address points of Protomaps zoom 15)"
        w.finalize(h, meta)
    print(f"{Path(src).name}: z{ZOOM} tiles {total}, with addresses {len(kept)}, {Path(dst).stat().st_size} bytes")


def catalog(catalog_path, houses_dir, tag):
    c = json.loads(Path(catalog_path).read_text())
    for r in c["regions"]:
        f = Path(houses_dir) / f"{r['id']}.pmtiles"
        if not f.exists():
            continue
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        r["houseUrl"] = f"https://github.com/{REPO}/releases/download/{tag}/{f.name}"
        r["houseSizeBytes"] = f.stat().st_size
        r["houseSha256"] = h
    print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "tiles":
        tiles(sys.argv[2], sys.argv[3])
    elif cmd == "catalog":
        catalog(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        sys.exit("usage: houses.py tiles|catalog …")
