"""Read-only: propose new car park records from an OpenStreetMap extract.

    python -m ferro_parking osm-places data/raw/greater-london-latest.osm.pbf

Writes candidates.jsonl (a db-create plan), candidates.csv for review and
counts.json under data/runs/<date>/osm_places/. It never touches the database,
the Google Sheet or the network.

What it proposes is an identity only: a name, a point, a borough and the OSM
reference. It never proposes who can park, what it costs or a maximum stay,
because an OSM tag proves that a car park exists and proves nothing about
permission. Research fills those columns later.

Eligibility, in the order the counts report it:

1. amenity=parking, excluding lifecycle prefixes (disused, abandoned,
   proposed, construction).
2. Not street side, lane, on street, kerb or shoulder parking.
3. Not restricted to lorries, coaches or HGVs.
4. No access tag of private, no, residents, permit, employees, delivery,
   staff or students.
5. Inside Greater London, tested as containment in the union of the 32
   borough polygons and the City of London, read from the extract itself.
6. Either an access tag of yes, public, permissive or customers, or, with
   no access tag, one qualifier: a name, an operator, a fee tag, a capacity
   of 10 or more, a multi-storey or underground type, or an area of at least
   500 square metres.

A qualifier admits a candidate identity. It is not a claim of public access.

OSM data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import osmium
from shapely import wkb
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .discovery import is_borough_boundary, build_borough_lookup
from .osm_match import to_m, osm_url
from .run_paths import new_run_dir

LIFECYCLE_PREFIXES = ("disused", "abandoned", "proposed", "construction", "razed", "demolished")
EXCLUDED_ACCESS = {"private", "no", "residents", "permit", "employees",
                   "delivery", "staff", "students", "agricultural", "forestry"}
PUBLIC_ACCESS = {"yes", "public", "permissive", "customers"}
EXCLUDED_PARKING = {"street_side", "lane", "on_street", "kerb", "shoulder",
                    "half_on_kerb", "on_kerb", "layby"}
LORRY_PARKING = {"lorry", "truck", "hgv", "coach", "bus"}
QUALIFYING_TYPE = {"multi-storey", "underground"}
MIN_CAPACITY = 10
MIN_AREA_M2 = 500.0

COUNCIL_PATTERN = re.compile(
    r"\b(council|borough of|city of london corporation|corporation of london)\b", re.I)

# OSM names a borough boundary "London Borough of Barnet". The sheet's own
# Borough column says "Barnet". Only the City of London keeps its prefix,
# because that is the sheet's own spelling for it.
BOROUGH_PREFIXES = ("London Borough of ", "Royal Borough of ", "City of ")
BOROUGH_KEEP_WHOLE = {"City of London"}

COUNCIL_CATEGORY = "Council car park"
DEFAULT_CATEGORY = "Private / operator car park"
GEO_SOURCE = "OpenStreetMap"
CAPTURED_BY = "OSM discovery"

CSV_HEADERS = ["source_ref", "Location Name", "Place Category", "Borough",
               "Postcode", "Street Address", "Latitude", "Longitude",
               "access", "parking", "capacity", "operator", "area_m2",
               "qualifier", "Notes"]


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def is_parking(tags):
    """amenity=parking, and not a lifecycle-prefixed version of it."""
    if tags.get("amenity") != "parking":
        return False
    if any(tags.get(f"{prefix}:amenity") for prefix in LIFECYCLE_PREFIXES):
        return False
    return True


def lifecycle_excluded(tags):
    return any(tags.get(f"{prefix}:amenity") for prefix in LIFECYCLE_PREFIXES) \
        or str(tags.get("amenity", "")).startswith(tuple(p + ":" for p in LIFECYCLE_PREFIXES))


def lorry_only(tags):
    """Parking a car may not use. A lorry or coach park is not a candidate."""
    if str(tags.get("parking", "")).lower() in LORRY_PARKING:
        return True
    if str(tags.get("motorcar", "")).lower() in {"no", "private"}:
        return True
    if str(tags.get("motor_vehicle", "")).lower() in {"no", "private"}:
        return True
    for key in ("hgv", "goods", "bus", "coach"):
        if str(tags.get(key, "")).lower() in {"designated", "only"} \
                and str(tags.get("motorcar", "")).lower() not in {"yes", "designated"}:
            return True
    return False


# Why a parking feature is not a candidate for creation. The key names the
# counter, the text names the reason for a report.
EXCLUSION_COUNTS = {
    "parking type": "excluded_parking_type",
    "lorry or coach": "excluded_lorry_or_coach",
    "access": "excluded_access",
}


def creation_excluded(tags):
    """(key, reason), or ("", "") when the feature is a creation candidate.

    Both the proposer and the hold list read this. An older hold list was
    written before some of these rules existed, so a candidate on it can still
    carry a tag that excludes it today. One function means the two can never
    disagree about what a driver is allowed to park in."""
    parking = str(tags.get("parking", "")).lower()
    if parking in EXCLUDED_PARKING:
        return "parking type", f"parking={parking} is street side, lane or kerb parking"
    if lorry_only(tags):
        return "lorry or coach", "the tags describe lorry or coach parking, not car parking"
    access = str(tags.get("access", "")).strip().lower()
    if access in EXCLUDED_ACCESS:
        return "access", f"access={access} excludes a driver from parking here"
    return "", ""


def qualifier(tags, area_m2):
    """Why a feature with no usable access tag is still a candidate identity,
    or "" when nothing qualifies it. This is never a claim of public access."""
    if str(tags.get("name", "")).strip():
        return "name"
    if str(tags.get("operator", "")).strip():
        return "operator"
    if str(tags.get("fee", "")).strip():
        return "fee"
    if _int(tags.get("capacity")) >= MIN_CAPACITY:
        return "capacity"
    if str(tags.get("parking", "")).lower() in QUALIFYING_TYPE:
        return "type"
    if area_m2 >= MIN_AREA_M2:
        return "area"
    return ""


def place_name(tags):
    """OSM name, else an operator car park, else the street, else unnamed."""
    name = str(tags.get("name", "")).strip()
    if name:
        return name
    operator = str(tags.get("operator", "")).strip()
    if operator:
        return f"{operator} car park"
    street = str(tags.get("addr:street", "")).strip()
    if street:
        return f"Car park, {street}"
    return "Car park (unnamed)"


def borough_name(osm_name):
    """The sheet's own spelling of a borough, from the OSM boundary name."""
    name = str(osm_name or "").strip()
    if name in BOROUGH_KEEP_WHOLE:
        return name
    for prefix in BOROUGH_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def place_category(tags):
    """Council only when a tag says so. Otherwise the cautious default.

    operator:type=public means a public company in OSM, not a public
    authority, so only government counts here."""
    if COUNCIL_PATTERN.search(str(tags.get("operator", ""))):
        return COUNCIL_CATEGORY
    if str(tags.get("operator:type", "")).lower() == "government":
        return COUNCIL_CATEGORY
    return DEFAULT_CATEGORY


