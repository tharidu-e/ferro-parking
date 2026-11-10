"""
Ferro PP: prepare tranche 1 for writing.

Takes discovery.py's tranche 1 missing places (car parks with public,
customers or no access tag, plus petrol stations, stations, supermarkets,
hospitals and retail parks) and gets them ready to actually add to the
sheet: filters out OSM junk discovery.py's category tags let through,
scores each survivor's confidence from its OSM tags, and writes the two
output files below.

READ-ONLY. It never touches the Google Sheet. It only reads the OSM
extract and a CSV export, and writes new CSV files under
data/runs/<date>/tranche1/.

Run (from the project root):
  python -m ferro_parking tranche1 data/raw/greater-london-latest.osm.pbf data/raw/all_london_clean.csv
Options:
  --out DIR     output directory (default: data/runs/<today>/tranche1)

OSM data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import csv
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import discovery
from .osm_match import contains_word, osm_url

# ---------------------------------------------------------------- hospital junk

HOSPITAL_JUNK_WORDS = ("department", "ward", "wing", "unit", "clinic")
HOSPITAL_JUNK_PHRASES = ("centre for",)


def _point_of(feat):
    """A single point for any feature: its own geometry if it is already
    a point, otherwise its polygon's centroid."""
    geom = feat["geom"]
    return geom if geom.geom_type == "Point" else geom.centroid


def hospital_is_junk(feat, hospital_features):
    """A hospital department/ward/unit mapped as its own point, or any
    hospital-tagged feature sitting inside another hospital's polygon
    (almost always the same site mapped twice)."""
    name = (feat["tags"].get("name") or "").lower()
    for word in HOSPITAL_JUNK_WORDS:
        if contains_word(name, word):
            return True, f"name contains '{word}'"
    for phrase in HOSPITAL_JUNK_PHRASES:
        if phrase in name:
            return True, f"name contains '{phrase}'"
    point = _point_of(feat)
    for other in hospital_features:
        if other is feat or other["geom"].geom_type == "Point":
            continue
        if other["geom"].contains(point):
            other_name = other["tags"].get("name", "")
            return True, f"sits inside another hospital site ({other_name})".rstrip()
    return False, ""


# ---------------------------------------------------------------- station junk

RAIL_STATION_TAGS = ("subway", "light_rail", "train", "tram")


def station_is_junk(feat):
    """discovery.py's station category also accepts public_transport=station
    on its own, which OSM uses for any public transport mode, so a boat
    pier or bus station can slip in. Require an actual rail signal."""
    tags = feat["tags"]
    if tags.get("railway") in ("station", "halt"):
        return False, ""
    if tags.get("station") in RAIL_STATION_TAGS:
        return False, ""
    return True, "not a rail station (public_transport=station only, e.g. a bus or boat stop)"


STATION_DEDUPE_RADIUS_M = 400


def dedupe_stations(features):
    """{id(feature) -> reason} for every duplicate station to drop: the
    same name within STATION_DEDUPE_RADIUS_M of another, keeping the one
    tagged railway=station (or, failing that, the lowest OSM id, for a
    deterministic pick). Single-linkage clustering by distance: good
    enough for the small groups (2-3) this actually finds in practice."""
    from .osm_match import norm
    by_name = {}
    for f in features:
        by_name.setdefault(norm(f["tags"].get("name", "")), []).append(f)

    excluded = {}
    for name, group in by_name.items():
        if not name or len(group) < 2:
            continue
        remaining = list(group)
        while remaining:
            seed = remaining.pop(0)
            cluster, rest = [seed], []
            for f in remaining:
                if f["geom"].distance(seed["geom"]) <= STATION_DEDUPE_RADIUS_M:
                    cluster.append(f)
                else:
                    rest.append(f)
            remaining = rest
            if len(cluster) < 2:
                continue
            keeper = max(cluster, key=lambda f: (f["tags"].get("railway") == "station", -f["id"]))
            for f in cluster:
                if f is not keeper:
                    excluded[id(f)] = f"duplicate station, kept {keeper['type']}/{keeper['id']}"
    return excluded


