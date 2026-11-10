"""
Ferro PP: OpenStreetMap parking match for unfinished sheet rows.

For each row with a blank Verification Result, it:
  1. finds the place itself in OSM (by brand/name near the row's coordinates,
     with a wider search when the pin is only a postcode centroid),
  2. finds car parks (amenity=parking) next to that place,
  3. reads their tags (access, fee, maxstay, opening_hours, operator...),
  4. suggests values for the sheet columns, following the PP validator rules
     (OSM is a weak source: Can Park? is never more than Conditional).

READ-ONLY. It never touches the Google Sheet. Output is a CSV for review.

Setup (once):
  pip install osmium shapely
  Download the London extract (about 100 MB, free):
    https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf
  Export tab "ALL LONDON (clean)" as CSV (File > Download > CSV).

Run (from the project root):
  python -m ferro_parking match data/raw/greater-london-latest.osm.pbf data/raw/all_london_clean.csv
Options:
  --out FILE              output file (default: data/runs/<today>/osm_results.csv)
  --all                   include rows that already have a Verification Result
  --limit N               only the first N selected rows (for a quick test)

OSM data (c) OpenStreetMap contributors, ODbL.
"""

from .run_paths import new_run_dir
import argparse
import csv
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone

import osmium
import shapely
from shapely import wkb
from shapely.geometry import Point
from shapely.strtree import STRtree

# ---------------------------------------------------------------- settings

# Search radius for the place itself, by the row's Geo Precision.
POI_RADIUS = {
    "Car park": 80, "Building": 80, "Station": 120,
    "Nearby POI (point of interest)": 150, "Nearby POI": 150,
    "Street": 250, "Postcode centroid": 250, "Area centre": 400,
}
DEFAULT_POI_RADIUS = 250
ADJACENT_M = 40          # car park counts as "this place's" if within this
BRAND_PARK_M = 150       # ...or within this if its name/operator matches brand
PRECISE = {"Car park", "Building", "Station"}

POI_KEYS = ("shop", "amenity", "tourism", "leisure", "office", "railway",
            "public_transport", "healthcare", "craft")
STOP = {"london", "the", "store", "superstore", "extra", "express", "local",
        "metro", "ltd", "limited", "branch", "uk", "plc", "and", "of",
        "road", "street", "lane", "high", "station", "customer"}

CLOSED_PREFIXES = ("disused:", "was:", "abandoned:")

# Metres per degree near London (equirectangular is fine at city scale).
LAT0 = 51.5
KX = 111320 * math.cos(math.radians(LAT0))
KY = 110574


def to_m(geom):
    return shapely.transform(geom, lambda c: c * [KX, KY])


# ---------------------------------------------------------------- OSM load

