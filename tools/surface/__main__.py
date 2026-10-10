"""The surface map: how to get to the cave.

    python3 -m tools.surface [--geojson surface/surface.geojson]

For visitors new to the area: an OpenStreetMap background with the
places to park and the walks to the entrance (from surface/surface.geojson),
and the entrance itself. Each car park gets a directions link and its walk's
length and time; on a phone, a button shows where you are.

GeoJSON features, by their "type" property (or geometry):
- type "parking" (or a Point whose name mentions parking): a car park
- type "route" (or any LineString): a walk; draw it from the parking
  towards the entrance, so its arrows point the right way
- anything else that is a Point: a labelled point of interest
Each can have "name" (or "title") and "description".

Map tiles are fetched once from OpenStreetMap and kept in surface/tiles/,
so builds don't hit their servers. The page is one self-contained file.
"""
import argparse
import base64
import datetime
import html
import json
import math
import os
import re
import sys
import tomllib
import urllib.request

from tools.routes import render as R

TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
UA = 'uk_mendips_swildons-hole surface map (https://github.com/CaveSurveying/uk_mendips_swildons-hole)'
WALK = '#1d8a4e'
PARK = '#1f5fbf'
esc = R.esc


# -- coordinates ------------------------------------------------------------------

def merc(lon, lat, z):
    """Web Mercator pixel coordinates at zoom z."""
    n = 256 * 2 ** z
    x = (lon + 180) / 360 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def dist_m(a, b):
    """Metres between two (lon, lat) points."""
    la1, la2 = math.radians(a[1]), math.radians(b[1])
    dl = math.radians(b[0] - a[0])
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dl / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


def line_m(pts):
    return sum(dist_m(a, b) for a, b in zip(pts, pts[1:]))


def entrance(kml='output/Swildons-centreline.kml'):
    t = open(kml, encoding='utf-8').read()
    m = re.search(r'<styleUrl>#ThEntranceIcon</styleUrl>\s*<name>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</name>.*?<coordinates>\s*([-\d.]+),([-\d.]+)', t, re.S)
    return m.group(1), (float(m.group(2)), float(m.group(3)))


def tile(z, x, y, cache='surface/tiles'):
    os.makedirs(cache, exist_ok=True)
    f = os.path.join(cache, f'{z}-{x}-{y}.png')
    if not os.path.exists(f):
        req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={'User-Agent': UA})
        data = urllib.request.urlopen(req, timeout=30).read()
        open(f, 'wb').write(data)
    return 'data:image/png;base64,' + base64.b64encode(open(f, 'rb').read()).decode()


# -- the page -------------------------------------------------------------------------