# ---------------------------------------------------------------- supermarket junk

SUPERMARKET_JUNK_WORDS = ("phone", "vape", "mobile", "barber", "salon")

# shop= values that are still a food supermarket/convenience shop. OSM
# allows a semicolon-separated multi-value shop tag (shop=supermarket;mobile_phone);
# any other value alongside supermarket means the feature is not really a
# supermarket, or is sharing a node with an unrelated retail unit.
FOOD_SHOP_VALUES = {"supermarket", "convenience", "grocery", "greengrocer",
                    "butcher", "bakery", "deli", "farm"}


def supermarket_is_junk(feat):
    name = (feat["tags"].get("name") or "").lower()
    for word in SUPERMARKET_JUNK_WORDS:
        if contains_word(name, word):
            return True, f"name contains '{word}'"
    shop_values = [v.strip() for v in feat["tags"].get("shop", "").split(";") if v.strip()]
    non_food = [v for v in shop_values if v not in FOOD_SHOP_VALUES]
    if non_food:
        return True, f"non-food shop tag ({', '.join(non_food)})"
    return False, ""


# ---------------------------------------------------------------- car park / hotel site

HOTEL_CAR_PARK_RADIUS_M = 50


def car_park_is_hotel_site(feat, hotel_features):
    """True if this car park sits on, or right next to, a hotel: it still
    gets written, just tagged as a hotel car park rather than a public one."""
    point = _point_of(feat)
    for hotel in hotel_features:
        geom = hotel["geom"]
        if geom.geom_type != "Point" and geom.contains(point):
            return True
        if point.distance(geom) <= HOTEL_CAR_PARK_RADIUS_M:
            return True
    return False


# ---------------------------------------------------------------- confidence

def _parse_osm_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _within_years(dt, years, now):
    return dt is not None and now - dt <= timedelta(days=365 * years)


def confidence(feat, now=None):
    """High: a brand tag, a railway station, or a hospital tagged as an
    actual hospital (emergency or healthcare=hospital), not just a site
    that happens to have the word in its name.
    Medium: contact details (website, phone, opening_hours), or a
    check_date / survey:date / last OSM edit within 2 years.
    Low: none of the above."""
    now = now or datetime.now(timezone.utc)
    tags = feat["tags"]
    if tags.get("brand") or tags.get("brand:wikidata"):
        return "High"
    if feat["category"] == "station":
        return "High"
    if feat["category"] == "hospital" and (tags.get("emergency") or tags.get("healthcare") == "hospital"):
        return "High"

    if tags.get("website") or tags.get("phone") or tags.get("contact:phone") or tags.get("opening_hours"):
        return "Medium"
    if _within_years(_parse_osm_date(tags.get("check_date") or tags.get("survey:date")), 2, now):
        return "Medium"
    if _within_years(feat.get("ts"), 2, now):
        return "Medium"
    return "Low"


# ---------------------------------------------------------------- main

def filter_tranche1(features, by_category_osm):
    """Splits tranche 1's missing features into (kept, excluded_rows).
    excluded_rows already carry a Reason; kept is the plain feature list,
    still needing a confidence score and the hotel-car-park note."""
    hospital_features = by_category_osm.get("hospital", [])
    hotel_features = by_category_osm.get("hotel", [])

    station_candidates = [f for f in features if f["category"] == "station"]
    station_junk = {}
    station_survivors = []
    for f in station_candidates:
        junk, reason = station_is_junk(f)
        if junk:
            station_junk[id(f)] = reason
        else:
            station_survivors.append(f)
    station_dupes = dedupe_stations(station_survivors)

    kept, excluded_rows = [], []
    for feat in features:
        cat = feat["category"]
        junk, reason = False, ""
        if cat == "hospital":
            junk, reason = hospital_is_junk(feat, hospital_features)
        elif cat == "station":
            if id(feat) in station_junk:
                junk, reason = True, station_junk[id(feat)]
            elif id(feat) in station_dupes:
                junk, reason = True, station_dupes[id(feat)]
        elif cat == "supermarket":
            junk, reason = supermarket_is_junk(feat)
        elif cat == "car_park":
            access = feat["tags"].get("access", "")
            if access in ("private", "residents"):
                junk, reason = True, f"access={access} (should already be excluded from tranche 1)"

        if junk:
            tags = feat["tags"]
            excluded_rows.append({
                "OSM Type": feat["type"], "OSM Id": feat["id"], "OSM Link": osm_url(feat),
                "Name": tags.get("name", ""), "Category": cat, "Reason": reason,
            })
        else:
            kept.append(feat)
    return kept, excluded_rows