class Collector(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.parks, self.pois = [], []

    @staticmethod
    def _is_poi(t):
        if t.get("amenity") == "parking":
            return False
        if "name" not in t and "brand" not in t:
            return False
        if any(k in t for k in POI_KEYS):
            return True
        return any(x.k.startswith(CLOSED_PREFIXES) for x in t)

    def _add(self, kind, oid, tags, geom, ts):
        rec = {"type": kind, "id": oid, "tags": tags, "geom": to_m(geom),
               "ll": geom.representative_point(), "ts": ts}
        if tags.get("amenity") == "parking":
            self.parks.append(rec)
        else:
            self.pois.append(rec)

    def node(self, n):
        t = n.tags
        if t.get("amenity") == "parking" or self._is_poi(t):
            tags = {x.k: x.v for x in t}
            self._add("node", n.id, tags,
                      Point(n.location.lon, n.location.lat), n.timestamp)

    def area(self, a):
        t = a.tags
        if not (t.get("amenity") == "parking" or self._is_poi(t)):
            return
        try:
            g = wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        tags = {x.k: x.v for x in t}
        kind = "way" if a.from_way() else "relation"
        self._add(kind, a.orig_id(), tags, g, a.timestamp)


# ---------------------------------------------------------------- matching

def norm(s):
    s = (s or "").lower().replace("&", " and ").replace("'", "")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def contains_word(text, phrase):
    """Whole-word match: plain substring would read "Public Car Park" as
    containing "pub". Shared by policy_fill.py and discovery.py so this
    fix lives in one place."""
    if not phrase:
        return False
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def toks(s):
    return set(norm(s).split()) - STOP


def get(row, *names):
    low = {k.strip().lower(): k for k in row}
    for n in names:
        k = low.get(n.lower())
        if k is not None:
            return (row[k] or "").strip()
    return ""


def brand_key(row):
    b = get(row, "Brand")
    if not b:
        m = re.search(r"\(([^)]+)\)", get(row, "Type (as captured)"))
        b = m.group(1) if m else ""
    if not b:
        b = re.split(r"\s[-\u2013|]\s|,", get(row, "Location Name"))[0]
        b = " ".join(b.split()[:2])
    return norm(b)


def osm_label(tags):
    return " ".join(tags.get(k, "") for k in
                    ("name", "brand", "operator", "official_name"))


NAME_FIELDS = ("name", "brand", "operator", "official_name")


def name_score(row, tags, bkey):
    """Compare against each OSM name field separately, keep the best."""
    a = toks(get(row, "Location Name"))
    brand_hit, jac = False, 0.0
    for k in NAME_FIELDS:
        label = norm(tags.get(k, ""))
        if not label:
            continue
        # brand match: the brand key appears in the label, or the label IS the
        # brand (its first word equals the brand's first word). A place word
        # inside the location name (e.g. "Cheam") does not count.
        if bkey and (bkey in label or label.split()[0] == bkey.split()[0]):
            brand_hit = True
        b = toks(label)
        if a and b:
            jac = max(jac, len(a & b) / len(a | b))
    return brand_hit, jac


OPEN_SPACE = {"park", "garden", "nature_reserve", "common", "recreation_ground",
              "playground", "pitch", "golf_course"}


def is_station_row(row):
    s = norm(get(row, "Place Category") + " " + get(row, "Type (as captured)"))
    return "station" in s and "petrol" not in s and "fuel" not in s


def is_open_space_row(row):
    s = norm(get(row, "Place Category") + " " + get(row, "Type (as captured)"))
    return "park" in s.replace("car park", "") or "open space" in s


def compatible(row, tags):
    """Reject matches of the wrong kind of place (e.g. a station row to a park)."""
    if is_station_row(row):
        return (tags.get("railway") in ("station", "halt")
                or tags.get("public_transport") == "station"
                or tags.get("station") in ("subway", "light_rail", "train"))
    if tags.get("leisure") in OPEN_SPACE and not is_open_space_row(row):
        return False
    return True


PUBLIC_OPERATORS = ("national car parks", "ncp", "q park", "apcoa", "vinci",
                    "saba", "council", "borough", "city of", "transport for london",
                    "tfl", "network rail")


def other_owner(row, tags, bkey):
    """Why an adjacent car park is NOT this place's, or '' if it may be.
    Only used when the car park's name/operator does not match the row's brand."""
    label = norm(" ".join(tags.get(k, "") for k in ("name", "brand", "operator", "shop")))
    mine = chain_key(row)
    for key in CHAIN_KEYS:
        if len(key) >= 4 and key != mine and key not in bkey and re.search(r"\b" + re.escape(key) + r"\b", label):
            return f"belongs to another brand ({key})"
    if tags.get("access") in ("yes", "public"):
        op = norm(tags.get("operator", ""))
        if tags.get("operator:type") in ("government", "public") or any(o in op for o in PUBLIC_OPERATORS):
            return "public car park nearby, not this place's own"
    return ""


def is_car_park_row(row):
    """A standalone car park. A store's 'customer car park' row is not one:
    its answer comes from the store's page, so it is routed like the store."""
    t = norm(get(row, "Place Category") + " " + get(row, "Type (as captured)"))
    if "car park" in t or "parking" in t:
        return True
    n = norm(get(row, "Location Name"))
    if "customer car park" in n or "customer parking" in n:
        return False
    return "car park" in n or "parking" in n


# ---------------------------------------------------------------- tag mapping

def parse_maxstay(v):
    v = (v or "").strip().lower()
    if not v:
        return ""
    if v in ("no", "none", "unlimited"):
        return "No limit"
    if re.match(r"^\d+$", v):          # bare number: OSM convention is minutes
        return v
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)$", v)
    if not m:
        return ""
    n, unit = float(m.group(1)), m.group(2)
    mult = 1 if unit.startswith("m") else 60 if unit.startswith("h") else 1440
    return str(int(round(n * mult)))


