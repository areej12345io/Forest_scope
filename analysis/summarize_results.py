"""Reproduce the figures quoted in ANALYSIS.md.

Usage (from the project folder):
    python analysis/summarize_results.py
    python analysis/summarize_results.py cache/combined_results.json data/polygons.geojson

Uses only the Python standard library. Without the GeoJSON, the region and polygon-size
sections are skipped. Polygon ids are the position of each feature in the GeoJSON file
(1, 2, 3, ...), which is how db/load_polygons.py numbers them.
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict
from statistics import mean, median

RESULTS_PATH = sys.argv[1] if len(sys.argv) > 1 else "cache/combined_results.json"
GEOJSON_PATH = sys.argv[2] if len(sys.argv) > 2 else "data/polygons.geojson"

FORTY_BANDS = [
    "PrimaryForest",
    "NaturallyRegeneratingForest",
    "PlantedForest",
    "PlantationForest",
    "TreeCropsAndAgroforestry",
]
FOREST_BANDS_STRICT = FORTY_BANDS[:3]          # primary, naturally regenerating, planted

with open(RESULTS_PATH, encoding="utf-8") as file:
    results = json.load(file)["results"]
total = len(results)


# ---------- classification rules (same as the dashboard) ----------
def jrc_share(r):
    return r["jrc"]["forest_percentage"] or 0


def jrc_class(r):
    share = jrc_share(r)
    if share <= 0:
        return "none (0%)"
    return "full (100%)" if share >= 100 else "partial (1-99%)"


def forty_scores(r):
    values = r["forty"]["values"]
    scores = {b: (values[b] or 0) if values else 0 for b in FORTY_BANDS}
    scores["Other land (estimated)"] = max(0, 250 - sum(scores.values()))
    return scores


def forty_dominant(r):
    if not r["forty"]["values"]:
        return "No ForTy data"
    scores = forty_scores(r)
    return max(scores, key=scores.get)          # ties go to a forest class


def forty_forest(r):
    return forty_dominant(r) in FORTY_BANDS


def band_sum(r):
    values = r["forty"]["values"]
    return sum((values[b] or 0) for b in FORTY_BANDS) if values else 0


def agreement(r):
    jrc_any, forty_any = jrc_share(r) > 0, forty_forest(r)
    if jrc_any and forty_any:
        return "both"
    if forty_any:
        return "ForTy only"
    return "JRC only" if jrc_any else "neither"


def pct(n, d):
    return f"{100 * n / d:.1f}%" if d else "n/a"


def show(title, counter, n=None):
    n = n or total
    print(f"\n{title}")
    for key, count in counter.most_common():
        print(f"  {key:<34} {count:>4}  ({pct(count, n)})")


# ---------- 1. whole data set ----------
print(f"Polygons analysed: {total}")
show("JRC forest share of polygon", Counter(jrc_class(r) for r in results))
show("ForTy dominant class", Counter(forty_dominant(r) for r in results))
show("Agreement (JRC any forest vs ForTy forest-type dominant)", Counter(agreement(r) for r in results))

shares = [jrc_share(r) for r in results]
partial = [s for s in shares if 0 < s < 100]
print(f"\nJRC share: mean {mean(shares):.1f}%, median {median(shares):.1f}%"
      + (f"; partial polygons only: median {median(partial):.1f}%" if partial else ""))
sums = [band_sum(r) for r in results]
print(f"ForTy band sums: min {min(sums):.1f}, median {median(sums):.1f}, max {max(sums):.1f}")

cross = Counter((forty_dominant(r), jrc_class(r)) for r in results)
print("\nForTy dominant class x JRC result")
for key in sorted(cross):
    print(f"  {key[0]:<30} {key[1]:<16} {cross[key]:>4}")

by_year = defaultdict(list)
for r in results:
    by_year[str(r["year"])].append(r)
print("\nJRC 'none' and ForTy forest-type by deforestation year")
for year in sorted(by_year):
    group = by_year[year]
    print(f"  {year}: n={len(group):<3} JRC none {pct(sum(jrc_share(r) == 0 for r in group), len(group)):>6} "
          f"| ForTy forest type {pct(sum(forty_forest(r) for r in group), len(group)):>6}")

print("\nRule sensitivity")
for name, rule in [("JRC share > 0", lambda r: jrc_share(r) > 0),
                   ("JRC share >= 10%", lambda r: jrc_share(r) >= 10),
                   ("JRC share >= 50%", lambda r: jrc_share(r) >= 50),
                   ("JRC share = 100%", lambda r: jrc_share(r) >= 100)]:
    n = sum(rule(r) for r in results)
    print(f"  {name:<44} {n:>4}  ({pct(n, total)})")

for name, rule in [("ForTy: dominant class is one of the five", forty_forest),
                   ("ForTy: band sum >= 125", lambda r: band_sum(r) >= 125),
                   ("ForTy: band sum >= 200", lambda r: band_sum(r) >= 200),
                   ("ForTy: primary/natural/planted dominant only",
                    lambda r: forty_dominant(r) in FOREST_BANDS_STRICT)]:
    f = [rule(r) for r in results]
    j = [jrc_share(r) > 0 for r in results]
    both = sum(a and b for a, b in zip(f, j))
    fo = sum(a and not b for a, b in zip(f, j))
    jo = sum(b and not a for a, b in zip(f, j))
    ne = sum(not a and not b for a, b in zip(f, j))
    print(f"  {name:<44} {sum(f):>4}  ({pct(sum(f), total)})   both {both}, ForTy only {fo}, JRC only {jo}, neither {ne}")

print(f"\nMedian ForTy band sum where JRC has no forest: {median(band_sum(r) for r in results if jrc_share(r) == 0):.1f}; "
      f"where JRC has forest: {median(band_sum(r) for r in results if jrc_share(r) > 0):.1f}")


# ---------- 2. polygon geometry (area, region) ----------
def ring_area_m2(ring):
    a, e2, rad = 6378137.0, 0.00669437999014, math.pi / 180
    lat0 = sum(p[1] for p in ring) / len(ring) * rad
    w = 1 - e2 * math.sin(lat0) ** 2
    m_lat = a * (1 - e2) / w ** 1.5 * rad
    m_lon = a / math.sqrt(w) * math.cos(lat0) * rad
    lon0, lat_ref = ring[0]
    pts = [((p[0] - lon0) * m_lon, (p[1] - lat_ref) * m_lat) for p in ring]
    twice = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                for i in range(len(pts)))
    return abs(twice) / 2


def geometry_area_m2(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return sum((ring_area_m2(ring) if i == 0 else -ring_area_m2(ring))
               for rings in polygons for i, ring in enumerate(rings))


def centre_lat(geometry):
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    lats = [p[1] for rings in polygons for ring in rings for p in ring]
    return (min(lats) + max(lats)) / 2


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out, i = [0.0] * len(values), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(x, y):
    rx, ry = ranks(x), ranks(y)
    mx, my = mean(rx), mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))


if not os.path.exists(GEOJSON_PATH):
    print(f"\n(No {GEOJSON_PATH}: region and polygon-size sections skipped.)")
    sys.exit(0)

with open(GEOJSON_PATH, encoding="utf-8") as file:
    features = json.load(file)["features"]

by_id = {int(r["polygon_id"]): r for r in results}
rows = []
for position, feature in enumerate(features, start=1):
    record = by_id.get(position)
    if record is None:
        continue
    record["area"] = geometry_area_m2(feature["geometry"])
    record["region"] = "Brazil" if centre_lat(feature["geometry"]) < -10 else "Uganda"
    rows.append(record)

areas = sorted(r["area"] for r in rows)
print("\n=== Polygon size ===")
print(f"under 100 m2 (smaller than one pixel): {sum(a < 100 for a in areas)}; under 400 m2: "
      f"{sum(a < 400 for a in areas)}; median {median(areas):,.0f} m2; min {areas[0]:,.0f}; max {areas[-1]:,.0f}")

print("\n=== By region ===")
for region in ("Brazil", "Uganda"):
    group = [r for r in rows if r["region"] == region]
    n = len(group)
    jc = Counter(jrc_class(r) for r in group)
    print(f"{region}: n={n}, median area {median(r['area'] for r in group):,.0f} m2, "
          f"under 400 m2: {sum(r['area'] < 400 for r in group)}")
    print(f"  JRC: none {jc['none (0%)']} ({pct(jc['none (0%)'], n)}), partial {jc['partial (1-99%)']}, "
          f"full {jc['full (100%)']}; median share {median(jrc_share(r) for r in group):.1f}%")
    print(f"  ForTy dominant: {dict(Counter(forty_dominant(r) for r in group))}")
    print(f"  agreement: {dict(Counter(agreement(r) for r in group))}")
    print("  JRC none by year: " + ", ".join(
        f"{y}: {pct(sum(jrc_share(r) == 0 for r in g), len(g))} (n={len(g)})"
        for y, g in sorted(
            {y: [r for r in group if str(r['year']) == y] for y in sorted({str(r['year']) for r in group})}.items())))

print("\n=== JRC result by polygon size ===")
bins = [("<100", 0, 100), ("100-400", 100, 400), ("400-1000", 400, 1000),
        ("1000-4000", 1000, 4000), (">4000", 4000, float("inf"))]
for label, lo, hi in bins:
    group = [r for r in rows if lo <= r["area"] < hi]
    n = len(group)
    jc = Counter(jrc_class(r) for r in group)
    print(f"  {label:>10}: n={n:<3} none {pct(jc['none (0%)'], n):>6}  full {pct(jc['full (100%)'], n):>6}  "
          f"median share {median(jrc_share(r) for r in group):5.1f}%  ForTy forest type {pct(sum(forty_forest(r) for r in group), n)}")
print(f"  Spearman correlation, polygon area vs JRC share: {spearman([r['area'] for r in rows], [jrc_share(r) for r in rows]):.2f}")
print(f"  Spearman correlation, polygon area vs ForTy band sum: {spearman([r['area'] for r in rows], [band_sum(r) for r in rows]):.2f}")

big = [r for r in rows if r["area"] >= 400]
jc = Counter(jrc_class(r) for r in big)
print(f"\n=== Only polygons of at least 400 m2 (4 pixels), n={len(big)} ===")
print(f"  JRC none {pct(jc['none (0%)'], len(big))}, partial {pct(jc['partial (1-99%)'], len(big))}, "
      f"full {pct(jc['full (100%)'], len(big))}; ForTy forest type {pct(sum(forty_forest(r) for r in big), len(big))}")
print(f"  agreement: {dict(Counter(agreement(r) for r in big))}")

print("\n=== JRC 'none' rate by region within similar size ranges ===")
for lo, hi in [(0, 400), (400, 1500), (1500, float("inf"))]:
    parts = []
    for region in ("Brazil", "Uganda"):
        g = [r for r in rows if r["region"] == region and lo <= r["area"] < hi]
        parts.append(f"{region} {pct(sum(jrc_share(r) == 0 for r in g), len(g))} (n={len(g)})")
    print(f"  {lo:>5}-{hi if hi != float('inf') else 'up':<6} " + "; ".join(parts))

nat = [r for r in rows if forty_dominant(r) == "NaturallyRegeneratingForest"]
print(f"\nNaturally regenerating polygons: n={len(nat)}, JRC none {pct(sum(jrc_share(r) == 0 for r in nat), len(nat))}")
for region in ("Brazil", "Uganda"):
    g = [r for r in nat if r["region"] == region]
    print(f"  {region}: n={len(g)}, JRC none {pct(sum(jrc_share(r) == 0 for r in g), len(g))}")
