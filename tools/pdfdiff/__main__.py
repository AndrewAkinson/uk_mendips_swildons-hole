"""Visual diffs of the built sheets, for reviewing a pull request.

    python3 -m tools.pdfdiff --base https://cavesurveying.github.io/uk_mendips_swildons-hole/ \\
                             --head output --out pr-diff

Renders every sheet (output/*.pdf) from this build and from the base (the
published survey site, or a folder of PDFs), and writes, for each sheet
that changed:

- an overview of the whole sheet, with what was removed in red, what was
  added in blue and everything unchanged in pale grey, and each changed
  area boxed and numbered
- for each changed area, a close-up of that diff and the same area as it
  now looks

and manifest.json listing them. CI posts these on the pull request (see
.github/workflows/pr-comment.yml).

When a sheet's size has changed, usually because the drawing has grown,
the two renders are lined up on the drawing before comparing them, so
the header and legend may show as moved.

Needs pdftoppm (poppler-utils), numpy and Pillow.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFont

UA = 'uk_mendips_swildons-hole PR diff (https://github.com/CaveSurveying/uk_mendips_swildons-hole)'
DPI = 150           # 1 m at 1:500 is about 12 px: enough to see a wall move
THRESHOLD = 0.25    # how much a pixel's ink must change to count...
SLACK = 1           # ...beyond its neighbours this many px away, so a sub-pixel shift doesn't
MIN_PIXELS = 20     # areas with fewer changed pixels than this are rendering noise
BLOCK = 16          # px: changed pixels are grouped into areas on this grid...
JOIN = 3            # ...and areas within this many blocks of each other merge
PAD = 80            # px of context around each close-up
MAX_AREAS = 8
OVERVIEW_W = 1600
CLOSEUP_W = 1400
CLOSEUP_MIN_W = 600 # small close-ups are enlarged to this, up to 3 times
REMOVED = np.array([0.84, 0.15, 0.16])
ADDED = np.array([0.12, 0.40, 0.85])
UNCHANGED = 0.35    # how dark unchanged ink is drawn


# -- rendering -------------------------------------------------------------------------

def render(pdf, gray=True):
    """The first page of a PDF at DPI, as a Pillow image."""
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, 'page')
        subprocess.run(['pdftoppm', '-r', str(DPI), '-singlefile', '-f', '1', '-l', '1',
                        '-gray' if gray else '-png', pdf, prefix], check=True)
        out = glob.glob(prefix + '.*')[0]
        im = Image.open(out)
        im.load()
        return im


def ink(im):
    """How much ink is on each pixel, 0 (white) to 1 (black)."""
    return 1 - np.asarray(im.convert('L'), dtype=np.float32) / 255


def offset(a, b):
    """Where b's top-left corner sits in a's coordinates, found by lining up
    their ink: cross-correlated at a quarter of the size, then refined."""
    def small(x):
        h, w = x.shape[0] // 4 * 4, x.shape[1] // 4 * 4
        return x[:h, :w].reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3))
    sa, sb = small(a), small(b)
    shape = (sa.shape[0] + sb.shape[0], sa.shape[1] + sb.shape[1])
    corr = np.fft.irfft2(np.fft.rfft2(sa, shape) * np.conj(np.fft.rfft2(sb, shape)), shape)
    y, x = np.unravel_index(np.argmax(corr), shape)
    dy = (y if y < sa.shape[0] else y - shape[0]) * 4
    dx = (x if x < sa.shape[1] else x - shape[1]) * 4
    best = None
    for ry in range(dy - 4, dy + 5):
        for rx in range(dx - 4, dx + 5):
            ca, cb = canvas(a, b, ry, rx)
            score = np.abs(ca - cb).sum()
            if best is None or score < best[0]:
                best = (score, ry, rx)
    return best[1], best[2]


def canvas(a, b, dy, dx):
    """a and b on one canvas, with b's top-left at (dy, dx) in a's coordinates."""
    y0, x0 = min(0, dy), min(0, dx)
    h = max(a.shape[0], dy + b.shape[0]) - y0
    w = max(a.shape[1], dx + b.shape[1]) - x0
    ca = np.zeros((h, w), np.float32)
    cb = np.zeros((h, w), np.float32)
    ca[-y0:-y0 + a.shape[0], -x0:-x0 + a.shape[1]] = a
    cb[dy - y0:dy - y0 + b.shape[0], dx - x0:dx - x0 + b.shape[1]] = b
    return ca, cb


# -- finding what changed --------------------------------------------------------------

def neighbourhood(x, op):
    """op (np.maximum or np.minimum) of each pixel and its neighbours within SLACK px."""
    out = x.copy()
    for dy in range(-SLACK, SLACK + 1):
        for dx in range(-SLACK, SLACK + 1):
            out[max(0, dy):x.shape[0] + min(0, dy), max(0, dx):x.shape[1] + min(0, dx)] = op(
                out[max(0, dy):x.shape[0] + min(0, dy), max(0, dx):x.shape[1] + min(0, dx)],
                x[max(0, -dy):x.shape[0] + min(0, -dy), max(0, -dx):x.shape[1] + min(0, -dx)])
    return out


def changes(a, b):
    """The pixels whose ink differs between a and b by more than THRESHOLD,
    even allowing for a shift of up to SLACK px either way."""
    def gone(x, y):
        return (x > neighbourhood(y, np.maximum) + THRESHOLD) | (x < neighbourhood(y, np.minimum) - THRESHOLD)
    return gone(a, b) & gone(b, a)


def areas(changed):
    """Bounding boxes (y0, x0, y1, x1) of the clusters of changed pixels,
    largest first, with how many changed pixels each holds."""
    h, w = changed.shape
    bh, bw = -(-h // BLOCK), -(-w // BLOCK)
    padded = np.zeros((bh * BLOCK, bw * BLOCK), bool)
    padded[:h, :w] = changed
    counts = padded.reshape(bh, BLOCK, bw, BLOCK).sum(axis=(1, 3))
    grown = counts > 0
    for _ in range(JOIN):
        g = grown.copy()
        g[1:] |= grown[:-1]; g[:-1] |= grown[1:]
        g[:, 1:] |= grown[:, :-1]; g[:, :-1] |= grown[:, 1:]
        grown = g
    seen = np.zeros_like(grown)
    found = []
    for sy, sx in zip(*np.nonzero(grown)):
        if seen[sy, sx]:
            continue
        seen[sy, sx] = True
        stack, cells = [(sy, sx)], []
        while stack:
            y, x = stack.pop()
            cells.append((y, x))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < bh and 0 <= nx < bw and grown[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        ys, xs = zip(*cells)
        n = int(sum(counts[y, x] for y, x in cells))
        if n >= MIN_PIXELS:
            sub = changed[min(ys) * BLOCK:(max(ys) + 1) * BLOCK, min(xs) * BLOCK:(max(xs) + 1) * BLOCK]
            iy, ix = np.nonzero(sub)
            y0, x0 = min(ys) * BLOCK + iy.min(), min(xs) * BLOCK + ix.min()
            y1, x1 = min(ys) * BLOCK + iy.max() + 1, min(xs) * BLOCK + ix.max() + 1
            found.append((n, (max(0, y0 - PAD), max(0, x0 - PAD), min(h, y1 + PAD), min(w, x1 + PAD))))
    found.sort(key=lambda f: -f[0])
    return found


def diff_image(a, b):
    """Removed ink in red, added in blue, unchanged in pale grey."""
    common = np.minimum(a, b)
    out = np.ones(a.shape + (3,), np.float32) - (common * UNCHANGED)[..., None]
    out -= (a - common)[..., None] * (1 - REMOVED)
    out -= (b - common)[..., None] * (1 - ADDED)
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))


def shrink(im, width, at_least=0):
    """im scaled down to width, or up towards at_least (no more than 3 times)."""
    if im.width > width:
        target = width
    elif im.width < at_least:
        target = min(at_least, im.width * 3)
    else:
        return im
    return im.resize((target, round(im.height * target / im.width)), Image.LANCZOS)


def save(im, path):
    im.save(path, optimize=True)
    return os.path.basename(path)


def font(size):
    for f in ('fonts/SourceSans3-Semibold.otf', 'fonts/SourceSans3-Regular.otf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


# -- one sheet -------------------------------------------------------------------------

def compare(name, base_pdf, head_pdf, out):
    stem = os.path.splitext(name)[0]
    if base_pdf is None:
        im = shrink(render(head_pdf, gray=False).convert('RGB'), OVERVIEW_W)
        return {'pdf': name, 'status': 'new', 'overview': save(im, os.path.join(out, f'{stem}-new.png'))}
    a, b = ink(render(base_pdf)), ink(render(head_pdf))
    dy = dx = 0
    if a.shape != b.shape:
        dy, dx = offset(a, b)
    ca, cb = canvas(a, b, dy, dx)
    found = areas(changes(ca, cb))
    sheet = {'pdf': name, 'status': 'changed' if found else 'unchanged',
             'resized': a.shape != b.shape}
    if not found:
        return sheet

    diff = diff_image(ca, cb)
    after = Image.new('RGB', diff.size, 'white')
    after.paste(render(head_pdf, gray=False).convert('RGB'), (dx - min(0, dx), dy - min(0, dy)))

    overview = shrink(diff, OVERVIEW_W)
    k = overview.width / diff.width
    draw = ImageDraw.Draw(overview)
    label = font(22)
    shown = found[:MAX_AREAS]
    for i, (_, (y0, x0, y1, x1)) in enumerate(shown, 1):
        box = (x0 * k, y0 * k, x1 * k, y1 * k)
        draw.rectangle(box, outline=(230, 140, 0), width=3)
        draw.text((box[0] + 4, box[1] + 2), str(i), fill=(230, 140, 0), font=label)
    sheet['overview'] = save(overview, os.path.join(out, f'{stem}-overview.png'))
    sheet['areas'] = []
    for i, (n, (y0, x0, y1, x1)) in enumerate(shown, 1):
        crop = (x0, y0, x1, y1)
        sheet['areas'].append({
            'pixels': n,
            'diff': save(shrink(diff.crop(crop), CLOSEUP_W, CLOSEUP_MIN_W), os.path.join(out, f'{stem}-{i}-diff.png')),
            'after': save(shrink(after.crop(crop), CLOSEUP_W, CLOSEUP_MIN_W), os.path.join(out, f'{stem}-{i}-after.png')),
        })
    sheet['more'] = len(found) - len(shown)
    return sheet


def fetch(base, name, tmp):
    """The base's copy of a sheet: a path, or None if the base hasn't got it."""
    if not base.startswith(('http://', 'https://')):
        path = os.path.join(base, name)
        return path if os.path.exists(path) else None
    url = urllib.parse.urljoin(base if base.endswith('/') else base + '/', name)
    try:
        data = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}),
                                      timeout=120).read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    path = os.path.join(tmp, name)
    with open(path, 'wb') as f:
        f.write(data)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m tools.pdfdiff', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True, help='URL of the published survey, or a folder of PDFs')
    ap.add_argument('--head', default='output', help='folder of the PDFs just built')
    ap.add_argument('--out', default='pr-diff')
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(a.head, '*.pdf')))
    sheets = []
    with tempfile.TemporaryDirectory() as tmp:
        for name in names:
            sheet = compare(name, fetch(a.base, name, tmp), os.path.join(a.head, name), a.out)
            sheets.append(sheet)
            n = len(sheet.get('areas', []))
            print(f"{name}: {sheet['status']}" + (f', {n} area(s)' if n else ''), file=sys.stderr)
    with open(os.path.join(a.out, 'manifest.json'), 'w') as f:
        json.dump({'base': a.base, 'sheets': sheets}, f, indent=1)


if __name__ == '__main__':
    main()
