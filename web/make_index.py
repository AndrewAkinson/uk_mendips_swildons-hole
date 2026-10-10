#!/usr/bin/env python3
"""
Build output/index.html -- the GitHub Pages landing page for this survey.

Run after Therion, from the project root:

    python3 web/make_index.py

It renders a PNG preview of the first page of each PDF (via Ghostscript,
which the Therion container already has), reads the survey statistics out
of output/therion.log, and writes a single self-contained index.html next to the
artefacts. No third-party Python packages.
"""

import html
import glob
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "output")
PREVIEW_DIR = os.path.join(OUT, "previews")

# (filename, title, blurb) -- order is the order they appear on the page.
SHEETS = [
    ("Swildons-plan.pdf",               "Plan",                     "Entrance to Sump 1, coloured by altitude, with cross-sections along the streamway. Scale 1:500."),
    ("Swildons-extended-elevation.pdf", "Extended elevation",      "The whole drawn cave unrolled along its passages, entrance to Sump 1. Scale 1:500."),
    ("Swildons-streamway-elevation.pdf", "Streamway elevation",     "Extended elevation from the Old 40 to Sump 1, with Barnes Loop above the streamway. Scale 1:500."),
    ("Swildons-entrance-plan.pdf",      "Entrance Series",          "The Entrance Series down to Rolling Thunder, with cross-sections; the entrances and Zig Zags drawn to one side, clear of the passages beneath. Scale 1:200."),
    ("Swildons-entrance-extended-elevation.pdf", "Entrance Series extended elevation", "The Entrance Series unrolled along its passages. Scale 1:200."),
    ("Swildons-entrance-elevation.pdf", "Entrance Series east-west elevation", "Footleg's projected elevation; only partly drawn so far. Scale 1:200."),
    ("Swildons-plan-bw.pdf",            "Plan, greyscale",          "Same drawing, for a black-and-white printer."),
    ("Swildons-plan-centreline.pdf",    "Plan with centreline",     "The plan with survey legs and station names, for resurveying. Scale 1:500."),
    ("Swildons-plan-with-stanton.pdf",  "Plan with Stanton's survey", "The plan plus W. I. Stanton's survey beyond it as centreline, with station names, for planning the resurvey. Scale 1:500."),
]

DATA = [
    ("Swildons.3d",                 "Survex 3D model",   "The whole centreline. Opens in Aven."),
    ("Swildons.lox",                "Loch 3D model",     "Therion's own viewer format."),
    ("Swildons.vrml",               "VRML model",        "For generic 3D viewers."),
    ("Swildons-plan.svg",           "Plan, SVG",         "Vector -- edit in Inkscape or Illustrator."),
    ("Swildons-entrance-plan.svg",  "Entrance Series, SVG", "Vector, 1:200."),
    ("Swildons-plan.kml",           "Plan, KML",         "Drawn passage outlines for Google Earth."),
    ("Swildons-centreline.kml",     "Centreline, KML",   "The whole centreline for Google Earth."),
    ("Swildons-map.geojson",        "Plan, GeoJSON",     "The drawing in lat/long: passage outlines, water, walls, detail and names, each with its altitude. For QGIS or a web map."),
    ("Swildons-centreline.geojson", "Centreline, GeoJSON", "Every leg and station in lat/long with altitude, Stanton's marked, and the rock above each station."),
    ("Swildons-caves.html",         "Cave list",         "Summary table."),
    ("Swildons-surveys.html",       "Survey list",       "Every survey trip, with length and team."),
    ("Swildons-continuations.html", "Continuations",     "Leads still to push."),
    ("Swildons.csv",                "Centreline, CSV",   "Raw shots."),
    ("Swildons.sql",                "Centreline, SQL",   "Raw shots."),
]


def human(n):
    for unit in ("B", "kB", "MB"):
        if n < 1024 or unit == "MB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0


def render_preview(pdf_path, png_path, width=1100):
    """First page of a PDF to PNG. Ghostscript first, ImageMagick second."""
    gs = shutil.which("gs") or shutil.which("gswin64c")
    if gs:
        cmd = [gs, "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER",
               "-sDEVICE=png16m", "-r80", "-dFirstPage=1", "-dLastPage=1",
               "-dTextAlphaBits=4", "-dGraphicsAlphaBits=4",
               "-sOutputFile=" + png_path, pdf_path]
    else:
        magick = shutil.which("magick") or shutil.which("convert")
        if not magick:
            return False
        cmd = [magick, "-density", "80", pdf_path + "[0]",
               "-background", "white", "-alpha", "remove",
               "-resize", f"{width}x", png_path]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=180)
        return os.path.exists(png_path)
    except Exception:
        return False