def street_address(tags):
    number = str(tags.get("addr:housenumber", "")).strip()
    street = str(tags.get("addr:street", "")).strip()
    if number and street:
        return f"{number} {street}"
    return street


def notes(tags, area_m2, qualified_by):
    """Retained tags, as facts about the OSM feature. No parking answer."""
    parts = []
    for key in ("access", "parking", "capacity", "fee", "operator",
                "maxstay", "opening_hours", "surface", "covered"):
        value = str(tags.get(key, "")).strip()
        if value:
            parts.append(f"{key}={value}")
    if area_m2:
        parts.append(f"area={round(area_m2)} m2")
    if qualified_by:
        parts.append(f"qualified by {qualified_by}")
    if not parts:
        return "OSM amenity=parking, no further tags."
    return ("OSM tags: " + "; ".join(parts)
            + ". Parking rules not checked. Verify on site or from an official source.")


def point_for(geom_m, geom_ll):
    """A representative point inside the feature. A centroid can fall outside
    a concave polygon or a polygon with a hole, so fall back to a point the
    geometry guarantees is inside."""
    if geom_ll.geom_type == "Point":
        return geom_ll, "Node"
    centroid = geom_ll.centroid
    if geom_ll.contains(centroid):
        return centroid, "Polygon centroid"
    return geom_ll.representative_point(), "Polygon interior point"


class Collector(osmium.SimpleHandler):
    """One pass: every amenity=parking feature, plus every borough polygon."""

    def __init__(self):
        super().__init__()
        self.wkb = osmium.geom.WKBFactory()
        self.features = []
        self.boroughs = []
        self.counts = Counter()

    def _keep(self, kind, oid, tags, geom_ll, area_m2):
        self.features.append({"type": kind, "id": oid, "tags": tags,
                              "geom_ll": geom_ll, "area_m2": area_m2})

    def node(self, n):
        tags = {x.k: x.v for x in n.tags}
        if not is_parking(tags):
            if lifecycle_excluded(tags):
                self.counts["excluded_lifecycle"] += 1
            return
        self._keep("node", n.id, tags, Point(n.location.lon, n.location.lat), 0.0)

    def area(self, a):
        tags = {x.k: x.v for x in a.tags}
        boundary = is_borough_boundary(tags)
        parking = is_parking(tags)
        if not boundary and not parking:
            if lifecycle_excluded(tags):
                self.counts["excluded_lifecycle"] += 1
            return
        try:
            geom_ll = wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except Exception:
            self.counts["unreadable_geometry"] += 1
            return
        if boundary:
            self.boroughs.append({"name": tags["name"], "geom": to_m(geom_ll),
                                  "geom_ll": geom_ll})
        if parking:
            kind = "way" if a.from_way() else "relation"
            self._keep(kind, a.orig_id(), tags, geom_ll, to_m(geom_ll).area)


