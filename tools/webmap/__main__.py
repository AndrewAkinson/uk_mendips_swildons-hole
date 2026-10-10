"""The survey as GeoJSON, and a 2D map of it over the ground.

    python3 -m tools.webmap      # after the main build and tools.model3d

Reads Therion's shapefile exports (swildons.thconfig writes them to
output/esri-plan and output/esri-model), which are in OS grid metres,
and writes them as lat/long GeoJSON:

- output/Swildons-map.geojson: the drawing. Passage outlines (polygons,
  with each scrap's altitude), areas such as water and clay, the drawn
  lines (walls, borders, floor steps, ...) and points (labels, water
  flow, gradients, formations).
- output/Swildons-centreline.geojson: every survey leg (3D lines,
  with Stanton's legs, duplicates and splays marked) and station (3D
  points, with the rock above each where there is LIDAR).

and the map page, output/map/: index.html (MapLibre GL JS), a hillshade
and contours made from the LIDAR ground that tools.model3d has just
saved in output/3d/, and map.json, which ties them together.
"""
import argparse
import base64
import datetime
import json
import math
import os
import re
import shutil
import struct
import sys
import zlib
from collections import defaultdict

from tools.model3d.__main__ import ST, fit_affine, grid_to_ll, kml_entrance
from tools.webmap.shapefile import read

HERE = os.path.dirname(os.path.abspath(__file__))

# Point symbols whose orientation means something even when it is 0 (north)
ORIENTED = {'water-flow', 'gradient', 'air-draught'}

# Survey names as written, made readable where splitting the CamelCase isn't enough
SURVEY_NAMES = {
    'Old40to20': 'Old 40 to the 20 ft Pot',
    '20ftToBarnesLoop': '20 ft Pot to Barnes Loop',
    'DblPotsDownstream': 'Double Pots downstream',
    'Old40Route': 'The Old 40 route',
    'BarnesLoopToTratmans': "Barnes Loop to Tratman's Temple",
    'TratmansToSump1': "Tratman's Temple to Sump 1",
    'KenneysDigToShowerbath': "Kenney's Dig to Showerbath",
}


def survey_of(full):
    """'WetWayOxbows.Swildons.SwildonsHole' -> ('WetWayOxbows', False);
    Stanton's surveys sit under wstanton."""
    parts = full.split('.')
    return parts[0], 'wstanton' in parts


def survey_title(s):
    if s in SURVEY_NAMES:
        return SURVEY_NAMES[s]
    if re.match(r'^swil', s):
        return f"Stanton's survey ({s})"
    t = re.sub(r'(?<=[a-z])(?=[A-Z0-9])|(?<=[0-9])(?=[A-Z])', ' ', s)
    return t[0] + t[1:].replace(' To ', ' to ')


def clean_text(t):
    """Therion label markup to plain text, keeping line breaks."""
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]*>', '', t)
    return '\n'.join(s.strip() for s in t.split('\n') if s.strip())


# -- georeferencing -------------------------------------------------------------------

class Georef:
    """Survey x, y (metres in OS square ST, as Therion writes them) to
    lon, lat. The OS formulae and a Helmert shift (tools.model3d), moved so
    the entrance lands where Therion puts it with OSTN15, then fitted by
    an affine transform over the cave: the shift barely changes across a
    kilometre, so this is good to well under a centimetre."""

    def __init__(self, entrance, box):
        shift = (0.0, 0.0)
        ll = kml_entrance()
        if ll:
            mine = grid_to_ll(entrance[0] + ST[0], entrance[1] + ST[1])
            shift = (ll[0] - mine[0], ll[1] - mine[1])
        else:
            print('::warning::no OSTN15 entrance position in output/Swildons-centreline.kml; '
                  'the map may be a few metres out', file=sys.stderr)
        x0, y0, x1, y1 = box
        pairs = []
        for i in range(5):
            for j in range(5):
                x, y = x0 + (x1 - x0) * i / 4, y0 + (y1 - y0) * j / 4
                lat, lon = grid_to_ll(x + ST[0], y + ST[1])
                pairs.append(((x, y), (lon + shift[1], lat + shift[0])))
        self.a = fit_affine(pairs)

    def __call__(self, p):
        a = self.a
        x, y = p[0], p[1]
        ll = [round(a[0] + a[1] * x + a[2] * y, 7), round(a[3] + a[4] * x + a[5] * y, 7)]
        return ll + [round(p[2], 2)] if len(p) > 2 else ll


# -- the ground -----------------------------------------------------------------------

