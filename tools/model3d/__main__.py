"""The 3D view: the cave in 3D beneath the ground surface.

    python3 -m tools.model3d      # after the main build; writes output/3d/

Reads what Therion has just built: the centreline and stations from
output/Swildons.3d, the passage walls from output/Swildons-walls.lox, passage
names from the plan drawings (via tools.routes.survey and
output/Swildons.sql) and the entrance's lat/long from
output/Swildons-centreline.kml. The ground is the Environment Agency's
1 m LIDAR terrain model, fetched once and kept in surface/lidar/. The
satellite imagery is loaded by the page itself, from Esri.

Writes output/3d/index.html, scene.json and terrain.bin. With CHROMIUM
set to a Chrome or Chromium binary it also saves a preview.png for the
index page.
"""
import argparse
import array
import datetime
import gzip
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zlib

from tools.model3d.formats import read_3d, read_lox_walls, read_tiff

HERE = os.path.dirname(os.path.abspath(__file__))
# Swildons_Centreline.th puts the survey in OSGB:ST, the ST 100 km square
# of the National Grid: add these to get full grid references.
ST = (300000, 100000)
WCS = ('https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs'
       '?service=WCS&version=2.0.1&request=GetCoverage'
       '&coverageId=13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m'
       '&subset=E({e0},{e1})&subset=N({n0},{n1})&format=image/tiff')
UA = 'uk_mendips_swildons-hole 3D view (https://github.com/CaveSurveying/uk_mendips_swildons-hole)'
MARGIN = 250      # metres of ground around the cave
STEP = 2          # metres between terrain samples in the model


# -- the ground -----------------------------------------------------------------------

def lidar(e0, n0, e1, n1, cache='surface/lidar'):
    """Ground heights over a National Grid box, every STEP metres from the
    top-left corner, as a list of rows of metres (None where there is no
    LIDAR). Fetched from the Environment Agency the first time and kept."""
    w, h = (e1 - e0) // STEP, (n1 - n0) // STEP
    f = os.path.join(cache, f'dtm-{e0}-{n0}-{e1}-{n1}-{STEP}m.u16.gz')
    if not os.path.exists(f):
        print(f'fetching LIDAR for {e0},{n0} to {e1},{n1}', file=sys.stderr)
        req = urllib.request.Request(WCS.format(e0=e0, e1=e1, n0=n0, n1=n1), headers={'User-Agent': UA})
        tw, th, v, (x0, y0), px = read_tiff(urllib.request.urlopen(req, timeout=120).read())
        if (tw, th, x0, y0, px) != (e1 - e0, n1 - n0, e0, n1, 1.0):
            raise ValueError(f'unexpected LIDAR grid {tw}x{th} at {x0},{y0} ({px} m)')
        out = array.array('H')
        for j in range(h):
            for i in range(w):
                s = [v[(j * STEP + b) * tw + i * STEP + a] for b in range(STEP) for a in range(STEP)]
                s = [x for x in s if x > -1000]
                out.append(round(sum(s) / len(s) * 100) if s else 0)    # centimetres; 0 = none
        if sys.byteorder != 'little':
            out.byteswap()
        os.makedirs(cache, exist_ok=True)
        with gzip.open(f, 'wb') as g:
            g.write(out.tobytes())
    raw = array.array('H', gzip.open(f).read())
    if sys.byteorder != 'little':
        raw.byteswap()
    return w, h, raw


# -- National Grid to lat/long ----------------------------------------------------------

