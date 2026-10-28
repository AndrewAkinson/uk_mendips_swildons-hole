"""Cross-section markers: which way they look, and where they're drawn.

A plan scrap holds, for each of its cross-sections, a `line section`
across the passage at the station and a `point section` where Therion
draws the section itself. This

- turns every `line section` so its arrows (`-direction both`) point the
  way the section is seen: looking along the survey, from the station
  towards the next one. Therion puts the arrows on the left of the line.
- moves any section drawing that overlaps a passage or another section to
  the nearest clear spot, preferring one in line with the cut. All the
  surveys on a sheet are placed together, so sections from different
  surveys don't land on each other either.

Passages come from Therion's KML of the plan maps, put into survey
coordinates by fitting it to the centreline. Run from the top of the
repository after the main build:

    therion -l output/therion-sections.log tools/sections/sections.thconfig
    python3 -m tools.sections
"""
import glob
import math
import os
import re
from xml.etree import ElementTree

from shapely.affinity import translate
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

from ..routes.survey import Survey, _fit
from ..sketch2therion.tidy import bezier_points, parse_scrap, scale_of

PASSAGES_KML = 'output/sections-passages.kml'
CENTRELINE_KML = 'output/Swildons-centreline.kml'

# The sheets the cross-sections are drawn on: which surveys' sections
# (by th2 file), and which plan maps (by KML title) they must keep off,
# each with the offset it is drawn at on that sheet (metres east, north).
SHEETS = {
    'entrance': {'files': ('Entrance/**/*Ee.th2', 'Entrance/**/*P.th2'),
                 'maps': {'Swildons Hole - Entrance Series': (0.0, 0.0)}},
    'master': {'files': ('Streamway/**/*Ee.th2', 'Streamway/**/*P.th2',
                         '*/**/*E000*.th2'),
               'maps': {'Swildons Hole - Entrance Series': (0.0, 0.0),
                        'Swildons 1 - Streamway': (0.0, 0.0)}},
}
MARGIN = 0.4        # metres kept clear round passages and sections
ARROW = {'entrance': 0.6, 'master': 1.5}   # m: a section arrow, about 3 mm on each sheet
REACH = 30.0        # how far from its station a section may go (m)

KML = '{http://earth.google.com/kml/2.0}'


# -- the passages, in survey coordinates ------------------------------------------

def _kml_polygons(path):
    """{placemark name: [[(lon, lat), ...] outer rings]}"""
    root = ElementTree.parse(path).getroot()
    out = {}
    for pm in root.iter(KML + 'Placemark'):
        name = (pm.findtext(KML + 'name') or '').strip()
        rings = []
        for poly in pm.iter(KML + 'Polygon'):
            c = poly.find(f'{KML}outerBoundaryIs/{KML}LinearRing/{KML}coordinates')
            if c is not None:
                rings.append([tuple(map(float, v.split(',')[:2])) for v in c.text.split()])
        if rings:
            out[name] = rings
    return out


def _affine(pairs):
    """Least-squares affine map from pairs [((x, y), (u, v))]."""
    n = len(pairs)
    mx = sum(p[0][0] for p in pairs) / n
    my = sum(p[0][1] for p in pairs) / n
    mu = sum(p[1][0] for p in pairs) / n
    mv = sum(p[1][1] for p in pairs) / n
    sxx = sum((p[0][0] - mx) ** 2 for p in pairs)
    syy = sum((p[0][1] - my) ** 2 for p in pairs)
    sxy = sum((p[0][0] - mx) * (p[0][1] - my) for p in pairs)
    det = sxx * syy - sxy * sxy

    def solve(k, m):
        sx = sum((p[0][0] - mx) * (p[1][k] - m) for p in pairs)
        sy = sum((p[0][1] - my) * (p[1][k] - m) for p in pairs)
        return (sx * syy - sy * sxy) / det, (sy * sxx - sx * sxy) / det
    a, b = solve(0, mu)
    c, d = solve(1, mv)
    return lambda p: (mu + a * (p[0] - mx) + b * (p[1] - my), mv + c * (p[0] - mx) + d * (p[1] - my))