class Ground:
    """The LIDAR heights tools.model3d saved (output/3d), in survey x, y."""

    def __init__(self, d='output/3d'):
        scene = json.load(open(os.path.join(d, 'scene.json')))
        t = scene['terrain']
        self.w, self.h, self.step = t['w'], t['h'], t['step']
        self.x0 = scene['origin'][0] + t['x0'] - ST[0]       # west edge
        self.y1 = scene['origin'][1] + t['y0'] - ST[1]       # north edge
        raw = open(os.path.join(d, t['file']), 'rb').read()
        v = struct.unpack(f'<{self.w * self.h}H', raw)
        self.v = [x / 100 if x else None for x in v]         # row 0 is the north edge

    @property
    def box(self):
        return (self.x0, self.y1 - self.h * self.step, self.x0 + self.w * self.step, self.y1)

    def at(self, x, y):
        """Bilinear height at survey x, y, or None."""
        fi = (x - self.x0) / self.step - 0.5
        fj = (self.y1 - y) / self.step - 0.5
        i, j = math.floor(fi), math.floor(fj)
        if not (0 <= i < self.w - 1 and 0 <= j < self.h - 1):
            return None
        q = [self.v[(j + b) * self.w + i + a] for b in (0, 1) for a in (0, 1)]
        if None in q:
            return None
        u, t = fi - i, fj - j
        return (q[0] * (1 - u) + q[1] * u) * (1 - t) + (q[2] * (1 - u) + q[3] * u) * t

    def smoothed(self):
        """3 x 3 mean, for contours that don't follow every bump."""
        w, h, v, out = self.w, self.h, self.v, []
        for j in range(h):
            for i in range(w):
                s = [v[b * w + a] for b in range(max(0, j - 1), min(h, j + 2))
                     for a in range(max(0, i - 1), min(w, i + 2)) if v[b * w + a] is not None]
                out.append(sum(s) / len(s) if v[j * w + i] is not None and s else None)
        return out

    def hillshade_png(self, path, azimuth=315, altitude=40, zfactor=2.0):
        """A shaded-relief overlay: transparent where the ground is level,
        darker on slopes facing away from the light, lighter facing it."""
        w, h, v, s = self.w, self.h, self.v, self.step
        az, alt = math.radians(360 - azimuth + 90), math.radians(altitude)
        flat = math.sin(alt)
        rows = []
        for j in range(h):
            row = bytearray([0])
            for i in range(w):
                c = v[j * w + i]

                def g(a, b):
                    a, b = min(max(a, 0), w - 1), min(max(b, 0), h - 1)
                    x = v[b * w + a]
                    return c if x is None else x
                if c is None:
                    row += b'\0\0\0\0'
                    continue
                dzdx = (g(i + 1, j) - g(i - 1, j)) / (2 * s) * zfactor
                dzdy = (g(i, j - 1) - g(i, j + 1)) / (2 * s) * zfactor     # north is up
                slope = math.atan(math.hypot(dzdx, dzdy))
                aspect = math.atan2(dzdy, -dzdx)
                shade = (math.sin(alt) * math.cos(slope)
                         + math.cos(alt) * math.sin(slope) * math.cos(az - aspect))
                d = shade - flat
                if d < 0:
                    row += bytes([20, 24, 32, min(255, round(-d * 520))])
                else:
                    row += bytes([255, 252, 240, min(255, round(d * 300))])
            rows.append(bytes(row))

        def chunk(kind, data):
            return (struct.pack('>I', len(data)) + kind + data
                    + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff))
        with open(path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>2I5B', w, h, 8, 6, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(b''.join(rows), 9)) + chunk(b'IEND', b''))

    def contours(self, interval=1.0):
        """Marching squares over the smoothed heights: {level: [[(x, y), ...], ...]}."""
        w, h, step, v = self.w, self.h, self.step, self.smoothed()
        # a crossing is named by the grid edge it lies on: ('h', i, j) runs
        # from sample (i, j) to (i + 1, j), ('v', i, j) from (i, j) to (i, j + 1)
        segs = defaultdict(list)

        def cut(L, e):
            k, i, j = e
            a = v[j * w + i]
            b = v[j * w + i + 1] if k == 'h' else v[(j + 1) * w + i]
            t = (L - a) / (b - a)
            return (i + t, j) if k == 'h' else (i, j + t)
        for j in range(h - 1):
            for i in range(w - 1):
                a, b, c, d = v[j * w + i], v[j * w + i + 1], v[(j + 1) * w + i + 1], v[(j + 1) * w + i]
                if None in (a, b, c, d):
                    continue
                lo, hi = min(a, b, c, d), max(a, b, c, d)
                L = math.ceil(lo / interval) * interval
                while L < hi:
                    top, right, bottom, left = ('h', i, j), ('v', i + 1, j), ('h', i, j + 1), ('v', i, j)
                    m = (a > L) << 3 | (b > L) << 2 | (c > L) << 1 | (d > L)
                    if m > 7:
                        m ^= 15
                    pairs = {1: [(left, bottom)], 2: [(bottom, right)], 3: [(left, right)],
                             4: [(top, right)], 6: [(top, bottom)], 7: [(top, left)]}.get(m)
                    if m == 5:      # saddles: decide by the middle
                        mid = (a + b + c + d) / 4 > L
                        hi_ac = a > L
                        pairs = ([(top, right), (left, bottom)] if mid != hi_ac
                                 else [(top, left), (bottom, right)])
                    for e1, e2 in pairs or []:
                        segs[L].append((e1, e2))
                    L += interval
        out = {}
        for L, ss in segs.items():
            nbr = defaultdict(list)
            for e1, e2 in ss:
                nbr[e1].append(e2)
                nbr[e2].append(e1)
            seen, lines = set(), []
            starts = [e for e, n in nbr.items() if len(n) == 1] + list(nbr)
            for s0 in starts:
                if s0 in seen:
                    continue
                line, cur, prev = [s0], s0, None
                seen.add(s0)
                while True:
                    nxt = [n for n in nbr[cur] if n != prev and n not in seen]
                    if not nxt:
                        if line[0] in nbr[cur] and len(line) > 2:
                            line.append(line[0])     # closed ring
                        break
                    prev, cur = cur, nxt[0]
                    seen.add(cur)
                    line.append(cur)
                if len(line) > 3:
                    pts = [cut(L, e) for e in line]
                    pts = [(self.x0 + (i + 0.5) * step, self.y1 - (j + 0.5) * step) for i, j in pts]
                    lines.append(simplify(pts, 0.4))
            out[L] = lines
        return out


def simplify(pts, tol):
    """Douglas-Peucker, keeping the ends."""
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy)
    best, k = -1, 0
    for i in range(1, len(pts) - 1):
        x, y = pts[i]
        d = abs(dy * (x - x1) - dx * (y - y1)) / n if n else math.hypot(x - x1, y - y1)
        if d > best:
            best, k = d, i
    if best <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[:k + 1], tol)[:-1] + simplify(pts[k:], tol)