def grid_to_ll(e, n):
    """OSGB36 National Grid to WGS84 lat/long (degrees), by the Ordnance
    Survey's formulae and a Helmert shift: good to a few metres, and the
    caller corrects what is left with the entrance's OSTN15 position."""
    a, b, f0 = 6377563.396, 6356256.909, 0.9996012717
    lat0, lon0, e0, n0 = math.radians(49), math.radians(-2), 400000, -100000
    e2 = 1 - b * b / (a * a)
    nn = (a - b) / (a + b)
    lat, m = lat0, 0
    while abs(n - n0 - m) >= 1e-5:
        lat += (n - n0 - m) / (a * f0)
        m = b * f0 * ((1 + nn + 1.25 * nn ** 2 + 1.25 * nn ** 3) * (lat - lat0)
                      - (3 * nn + 3 * nn ** 2 + 21 / 8 * nn ** 3) * math.sin(lat - lat0) * math.cos(lat + lat0)
                      + (15 / 8 * nn ** 2 + 15 / 8 * nn ** 3) * math.sin(2 * (lat - lat0)) * math.cos(2 * (lat + lat0))
                      - 35 / 24 * nn ** 3 * math.sin(3 * (lat - lat0)) * math.cos(3 * (lat + lat0)))
    s, c, t = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * f0 / math.sqrt(1 - e2 * s * s)
    rho = a * f0 * (1 - e2) / (1 - e2 * s * s) ** 1.5
    eta2 = nu / rho - 1
    de = e - e0
    lat = (lat - t / (2 * rho * nu) * de ** 2
           + t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2) * de ** 4
           - t / (720 * rho * nu ** 5) * (61 + 90 * t * t + 45 * t ** 4) * de ** 6)
    lon = (lon0 + de / (c * nu)
           - de ** 3 / (6 * c * nu ** 3) * (nu / rho + 2 * t * t)
           + de ** 5 / (120 * c * nu ** 5) * (5 + 28 * t * t + 24 * t ** 4)
           - de ** 7 / (5040 * c * nu ** 7) * (61 + 662 * t * t + 1320 * t ** 4 + 720 * t ** 6))
    # Airy 1830 to GRS80 through Cartesian coordinates
    s, c = math.sin(lat), math.cos(lat)
    nu = a / math.sqrt(1 - e2 * s * s)
    x, y, z = nu * c * math.cos(lon), nu * c * math.sin(lon), nu * (1 - e2) * s
    tx, ty, tz, sc = 446.448, -125.157, 542.060, -20.4894e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421))
    x, y, z = (tx + (1 + sc) * x - rz * y + ry * z,
               ty + rz * x + (1 + sc) * y - rx * z,
               tz - ry * x + rx * y + (1 + sc) * z)
    a2, b2 = 6378137.0, 6356752.3141
    e2 = 1 - b2 * b2 / (a2 * a2)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        lat = math.atan2(z + e2 * a2 / math.sqrt(1 - e2 * math.sin(lat) ** 2) * math.sin(lat), p)
    return math.degrees(lat), math.degrees(math.atan2(y, x))


def mercator(lat, lon):
    """Web Mercator, as a fraction of the world (0..1 across and down)."""
    s = math.sin(math.radians(lat))
    return (lon + 180) / 360, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)


def fit_affine(pairs):
    """Least-squares (u, v) = A (1, x, y) over (x, y) -> (u, v) pairs."""
    m = [[0.0] * 3 for _ in range(3)]
    ru, rv = [0.0] * 3, [0.0] * 3
    for (x, y), (u, v) in pairs:
        r = (1.0, x, y)
        for i in range(3):
            ru[i] += r[i] * u
            rv[i] += r[i] * v
            for j in range(3):
                m[i][j] += r[i] * r[j]

    def solve(rhs):
        a = [row[:] + [rhs[i]] for i, row in enumerate(m)]
        for i in range(3):
            p = max(range(i, 3), key=lambda k: abs(a[k][i]))
            a[i], a[p] = a[p], a[i]
            for k in range(3):
                if k != i:
                    f = a[k][i] / a[i][i]
                    a[k] = [x - f * y for x, y in zip(a[k], a[i])]
        return [a[i][3] / a[i][i] for i in range(3)]
    return solve(ru) + solve(rv)


def kml_entrance(kml='output/Swildons-centreline.kml'):
    if not os.path.exists(kml):
        return None
    t = open(kml, encoding='utf-8').read()
    m = re.search(r'#ThEntranceIcon</styleUrl>.*?<coordinates>\s*([-\d.]+),([-\d.]+)', t, re.S)
    return (float(m.group(2)), float(m.group(1))) if m else None


# -- the scene ------------------------------------------------------------------------