def suggest(tags, ts):
    """Suggested sheet values from one OSM car park, per PP validator rules."""
    acc = tags.get("access", "")
    fee = tags.get("fee", "")
    maxstay = parse_maxstay(tags.get("maxstay", ""))
    s = {}
    notes = []

    # Who can park. OSM is a weak source: never "Yes".
    s["Can Park? (Yes/No/Conditional)"] = "Conditional"
    if acc in ("customers", "destination"):
        s["Who Can Park"] = "Customers only"
    else:
        s["Who Can Park"] = "Unknown"
        if acc in ("yes", "public", "permissive"):
            notes.append(f"OSM access={acc} (public); an official source could upgrade to Yes")
        elif acc in ("private", "no", "permit", "residents"):
            notes.append(f"OSM access={acc}: may not be usable by drivers, check")

    # Use the same cautious cost rule as fill; raw OSM tags are notes.
    from .fill import derive_cost
    s.update(derive_cost(tags, notes))
    if "charge" in tags:
        notes.append(f"OSM charge={tags['charge']}")
    if "fee:conditional" in tags:
        notes.append(f"OSM fee:conditional={tags['fee:conditional']}")

    s["Max Stay (mins)"] = "Not published"
    if maxstay:
        notes.append(f"OSM says max stay {maxstay} mins (not confirmed; rule R4)")
    if tags.get("opening_hours"):
        s["Hours (OpenStreetMap opening_hours format)"] = tags["opening_hours"]
        s["Hours Basis"] = "Car park hours"
    s["Operator"] = tags.get("operator", "") or "Not published"

    for k in ("capacity", "capacity:disabled", "capacity:parent",
              "capacity:charging", "maxheight", "parking", "park_ride"):
        if k in tags:
            notes.append(f"{k}={tags[k]}")

    # Confidence components.
    s["Source Tier"] = "OpenStreetMap"
    s["Specificity"] = "Site-specific"
    s["Rules Stated"] = "Yes" if (acc or maxstay or tags.get("opening_hours")) else "No"
    s["Prices Stated"] = "No"
    if ts:
        age_days = (datetime.now(timezone.utc) - ts).days
        s["Evidence Age"] = ("Under 12 months" if age_days < 365 else
                             "1-2 years" if age_days < 730 else "Older or undated")
    s["OSM Notes"] = "; ".join(notes)
    return s


# ---------------------------------------------------------------- main

SUGGEST_COLS = [
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type",
    "Price Status", "Tariff Type", "Tariff Detail", "Max Stay (mins)",
    "Hours (OpenStreetMap opening_hours format)", "Hours Basis", "Operator",
    "Source Tier", "Specificity", "Rules Stated", "Prices Stated",
    "Evidence Age", "OSM Notes",
]
OUT_COLS = (["Sheet Row", "Place ID", "Location Name", "Borough",
             "Geo Precision", "Result",
             "OSM Place Match", "OSM Place Name", "Place Distance (m)",
             "OSM Car Park", "Car Park Link", "Car Park Distance (m)",
             "OSM Car Park Name", "OSM Raw Tags",
             "Suggested Lat", "Suggested Lon", "Suggested Geo Precision"]
            + ["Suggested " + c for c in SUGGEST_COLS])