def survey_stats():
    """Headline numbers, from the centreline CSV and output/therion.log.

    Deliberately NOT from the log's "Survey contains N survey stations"
    line: Survex counts every splay endpoint as a station, so for this
    survey it reports over 2,700 rather than the stations actually on
    the centreline. The CSV has a row per shot with "-" as the To
    station for splays, which lets us separate them properly, plus
    blocks of equated station pairs, which have to be merged.
    """
    stats = {}
    csv_path = os.path.join(OUT, "Swildons.csv")
    if os.path.exists(csv_path):
        import csv as _csv
        legs = splays = 0
        names = set()
        # Between "# Equated stations" and "# End equated stations" the
        # CSV lists From,To pairs with no length: two names for one
        # station, not a leg. Merge them so they count once.
        parent = {}

        def find(n):
            while parent.get(n, n) != n:
                n = parent[n]
            return n

        with open(csv_path, newline="", errors="replace") as fh:
            for row in _csv.DictReader(fh):
                frm = (row.get("From") or "").strip()
                to = (row.get("To") or "").strip()
                if frm.startswith("#"):
                    continue
                if not (row.get("Length(m)") or "").strip():
                    if frm and to:
                        parent[find(frm)] = find(to)
                    continue
                if frm and frm != "-":
                    names.add(frm)
                if to in ("-", "."):
                    splays += 1
                else:
                    legs += 1
                    if to:
                        names.add(to)
        names = {find(n) for n in names}
        if names:
            stats["Stations"] = str(len(names))
            stats["Legs"] = str(legs)
            stats["Splay shots"] = str(splays)

    log = os.path.join(ROOT, "output", "therion.log")
    if not os.path.exists(log):
        return stats
    text = open(log, "r", errors="replace").read()
    m = re.search(r"Total length of survey legs\s*=\s*([\d.]+)m", text)
    if m:
        stats["Surveyed length"] = f"{float(m.group(1)):.1f} m"
    m = re.search(r"Vertical range = ([\d.]+)m", text)
    if m:
        stats["Vertical range"] = f"{float(m.group(1)):.2f} m"
    m = re.search(r"output coordinate system:\s*(\S+)", text)
    if m:
        stats["Coordinate system"] = m.group(1)
    return stats