def place_names():
    """Passage names from the plan drawings, each at the height of the
    nearest station, or [] if the database export isn't there."""
    try:
        from tools.routes.survey import Survey
        s = Survey()
        labels = s.load_labels()
    except (OSError, ImportError) as e:
        print(f'no passage names: {e}', file=sys.stderr)
        return []
    # only stations on a leg: Swildons_Centreline.th fixes a fake station,
    # 'bottom', at 140 m beside the entrance to pin the altitude colours
    real = [k for k in s.pos if s.adj.get(k)]
    seen, out = set(), []
    for t, x, y in labels:
        t = re.sub(r'\s*\(.*?\)', '', t).strip()
        if len(t) < 4 or t in seen or re.match(r'^C[\d.]+$', t):
            continue
        k = min(real, key=lambda k: math.hypot(s.pos[k][0] - x, s.pos[k][1] - y))
        if math.hypot(s.pos[k][0] - x, s.pos[k][1] - y) > 20:
            continue
        seen.add(t)
        out.append((t, x, y, s.pos[k][2]))
    return out


def build(out_dir, chromium=None):
    legs, stations = read_3d('output/Swildons.3d')
    lox = 'output/Swildons-walls.lox'     # walls from the drawings only (swildons.thconfig)
    walls = read_lox_walls(lox) if os.path.exists(lox) else []
    cave = [p for a, b, f in legs if not f & 1 for p in (a, b)]
    xs, ys, zs = zip(*cave)

    # the ground: the cave's extent plus a margin, on a 50 m grid
    e0 = int(math.floor((min(xs) + ST[0] - MARGIN) / 50) * 50)
    e1 = int(math.ceil((max(xs) + ST[0] + MARGIN) / 50) * 50)
    n0 = int(math.floor((min(ys) + ST[1] - MARGIN) / 50) * 50)
    n1 = int(math.ceil((max(ys) + ST[1] + MARGIN) / 50) * 50)
    try:
        tw, th, heights = lidar(e0, n0, e1, n1)
    except (OSError, ValueError) as e:
        # an extra, so it shouldn't stop the rest of the site being published
        print(f'::warning::no 3D view: could not get the LIDAR ({e})', file=sys.stderr)
        return
    # the scene's origin: the middle of the ground, in survey coordinates
    ox, oy = (e0 + e1) / 2 - ST[0], (n0 + n1) / 2 - ST[1]

    # georeference for the imagery: survey x, y (from the origin) to Web
    # Mercator, nudged so the entrance lands where Therion (with OSTN15) puts it
    ent = next(((n, p) for n, p, f in stations if f & 4), None)
    shift = (0.0, 0.0)
    ll = kml_entrance()
    if ent and ll:
        mine = grid_to_ll(ent[1][0] + ST[0], ent[1][1] + ST[1])
        shift = (ll[0] - mine[0], ll[1] - mine[1])
    pairs = []
    for i in range(5):
        for j in range(5):
            x, y = e0 + (e1 - e0) * i / 4, n0 + (n1 - n0) * j / 4
            lat, lon = grid_to_ll(x, y)
            pairs.append(((x - ST[0] - ox, y - ST[1] - oy), mercator(lat + shift[0], lon + shift[1])))
    merc = fit_affine(pairs)

    def r(v):
        return round(v, 2)

    def rel(p):
        return [r(p[0] - ox), r(p[1] - oy), r(p[2])]

    kinds = {'legs': [], 'duplicates': [], 'splays': [], 'surface': []}
    for a, b, f in legs:
        k = 'surface' if f & 1 else 'splays' if f & 4 else 'duplicates' if f & 2 else 'legs'
        kinds[k] += rel(a) + rel(b)
    wall_pos, wall_idx = [], []
    for pts, tris in walls:
        base = len(wall_pos) // 3
        for p in pts:
            wall_pos += rel(p)
        for t in tris:
            wall_idx += [base + i for i in t]

    names = [{'t': t, 'p': rel((x, y, z))} for t, x, y, z in place_names()]
    for n, p, f in stations:
        if f & 4:
            names.insert(0, {'t': 'Entrance', 'p': rel(p), 'entrance': True})

    length = sum(math.dist(a, b) for a, b, f in legs if not f & 7)
    hs = [v / 100 for v in heights if v]
    scene = {
        'title': 'Swildons Hole',
        'subtitle': 'Priddy, Mendip',
        'built': datetime.date.today().isoformat(),
        'origin': [ox + ST[0], oy + ST[1]],
        'grid_ref': f'ST {round(ent[1][0]) if ent else ""} {round(ent[1][1]) if ent else ""}',
        'stats': {'length': round(length), 'depth': round(max(zs) - min(zs)),
                  'top': r(max(zs)), 'bottom': r(min(zs))},
        'terrain': {'file': 'terrain.bin', 'w': tw, 'h': th, 'step': STEP,
                    'x0': e0 - ST[0] - ox, 'y0': n1 - ST[1] - oy, 'min': min(hs), 'max': max(hs)},
        'merc': merc,
        'walls': {'pos': wall_pos, 'idx': wall_idx},
        'names': names,
        **kinds,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'scene.json'), 'w') as f:
        json.dump(scene, f, separators=(',', ':'))
    with open(os.path.join(out_dir, 'terrain.bin'), 'wb') as f:
        f.write(heights.tobytes())
    shutil.copy(os.path.join(HERE, 'viewer.html'), os.path.join(out_dir, 'index.html'))
    print(f'3D view written to {out_dir}: {len(legs)} legs, {len(walls)} wall meshes, '
          f'{len(names)} names, ground {tw}x{th} at {STEP} m', file=sys.stderr)
    if chromium:
        preview(chromium, out_dir)