def lonlat_to_survey(survey):
    """A map from KML lon/lat to the survey's grid, fitted to the centreline
    (every leg in Therion's centreline KML ends on a station)."""
    pts = []
    root = ElementTree.parse(CENTRELINE_KML).getroot()
    for c in root.iter(KML + 'coordinates'):
        for v in c.text.split():
            lon, lat, z = map(float, v.split(','))
            pts.append((lon, lat, z))
    stations = list(survey.pos.values())
    # rough: metres east and north of the entrance (the KML's one point)
    root_pt = next(root.iter(KML + 'Point')).findtext(KML + 'coordinates').split(',')
    lon0, lat0, z0 = map(float, root_pt)
    ent = min(stations, key=lambda q: abs(q[2] - z0) + (0 if survey.lookup.get('Ent@Swildons') is None
                                                         else math.dist(q, survey.pos[survey.lookup['Ent@Swildons']])))
    kx, ky = 111320 * math.cos(math.radians(lat0)), 111250
    pairs = []
    for lon, lat, z in pts:
        guess = (ent[0] + (lon - lon0) * kx, ent[1] + (lat - lat0) * ky)
        best = min(stations, key=lambda q: math.dist(guess, q[:2]) + 3 * abs(q[2] - z))
        if math.dist(guess, best[:2]) < 15 and abs(best[2] - z) < 0.05:
            pairs.append(((lon, lat), best[:2]))
    f = _affine(pairs)
    # refine once with the fitted map
    pairs2 = []
    for lon, lat, z in pts:
        g = f((lon, lat))
        best = min(stations, key=lambda s: math.dist(g, s[:2]) + 3 * abs(s[2] - z))
        if math.dist(g, best[:2]) < 0.5 and abs(best[2] - z) < 0.05:
            pairs2.append(((lon, lat), best[:2]))
    f = _affine(pairs2)
    err = sum(math.dist(f(a), b) for a, b in pairs2) / len(pairs2)
    return f, err, len(pairs2)


# -- the cross-section scraps -------------------------------------------------------

def _scraps(text):
    for m in re.finditer(r'^(scrap (\S+)[^\n]*)\n(.*?)^endscrap', text, re.S | re.M):
        yield m


def _survey_of(th2):
    """The survey a th2 file is input in, from the .th files. An input's
    path is relative to the file it is in."""
    for th in glob.glob('**/*.th', recursive=True):
        t = open(th, encoding='utf-8', errors='replace').read()
        rel = os.path.relpath(th2, os.path.dirname(th) or '.')
        m = re.search(r'^\s*input\s+' + re.escape(rel) + r'\s*$', t, re.M)
        if not m:
            continue
        i = m.start()
        found = re.findall(r'^\s*survey (\S+)', t[:i], re.M)
        if found:
            return found[-1]
    return None


def _station_of(xs_name, survey):
    """'xs22_12' -> '22.12@survey'; 'xs_LongDryWay_2_31' -> '2.31@LongDryWay'."""
    m = re.fullmatch(r'xs_(\w+?)_(\d+)_(\d+)', xs_name)
    if m:
        return f'{m.group(2)}.{m.group(3)}@{m.group(1)}'
    m = re.fullmatch(r'xs(\d+)_(\d+)', xs_name)
    if m:
        return f'{m.group(1)}.{m.group(2)}@{survey}'
    return None


def _neighbour(s, name):
    """The next station along (or, at the end, the one before), and +1/-1."""
    base, at = name.split('@')
    a, b = base.rsplit('.', 1)
    for d in (1, -1):
        n = f'{a}.{int(b) + d}@{at}'
        if n in s.lookup:
            return n, d
    return None, 0


def _footprint(body, K):
    """A section drawing's outline relative to the middle of its extent,
    in metres (Therion draws it centred on the point section)."""
    pts = []
    for o in parse_scrap(body):
        if o.kind == 'line':
            pts += bezier_points(o.segments())
        elif o.kind == 'point':
            v = o.head.split()
            try:
                pts.append((float(v[1]), float(v[2])))
            except ValueError:
                pass
    if len(pts) < 3:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    return MultiPoint([((x - cx) / K, (y - cy) / K) for x, y in pts]).convex_hull


class Section:
    pass


FILES = {}     # path -> (text, {scrap name: parsed objects}) for writing back


