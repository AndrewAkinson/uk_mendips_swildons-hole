"""The cave as a graph, from Therion's own database export.

Therion's SQL export (output/Swildons.sql, from `export database -fmt sql`)
has every station's adjusted position (OS grid metres, altitude) and every
shot. Equated stations share a position, so stations are merged into
nodes by position. Splays are left out; Stanton's legs that the resurvey
has replaced (flagged duplicate) are kept but cost more, so a route
prefers the resurvey.

Passage names come from the label points in the plan drawings (.th2),
placed into survey coordinates by fitting each scrap to its stations.
"""
import glob
import math
import re
import sqlite3
from collections import defaultdict


def _key(x, y, z):
    return (round(x, 2), round(y, 2), round(z, 2))


class Survey:
    def __init__(self, sql_path='output/Swildons.sql', root='.'):
        db = sqlite3.connect(':memory:')
        db.executescript(open(sql_path, encoding='utf-8', errors='replace').read())
        surveys = {i: (p, n) for i, p, n in db.execute('select ID, PARENT_ID, NAME from SURVEY')}
        self.pos = {}           # node -> (x, y, z)
        self.names = defaultdict(list)    # node -> ['2.5@LongDryWay', ...]
        self.lookup = {}        # 'name@survey' and bare 'name' -> node
        bare = defaultdict(set)
        node_of_id = {}
        for sid, name, survey, x, y, z in db.execute('select ID, NAME, SURVEY_ID, X, Y, Z from STATION'):
            if not name or name == '-' or name == '.':
                continue
            k = _key(x, y, z)
            self.pos[k] = (x, y, z)
            full = f"{name}@{surveys.get(survey, (0, ''))[1]}"
            self.names[k].append(full)
            self.lookup[full] = k
            bare[name].add(k)
            node_of_id[sid] = k
        for n, ks in bare.items():
            if len(ks) == 1:
                self.lookup.setdefault(n, next(iter(ks)))
        flags = defaultdict(set)
        for shot, f in db.execute('select SHOT_ID, FLAG from SHOT_FLAG'):
            flags[shot].add(f)
        self.adj = defaultdict(dict)    # node -> {node: cost}
        self.legs = []
        for shot, a, b, L in db.execute('select ID, FROM_ID, TO_ID, ADJ_LENGTH from SHOT'):
            if 'spl' in flags[shot] or a not in node_of_id or b not in node_of_id:
                continue
            A, B = node_of_id[a], node_of_id[b]
            if A == B:
                continue
            cost = L * (3.0 if 'dpl' in flags[shot] else 1.0)
            if B not in self.adj[A] or cost < self.adj[A][B]:
                self.adj[A][B] = cost
                self.adj[B][A] = cost
                self.legs.append((A, B, 'dpl' in flags[shot]))
        self.labels = []         # passage and place names
        self.notes = []          # other notes on the drawings ("Calcite choke")

    def node(self, name):
        if name not in self.lookup:
            raise KeyError(f"no station {name!r} in the survey")
        return self.lookup[name]

    def name(self, k):
        """A readable name for a node: prefer resurvey names over Stanton's."""
        ns = sorted(self.names.get(k, ['?']), key=lambda n: ('wstanton' in n or n.split('@')[1].startswith('swil'), n))
        return ns[0]

    # -- routing ---------------------------------------------------------------
    def path(self, a, b, avoid=()):
        """Shortest path between two nodes (Dijkstra), avoiding some nodes."""
        import heapq
        dist = {a: 0.0}
        prev = {}
        q = [(0.0, a)]
        avoid = set(avoid) - {a, b}
        while q:
            d, u = heapq.heappop(q)
            if u == b:
                break
            if d > dist.get(u, 1e18):
                continue
            for v, c in self.adj[u].items():
                if v in avoid:
                    continue
                nd = d + c
                if nd < dist.get(v, 1e18):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(q, (nd, v))
        if b not in dist:
            raise ValueError(f"no way from {self.name(a)} to {self.name(b)}")
        out = [b]
        while out[-1] != a:
            out.append(prev[out[-1]])
        return out[::-1]

    def route(self, waypoints, avoid=()):
        """Path through a list of station names, in order."""
        nodes = [self.node(w) for w in waypoints]
        av = [self.node(w) for w in avoid]
        out = [nodes[0]]
        for a, b in zip(nodes, nodes[1:]):
            out += self.path(a, b, av)[1:]
        return out

    def dist3(self, a, b):
        return math.dist(self.pos[a], self.pos[b])

    # -- passage names -----------------------------------------------------------
    def load_labels(self, patterns=('Entrance/**/*P.th2', 'Streamway/**/*P.th2', '*/**/Swil1P_*.th2')):
        """Labels from the plan drawings, in survey coordinates."""
        for f in sorted({f for g in patterns for f in glob.glob(g, recursive=True)}):
            txt = open(f, encoding='utf-8', errors='replace').read().replace('\r', '')
            for m in re.finditer(r'^scrap (\S+).*?^endscrap', txt, re.S | re.M):
                body = m.group(0)
                st = [(float(a), float(b), n) for a, b, n in
                      re.findall(r'^point\s+([-\d.]+)\s+([-\d.]+)\s+station\s+-name\s+(\S+)', body, re.M)]
                pairs = []
                for x, y, n in st:
                    k = self.lookup.get(n) or self.lookup.get(n.split('@')[0])
                    if k:
                        pairs.append(((x, y), self.pos[k][:2]))
                if len(pairs) < 2:
                    continue
                T = _fit(pairs)
                if T is None:
                    continue
                for x, y, text, rest in re.findall(
                        r'^point\s+([-\d.]+)\s+([-\d.]+)\s+label\b(.*?)-text\s+"([^"]*)"', body, re.M):
                    pass
                for line in body.splitlines():
                    lm = re.match(r'point\s+([-\d.]+)\s+([-\d.]+)\s+label\b.*?-text\s+"([^"]*)"', line)
                    if lm:
                        t = re.sub(r'<[^>]*>', ' ', lm.group(3)).replace("\\'", "'")
                        t = ' '.join(t.split())
                        if not t or re.match(r'^(C[\d.]+m|[\d.]+)$', t) or re.search(r'\(C[\d.]+m\)', t):
                            continue
                        xy = T((float(lm.group(1)), float(lm.group(2))))
                        if _is_name(t):
                            self.labels.append((t, *xy))
                        else:
                            self.notes.append((t, *xy))
        return self.labels

    def notes_near(self, k, within=5.0):
        x, y = self.pos[k][:2]
        return [t for t, lx, ly in self.notes if math.hypot(lx - x, ly - y) < within]

    def place_name(self, k, within=12.0):
        """The nearest passage label to a node, if any is close."""
        x, y = self.pos[k][:2]
        best = None
        for t, lx, ly in self.labels:
            d = math.hypot(lx - x, ly - y)
            if d < within and (best is None or d < best[0]):
                best = (d, t)
        return best[1] if best else None