def ready_row(feat, conf, notes, borough_of):
    tags = feat["tags"]
    address = " ".join(x for x in (tags.get("addr:housenumber", ""), tags.get("addr:street", "")) if x).strip()
    return {
        "OSM Type": feat["type"], "OSM Id": feat["id"], "OSM Link": osm_url(feat),
        "Name": tags.get("name", ""), "Category": feat["category"],
        "Address (OSM)": address, "Postcode": tags.get("addr:postcode", ""),
        "Borough": borough_of(feat["geom"]),
        "Lat": round(feat["ll"].y, 6), "Lon": round(feat["ll"].x, 6),
        "Operator": tags.get("operator", ""), "Access": tags.get("access", ""),
        "Fee": tags.get("fee", ""), "Confidence": conf, "Notes": notes,
    }


def run(pbf_path, csv_path, out_dir, categories=None):
    started = time.perf_counter()
    result = discovery.collect(pbf_path, csv_path, categories)
    by_category_osm = result["by_category_osm"]
    borough_of = result["borough_of"]

    before_count = len(result["tranche1_features"])
    kept, excluded_rows = filter_tranche1(result["tranche1_features"], by_category_osm)

    hotel_features = by_category_osm.get("hotel", [])
    ready_rows = []
    for feat in kept:
        notes = ""
        if feat["category"] == "car_park" and car_park_is_hotel_site(feat, hotel_features):
            notes = "Hotel car park (not public)"
        ready_rows.append(ready_row(feat, confidence(feat), notes, borough_of))

    summary = Counter((r["Category"], r["Confidence"]) for r in ready_rows)
    exclusion_reasons = Counter(r["Reason"] for r in excluded_rows)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "tranche1_excluded.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Reason"], excluded_rows)
    _write_csv(out_dir / "tranche1_ready.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Address (OSM)",
                "Postcode", "Borough", "Lat", "Lon", "Operator", "Access", "Fee",
                "Confidence", "Notes"], ready_rows)

    elapsed = time.perf_counter() - started
    return {
        "before_count": before_count, "after_count": len(ready_rows),
        "excluded_rows": excluded_rows, "exclusion_reasons": exclusion_reasons.most_common(),
        "ready_rows": ready_rows, "confidence_summary": dict(summary),
        "no_borough_count": result["no_borough_count"],
        "no_borough_causes": result["no_borough_causes"],
        "elapsed_seconds": elapsed, "out_dir": out_dir,
    }


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
        args.out = Path("data") / "runs" / _dt.date.today().isoformat() / "tranche1"

    result = run(args.pbf, args.csv_in, args.out)

    print(f"Tranche 1 before filtering: {result['before_count']}")
    print(f"Tranche 1 after filtering:  {result['after_count']}")
    print("\nExclusion reasons:")
    for reason, count in result["exclusion_reasons"]:
        print(f"  {count:>4}  {reason}")
    print("\nConfidence by category:")
    for (cat, conf), count in sorted(result["confidence_summary"].items()):
        print(f"  {cat:<18}{conf:<8}{count}")
    print(f"\nMissing places with no borough found: {result['no_borough_count']}")
    print(f"\nDone in {result['elapsed_seconds']:.0f}s. Results in {result['out_dir']}. "
          "OSM data (c) OpenStreetMap contributors, ODbL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
