"""
Ferro PP: read-only discovery count.

Counts how many places OpenStreetMap has, per category, that the sheet
("ALL LONDON (clean)") does not have yet. Category definitions and OSM tag
rules live in config/discovery_categories.toml, not in this file, so the
same code runs for another UK city.

READ-ONLY. It never touches the Google Sheet and never writes a row into
the sheet's own files. It only reads the OSM extract and a CSV export, and
writes new CSV files under data/runs/<date>/discovery/.

Run (from the project root):
  python -m ferro_parking discover data/raw/greater-london-latest.osm.pbf data/raw/all_london_clean.csv
Options:
  --out DIR     output directory (default: data/runs/<today>/discovery)

Match radius is 100 m, except supermarket, DIY store, retail park, hospital
and station, which use 150 m (see RADIUS_OVERRIDES_M). Car park rows get a
second pass against unnamed car parks too (see match_unnamed_car_parks).

OSM data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import csv
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

import osmium
import shapely
from shapely import wkb
from shapely.geometry import Point
from shapely.strtree import STRtree

from .osm_match import (get, norm, brand_key, name_score, to_m, osm_url,
                         contains_word, is_car_park_row)

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "discovery_categories.toml"
DEFAULT_RADIUS_M = 100
BOROUGH_ADMIN_LEVEL = "8"

# Categories whose sheet rows and OSM features match each other too, not
# just within their own name: a store is tagged shop=supermarket or
# shop=convenience almost arbitrarily by format, and the sheet's own
# "Supermarket - large format" / "- convenience" split is the same
# judgement call, so a feature in either OSM tag may be the same place as
# a sheet row in either sheet category.
GROCERY_GROUP = ("supermarket", "convenience_store")

# A wider search radius for categories whose own footprint, or whose
# sheet pin, tends to sit further from the matched OSM node (a hospital
# or retail park's main entrance node vs. its gate; a station's building
# vs. its platform node). Categories not listed keep DEFAULT_RADIUS_M.
RADIUS_OVERRIDES_M = {
    "supermarket": 150, "diy_store": 150, "retail_park": 150,
    "hospital": 150, "station": 150,
}

# Phase 2 car park matching (unnamed OSM car parks): a sheet car park row
# with no named-feature match still counts as found if an unnamed
# amenity=parking is within UNNAMED_CAR_PARK_RADIUS_M and either contains
# the sheet's point (its mapped polygon) or sits within
# UNNAMED_CAR_PARK_EDGE_M of it.
UNNAMED_CAR_PARK_RADIUS_M = 150
UNNAMED_CAR_PARK_EDGE_M = 50

# ---------------------------------------------------------------- config

def load_categories(path=CONFIG_PATH):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data["categories"]


def flagged_categories(categories):
    """[(name, reason), ...] for every category with no clear single OSM tag,
    or a tag known to undercount it."""
    return [(name, cfg.get("flag_reason", "")) for name, cfg in categories.items()
            if cfg.get("flagged")]


# ---------------------------------------------------------------- OSM-side classification

def _rule_matches(tags, rule):
    return all(tags.get(k) in values for k, values in rule.items())


def classify_osm(tags, categories):
    """The first category (in config file order) whose osm_rules match these
    tags, or None if this feature belongs to no tracked category."""
    for name, cfg in categories.items():
        for rule in cfg.get("osm_rules", []):
            if _rule_matches(tags, rule):
                return name
    return None


# The 32 boroughs are admin_level=8. The City of London is not a borough:
# it is its own sui generis authority, tagged admin_level=6 in OSM (the
# same level as a county). Both rules are needed, or every place inside
# the City (the financial district around Bank, Moorgate, Liverpool
# Street) gets no borough at all.
BOROUGH_RULES = (
    {"boundary": ["administrative"], "admin_level": [BOROUGH_ADMIN_LEVEL]},
    {"boundary": ["administrative"], "admin_level": ["6"], "designation": ["sui_generis"]},
)


def is_borough_boundary(tags):
    return bool(tags.get("name")) and any(_rule_matches(tags, rule) for rule in BOROUGH_RULES)


class DiscoveryCollector(osmium.SimpleHandler):
    """One pass over the OSM file: every feature that matches a tracked
    category (named or not), plus every London borough boundary."""

    def __init__(self, categories):
        super().__init__()
        self.categories = categories
        self.wkb = osmium.geom.WKBFactory()
        self.features = []
        self.boroughs = []

    def _add_feature(self, kind, oid, tags, category, geom, ts):
        self.features.append({
            "type": kind, "id": oid, "tags": tags, "category": category,
            "geom": to_m(geom), "ll": geom.representative_point(), "ts": ts,
        })

    def node(self, n):
        tags = {x.k: x.v for x in n.tags}
        category = classify_osm(tags, self.categories)
        if category:
            self._add_feature("node", n.id, tags, category,
                               Point(n.location.lon, n.location.lat), n.timestamp)

    def area(self, a):
        tags = {x.k: x.v for x in a.tags}
        category = classify_osm(tags, self.categories)
        boundary = is_borough_boundary(tags)
        if not category and not boundary:
            return
        try:
            geom = wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        if boundary:
            self.boroughs.append({"name": tags["name"], "geom": to_m(geom)})
        if category:
            kind = "way" if a.from_way() else "relation"
            self._add_feature(kind, a.orig_id(), tags, category, geom, a.timestamp)


# ---------------------------------------------------------------- borough lookup

def build_borough_lookup(boroughs):
    if not boroughs:
        return lambda point_m: ""
    tree = STRtree([b["geom"] for b in boroughs])

    def lookup(point_m):
        for idx in tree.query(point_m):
            if boroughs[idx]["geom"].intersects(point_m):
                return boroughs[idx]["name"]
        return ""
    return lookup


# ---------------------------------------------------------------- sheet-side classification

def classify_sheet_row(row, categories):
    """Whole-word checks throughout (osm_match.contains_word), so "pub"
    never matches inside "public"; this is the one place that keyword
    check lives (policy_fill.py's own chain-detection text uses the same
    shared helper)."""
    place_cat = get(row, "Place Category")
    if place_cat:
        for name, cfg in categories.items():
            if place_cat in cfg.get("sheet_place_categories", []):
                return name

    bkey = brand_key(row)
    for name, cfg in categories.items():
        brands = cfg.get("sheet_brand_in", [])
        if brands and any(contains_word(bkey, norm(b)) for b in brands):
            return name

    typ = norm(get(row, "Type (as captured)"))
    if not typ:
        return "other"

    small_format = categories.get("supermarket", {}).get("sheet_small_format_brands", [])
    if contains_word(typ, "supermarket"):
        if any(contains_word(bkey, norm(b)) for b in small_format):
            return "convenience_store"
        return "supermarket"

    for name, cfg in categories.items():
        excludes = cfg.get("sheet_keyword_excludes", [])
        if any(contains_word(typ, norm(x)) for x in excludes):
            continue
        for kw in cfg.get("sheet_keywords", []):
            if contains_word(typ, norm(kw)):
                return name
    return "other"


def row_point_m(row):
    try:
        lat, lon = float(get(row, "Latitude")), float(get(row, "Longitude"))
    except ValueError:
        return None
    return to_m(Point(lon, lat))


# ---------------------------------------------------------------- matching

def match_category(osm_feats, sheet_rows, sheet_points, radius_m):
    """Greedy one-to-one match: highest name/brand score first, each OSM
    feature and each sheet row used at most once. Returns
    (feature_idx -> row_idx, {matched row indices}).
    Reuses osm_match.name_score and osm_match.brand_key for the name compare,
    same as the row-to-OSM matcher in osm_match.py."""
    if not osm_feats or not sheet_rows:
        return {}, set()
    valid = [i for i, p in enumerate(sheet_points) if p is not None]
    if not valid:
        return {}, set()
    tree = STRtree([sheet_points[i] for i in valid])

    candidates = []
    for fi, feat in enumerate(osm_feats):
        for pos in tree.query(feat["geom"].buffer(radius_m)):
            ri = valid[pos]
            d = sheet_points[ri].distance(feat["geom"])
            if d > radius_m:
                continue
            row = sheet_rows[ri]
            bkey = brand_key(row)
            brand_hit, jac = name_score(row, feat["tags"], bkey)
            if not brand_hit and jac < 0.5:
                continue
            score = (0.6 if brand_hit else 0) + 0.4 * jac
            candidates.append((score, d, fi, ri))

    candidates.sort(key=lambda c: (-c[0], c[1]))
    matched_feats, matched_rows, feature_to_row = set(), set(), {}
    for score, d, fi, ri in candidates:
        if fi in matched_feats or ri in matched_rows:
            continue
        matched_feats.add(fi)
        matched_rows.add(ri)
        feature_to_row[fi] = ri
    return feature_to_row, matched_rows


def build_match_groups(categories):
    """[[category names matched together], ...], one list per OSM-matched
    category, except the grocery group which is merged into one list so a
    supermarket feature and a convenience-store sheet row (or vice versa)
    can match each other with a single one-to-one assignment."""
    groups, done = [], set()
    for name, cfg in categories.items():
        if name in done or not cfg.get("osm_rules"):
            continue
        group = [n for n in GROCERY_GROUP if n in categories] if name in GROCERY_GROUP else [name]
        done.update(group)
        groups.append(group)
    return groups


def group_radius_m(group):
    return max(RADIUS_OVERRIDES_M.get(name, DEFAULT_RADIUS_M) for name in group)


def match_unnamed_car_parks(rows, points, unnamed_car_parks,
                             radius_m=UNNAMED_CAR_PARK_RADIUS_M, edge_m=UNNAMED_CAR_PARK_EDGE_M):
    """Phase 2 for car park sheet rows still unmatched after the name
    compare: the nearest unnamed amenity=parking whose mapped polygon
    contains the sheet point, or whose edge sits within edge_m. Greedy
    one-to-one, nearest first. Returns (row_idx -> (feature, method), {matched row idx})."""
    if not rows or not unnamed_car_parks:
        return {}, set()
    valid = [i for i, p in enumerate(points) if p is not None]
    if not valid:
        return {}, set()
    tree = STRtree([points[i] for i in valid])

    candidates = []
    for fi, feat in enumerate(unnamed_car_parks):
        for pos in tree.query(feat["geom"].buffer(radius_m)):
            ri = valid[pos]
            point = points[ri]
            d = point.distance(feat["geom"])
            if d > radius_m:
                continue
            if feat["geom"].geom_type != "Point" and feat["geom"].contains(point):
                method = "polygon"
            elif d <= edge_m:
                method = "distance"
            else:
                continue
            candidates.append((d, fi, ri, method))

    candidates.sort(key=lambda c: c[0])
    matched_feats, matched_rows, row_to_match = set(), set(), {}
    for d, fi, ri, method in candidates:
        if fi in matched_feats or ri in matched_rows:
            continue
        matched_feats.add(fi)
        matched_rows.add(ri)
        row_to_match[ri] = (unnamed_car_parks[fi], method)
    return row_to_match, matched_rows


def nearest_borough(boroughs, point_m):
    """The closest borough boundary to a point that intersects none of
    them (a diagnostic for "why is Borough blank", not the Borough value
    itself: it is the boundary that almost, but did not, catch this point)."""
    if not boroughs:
        return ""
    return min(boroughs, key=lambda b: b["geom"].distance(point_m))["name"]


ACCESS_GROUPS = {
    "yes": "public", "public": "public", "permissive": "public",
    "customers": "customers", "destination": "customers",
    "private": "private", "no": "private",
    "residents": "residents", "permit": "residents",
}


def access_group(tags):
    return ACCESS_GROUPS.get(tags.get("access", ""), "unknown")


# ---------------------------------------------------------------- main

TRANCHE1_CATEGORIES = {"petrol_station", "station", "supermarket", "hospital", "retail_park"}
TRANCHE1_CAR_PARK_ACCESS = {"", "yes", "public", "permissive", "customers", "destination"}


def is_tranche1(missing_row):
    """A category earmarked for the first batch of places to add: every
    missing place in the five categories below, and a missing car park
    only if drivers in general (public/customers) or nobody's checked
    (no access tag) could actually use it."""
    if missing_row["Category"] == "car_park":
        return missing_row["Access"] in TRANCHE1_CAR_PARK_ACCESS
    return missing_row["Category"] in TRANCHE1_CATEGORIES


def collect(pbf_path, csv_path, categories=None):
    """One full discovery pass: OSM collection, classification, and
    matching. Returns the raw feature objects (tags, geometry, category)
    alongside the flat CSV-ready rows, so a downstream step (tranche1.py)
    can filter and score on tag and geometry detail the flat rows don't
    carry, without re-running the match from scratch."""
    categories = categories if categories is not None else load_categories()
    started = time.perf_counter()

    print("Reading OSM file (a few minutes for London)...", file=sys.stderr)
    collector = DiscoveryCollector(categories)
    collector.apply_file(pbf_path, locations=True)
    print(f"  {len(collector.features):,} category features, "
          f"{len(collector.boroughs)} borough boundaries", file=sys.stderr)
    borough_of = build_borough_lookup(collector.boroughs)

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        sheet_rows = list(csv.DictReader(f))

    by_category_osm = {}
    unnamed = []
    for feat in collector.features:
        if feat["tags"].get("name"):
            by_category_osm.setdefault(feat["category"], []).append(feat)
        else:
            unnamed.append(feat)
    unnamed_car_parks = [f for f in unnamed if f["category"] == "car_park"]

    by_category_sheet = {}
    for row in sheet_rows:
        by_category_sheet.setdefault(classify_sheet_row(row, categories), []).append(row)

    summary_rows = []
    missing_rows = []
    missing_features = []
    sheet_unmatched_rows = []
    access_split = Counter()
    car_park_match_methods = Counter()
    no_borough_causes = Counter()

    for group in build_match_groups(categories):
        is_car_park_group = group == ["car_park"]
        radius = group_radius_m(group)
        osm_feats = [f for name in group for f in by_category_osm.get(name, [])]

        if is_car_park_group:
            # Widened pool: ANY sheet row that reads as a car park, in
            # whatever sheet category it landed in (osm_match.is_car_park_row
            # already excludes a store's own "customer car park" row, which
            # is matched under its store's category instead).
            pool = [(r, "car_park") for r in sheet_rows if is_car_park_row(r)]
        else:
            pool = [(r, name) for name in group for r in by_category_sheet.get(name, [])]
        rows = [r for r, _ in pool]
        native_cats = [c for _, c in pool]
        points = [row_point_m(r) for r in rows]

        feature_to_row, matched_row_idx = match_category(osm_feats, rows, points, radius)

        if is_car_park_group:
            car_park_match_methods["name"] += len(feature_to_row)
            unmatched_idx = [i for i in range(len(rows)) if i not in matched_row_idx]
            row_to_match, matched_local = match_unnamed_car_parks(
                [rows[i] for i in unmatched_idx], [points[i] for i in unmatched_idx],
                unnamed_car_parks)
            for local_i, (_feat, method) in row_to_match.items():
                car_park_match_methods[method] += 1
                matched_row_idx.add(unmatched_idx[local_i])

        matched_feature_idx = set(feature_to_row)
        matched_by_category = Counter(osm_feats[fi]["category"] for fi in matched_feature_idx)

        for fi, feat in enumerate(osm_feats):
            if fi in matched_feature_idx:
                continue
            tags, cat = feat["tags"], feat["category"]
            if cat == "car_park":
                access_split[access_group(tags)] += 1
            borough = borough_of(feat["geom"])
            if not borough:
                no_borough_causes[nearest_borough(collector.boroughs, feat["geom"])] += 1
            missing_rows.append({
                "OSM Type": feat["type"], "OSM Id": feat["id"],
                "OSM Link": osm_url(feat), "Name": tags.get("name", ""),
                "Category": cat, "Lat": round(feat["ll"].y, 6),
                "Lon": round(feat["ll"].x, 6),
                "Postcode": tags.get("addr:postcode", ""), "Borough": borough,
                "Operator": tags.get("operator", ""),
                "Access": tags.get("access", ""), "Fee": tags.get("fee", ""),
            })
            missing_features.append(feat)

        for ri, row in enumerate(rows):
            if ri in matched_row_idx:
                continue
            sheet_unmatched_rows.append({
                "Place ID": get(row, "Place ID"),
                "Location Name": get(row, "Location Name"),
                "Category": native_cats[ri],
            })

        for name in group:
            osm_count = len(by_category_osm.get(name, []))
            sheet_count = sum(1 for c in native_cats if c == name)
            matched_count = sum(1 for i in range(len(rows))
                                 if i in matched_row_idx and native_cats[i] == name)
            summary_rows.append({
                "Category": name, "OSM Count": osm_count, "Sheet Count": sheet_count,
                "Matched": matched_count,
                "OSM Missing From Sheet": osm_count - matched_by_category.get(name, 0),
                "Sheet Rows With No OSM Match": sheet_count - matched_count,
            })

    unnamed_rows = [{
        "Category": f["category"], "OSM Type": f["type"], "OSM Id": f["id"],
        "Lat": round(f["ll"].y, 6), "Lon": round(f["ll"].x, 6),
    } for f in unnamed]

    no_borough_count = sum(1 for r in missing_rows if not r["Borough"])
    tranche1_rows = [r for r in missing_rows if is_tranche1(r)]
    tranche1_features = [f for f in missing_features
                          if is_tranche1({"Category": f["category"],
                                          "Access": f["tags"].get("access", "")})]

    elapsed = time.perf_counter() - started
    return {
        "categories": categories, "by_category_osm": by_category_osm,
        "by_category_sheet": by_category_sheet, "boroughs": collector.boroughs,
        "borough_of": borough_of,
        "summary_rows": summary_rows, "missing_rows": missing_rows,
        "missing_features": missing_features,
        "unnamed_rows": unnamed_rows, "sheet_unmatched_rows": sheet_unmatched_rows,
        "car_park_access_split": dict(access_split),
        "car_park_match_methods": dict(car_park_match_methods),
        "no_borough_count": no_borough_count,
        "no_borough_causes": no_borough_causes.most_common(20),
        "tranche1_rows": tranche1_rows, "tranche1_features": tranche1_features,
        "elapsed_seconds": elapsed,
    }


def run(pbf_path, csv_path, out_dir, categories=None):
    """collect(), then write the four flat discovery CSVs. The CLI entry
    point; tranche1.py calls collect() directly instead, for the raw
    feature objects this function's CSV rows do not carry."""
    result = collect(pbf_path, csv_path, categories)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "discovery_summary.csv",
               ["Category", "OSM Count", "Sheet Count", "Matched",
                "OSM Missing From Sheet", "Sheet Rows With No OSM Match"], result["summary_rows"])
    _write_csv(out_dir / "missing_places.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Lat", "Lon",
                "Postcode", "Borough", "Operator", "Access", "Fee"], result["missing_rows"])
    _write_csv(out_dir / "unnamed_features.csv",
               ["Category", "OSM Type", "OSM Id", "Lat", "Lon"], result["unnamed_rows"])
    _write_csv(out_dir / "sheet_unmatched.csv",
               ["Place ID", "Location Name", "Category"], result["sheet_unmatched_rows"])

    result["out_dir"] = out_dir
    return result


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("csv_in")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    if args.out is None:
        import datetime as _dt
        args.out = Path("data") / "runs" / _dt.date.today().isoformat() / "discovery"

    categories = load_categories()
    result = run(args.pbf, args.csv_in, args.out, categories)

    print(f"\n{'Category':<18}{'OSM':>8}{'Sheet':>8}{'Matched':>9}{'Missing':>9}{'Unmatched':>11}")
    for r in result["summary_rows"]:
        print(f"{r['Category']:<18}{r['OSM Count']:>8}{r['Sheet Count']:>8}"
              f"{r['Matched']:>9}{r['OSM Missing From Sheet']:>9}"
              f"{r['Sheet Rows With No OSM Match']:>11}")

    print(f"\nUnnamed OSM features (counted, not treated as missing): {len(result['unnamed_rows'])}")
    print(f"Car park access split (missing car parks only): {result['car_park_access_split']}")
    print(f"Car park sheet-row matches by method: {result['car_park_match_methods']}")
    print(f"Missing places with no borough found: {result['no_borough_count']}")
    print("  nearest borough (did not actually contain the point), most common:")
    for name, count in result["no_borough_causes"]:
        print(f"    {count:>4}  {name}")
    print(f"Tranche 1 missing places (ready to add first): {len(result['tranche1_rows'])}")
    for name, reason in flagged_categories(categories):
        print(f"FLAGGED: {name}: {reason}")
    print(f"\nDone in {result['elapsed_seconds']:.0f}s. Results in {result['out_dir']}. "
          "OSM data (c) OpenStreetMap contributors, ODbL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
