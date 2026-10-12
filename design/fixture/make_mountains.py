"""Generate design/hifi/assets/mountains.svg: layered misty ridges, snow, pine treeline."""
import math
import random
from pathlib import Path

W, H = 1200, 520


def ridge(seed, base, peaks, rough=0.45, levels=6):
    """Peaks joined through explicit valleys, then midpoint displacement for rocky detail."""
    rng = random.Random(seed)
    peaks = sorted(peaks)
    anchors = [(0.0, base - peaks[0][1] * 0.35)]
    for (x1, h1), (x2, h2) in zip(peaks, peaks[1:]):
        anchors.append((x1, base - h1))
        vx = x1 + (x2 - x1) * rng.uniform(0.4, 0.6)
        anchors.append((vx, base - min(h1, h2) * rng.uniform(0.25, 0.5)))
    anchors.append((peaks[-1][0], base - peaks[-1][1]))
    anchors.append((float(W), base - peaks[-1][1] * 0.3))
    pts = anchors
    for lvl in range(levels):
        nxt = [pts[0]]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            span = x2 - x1
            mx = (x1 + x2) / 2 + rng.uniform(-0.08, 0.08) * span
            my = (y1 + y2) / 2 + rng.uniform(-1, 1) * span * 0.16 * (rough ** lvl)
            nxt += [(mx, my), (x2, y2)]
        pts = nxt
    return pts


def area(pts):
    return "M0,%d " % H + " ".join("L%.1f,%.1f" % p for p in pts) + " L%d,%d Z" % (W, H)


def snow(pts, depth, seed):
    """Snow caps: the part of the ridge within `depth` px of each local summit."""
    rng = random.Random(seed)
    top_y = min(y for _, y in pts)
    line = top_y + depth
    out, seg = [], []
    for p in pts + [(W, 10_000)]:
        if p[1] < line:
            seg.append(p)
            continue
        if len(seg) > 2:
            top = " ".join("L%.1f,%.1f" % q for q in seg)
            phase = rng.uniform(0, 6.28)
            bottom = " ".join(
                "L%.1f,%.1f" % (x, min(line, y + (line - y) * (0.86 + 0.1 * math.sin(x / 17 + phase) + 0.04 * math.sin(x / 6))))
                for x, y in reversed(seg))
            out.append("M%.1f,%.1f %s %s Z" % (seg[0][0], seg[0][1], top, bottom))
        seg = []
    return out


def trees(seed, base, n, hmin, hmax, color):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        x, h = rng.uniform(-20, W + 20), rng.uniform(hmin, hmax)
        w, y = h * rng.uniform(0.22, 0.3), base + rng.uniform(-10, 12)
        tiers = " ".join(
            "M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f Z" % (x, y - h + t * h * 0.28, x + w * (0.55 + t * 0.25), y - h * (0.55 - t * 0.25), x - w * (0.55 + t * 0.25), y - h * (0.55 - t * 0.25))
            for t in range(3))
        out.append('<path d="%s M%.1f,%.1f L%.1f,%.1f L%.1f,%.1f Z" fill="%s"/>' % (tiers, x, y - h * 0.4, x + w, y, x - w, y, color))
    return "".join(out)


far = ridge(3, 360, [(120, 130), (380, 205), (640, 150), (930, 230), (1140, 170)])
mid = ridge(8, 410, [(90, 120), (300, 230), (540, 160), (820, 300), (1080, 215)])
near = ridge(15, 450, [(180, 90), (480, 120), (760, 80), (1060, 130)], rough=0.6)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMax slice" role="img" aria-label="Misty snow-capped mountains above a pine forest">
<defs>
 <linearGradient id="far" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#C3D1E6"/><stop offset="1" stop-color="#E3EAF5"/></linearGradient>
 <linearGradient id="mid" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8EA2C2"/><stop offset=".55" stop-color="#B5C4DC"/><stop offset="1" stop-color="#DDE5F2"/></linearGradient>
 <linearGradient id="near" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#97ABC6"/><stop offset="1" stop-color="#CBD7E8"/></linearGradient>
 <linearGradient id="mist" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#EEF3FA" stop-opacity="0"/><stop offset=".5" stop-color="#EEF3FA" stop-opacity=".9"/><stop offset="1" stop-color="#EEF3FA" stop-opacity="0"/></linearGradient>
 <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6F8799"/><stop offset="1" stop-color="#4E6677"/></linearGradient>
</defs>
<path d="{area(far)}" fill="url(#far)"/>
{"".join(f'<path d="{p}" fill="#F8FBFF" opacity=".85"/>' for p in snow(far, 85, 1))}
<rect y="280" width="{W}" height="120" fill="url(#mist)"/>
<path d="{area(mid)}" fill="url(#mid)"/>
{"".join(f'<path d="{p}" fill="#FBFDFF" opacity=".95"/>' for p in snow(mid, 125, 2))}
<rect y="320" width="{W}" height="120" fill="url(#mist)" opacity=".85"/>
<path d="{area(near)}" fill="url(#near)" opacity=".85"/>
<rect y="380" width="{W}" height="100" fill="url(#mist)" opacity=".8"/>
{trees(5, 452, 150, 22, 44, "#A2B5C6")}
{trees(9, 478, 190, 30, 58, "#7F97AA")}
{trees(13, 506, 220, 36, 74, "#5D7789")}
<rect y="492" width="{W}" height="{H-492}" fill="url(#ground)"/>
</svg>'''
Path(__file__).parents[1].joinpath("hifi/assets/mountains.svg").write_text(svg)
print("ok", len(svg))