GENERIC = {'Dig', 'Choke', 'Junction'}
SMALL = {'of', 'the', 'and', 'for', 'to', 'at', 'in', 'on', 'a'}


def _is_name(t):
    """A passage or place name is in title case: "Long Dry Way", "Old 40ft Pot";
    a note isn't: "Calcite choked at roof level", "Bolt for dive line"."""
    if t in GENERIC:
        return False
    words = re.findall(r"[A-Za-z0-9']+", t)
    return bool(words) and (words[0][0].isupper() or words[0][0].isdigit()) and all(
        w[0].isupper() or w[0].isdigit() or w.lower() in SMALL for w in words)


def _fit(pairs):
    """Similarity transform (scale, rotation, shift) from scrap to survey coordinates."""
    n = len(pairs)
    sx = sum(p[0][0] for p in pairs) / n
    sy = sum(p[0][1] for p in pairs) / n
    tx = sum(p[1][0] for p in pairs) / n
    ty = sum(p[1][1] for p in pairs) / n
    a = b = d = 0.0
    for (x, y), (u, v) in pairs:
        x -= sx; y -= sy; u -= tx; v -= ty
        a += x * u + y * v
        b += x * v - y * u
        d += x * x + y * y
    if d == 0:
        return None
    a /= d
    b /= d
    return lambda p: (tx + a * (p[0] - sx) - b * (p[1] - sy), ty + b * (p[0] - sx) + a * (p[1] - sy))