# -- polygons ---------------------------------------------------------------------------

def ring_area(r):
    return sum(r[k][0] * r[k + 1][1] - r[k + 1][0] * r[k][1] for k in range(len(r) - 1)) / 2


def inside(p, r):
    c = False
    for k in range(len(r) - 1):
        (x1, y1), (x2, y2) = r[k][:2], r[k + 1][:2]
        if (y1 > p[1]) != (y2 > p[1]) and p[0] < (x2 - x1) * (p[1] - y1) / (y2 - y1) + x1:
            c = not c
    return c


def polygons(parts):
    """Shapefile rings to GeoJSON polygons (outer rings anticlockwise,
    holes clockwise), deciding holes by nesting rather than trusting the
    winding order."""
    rings = [r if r[0] == r[-1] else r + [r[0]] for r in parts if len(r) >= 3]
    depth = [sum(inside(r[0], o) for o in rings if o is not r) for r in rings]
    outers = [k for k, d in enumerate(depth) if d % 2 == 0]
    polys = {k: [rings[k] if ring_area(rings[k]) > 0 else rings[k][::-1]] for k in outers}
    for k, d in enumerate(depth):
        if d % 2:
            host = min((o for o in outers if inside(rings[k][0], rings[o])),
                       key=lambda o: abs(ring_area(rings[o])), default=None)
            if host is not None:
                polys[host].append(rings[k] if ring_area(rings[k]) < 0 else rings[k][::-1])
    return list(polys.values())