def preview(chromium, out_dir, port=8765, size=(1200, 750)):
    """A still of the view for the index page, by headless Chrome."""
    import functools
    import http.server
    import threading

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', port), functools.partial(Quiet, directory=out_dir))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    png = os.path.abspath(os.path.join(out_dir, 'preview.png'))
    chrome = [chromium, '--headless=new', '--no-sandbox', '--hide-scrollbars', f'--window-size={size[0]},{size[1]}']
    try:
        # Headless Chrome's screenshot is the whole window, which is taller
        # than the page by a toolbar's height: find out by how much, to crop.
        r = subprocess.run(chrome + ['--dump-dom', 'data:text/html,<script>document.write(innerHeight)</script>'],
                           capture_output=True, text=True, timeout=60)
        m = re.search(r'<body>(\d+)', r.stdout)
        # Now and then Chrome takes the shot before three.js has arrived from
        # the CDN, leaving only the loading screen (a small, plain PNG): retry.
        for _ in range(3):
            subprocess.run(chrome + ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist',
                                     '--virtual-time-budget=30000', f'--screenshot={png}',
                                     f'http://127.0.0.1:{port}/index.html?still'],
                           check=True, timeout=180, capture_output=True)
            if os.path.getsize(png) > 300_000:
                break
        else:
            print('the preview only shows the loading screen', file=sys.stderr)
        if m:
            crop_png(png, int(m.group(1)))
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        print(f'no preview: {e}', file=sys.stderr)
    finally:
        srv.shutdown()


def crop_png(path, height):
    """Keep the top rows of an 8-bit PNG. Each row's filter refers only to
    the row above, so the rows can be cut without decoding them."""
    d = open(path, 'rb').read()
    i, chunks = 8, []
    while i < len(d):
        n = struct.unpack('>I', d[i:i + 4])[0]
        chunks.append((d[i + 4:i + 8], d[i + 8:i + 8 + n]))
        i += 12 + n
    ihdr = chunks[0][1]
    w, h, depth, colour = struct.unpack('>IIBB', ihdr[:10])
    if height >= h or depth != 8 or ihdr[12] != 0:
        return
    row = 1 + w * {0: 1, 2: 3, 4: 2, 6: 4}[colour]
    pixels = zlib.decompress(b''.join(c for t, c in chunks if t == b'IDAT'))[:row * height]

    def chunk(t, c):
        return struct.pack('>I', len(c)) + t + c + struct.pack('>I', zlib.crc32(t + c))
    out = d[:8] + chunk(b'IHDR', ihdr[:4] + struct.pack('>I', height) + ihdr[8:])
    out += b''.join(chunk(t, c) for t, c in chunks[1:] if t not in (b'IDAT', b'IEND'))
    out += chunk(b'IDAT', zlib.compress(pixels, 9)) + chunk(b'IEND', b'')
    open(path, 'wb').write(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default='output/3d')
    args = ap.parse_args()
    build(args.out, os.environ.get('CHROMIUM'))


if __name__ == '__main__':
    main()