def main():
    if not os.path.isdir(OUT):
        sys.exit("no output/ directory -- run therion first")
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    sha = os.environ.get("GITHUB_SHA", "")
    ref = os.environ.get("GITHUB_REF_NAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    cards = []
    for fn, title, blurb in SHEETS:
        path = os.path.join(OUT, fn)
        if not os.path.exists(path):
            continue
        png = os.path.join(PREVIEW_DIR, fn.replace(".pdf", ".png"))
        has_png = render_preview(path, png)
        cards.append({
            "file": fn, "title": title, "blurb": blurb,
            "size": human(os.path.getsize(path)),
            "png": "previews/" + os.path.basename(png) if has_png else None,
        })

    rows = []
    for fn, title, blurb in DATA:
        path = os.path.join(OUT, fn)
        if os.path.exists(path):
            rows.append((fn, title, blurb, human(os.path.getsize(path))))

    stats = survey_stats()

    e = html.escape
    doc = []
    doc.append(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swildons Hole &mdash; cave survey</title>
<style>
  :root {{
    --bg:#ffffff; --fg:#1a1d22; --muted:#5a6068; --line:#e2e5e9;
    --card:#fbfcfd; --accent:#2f6f7e;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#14171a; --fg:#e8eaed; --muted:#9aa3ad; --line:#2a2f35;
             --card:#1b1f23; --accent:#7fc3d3; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--fg);
    font:16px/1.55 "DejaVu Sans", ui-sans-serif, system-ui, -apple-system,
    "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:48px 24px 80px; }}
  header {{ border-bottom:2px solid var(--fg); padding-bottom:18px; margin-bottom:8px; }}
  h1 {{ font-size:44px; font-weight:600; margin:0 0 6px; letter-spacing:-.5px; }}
  .sub {{ color:var(--muted); font-style:italic; margin:0; }}
  .meta {{ display:flex; flex-wrap:wrap; gap:28px; padding:16px 0 28px;
    border-bottom:1px solid var(--line); margin-bottom:36px; }}
  .meta div {{ min-width:110px; }}
  .meta dt {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); margin:0 0 3px; }}
  .meta dd {{ margin:0; font-size:17px; }}
  h2 {{ font-size:12px; letter-spacing:.11em; text-transform:uppercase;
    color:var(--muted); font-weight:600; margin:44px 0 16px; }}
  .grid {{ display:grid; gap:22px;
    grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); }}
  .card {{ border:1px solid var(--line); border-radius:10px; overflow:hidden;
    background:var(--card); display:flex; flex-direction:column;
    transition:border-color .15s, transform .15s; }}
  .card:hover {{ border-color:var(--accent); transform:translateY(-2px); }}
  .card a.thumb {{ display:block; background:#fff; border-bottom:1px solid var(--line);
    aspect-ratio:4/3; overflow:hidden; }}
  .card a.thumb img {{ width:100%; height:100%; object-fit:contain;
    object-position:center top; display:block; }}
  .card .body {{ padding:14px 16px 16px; }}
  .card h3 {{ margin:0 0 4px; font-size:18px; font-weight:600; }}
  .card h3 a {{ color:inherit; text-decoration:none; }}
  .card h3 a:hover {{ color:var(--accent); }}
  .card p {{ margin:0; color:var(--muted); font-size:14px; }}
  .card .size {{ margin-top:8px; font-size:12px; color:var(--muted);
    font-variant-numeric:tabular-nums; }}
  table {{ width:100%; border-collapse:collapse; font-size:15px; }}
  th, td {{ text-align:left; padding:9px 12px 9px 0; border-bottom:1px solid var(--line); }}
  th {{ font-size:11px; letter-spacing:.09em; text-transform:uppercase;
    color:var(--muted); font-weight:600; }}
  td a {{ color:var(--accent); text-decoration:none; font-weight:500; }}
  td a:hover {{ text-decoration:underline; }}
  td.blurb {{ color:var(--muted); }}
  td.size {{ text-align:right; padding-right:0; color:var(--muted);
    font-variant-numeric:tabular-nums; white-space:nowrap; }}
  footer {{ margin-top:56px; padding-top:20px; border-top:1px solid var(--line);
    color:var(--muted); font-size:13px; }}
  footer a {{ color:var(--accent); }}
  code {{ font-family:ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size:.9em; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Swildons Hole</h1>
  <p class="sub">Priddy, Mendip &mdash; resurvey led by Paul &lsquo;Footleg&rsquo; Fretwell. Built automatically from the survey data in this repository.</p>
</header>

<dl class="meta">""")

    for k, v in stats.items():
        doc.append(f"  <div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>")
    doc.append(f'  <div><dt>Built</dt><dd>{e(built)}</dd></div>')
    if sha:
        short = sha[:7]
        link = f"https://github.com/{repo}/commit/{sha}" if repo else "#"
        doc.append(f'  <div><dt>Commit</dt><dd><a href="{e(link)}"><code>{e(short)}</code></a>'
                   + (f" on {e(ref)}" if ref else "") + "</dd></div>")
    doc.append("</dl>")

    doc.append("<h2>Sheets</h2>\n<div class=\"grid\">")
    for c in cards:
        thumb = (f'<a class="thumb" href="{e(c["file"])}">'
                 f'<img src="{e(c["png"])}" alt="{e(c["title"])} preview" loading="lazy"></a>'
                 if c["png"] else "")
        doc.append(f"""  <div class="card">
    {thumb}
    <div class="body">
      <h3><a href="{e(c['file'])}">{e(c['title'])}</a></h3>
      <p>{e(c['blurb'])}</p>
      <div class="size">PDF &middot; {e(c['size'])}</div>
    </div>
  </div>""")
    doc.append("</div>")

    # The 3D view (tools/model3d), if it was built
    if os.path.exists(os.path.join(OUT, "3d", "index.html")):
        thumb = ('<a class="thumb" href="3d/index.html"><img src="3d/preview.png" '
                 'alt="The cave in 3D beneath the ground" loading="lazy"></a>'
                 if os.path.exists(os.path.join(OUT, "3d", "preview.png")) else "")
        doc.append(f"""<h2>In 3D</h2>\n<div class="grid">
  <div class="card">
    {thumb}
    <div class="body">
      <h3><a href="3d/index.html">The cave beneath the ground</a></h3>
      <p>The survey in 3D under the Environment Agency&rsquo;s LIDAR ground surface and satellite imagery. Drag to turn it, scroll or pinch to zoom.</p>
      <div class="size"><a href="3d/index.html">Open in the browser</a></div>
    </div>
  </div>
</div>""")

    # The 2D map (tools/webmap), if it was built
    if os.path.exists(os.path.join(OUT, "map", "index.html")):
        thumb = ('<a class="thumb" href="map/index.html"><img src="map/preview.png" '
                 'alt="The cave on the map, under the fields at Priddy" loading="lazy"></a>'
                 if os.path.exists(os.path.join(OUT, "map", "preview.png")) else "")
        doc.append(f"""<h2>On the map</h2>\n<div class="grid">
  <div class="card">
    {thumb}
    <div class="body">
      <h3><a href="map/index.html">The cave under the fields</a></h3>
      <p>The plan over OpenStreetMap or satellite imagery, with the ground&rsquo;s shape from LIDAR. Click a passage for its depth and the rock above it, or turn on the stations.</p>
      <div class="size"><a href="map/index.html">Open the map</a> &middot; <a href="Swildons-map.geojson">GeoJSON</a></div>
    </div>
  </div>
</div>""")

    # The surface map (tools/surface), if it was built
    surf = os.path.join(OUT, "surface", "index.html")
    if os.path.exists(surf):
        spdf = os.path.join(OUT, "surface", "index.pdf")
        png = os.path.join(PREVIEW_DIR, "surface.png")
        has_png = os.path.exists(spdf) and render_preview(spdf, png)
        thumb = (f'<a class="thumb" href="surface/index.html"><img src="previews/surface.png" '
                 f'alt="Surface map preview" loading="lazy"></a>' if has_png else "")
        pdf_link = (f' &middot; <a href="surface/index.pdf">PDF to print, A4</a>' if os.path.exists(spdf) else "")
        doc.append(f"""<h2>Getting there</h2>\n<div class="grid">
  <div class="card">
    {thumb}
    <div class="body">
      <h3><a href="surface/index.html">Getting to Swildons Hole</a></h3>
      <p>Where to park and the walk to the entrance, for visitors new to the area.</p>
      <div class="size"><a href="surface/index.html">On screen or phone</a>{pdf_link}</div>
    </div>
  </div>
</div>""")

    # Route cards (tools/routes), if they were built
    routes = sorted(glob.glob(os.path.join(OUT, "routes", "*.pdf")))
    if routes:
        doc.append("<h2>Route cards <small>(draft)</small></h2>\n"
                   "<p>Routes through the cave with the way to go at each junction, worked out "
                   "from the survey. Not yet checked underground. Open a card on your phone (save the page "
                   "to have it offline underground), or print the PDF at A3.</p>\n<div class=\"grid\">")
        for pdf in routes:
            name = os.path.basename(pdf)
            htm_name = name[:-4] + ".html"
            htm = os.path.join(OUT, "routes", htm_name)
            title, sub = name, ""
            if os.path.exists(htm):
                head = open(htm, encoding="utf-8").read(6000)
                m = re.search(r"<title>(.*?) ·", head)
                title = html.unescape(m.group(1)) if m else name
            # the subtitle is after the embedded drawing, further into the file
            if os.path.exists(htm):
                m = re.search(r'<div class="subtitle">(.*?)</div>', open(htm, encoding="utf-8").read())
                sub = html.unescape(m.group(1)) if m else ""
            # the HTML card is the main link: it reflows on a phone (and
            # works offline once saved), and prints as the A3 sheet
            main = f"routes/{htm_name}" if os.path.exists(htm) else f"routes/{name}"
            png = os.path.join(PREVIEW_DIR, "route-" + name.replace(".pdf", ".png"))
            has_png = render_preview(pdf, png)
            thumb = (f'<a class="thumb" href="{e(main)}"><img src="previews/{e(os.path.basename(png))}" '
                     f'alt="{e(title)} preview" loading="lazy"></a>' if has_png else "")
            links = []
            if os.path.exists(htm):
                links.append(f'<a href="routes/{e(htm_name)}">On screen or phone</a>')
            links.append(f'<a href="routes/{e(name)}">PDF to print, A3</a> &middot; {e(human(os.path.getsize(pdf)))}')
            doc.append(f"""  <div class="card">
    {thumb}
    <div class="body">
      <h3><a href="{e(main)}">{e(title)}</a></h3>
      <p>{e(sub)}</p>
      <div class="size">{" &middot; ".join(links)}</div>
    </div>
  </div>""")
        doc.append("</div>")

    if rows:
        doc.append("<h2>Models and data</h2>\n<table>")
        doc.append("<tr><th>File</th><th>What it is</th><th style=\"text-align:right\">Size</th></tr>")
        for fn, title, blurb, size in rows:
            doc.append(f'<tr><td><a href="{e(fn)}">{e(title)}</a></td>'
                       f'<td class="blurb">{e(blurb)}</td>'
                       f'<td class="size">{e(size)}</td></tr>')
        doc.append("</table>")

    src = f"https://github.com/{repo}" if repo else "#"
    doc.append(f"""<footer>
  Generated by <code>web/make_index.py</code> from the Therion sources in
  <a href="{e(src)}">this repository</a>. Every push to <code>main</code> rebuilds this page.
</footer>
</div>
</body>
</html>""")

    with open(os.path.join(OUT, "index.html"), "w") as f:
        f.write("\n".join(doc))

    # Same numbers as markdown, so the workflow's job summary and PR
    # comment can reuse them instead of re-parsing the log themselves.
    with open(os.path.join(OUT, "stats.md"), "w") as f:
        for k, v in stats.items():
            f.write(f"- {k}: **{v}**\n")

    print(f"index.html written: {len(cards)} sheets, {len(rows)} data files")


if __name__ == "__main__":
    main()