PACKET_COLS = ["Route", "Route Reason", "Official URL (sheet)", "OSM Website",
               "OSM Closure Hint", "Car Park Last Edited", "Packet Flags",
               "Nearby Car Park (not this place's)"]
OUT_COLS = PACKET_COLS[:2] + OUT_COLS + PACKET_COLS[2:]

ROUTES = {
    "SKIP": "Skip: blank row",
    "A": "A. Operator or council page (text only)",
    "B": "B. Branch page + chain rule",
    "C": "C. OSM car park + official page check",
    "D": "D. Full research (Maps allowed)",
    "E": "E. Full research + Maps photos",
}


def website_of(tags):
    for k in ("website", "contact:website", "url"):
        if tags.get(k):
            return tags[k]
    return ""


def closure_hint(tags):
    keys = [k for k in tags if k.startswith(CLOSED_PREFIXES)]
    if keys:
        return "OSM tags " + ", ".join(sorted(keys)[:3])
    if tags.get("opening_hours", "").strip().lower() in ("closed", "off"):
        return "OSM opening_hours=closed"
    if tags.get("shop") == "vacant":
        return "OSM shop=vacant"
    return ""


GENERIC_FIRST = {"the", "hotel", "london", "royal", "st", "saint", "east", "west",
                 "north", "south", "new", "old", "city", "grand", "park", "car",
                 "great", "little", "upper", "lower", "central"}
CHAIN_MIN = 5
CHAIN_KEYS = set()


def chain_key(row):
    """First word of the name (two words if the first is generic), normalised."""
    words = norm(get(row, "Location Name")).split()
    if not words:
        return ""
    if words[0] in GENERIC_FIRST and len(words) > 1:
        return " ".join(words[:2])
    return words[0]


def build_chain_keys(rows):
    counts = Counter(chain_key(r) for r in rows)
    return {k for k, c in counts.items()
            if c >= CHAIN_MIN and k and k not in GENERIC_FIRST}


def finish(row, out, best, park, stats):
    """Add the packet columns and choose the research route for the bot."""
    urls = re.split(r"\s*;\s*", get(row, "Source URLs (primary first)"))
    out["Official URL (sheet)"] = next((u for u in urls if u.startswith("http")), "")
    site = (website_of(best["tags"]) if best else "") or (website_of(park["tags"]) if park else "")
    out["OSM Website"] = site
    hint = closure_hint(best["tags"]) if best else ""
    out["OSM Closure Hint"] = hint
    if park is not None and park.get("ts"):
        out["Car Park Last Edited"] = park["ts"].date().isoformat()

    flags = []
    borough = get(row, "Borough")
    if not borough or borough.upper().startswith("UNCLEAR"):
        flags.append("Borough unclear")
    if out.get("Result") == "No coordinates":
        flags.append("No coordinates")
    out["Packet Flags"] = "; ".join(flags)

    autopay = "\u2705" in get(row, "Ferro Autopay")
    status = get(row, "Location Status")
    is_chain = (bool(get(row, "Brand")) or "(" in get(row, "Type (as captured)")
                or chain_key(row) in CHAIN_KEYS)
    car_park_or_station = is_car_park_row(row) or is_station_row(row)

    if not get(row, "Location Name"):
        key, why = "SKIP", "No location name: blank or junk row, flag for a person"
    elif hint or status in ("Closed", "Temporarily closed"):
        key, why = "E", "Possible closure: " + (hint or f"sheet status {status}")
    elif autopay and car_park_or_station:
        key, why = "A", ("Autopay car park: operator page as text + Autopay price check; "
                         "Google Maps photos only if the page is missing or the price conflicts")
    elif autopay:
        key, why = "E", "Autopay row, not a car park: feeds payments, needs the strongest evidence"
    elif is_car_park_row(row):
        key, why = "A", "Row is a car park: operator or council page gives the full tariff"
    elif is_station_row(row):
        key, why = "A", "Station: National Rail station page (or Knowledgebase feed) lists the car park"
    elif park is not None:
        key, why = "C", "OSM shows a car park (" + (out.get("Car Park Link") or "") + \
            "): confirm terms on the official page, skip Maps About"
    elif is_chain:
        key, why = "B", "Chain branch: check branch page, apply chain rule"
    else:
        key, why = "D", "No OSM car park and not a chain: full research"
    out["Route"] = ROUTES[key]
    out["Route Reason"] = why
    stats["route_" + key] += 1
    return out