def build(cfg, gj, out_dir):
    ent_name, ent = entrance()

    feats = gj.get('features', []) if gj else []
    parks, walks, pois = [], [], []
    for f in feats:
        p = f.get('properties') or {}
        g = f.get('geometry') or {}
        name = p.get('name') or p.get('title') or ''
        kind = (p.get('type') or p.get('kind') or '').lower()
        if g.get('type') == 'Point':
            ll = tuple(g['coordinates'][:2])
            if kind == 'parking' or (not kind and 'park' in name.lower()):
                parks.append((name or 'Parking', p.get('description', ''), ll))
            else:
                pois.append((name, p.get('description', ''), ll))
        elif g.get('type') in ('LineString', 'MultiLineString'):
            lines = [g['coordinates']] if g['type'] == 'LineString' else g['coordinates']
            for ln in lines:
                walks.append((name or 'Walk', p.get('description', ''), [tuple(c[:2]) for c in ln]))

    # extent: everything, plus a margin
    every = [ent] + [ll for *_, ll in parks + pois] + [p for *_, pts in walks for p in pts]
    lons = [p[0] for p in every]
    lats = [p[1] for p in every]
    pad_lon, pad_lat = 0.0015, 0.001
    lon0, lon1 = min(lons) - pad_lon, max(lons) + pad_lon
    lat0, lat1 = min(lats) - pad_lat, max(lats) + pad_lat
    z = 18
    while z > 12:
        x0, y0 = merc(lon0, lat1, z)
        x1, y1 = merc(lon1, lat0, z)
        if x1 - x0 <= 2200 and y1 - y0 <= 1500:
            break
        z -= 1
    x0, y0 = merc(lon0, lat1, z)
    x1, y1 = merc(lon1, lat0, z)
    # fill the panel's shape (print: 180 x 150 mm on A4)
    W, H = x1 - x0, y1 - y0
    ar = 180 / 150
    if W / H < ar:
        d = H * ar - W
        x0 -= d / 2; x1 += d / 2
    else:
        d = W / ar - H
        y0 -= d / 2; y1 += d / 2
    W, H = x1 - x0, y1 - y0
    # Draw relative to the map's top-left corner. At zoom 18 the absolute
    # Mercator coordinates are around 33 million, beyond the float precision
    # Firefox and Safari use for SVG, which then draw nothing at all.
    ox, oy = x0, y0
    P = lambda ll: (merc(ll[0], ll[1], z)[0] - ox, merc(ll[0], ll[1], z)[1] - oy)
    m_per_px = 156543.03392 * math.cos(math.radians(ent[1])) / 2 ** z
    k = W / 180          # map units per mm on the printed page

    def label(x, y, r, text, colour, size):
        w = len(text) * size * 0.55 * k
        left = x > W * 0.6 or x + r + k + w > W - k * 4
        tx = x - r - k if left else x + r + k
        return (f'<text x="{tx:.1f}" y="{y + k * size * 0.35:.1f}" font-size="{k * size:.2f}" font-weight="700" fill="{colour}" '
                f'text-anchor="{"end" if left else "start"}" stroke="#fff" stroke-width="{k * 0.9:.2f}" paint-order="stroke">{esc(text)}</text>')

    o = []
    for tx in range(int(x0 // 256), int(x1 // 256) + 1):
        for ty in range(int(y0 // 256), int(y1 // 256) + 1):
            o.append(f'<image href="{tile(z, tx, ty)}" x="{tx * 256 - ox:.1f}" y="{ty * 256 - oy:.1f}" width="256.6" height="256.6"/>')
    o.append(f'<rect x="0" y="0" width="{W:.1f}" height="{H:.1f}" fill="#fbfaf7" fill-opacity="0.18"/>')
    # walks
    for name, desc, pts in walks:
        sp = [P(p) for p in pts]
        o.append(f'<path d="{R.path_d(sp)}" fill="none" stroke="#fff" stroke-width="{k * 2.6:.2f}" '
                 f'stroke-linejoin="round" stroke-linecap="round" stroke-opacity="0.95"/>'
                 f'<path d="{R.path_d(sp)}" fill="none" stroke="{WALK}" stroke-width="{k * 1.5:.2f}" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
        sz = k * 0.5
        for x, y, a in R.along(sp, k * 9, k * 4.5):
            o.append(f'<path d="M{-sz:.2f} {-sz * 1.1:.2f} L{sz * 0.6:.2f} 0 L{-sz:.2f} {sz * 1.1:.2f}" fill="none" '
                     f'stroke="#fff" stroke-width="{k * 0.32:.2f}" stroke-linecap="round" stroke-linejoin="round" '
                     f'transform="translate({x:.2f} {y:.2f}) rotate({a:.1f})"/>')
    # points of interest
    for name, desc, ll in pois:
        x, y = P(ll)
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{k * 1.2:.2f}" fill="#fff" stroke="{R.INK}" stroke-width="{k * 0.4:.2f}"/>'
                 f'<text x="{x + k * 2:.1f}" y="{y + k * 1:.1f}" font-size="{k * 3:.2f}" fill="{R.INK}" stroke="#fff" '
                 f'stroke-width="{k * 0.8:.2f}" paint-order="stroke">{esc(name)}</text>')
    # parking
    for n, (name, desc, ll) in enumerate(parks, 1):
        x, y = P(ll)
        r = k * 3.2
        o.append(f'<g transform="translate({x:.1f} {y:.1f})"><rect x="{-r:.1f}" y="{-r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" '
                 f'rx="{k * 0.8:.2f}" fill="{PARK}" stroke="#fff" stroke-width="{k * 0.5:.2f}"/><text text-anchor="middle" '
                 f'dy="0.36em" font-size="{k * 4.4:.2f}" font-weight="700" fill="#fff">P</text></g>'
                 + label(x, y, r, name, PARK, 3.4))
    # entrance
    ex, ey = P(ent)
    r = k * 4
    o.append(f'<g transform="translate({ex:.1f} {ey:.1f})"><circle r="{r:.1f}" fill="{R.INK}" stroke="#fff" stroke-width="{k * 0.6:.2f}"/>'
             f'<path d="M{-r * 0.55:.1f} {r * 0.45:.1f} L{-r * 0.55:.1f} {-r * 0.05:.1f} A{r * 0.55:.1f} {r * 0.55:.1f} 0 0 1 '
             f'{r * 0.55:.1f} {-r * 0.05:.1f} L{r * 0.55:.1f} {r * 0.45:.1f} Z" fill="#fff"/></g>'
             f'<text x="{ex + r + k * 1.2:.1f}" y="{ey - k * 0.5:.1f}" font-size="{k * 4:.2f}" font-weight="700" fill="{R.INK}" '
             f'stroke="#fff" stroke-width="{k * 1:.2f}" paint-order="stroke">Entrance</text>')
    # you are here (filled in by the page's script)
    o.append(f'<g id="here" style="display:none"><circle r="{k * 6:.1f}" fill="#2b7de9" fill-opacity="0.18"/>'
             f'<circle r="{k * 1.8:.1f}" fill="#2b7de9" stroke="#fff" stroke-width="{k * 0.6:.2f}"/></g>')

    svg = (f'<svg class="map" viewBox="0 0 {W:.1f} {H:.1f}" width="100%" height="100%" '
           f'preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg">{"".join(o)}</svg>')
    # scale bar
    target = 180 * 0.25 * k * m_per_px
    nice = min((25, 50, 100, 200, 250, 500, 1000), key=lambda v: abs(v - target))
    Lmm = nice / m_per_px / k
    scalebar = (f'<svg class="scalebar" width="{Lmm + 14:.1f}mm" height="9mm" viewBox="0 0 {Lmm + 14:.1f} 9">'
                f'<rect x="1" y="4" width="{Lmm / 2:.2f}" height="1.6" fill="{R.INK}"/><rect x="{1 + Lmm / 2:.2f}" y="4" '
                f'width="{Lmm / 2:.2f}" height="1.6" fill="#fff" stroke="{R.INK}" stroke-width="0.3"/>'
                f'<text x="1" y="3" font-size="2.6" fill="{R.INK}">0</text><text x="{1 + Lmm:.2f}" y="3" font-size="2.6" '
                f'text-anchor="middle" fill="{R.INK}">{nice} m</text></svg>')

    # ---- the side panel ----------------------------------------------------------
    def nearest_walk(ll):
        best = None
        for name, desc, pts in walks:
            d = min(dist_m(ll, pts[0]), dist_m(ll, pts[-1]))
            if d < 120 and (best is None or d < best[0]):
                best = (d, name, line_m(pts))
        return best

    park_html = []
    for name, desc, ll in parks:
        lon, lat = ll
        w = nearest_walk(ll)
        walk = (f'<div class="meta">{w[2]:.0f} m walk to the entrance, about {max(1, round(w[2] / 75)):d} min</div>'
                if w else f'<div class="meta">{dist_m(ll, ent):.0f} m from the entrance as the crow flies</div>')
        park_html.append(
            f'<li><b>{esc(name)}</b>{walk}' + (f'<div>{esc(desc)}</div>' if desc else '') +
            f'<div class="links"><a href="https://www.google.com/maps/dir/?api=1&amp;destination={lat:.6f},{lon:.6f}">Directions</a>'
            f' · <a href="geo:{lat:.6f},{lon:.6f}?q={lat:.6f},{lon:.6f}({esc(name)})">Open in maps app</a>'
            f' · <span class="coord">{lat:.5f}, {lon:.5f}</span></div></li>')
    walk_html = [f'<li><b>{esc(n)}</b> <span class="meta">{line_m(p):.0f} m, about {max(1, round(line_m(p) / 75))} min</span>'
                 + (f'<div>{esc(d)}</div>' if d else '') + '</li>' for n, d, p in walks]
    poi_html = [f'<li><b>{esc(n)}</b>' + (f' {esc(d)}' if d else '') + '</li>' for n, d, _ in pois if n]
    gridref = cfg.get('grid_ref', '')
    access = cfg.get('access', '').strip()
    date = datetime.date.today().isoformat()

    def sec(title, items, cls='list'):
        return f'<section><h2>{esc(title)}</h2><ul class="{cls}">{"".join(items)}</ul></section>' if items else ''

    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(cfg.get("title", "Getting to the cave"))} · Swildons Hole</title>
{R.FONTS}<style>{R.CSS}{CSS}</style></head><body>
<div class="sheet surface">
<header><div>
  <div class="kicker">Swildons Hole · on the surface</div>
  <h1>{esc(cfg.get("title", "Getting to the cave"))}</h1>
  <div class="subtitle">{esc(cfg.get("subtitle", ""))}</div>
  <div class="desc">{esc(" ".join(cfg.get("description", "").split()))}</div>
</div><div class="stats">
  {f'<div class="stat"><b>{esc(gridref)}</b><span>entrance, OS grid</span></div>' if gridref else ''}
  <div class="stat"><b>{ent[1]:.5f}, {ent[0]:.5f}</b><span>entrance, lat / long</span></div>
</div></header>
<div class="overview">{svg}{R.NORTH}{scalebar}
  <button id="locate" type="button">Show where I am</button><div id="where"></div></div>
<aside>
  {sec("Parking", park_html)}
  {sec("Walks to the entrance", walk_html)}
  {sec("On the way", poi_html)}
  <section><h2>The entrance</h2><p>{esc(ent_name)}: {('grid reference ' + esc(gridref) + ', ') if gridref else ''}{ent[1]:.5f}, {ent[0]:.5f}.
  <a href="https://www.google.com/maps/search/?api=1&amp;query={ent[1]:.6f},{ent[0]:.6f}">Show on Google Maps</a>.</p></section>
  {f'<section><h2>Access</h2><p>{esc(access)}</p></section>' if access else ''}
</aside>
<footer><div class="legend">
  <span><svg width="14mm" height="5mm" viewBox="0 0 14 5"><path d="M1 2.5 L13 2.5" stroke="#fff" stroke-width="2.6"/><path d="M1 2.5 L13 2.5" stroke="{WALK}" stroke-width="1.5"/></svg> Walk to the entrance</span>
  <span><svg width="6mm" height="6mm" viewBox="-3 -3 6 6"><rect x="-2.6" y="-2.6" width="5.2" height="5.2" rx="0.7" fill="{PARK}"/><text text-anchor="middle" dy="0.36em" font-size="3.6" fill="#fff" font-weight="700">P</text></svg> Parking</span>
  <span><svg width="6mm" height="6mm" viewBox="-3 -3 6 6"><circle r="2.6" fill="{R.INK}"/><path d="M-1.4 1.2 L-1.4 -0.1 A1.4 1.4 0 0 1 1.4 -0.1 L1.4 1.2 Z" fill="#fff"/></svg> The entrance</span>
</div><div class="credit">Map © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors.
Access and parking can change: check before you go. Made {date}.</div></footer>
</div>
<script>
// "Show where I am": the phone's position as a dot on the map (no network needed)
(function () {{
  var z = {z}, ox = {ox:.3f}, oy = {oy:.3f}, vb = [0, 0, {W:.1f}, {H:.1f}];
  var ent = [{ent[0]:.6f}, {ent[1]:.6f}];
  function merc(lon, lat) {{
    var n = 256 * Math.pow(2, z), s = Math.sin(lat * Math.PI / 180);
    return [(lon + 180) / 360 * n - ox, (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * n - oy];
  }}
  function metres(a, b) {{
    var r = Math.PI / 180, la1 = a[1] * r, la2 = b[1] * r, dl = (b[0] - a[0]) * r;
    var h = Math.pow(Math.sin((la2 - la1) / 2), 2) + Math.cos(la1) * Math.cos(la2) * Math.pow(Math.sin(dl / 2), 2);
    return 12742000 * Math.asin(Math.sqrt(h));
  }}
  var btn = document.getElementById('locate'), out = document.getElementById('where');
  if (!navigator.geolocation) {{ btn.style.display = 'none'; return; }}
  btn.addEventListener('click', function () {{
    out.textContent = 'Finding you…';
    navigator.geolocation.watchPosition(function (p) {{
      var me = [p.coords.longitude, p.coords.latitude], xy = merc(me[0], me[1]);
      var g = document.getElementById('here');
      var inside = xy[0] > vb[0] && xy[0] < vb[0] + vb[2] && xy[1] > vb[1] && xy[1] < vb[1] + vb[3];
      g.setAttribute('transform', 'translate(' + xy[0] + ' ' + xy[1] + ')');
      g.style.display = inside ? '' : 'none';
      var d = metres(me, ent);
      out.textContent = (inside ? '' : 'Off the map: ') + 'the entrance is ' +
        (d < 1000 ? Math.round(d) + ' m' : (d / 1000).toFixed(1) + ' km') + ' away (±' + Math.round(p.coords.accuracy) + ' m)';
    }}, function (e) {{ out.textContent = 'Location not available: ' + e.message; }},
    {{ enableHighAccuracy: true }});
  }});
}})();
</script>
</body></html>'''
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, 'index.html')
    open(out, 'w').write(page)
    return out, z, len(parks), len(walks)


CSS = '''
/* A4 landscape: easy to print for a visiting club */
@page { size: 297mm 210mm; margin: 0; }
body:has(.sheet.surface) { width: 297mm; height: 210mm; }
.sheet.surface { width: 297mm; height: 210mm; padding: 8mm 9mm 5mm; column-gap: 6mm; row-gap: 3mm;
                 grid-template-columns: 180mm 1fr; grid-template-rows: auto minmax(0, 1fr) auto; }
.surface h1 { font-size: 9mm; }
.surface .subtitle { font-size: 4mm; }
.surface .desc { font-size: 3.2mm; }
.surface .overview { grid-row: 2; }
.surface aside { grid-row: 2; display: block; overflow: hidden; font-size: 3mm; line-height: 1.35; }
.surface aside section { margin-bottom: 3.2mm; }
.surface aside h2 { margin: 0 0 1.2mm; }
.surface aside ul { margin: 0; padding: 0; }
.surface aside ul.list { list-style: none; }
.surface aside ul.list li { margin-bottom: 1.8mm; }
.surface aside ul.bullets { padding-left: 4mm; }
.surface aside p { margin: 0; }
.surface .meta { color: #5b6573; font-size: 2.7mm; }
.surface .links { font-size: 2.7mm; margin-top: 0.4mm; }
.surface .coord { color: #5b6573; }
.surface a { color: #1f5fbf; }
.surface .stats { grid-template-columns: 52mm; }
.surface .stat b { font-size: 4.6mm; }
#locate { position: absolute; top: 4mm; left: 4mm; font: 600 3mm "Source Sans 3", Arial, sans-serif; padding: 1.6mm 3mm;
          border: 0.3mm solid #1f5fbf; color: #1f5fbf; background: #fff; border-radius: 2mm; }
#where { position: absolute; top: 12mm; left: 4mm; font-size: 2.8mm; background: rgba(255,255,255,0.9); padding: 0 1.5mm; border-radius: 1mm; }
@media print { #locate, #where { display: none; } }
/* Any screen: flows to fit; the A4 sheet is only for printing */
@media screen {
  .sheet.surface { width: auto; height: auto; display: block; padding: 14px; }
  .surface aside { font-size: 15px; margin-top: 16px; }
  .surface .meta, .surface .links { font-size: 13px; }
  .surface .stats { grid-template-columns: 1fr 1fr; }
  .surface .stat b { font-size: 16px; }
  .surface .overview { aspect-ratio: 180 / 150; }
  body:has(.sheet.surface) { width: auto; height: auto; }
  #locate { font-size: 14px; padding: 8px 12px; } #where { top: 52px; font-size: 13px; }
}
/* A laptop or bigger: the map beside the parking and walks */
@media screen and (min-width: 900px) {
  .sheet.surface { display: grid; max-width: 1280px; margin: 0 auto; padding: 28px 32px; column-gap: 28px;
                   grid-template-columns: minmax(0, 1.7fr) minmax(280px, 1fr); grid-template-rows: auto auto auto; }
  .surface header { grid-column: 1 / 3; display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 32px; }
  .surface h1 { font-size: 40px; } .surface .subtitle { font-size: 19px; } .surface .desc { font-size: 16px; }
  .surface .stats { grid-template-columns: 1fr; width: 260px; margin-top: 0; }
  .surface .overview { grid-column: 1; grid-row: 2; margin-top: 18px; align-self: start; }
  .surface aside { grid-column: 2; grid-row: 2; margin-top: 18px; }
  .surface footer { grid-column: 1 / 3; display: flex; justify-content: space-between; gap: 24px; margin-top: 18px; }
}
'''


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m tools.surface', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='surface/surface.toml')
    ap.add_argument('--geojson', help='walks and parking (default: from the config)')
    ap.add_argument('--out', default='output/surface')
    ap.add_argument('--no-pdf', action='store_true')
    a = ap.parse_args(argv)
    cfg = tomllib.load(open(a.config, 'rb')) if os.path.exists(a.config) else {}
    gpath = a.geojson or os.path.join(os.path.dirname(a.config), cfg.get('geojson', 'surface.geojson'))
    gj = json.load(open(gpath)) if os.path.exists(gpath) else None
    if gj is None:
        print(f"no {gpath}: the map will have the cave and entrance but no walks or parking")
    out, z, np_, nw = build(cfg, gj, a.out)
    print(f"{out}: zoom {z}, {np_} parking, {nw} walks")
    if not a.no_pdf:
        from tools.routes.__main__ import to_pdf
        pdf = to_pdf(out)
        if pdf:
            print(pdf)


if __name__ == '__main__':
    main()