def collect(survey, sheet):
    """The cross-sections on a sheet, each with what's needed to place it."""
    secs = []
    for path in sorted({f for g in SHEETS[sheet]['files'] for f in glob.glob(g, recursive=True)}):
        text = open(path, 'rb').read().decode('utf-8').replace('\r\n', '\n')
        FILES[path] = (text, {})
        bodies = {m.group(2): (m.group(1), m.group(3)) for m in _scraps(text)}
        sv = _survey_of(path)
        for m in _scraps(text):
            name = m.group(2)
            if '-projection plan' not in m.group(1) or not re.search(r'^line section', m.group(3), re.M):
                continue
            K = scale_of(m.group(1))
            objs = parse_scrap(m.group(3))
            FILES[path][1][name] = objs
            labels = [o for o in objs if o.kind == 'point' and ' label ' in o.head]
            # -station-names <prefix> <suffix> qualifies the scrap's bare station names
            names = re.search(r'-station-names\s+("[^"]*"|\S+)\s+("[^"]*"|\S+)', m.group(1))
            pre, suf = (n.strip('"') for n in names.groups()) if names else ('', '')
            pairs = []
            for o in objs:
                if o.kind == 'point' and re.match(r'point \S+ \S+ station\b', o.head):
                    st = re.search(r'-name (\S+)', o.head).group(1)
                    if '@' not in st:
                        st = pre + st + suf
                    full = st if '@' in st else f'{st}@{sv}'
                    if full in survey.lookup:
                        v = o.head.split()
                        pairs.append(((float(v[1]), float(v[2])), survey.pos[survey.lookup[full]][:2]))
            if not pairs:
                print(f'  {path} {name}: no survey stations found, skipped')
                continue
            if len(pairs) == 1:
                # one station: the scrap is drawn to its -scale, north up
                (x0, y0), (e0, n0) = pairs[0]
                to_grid = lambda p, x0=x0, y0=y0, e0=e0, n0=n0, K=K: (e0 + (p[0] - x0) / K, n0 + (p[1] - y0) / K)
                to_scrap = lambda p, x0=x0, y0=y0, e0=e0, n0=n0, K=K: (x0 + (p[0] - e0) * K, y0 + (p[1] - n0) * K)
            else:
                to_grid = _fit(pairs)
                to_scrap = _fit([(b, a) for a, b in pairs])
            line = None
            for o in objs:
                if o.kind == 'line' and o.head.startswith('line section'):
                    line = o
                elif o.kind == 'point' and ' section ' in o.head + ' ' and line is not None:
                    xs = re.search(r'-scrap (\S+)', o.head).group(1)
                    sec = Section()
                    sec.path, sec.scrap, sec.xs, sec.line, sec.point = path, name, xs, line, o
                    sec.to_grid, sec.to_scrap, sec.K = to_grid, to_scrap, K
                    sec.station = _station_of(xs, sv)
                    # the labels naming it (a plan scrap has other labels too)
                    base = sec.station.split('@')[0] if sec.station else None
                    sec.labels = [l for l in labels if f'-text "{base}"' in l.head]
                    hb = bodies.get(xs)
                    sec.shape = _footprint(hb[1], scale_of(hb[0])) if hb else None
                    v = o.head.split()
                    sec.at = (float(v[1]), float(v[2]))
                    ends = [tuple(s[-2:]) for s in line.segments()]
                    sec.cut = [sec.grid(p) for p in (ends[0], ends[-1])]
                    secs.append(sec)
                    line = None
    return secs


Section.grid = lambda self, p: self.to_grid(p)
Section.scrap_xy = lambda self, p: self.to_scrap(p)


# -- doing it ---------------------------------------------------------------------

def orient(survey, sec):
    """Turn the section line so its arrows (on its left) look along the survey."""
    if not sec.station or sec.station not in survey.lookup:
        return False
    nxt, d = _neighbour(survey, sec.station)
    if not nxt:
        return False
    a = survey.pos[survey.lookup[sec.station]]
    b = survey.pos[survey.lookup[nxt]]
    fx, fy = (b[0] - a[0]) * d, (b[1] - a[1]) * d
    (x0, y0), (x1, y1) = sec.cut
    left = (-(y1 - y0), x1 - x0)
    head = sec.line.head
    if '-direction' not in head:
        head += ' -direction both'
    changed = head != sec.line.head
    sec.line.head = head
    if left[0] * fx + left[1] * fy < 0:
        rows = [r for r in sec.line.rows if r.strip()]
        sec.line.rows = rows[::-1]          # straight two-point lines: just swap the ends
        sec.cut = sec.cut[::-1]
        changed = True
    return changed