def osm_url(rec):
    return f"https://www.openstreetmap.org/{rec['type']}/{rec['id']}"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("pbf")
    ap.add_argument("csv_in")
    ap.add_argument("--out", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    if args.out is None:
        import os, datetime as _dt
        run_dir = str(new_run_dir(""))
        args.out = os.path.join(run_dir, "osm_results.csv")

    print("Reading OSM file (a few minutes for London)...", file=sys.stderr)
    h = Collector()
    h.apply_file(args.pbf, locations=True)
    print(f"  {len(h.parks):,} car parks, {len(h.pois):,} named places",
          file=sys.stderr)
    park_tree = STRtree([p["geom"] for p in h.parks])
    poi_tree = STRtree([p["geom"] for p in h.pois])

    with open(args.csv_in, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    global CHAIN_KEYS
    CHAIN_KEYS = build_chain_keys(rows)
    print(f"  {len(CHAIN_KEYS)} chain names found (5+ rows each)", file=sys.stderr)

    selected = []
    for i, row in enumerate(rows):
        if not args.all and get(row, "Verification Result"):
            continue
        selected.append((i + 2, row))          # +2: header row, 1-based
    if args.limit:
        selected = selected[:args.limit]

    stats = Counter()
    with open(args.out, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        for sheet_row, row in selected:
            stats["rows"] += 1
            out = {"Sheet Row": sheet_row, "Place ID": get(row, "Place ID"),
                   "Location Name": get(row, "Location Name"),
                   "Borough": get(row, "Borough"),
                   "Geo Precision": get(row, "Geo Precision")}
            try:
                lat = float(get(row, "Latitude"))
                lon = float(get(row, "Longitude"))
            except ValueError:
                out["Result"] = "No coordinates"
                stats["no_coords"] += 1
                w.writerow(finish(row, out, None, None, stats))
                continue

            here = to_m(Point(lon, lat))
            prec = out["Geo Precision"]
            radius = POI_RADIUS.get(prec, DEFAULT_POI_RADIUS)
            bkey = brand_key(row)
            car_park_row = is_car_park_row(row)

            # 1. Find the place itself.
            pool, tree = (h.parks, park_tree) if car_park_row else (h.pois, poi_tree)
            best, best_score = None, 0.0
            for idx in tree.query(here.buffer(radius)):
                cand = pool[idx]
                d = cand["geom"].distance(here)
                if d > radius:
                    continue
                if not car_park_row and not compatible(row, cand["tags"]):
                    continue
                brand_hit, jac = name_score(row, cand["tags"], bkey)
                if not brand_hit and jac < 0.5:
                    continue
                score = (0.6 if brand_hit else 0) + 0.4 * jac
                score *= max(0.3, 1 - d / (radius * 1.5))
                if score > best_score:
                    best, best_score = cand, score
            place_geom = None
            if best is not None:
                stats["place_matched"] += 1
                place_geom = best["geom"]
                out.update({
                    "OSM Place Match": osm_url(best),
                    "OSM Place Name": best["tags"].get("name", best["tags"].get("brand", "")),
                    "Place Distance (m)": round(best["geom"].distance(here)),
                })

            # 2. Find this place's car park.
            park, link, pdist = None, "", None
            if car_park_row and best is not None:
                park, link, pdist = best, "Row is this car park", 0
            elif place_geom is not None:
                cands = []
                for idx in park_tree.query(place_geom.buffer(BRAND_PARK_M)):
                    p = h.parks[idx]
                    d = p["geom"].distance(place_geom)
                    brand_hit, _ = name_score(row, p["tags"], bkey)
                    if not brand_hit and d <= ADJACENT_M:
                        why_not = other_owner(row, p["tags"], bkey)
                        if why_not:
                            if not out.get("Nearby Car Park (not this place's)"):
                                out["Nearby Car Park (not this place's)"] = f"{osm_url(p)} ({why_not}, {round(d)} m)"
                            continue
                    if d <= ADJACENT_M or (brand_hit and d <= BRAND_PARK_M):
                        cands.append((not brand_hit, d, p, brand_hit))
                if cands:
                    cands.sort(key=lambda c: (c[0], c[1]))
                    _, pdist, park, bh = cands[0]
                    link = "Name/operator matches brand" if bh else "Adjacent to place"
            elif prec in PRECISE:
                cands = [(h.parks[i]["geom"].distance(here), h.parks[i])
                         for i in park_tree.query(here.buffer(ADJACENT_M))]
                cands = [c for c in cands if c[0] <= ADJACENT_M]
                if cands:
                    cands.sort(key=lambda c: c[0])
                    pdist, park = cands[0]
                    link = "Near precise pin (place not matched)"

            if park is not None:
                stats["park_found"] += 1
                t = park["tags"]
                for k in ("access", "fee", "maxstay", "opening_hours", "operator"):
                    if t.get(k):
                        stats["tag_" + k] += 1
                sug = suggest(t, park["ts"])
                # R3: OSM operator that is the store's own brand is the landowner,
                # not the parking company
                op = sug.get("Operator", "")
                if op != "Not published" and (norm(op).split() or [""])[0] == (bkey.split() or [""])[0]:
                    sug["OSM Notes"] = "; ".join(x for x in (sug["OSM Notes"], f'OSM operator "{op}" is the store itself, not the parking company (rule R3)') if x)
                    sug["Operator"] = "Not published"
                # R1: a store's car park is for its customers by default
                if sug["Who Can Park"] == "Unknown" and not car_park_row:
                    sug["Who Can Park"] = "Customers only"
                    sug["OSM Notes"] = "; ".join(x for x in (sug["OSM Notes"], "Who Can Park from rule R1 (store car park = customers by default)") if x)
                out.update({
                    "Result": "Car park found",
                    "OSM Car Park": osm_url(park),
                    "Car Park Link": link,
                    "Car Park Distance (m)": round(pdist),
                    "OSM Car Park Name": t.get("name", ""),
                    "OSM Raw Tags": "; ".join(f"{k}={v}" for k, v in sorted(t.items())),
                    "Suggested Lat": round(park["ll"].y, 6),
                    "Suggested Lon": round(park["ll"].x, 6),
                    "Suggested Geo Precision": "Car park",
                })
                out.update({"Suggested " + k: v for k, v in sug.items()})
            elif best is not None:
                out.update({
                    "Result": "Place found, no OSM car park",
                    "Suggested Lat": round(best["ll"].y, 6),
                    "Suggested Lon": round(best["ll"].x, 6),
                    "Suggested Geo Precision": "Building",
                })
            else:
                out["Result"] = "Place not found in OSM"
            w.writerow(finish(row, out, best, park, stats))

    n = stats["rows"] or 1
    pf = stats["park_found"] or 1
    print(f"\nRows checked:            {stats['rows']}")
    print(f"No coordinates:          {stats['no_coords']}")
    print(f"Place found in OSM:      {stats['place_matched']} ({stats['place_matched']/n:.0%})")
    print(f"Car park found:          {stats['park_found']} ({stats['park_found']/n:.0%})")
    for k in ("access", "fee", "maxstay", "opening_hours", "operator"):
        c = stats['tag_' + k]
        print(f"  ...with {k:<14} {c} ({c/pf:.0%} of car parks found)")
    print("\nRoutes for the bot:")
    for k, label in ROUTES.items():
        c = stats["route_" + k]
        print(f"  {label:<45} {c} ({c/n:.0%})")
    print(f"\nResults in {args.out}. OSM data (c) OpenStreetMap contributors, ODbL.")


if __name__ == "__main__":
    main()
