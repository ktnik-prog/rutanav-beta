"""Re-cuts the offline maps from a Protomaps daily build and updates the catalog (run by the recut-maps workflow).

    python3 recut.py outlines <maps.json> <dir>          region outlines (buffered ~1 km) as <dir>/<id>.geojson
    python3 recut.py catalog <maps.json> <dir> <tag> <version> > new-maps.json

The outlines come from the live catalog (simplified ~500 m): pushed out by ~1 km so no border strip is lost; neighbours
overlap a little, as before. The catalog keeps everything (graphs, search, landmarks, speech models); only each region's
map url, size and sha256 and the catalog version change.
"""
import hashlib
import json
import math
import sys
from pathlib import Path

BUFFER_DEG = 0.01
REPO = "ktnik-prog/rutanav-beta"


def signed_area(ring):
    return sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(len(ring) - 1)) / 2


def buffered(ring, d):
    """Each vertex pushed outward along the bisector of its edges' normals (miter, capped at 3×)."""
    closed = ring[0] == ring[-1]
    pts = ring[:-1] if closed else ring[:]
    n = len(pts)
    if n < 3:
        return ring
    outward = 1.0 if signed_area(pts + [pts[0]]) > 0 else -1.0  # counter-clockwise: (dy, -dx) points outward (right of travel)
    out = []
    for i in range(n):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[(i + 1) % n]
        k = 1 / max(math.cos(math.radians(y1)), 0.2)  # degrees of longitude are shorter
        def normal(ax, ay, bx, by):
            dx, dy = (bx - ax) / k, by - ay
            L = math.hypot(dx, dy) or 1e-12
            return dy / L * outward, -dx / L * outward
        nx1, ny1 = normal(x0, y0, x1, y1)
        nx2, ny2 = normal(x1, y1, x2, y2)
        bx, by = nx1 + nx2, ny1 + ny2
        bl = math.hypot(bx, by)
        if bl < 1e-9:
            bx, by, scale = nx1, ny1, 1.0
        else:
            bx, by = bx / bl, by / bl
            scale = min(1 / max(bx * nx1 + by * ny1, 1e-9), 3.0)
        out.append([round(x1 + bx * d * scale * k, 6), round(y1 + by * d * scale, 6)])
    return out + [out[0]]


def outlines(catalog_path, out_dir):
    c = json.loads(Path(catalog_path).read_text())
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for r in c["regions"]:
        if r.get("covers"):
            continue
        polys = [[buffered(ring, BUFFER_DEG) if i == 0 else ring for i, ring in enumerate(poly)] for poly in r["polygons"]]
        (out / f"{r['id']}.geojson").write_text(json.dumps(
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": polys}}))
        print(r["id"])


def catalog(catalog_path, maps_dir, tag, version):
    c = json.loads(Path(catalog_path).read_text())
    for r in c["regions"]:
        f = Path(maps_dir) / f"{r['id']}.pmtiles"
        if not f.exists():
            continue
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        r["url"] = f"https://github.com/{REPO}/releases/download/{tag}/{f.name}"
        r["sizeBytes"] = f.stat().st_size
        r["sha256"] = h.hexdigest()
    c["version"] = version
    print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "outlines":
        outlines(sys.argv[2], sys.argv[3])
    elif cmd == "catalog":
        catalog(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    else:
        sys.exit("usage: recut.py outlines|catalog …")