def extend_cut(sec, passages, others, arrow):
    """Carry a section line right across the passage it cuts, and an
    arrow's length beyond on each side so the arrows are clear of it. An
    end whose arrow would land on another passage gets none (-direction
    begin/end). Returns True if the line changed."""
    from shapely.geometry import LineString as LS
    (x0, y0), (x1, y1) = sec.cut
    L = math.dist((x0, y0), (x1, y1))
    if L < 1e-6:
        return False
    ux, uy = (x1 - x0) / L, (y1 - y0) / L
    mid = Point((x0 + x1) / 2, (y0 + y1) / 2)
    if sec.station and sec.station in sec.survey.lookup:
        g = sec.survey.pos[sec.survey.lookup[sec.station]]
        mid = Point(g[0], g[1])
    here = min(getattr(passages, 'geoms', [passages]), key=lambda p: p.distance(mid))

    def exit_at(sign):
        far = LS([(mid.x, mid.y), (mid.x + sign * ux * 60, mid.y + sign * uy * 60)])
        hit = far.intersection(here.boundary)
        pts = [q for q in getattr(hit, 'geoms', [hit]) if not q.is_empty and q.geom_type == 'Point']
        if not pts:
            return None
        return min(mid.distance(q) for q in pts)
    a, b = exit_at(-1), exit_at(1)
    if a is None or b is None:
        return False
    a, b = a + arrow, b + arrow
    start = (mid.x - ux * a, mid.y - uy * a)
    end = (mid.x + ux * b, mid.y + uy * b)
    # an arrow sits on the line's left at each end: is that clear?
    nx, ny = -uy, ux

    def clear(p):
        tip = Point(p[0] + nx * arrow * 0.6, p[1] + ny * arrow * 0.6)
        return not LS([p, (tip.x, tip.y)]).buffer(arrow * 0.3).intersects(others)
    cs, ce = clear(start), clear(end)
    direction = 'both' if (cs and ce) or not (cs or ce) else ('begin' if cs else 'end')
    old_ends = [sec.scrap_xy(sec.cut[0]), sec.scrap_xy(sec.cut[1])]
    new_ends = [sec.scrap_xy(start), sec.scrap_xy(end)]
    sec.line.rows = ['  %.2f %.2f' % new_ends[0], '  %.2f %.2f' % new_ends[1]]
    sec.line.head = re.sub(r'-direction \S+', '-direction ' + direction, sec.line.head)
    if '-direction' not in sec.line.head:
        sec.line.head += ' -direction ' + direction
    # the station label at each end of the line moves out with it
    for o, n in zip(old_ends, new_ends):
        near = [l for l in sec.labels if math.dist(_xy(l), o) < 1.5 * sec.K]
        if near:
            lab = min(near, key=lambda l: math.dist(_xy(l), o))
            x, y = _xy(lab)
            lab.head = re.sub(r'^point [-\d.]+ [-\d.]+', 'point %.2f %.2f'
                              % (x + n[0] - o[0], y + n[1] - o[1]), lab.head)
    sec.cut = [start, end]
    return True


LABEL_MM = {'xs': 1.4, 's': 1.8, 'm': 2.4, 'l': 3.4, 'xl': 4.6}
SCALE = {'entrance': 200, 'master': 500}


def clear_labels(secs, passages, sheet):
    """Move the cross-sections' labels that sit on a passage (from any
    survey on the sheet) to the nearest clear spot. Returns how many moved."""
    from shapely.geometry import box
    k = SCALE[sheet] / 1000          # metres on the ground per mm on the sheet
    seen, labs = set(), []
    for s in secs:
        for l in s.labels:
            if id(l) not in seen:
                seen.add(id(l))
                labs.append((l, s))
    taken = [s.fp for s in secs if getattr(s, 'fp', None) is not None]

    def size(l):
        t = re.search(r'-text "([^"]*)"', l.head)
        sc = re.search(r'-scale (\w+)', l.head)
        h = LABEL_MM.get(sc.group(1) if sc else 'm', 2.4) * k
        return max(1, len(t.group(1) if t else 'x')) * h * 0.6, h * 1.3
    boxes = {}
    for l, s in labs:
        w, h = size(l)
        x, y = s.grid(_xy(l))
        boxes[id(l)] = box(x - w / 2, y - h / 2, x + w / 2, y + h / 2)
    moved = 0
    clear_of = passages.buffer(0.1)
    for l, s in labs:
        b = boxes[id(l)]
        others = [boxes[i] for i in boxes if i != id(l)]
        if not b.intersects(clear_of):
            continue
        c = b.centroid
        spot = None
        for r in [i * 0.25 for i in range(1, 40)]:
            for a in range(16):
                dx, dy = r * math.cos(a * math.pi / 8), r * math.sin(a * math.pi / 8)
                nb = translate(b, dx, dy)
                if nb.intersects(clear_of) or any(nb.intersects(o) for o in others) \
                        or any(nb.intersects(t) for t in taken):
                    continue
                spot = (dx, dy)
                break
            if spot:
                break
        if spot is None:
            continue
        boxes[id(l)] = translate(b, *spot)
        new = s.scrap_xy((c.x + spot[0], c.y + spot[1]))
        l.head = re.sub(r'^point [-\d.]+ [-\d.]+', 'point %.2f %.2f' % new, l.head)
        moved += 1
    return moved