class Clipper:
    """Areas and lines cut to their scrap's outline, which Therion does
    when it draws the map but not in the shapefiles. Needs shapely; without
    it they are left as drawn, a little past the walls in places."""

    def __init__(self, outlines):
        try:
            from shapely.geometry import LineString, Polygon
            from shapely.ops import unary_union
        except ImportError:
            print('::warning::shapely is not installed, so areas are not clipped to the walls', file=sys.stderr)
            self.shapes = None
            return
        self.LineString, self.Polygon = LineString, Polygon
        # a few centimetres' grace, so lines along a wall survive
        self.shapes = {k: unary_union([Polygon(p[0], p[1:]) for p in ps]).buffer(0.05)
                       for k, ps in outlines.items()}

    @staticmethod
    def _parts(g, kind):
        return [x for x in getattr(g, 'geoms', [g]) if x.geom_type == kind and not x.is_empty]

    def polygon(self, poly, scrap):
        if not self.shapes or scrap not in self.shapes:
            return [poly]
        g = self.Polygon(poly[0], poly[1:]).buffer(0).intersection(self.shapes[scrap])
        return [[list(p.exterior.coords)[::-1] if not p.exterior.is_ccw else list(p.exterior.coords)]
                + [list(r.coords) if not r.is_ccw else list(r.coords)[::-1] for r in p.interiors]
                for p in self._parts(g, 'Polygon')]

    def line(self, pts, scrap):
        if not self.shapes or scrap not in self.shapes:
            return [pts]
        g = self.LineString(pts).intersection(self.shapes[scrap])
        return [list(x.coords) for x in self._parts(g, 'LineString')]


# -- the GeoJSON ------------------------------------------------------------------------

def feature(geom, props):
    return {'type': 'Feature', 'properties': {k: v for k, v in props.items() if v not in (None, '')},
            'geometry': geom}


def collection(features, name):
    return {'type': 'FeatureCollection', 'name': name, 'features': features}


def sql_station_names(sql='output/Swildons.sql'):
    """{station id: name} from Therion's SQL export. The shapefile stores
    names like 13.5 as numbers (13.500000), so 13.5 and 13.50 can't be
    told apart there; the ids are the same in both exports."""
    if not os.path.exists(sql):
        return {}
    text = open(sql, encoding='utf-8', errors='replace').read()
    return {m.group(1): m.group(2).replace("''", "'")
            for m in re.finditer(r"insert into STATION values \((\d+), '((?:[^']|'')*)'", text)}


def station_name(a, sql):
    name = sql.get(a['_ID'])
    try:
        if name is not None and (name == a['_NAME'] or float(name) == float(a['_NAME'])):
            return name
    except ValueError:
        pass
    return a['_NAME']


def build_centreline(model, geo, ground, entrance_z):
    stations = read(os.path.join(model, 'stations3d'))
    sql = sql_station_names()
    by_id = {a['_ID']: (a, p) for a, p in stations}
    legs, on_leg = [], set()
    length = 0.0
    zs = []
    for a, parts in read(os.path.join(model, 'shots3d')):
        if not parts:
            continue
        pts = parts[0]
        survey, stanton = survey_of(a['_SURVEY'])
        flags = {k: a[f'_{k.upper()}'] == '1' for k in ('splay', 'duplicate', 'surface')}
        flags['approximate'] = a['_APPROXIM_'] == '1'
        if not flags['splay']:
            on_leg.update((by_id[a['_FROM']][0]['_UID'], by_id[a['_TO']][0]['_UID']))
            zs += [p[2] for p in pts]
            if not (flags['duplicate'] or flags['surface']):
                length += math.dist(pts[0], pts[-1])
        legs.append(feature({'type': 'LineString', 'coordinates': [geo(p) for p in pts]}, {
            'kind': 'leg', 'survey': survey, 'survey_title': survey_title(survey),
            'altitude': round(sum(p[2] for p in pts) / len(pts), 1),
            'source': 'stanton' if stanton else 'resurvey',
            **{k: True for k, v in flags.items() if v}}))
    # stations: one per position (equated stations share a _UID), named
    # name@survey, skipping splay ends and stations off every leg (such as
    # the 'bottom' station that pins the altitude colours)
    names = defaultdict(list)
    flags = defaultdict(dict)   # entrance, fixed or a comment on any of the equated names
    first = {}
    for a, p in stations:
        if a['_NAME'] in ('-', '.', '') or a['_UID'] not in on_leg:
            continue
        survey, stanton = survey_of(a['_SURVEY'])
        names[a['_UID']].append(f"{station_name(a, sql)}@{survey}")
        first.setdefault(a['_UID'], (a, p, survey, stanton))
        for k in ('_ENTRANCE', '_FIXED', '_COMMENT'):
            flags[a['_UID']][k] = flags[a['_UID']].get(k) or a[k].strip('0')
    points = []
    for uid, (a, p, survey, stanton) in first.items():
        g = ground.at(p[0], p[1]) if ground else None
        points.append(feature({'type': 'Point', 'coordinates': geo(p)}, {
            'kind': 'station', 'name': names[uid][0], 'aliases': ', '.join(names[uid][1:]),
            'survey': survey, 'source': 'stanton' if stanton else 'resurvey',
            'altitude': round(p[2], 2), 'below_entrance': round(entrance_z - p[2], 1),
            'ground': round(g, 1) if g is not None else None,
            'rock_above': round(g - p[2], 1) if g is not None else None,
            'entrance': bool(flags[uid]['_ENTRANCE']) or None, 'fixed': bool(flags[uid]['_FIXED']) or None,
            'comment': flags[uid]['_COMMENT']}))
    stats = {'length': round(length), 'depth': round(max(zs) - min(zs)), 'top': round(max(zs), 1),
             'bottom': round(min(zs), 1)}
    return collection(legs + points, 'Swildons Hole centreline'), stats