def collect(pbf_path):
    handler = Collector()
    handler.apply_file(str(pbf_path), locations=True)
    return handler


def propose(pbf_path, today=None):
    """(candidates, counts). Read-only. candidates are db-create records."""
    today = today or date.today()
    handler = collect(pbf_path)
    counts = Counter(handler.counts)
    counts["boroughs_read"] = len(handler.boroughs)
    if not handler.boroughs:
        raise ValueError("no borough boundary found in the extract: cannot test "
                         "Greater London containment")
    london = unary_union([b["geom_ll"] for b in handler.boroughs])
    borough_of = build_borough_lookup(handler.boroughs)
    candidates = []
    for feature in handler.features:
        tags = feature["tags"]
        counts["amenity_parking"] += 1
        counts["kind_" + feature["type"]] += 1
        key, _ = creation_excluded(tags)
        if key:
            counts[EXCLUSION_COUNTS[key]] += 1
            continue
        access = str(tags.get("access", "")).strip().lower()
        point_ll, precision = point_for(None, feature["geom_ll"])
        if not london.contains(point_ll):
            counts["excluded_outside_greater_london"] += 1
            continue
        counts["inside_greater_london"] += 1
        qualified_by = ""
        if access in PUBLIC_ACCESS:
            counts["eligible_public_access"] += 1
        else:
            qualified_by = qualifier(tags, feature["area_m2"])
            if not qualified_by:
                counts["excluded_no_qualifier"] += 1
                continue
            counts["eligible_qualified_" + qualified_by] += 1
        borough = borough_name(borough_of(to_m(point_ll)))
        if not borough:
            counts["no_borough"] += 1
        row = {
            "Location Name": place_name(tags),
            "Place Category": place_category(tags),
            "Street Address": street_address(tags),
            "Postcode": str(tags.get("addr:postcode", "")).strip(),
            "Borough": borough,
            "Latitude": f"{point_ll.y:.6f}",
            "Longitude": f"{point_ll.x:.6f}",
            "Geo Source": GEO_SOURCE,
            "Geo Precision": precision,
            "Captured By": CAPTURED_BY,
            "Date Captured": today.isoformat(),
            "Source URLs (primary first)": osm_url(feature),
            "OSM ID": f"{feature['type']}/{feature['id']}",
            "Notes": notes(tags, feature["area_m2"], qualified_by),
        }
        candidates.append({
            "source": "osm",
            "source_ref": f"{feature['type']}/{feature['id']}",
            "row": row,
            "_review": {
                "access": access, "parking": str(tags.get("parking", "")),
                "capacity": str(tags.get("capacity", "")),
                "operator": str(tags.get("operator", "")),
                "area_m2": round(feature["area_m2"]) if feature["area_m2"] else "",
                "qualifier": qualified_by or "access tag",
            },
        })
    counts["proposed"] = len(candidates)
    counts["proposed_council_category"] = sum(
        1 for c in candidates if c["row"]["Place Category"] == COUNCIL_CATEGORY)
    counts["proposed_with_postcode"] = sum(1 for c in candidates if c["row"]["Postcode"])
    counts["proposed_named"] = sum(
        1 for c in candidates if not c["row"]["Location Name"].startswith("Car park"))
    return candidates, dict(counts)


def write_outputs(candidates, counts, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan_path = out_dir / "candidates.jsonl"
    with open(plan_path, "x", encoding="utf-8") as stream:
        for candidate in candidates:
            stream.write(json.dumps(
                {k: v for k, v in candidate.items() if k != "_review"},
                ensure_ascii=False) + "\n")
    csv_path = out_dir / "candidates.csv"
    with open(csv_path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_HEADERS, extrasaction="ignore")
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({"source_ref": candidate["source_ref"],
                             **candidate["row"], **candidate["_review"]})
    (out_dir / "counts.json").write_text(json.dumps(counts, indent=2, sort_keys=True),
                                         encoding="utf-8")
    return plan_path, csv_path


def main(argv=None):
    parser = argparse.ArgumentParser(prog="osm-places")
    parser.add_argument("pbf")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=0,
                        help="propose at most this many records, the named ones first")
    args = parser.parse_args(argv)

    candidates, counts = propose(args.pbf)
    if args.limit:
        candidates.sort(key=lambda c: (c["row"]["Location Name"].startswith("Car park"),
                                       c["row"]["Location Name"]))
        candidates = candidates[:args.limit]
        counts["limited_to"] = len(candidates)
    out_dir = Path(args.out) if args.out else new_run_dir("osm_places")
    plan_path, csv_path = write_outputs(candidates, counts, out_dir)
    for key in sorted(counts):
        print(f"{key:38s} {counts[key]}")
    print(f"\nPlan:  {plan_path}")
    print(f"Review: {csv_path}")
    return 0