def place(secs, obstacles):
    """Move section drawings off the passages and each other. Returns how many moved."""
    obst = prep(obstacles)
    fixed, todo = [], []
    for s in secs:
        if s.shape is None:
            continue
        c = s.grid(s.at)
        s.fp = translate(s.shape, c[0], c[1]).buffer(MARGIN)
    for s in secs:
        if s.shape is None:
            continue
        clash = obst.intersects(s.fp) or any(s.fp.intersects(t.fp) for t in secs
                                              if t is not s and t.shape is not None and t not in todo)
        (todo if clash else fixed).append(s)
    placed = [s.fp for s in fixed]
    moved = 0
    for s in todo:
        (x0, y0), (x1, y1) = s.cut
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        axis = math.atan2(y1 - y0, x1 - x0)
        cands = []
        for r10 in range(10, int(REACH * 10) + 1, 5):
            r = r10 / 10
            for k in range(36):
                ang = k * math.pi / 18
                off = abs(math.sin(ang - axis))        # 0 in line with the cut
                cands.append((r * (1 + 0.8 * off), mx + r * math.cos(ang), my + r * math.sin(ang)))
        cands.sort()
        here = prep(unary_union(placed)) if placed else None
        for _, cx, cy in cands:
            fp = translate(s.shape, cx, cy).buffer(MARGIN)
            if obst.intersects(fp) or (here and here.intersects(fp)):
                continue
            new = s.scrap_xy((cx, cy))
            dx, dy = new[0] - s.at[0], new[1] - s.at[1]
            s.point.head = re.sub(r'^point [-\d.]+ [-\d.]+', 'point %.2f %.2f' % new, s.point.head)
            # the label naming the section moves with it
            near = [o for o in s.labels if math.dist(_xy(o), s.at) < 3 * s.K]
            if near:
                lab = min(near, key=lambda o: math.dist(_xy(o), s.at))
                x, y = _xy(lab)
                lab.head = re.sub(r'^point [-\d.]+ [-\d.]+', 'point %.2f %.2f' % (x + dx, y + dy), lab.head)
            s.fp = fp
            placed.append(fp)
            moved += 1
            break
        else:
            print(f'  {s.scrap} {s.xs}: no clear spot within {REACH:g} m, left where it was')
            placed.append(s.fp)
    return moved


def run():
    survey = Survey()
    to_grid, err, n = lonlat_to_survey(survey)
    print(f'KML to survey grid: fitted on {n} centreline points, {err * 100:.1f} cm average')
    polys = _kml_polygons(PASSAGES_KML)
    for sheet, spec in SHEETS.items():
        parts = []
        for title, (dx, dy) in spec['maps'].items():
            for ring in polys.get(title, []):
                g = Polygon([to_grid(p) for p in ring]).buffer(0)
                parts.append(translate(g, dx, dy))
            if title not in polys:
                print(f'  warning: no map "{title}" in {PASSAGES_KML}')
        passages = unary_union(parts)
        obstacles = passages.buffer(MARGIN)
        secs = collect(survey, sheet)
        turned = sum(orient(survey, s) for s in secs)
        across = 0
        for s in secs:
            s.survey = survey
            here = min(getattr(passages, 'geoms', [passages]),
                       key=lambda p: p.distance(Point(*((s.cut[0][0] + s.cut[1][0]) / 2, (s.cut[0][1] + s.cut[1][1]) / 2))))
            others = passages.difference(here.buffer(0.05))
            across += extend_cut(s, passages, others, ARROW[sheet])
        moved = place(secs, obstacles)
        labels = clear_labels(secs, passages, sheet)
        print(f'{sheet}: {len(secs)} cross-sections, {turned} lines turned, {across} carried across the passage, '
              f'{moved} drawings moved, {labels} labels moved off passages')
    write()


def write():
    for path, (text, scraps) in FILES.items():
        raw = open(path, 'rb').read()
        out, pos = [], 0
        for m in _scraps(text):
            if m.group(2) not in scraps:
                continue
            body = '\n'.join(o.text() for o in scraps[m.group(2)])
            out.append(text[pos:m.start(3)] + body.rstrip('\n') + '\n')
            pos = m.end(3)
        out.append(text[pos:])
        t = ''.join(out)
        if b'\r\n' in raw:
            t = t.replace('\n', '\r\n')
        open(path, 'wb').write(t.encode('utf-8'))


def _xy(o):
    v = o.head.split()
    return float(v[1]), float(v[2])