def build_map(plan, geo, ground, entrance_z):
    feats = []
    zscrap = {}
    outlines = defaultdict(list)
    for a, parts in read(os.path.join(plan, 'outline2d')):
        z = float(a['_Z'])
        zscrap[a['_ID']] = z
        survey, _ = survey_of(a['_SURVEY'])
        if not parts:
            continue
        for poly in polygons(parts):
            outlines[a['_ID']].append(poly)
            rings = [[geo(p) for p in r] for r in poly]
            # rock above: the ground at the middle of the outline, less its altitude
            xs, ys = zip(*[p[:2] for p in poly[0]])
            g = ground.at((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2) if ground else None
            feats.append(feature({'type': 'Polygon', 'coordinates': rings}, {
                'kind': 'passage', 'scrap': a['_NAME'], 'survey': survey,
                # scraps straight under Swildons have no survey of their own: name them from the scrap
                'survey_title': survey_title(survey if survey != 'Swildons' else re.sub(r'SP\d+$', '', a['_NAME'])),
                'altitude': round(z, 1), 'below_entrance': round(entrance_z - z, 1),
                'rock_above': round(g - z, 1) if g is not None else None}))
    feats.sort(key=lambda f: f['properties']['altitude'])

    clip = Clipper(outlines)
    for a, parts in read(os.path.join(plan, 'areas2d')):
        for poly in polygons(parts or []):
            pieces = clip.polygon(poly, a['_SCRAP_ID']) if a['_CLIP'] != 'off' else [poly]
            for poly in pieces:
                feats.append(feature({'type': 'Polygon', 'coordinates': [[geo(p) for p in r] for r in poly]}, {
                    'kind': 'area', 'type': a['_TYPE'], 'altitude': zscrap.get(a['_SCRAP_ID'])}))

    for a, parts in read(os.path.join(plan, 'lines2d')):
        # the drawn centreline is in Swildons-centreline.geojson, properly
        if a['_TYPE'] == 'centerline' or not parts:
            continue
        for part in parts:
            if len(part) < 2:
                continue
            # walls make the outline, so only the detail inside gets clipped
            pieces = (clip.line(part, a['_SCRAP_ID'])
                      if a['_CLIP'] != 'off' and a['_TYPE'] != 'wall' else [part])
            for part in pieces:
                feats.append(feature({'type': 'LineString', 'coordinates': [geo(p) for p in part]}, {
                    'kind': 'line', 'type': a['_TYPE'], 'subtype': a['_SUBTYPE'],
                    'altitude': zscrap.get(a['_SCRAP_ID'])}))

    for a, p in read(os.path.join(plan, 'points2d')):
        # drawn stations are in the centreline file, with their names
        if a['_TYPE'] == 'station' or p is None:
            continue
        # Therion's orientation runs anticlockwise from north; give a bearing
        rot = float(a['_TYPEFCR'] or 0)
        oriented = rot or a['_TYPE'] in ORIENTED
        feats.append(feature({'type': 'Point', 'coordinates': geo(p)}, {
            'kind': 'point', 'type': a['_TYPE'], 'text': clean_text(a['_TEXT']),
            'bearing': round(-rot % 360, 1) if oriented else None,
            'altitude': zscrap.get(a['_SCRAP_ID'])}))
    return collection(feats, 'Swildons Hole plan drawing')


def build(out, plan, model, standalone=None):
    stations = read(os.path.join(model, 'stations3d'))
    ent = next(((a, p) for a, p in stations if a['_ENTRANCE'] == '1'), None)
    if not ent:
        raise SystemExit('no entrance station in the model export')
    entrance = ent[1]
    try:
        ground = Ground()
    except (OSError, KeyError, ValueError) as e:
        print(f'::warning::no LIDAR ground for the map ({e}); run tools.model3d first', file=sys.stderr)
        ground = None
    xs = [p[0] for _, p in stations]
    ys = [p[1] for _, p in stations]
    box = ground.box if ground else (min(xs) - 200, min(ys) - 200, max(xs) + 200, max(ys) + 200)
    geo = Georef(entrance, box)

    centreline, stats = build_centreline(model, geo, ground, entrance[2])
    drawing = build_map(plan, geo, ground, entrance[2])

    def dump(obj, path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, separators=(',', ':'), ensure_ascii=False)
            f.write('\n')
    dump(centreline, os.path.join(out, 'Swildons-centreline.geojson'))
    dump(drawing, os.path.join(out, 'Swildons-map.geojson'))

    page = os.path.join(out, 'map')
    os.makedirs(page, exist_ok=True)
    config = {
        'title': 'Swildons Hole', 'subtitle': 'Priddy, Mendip',
        'built': datetime.date.today().isoformat(),
        'grid_ref': f'ST {round(entrance[0])} {round(entrance[1])}',
        'entrance': geo(entrance), 'stats': stats,
        'bounds': [geo((min(xs), min(ys))), geo((max(xs), max(ys)))],
    }
    if ground:
        ground.hillshade_png(os.path.join(page, 'hillshade.png'))
        x0, y0, x1, y1 = ground.box
        config['hillshade'] = {'url': 'hillshade.png',
                               'coordinates': [geo((x0, y1)), geo((x1, y1)), geo((x1, y0)), geo((x0, y0))]}
        lines = []
        for L, ls in sorted(ground.contours().items()):
            for line in ls:
                lines.append(feature({'type': 'LineString',
                                      'coordinates': [[round(c, 6) for c in geo(p)] for p in line]},
                                     {'height': round(L, 1), 'index': round(L) % 5 == 0}))
        dump(collection(lines, 'Ground contours from Environment Agency LIDAR'), os.path.join(page, 'contours.geojson'))
        config['contours'] = 'contours.geojson'
        hs = [v for v in ground.v if v is not None]
        config['stats']['ground'] = [round(min(hs), 1), round(max(hs), 1)]
    dump(config, os.path.join(page, 'map.json'))
    shutil.copy(os.path.join(HERE, 'viewer.html'), os.path.join(page, 'index.html'))
    if standalone:
        write_standalone(standalone, page, config, drawing, centreline)
    print(f"GeoJSON written: {sum(f['properties']['kind'] == 'leg' for f in centreline['features'])} legs, "
          f"{sum(f['properties']['kind'] == 'station' for f in centreline['features'])} stations, "
          f"{len(drawing['features'])} drawn features; map page in {page}", file=sys.stderr)


def write_standalone(path, page, config, drawing, centreline):
    """The map page as one file, with the survey, contours and hillshade
    inside it, to open from disk without a web server."""
    data = {'map.json': dict(config), '../Swildons-map.geojson': drawing,
            '../Swildons-centreline.geojson': centreline}
    if 'hillshade' in config:
        png = base64.b64encode(open(os.path.join(page, 'hillshade.png'), 'rb').read()).decode()
        data['map.json']['hillshade'] = {**config['hillshade'], 'url': 'data:image/png;base64,' + png}
        data['contours.geojson'] = json.load(open(os.path.join(page, 'contours.geojson')))
    blob = json.dumps(data, separators=(',', ':'), ensure_ascii=False).replace('</', '<\\/')
    html = open(os.path.join(HERE, 'viewer.html'), encoding='utf-8').read()
    html = html.replace('<!--MAP_DATA-->', f'<script>window.MAP_DATA = {blob};</script>', 1)
    html = html.replace('href="../index.html"', 'href="https://cavesurveying.github.io/uk_mendips_swildons-hole/"')
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'single-file map written to {path} ({os.path.getsize(path) // 1024} kB)', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default='output')
    ap.add_argument('--plan', default='output/esri-plan', help="Therion's export map -fmt esri")
    ap.add_argument('--model', default='output/esri-model', help="Therion's export model -fmt esri")
    ap.add_argument('--standalone', metavar='HTML', help='also write the map page as one self-contained file')
    args = ap.parse_args()
    build(args.out, args.plan, args.model, args.standalone)


if __name__ == '__main__':
    main()
