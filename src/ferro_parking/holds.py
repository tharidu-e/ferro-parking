"""Read-only: turn every held car park candidate into one of three verdicts.

    python -m ferro_parking holds-bundle --pbf data/raw/greater-london-latest.osm.pbf
    python -m ferro_parking holds-bundle --bundle data/runs/<date>/holds/bundle.jsonl
    python -m ferro_parking holds-merge --a reviewer_a.csv --b reviewer_b.csv \
        --bundle data/runs/<date>/holds/bundle.jsonl

Step 2 held 461 OpenStreetMap candidates because each pin landed within 30 m of
a place the database already holds. Proximity is not proof: two levels of one
car park, two adjacent car parks and two businesses on one street all sit within
metres of each other. This module gathers the evidence that can settle a held
case, applies an ordered rule registry to it, and sends everything the rules
cannot settle to two independent reviewers.

Nothing here writes. The database is opened read only, so no run can change it.
The Google Sheet is never touched, no request leaves the machine, and nothing
under data/runs is deleted or moved.

A verdict is one of three words. "duplicate" means the database already holds
this car park. "distinct" means it does not. "unresolved" means the evidence
does not say, which is the honest answer and the only safe default. A case a
rule cannot settle is unresolved, never a guess.

Rules run in a fixed order and the first match wins. Rule 1 reads a fact: a
place already carries this exact OpenStreetMap reference. Rule 2 stops on a row
a person hand checked, which no automated rule may overrule. Rules 3 and 4 read
geometry: a pin inside the candidate polygon, or one candidate area containing
another candidate point, each confirmed by a shared brand token in the two
names.

A distance measured to a postcode centroid is thrown out by distance_near, so
no rule can call two places the same car park on the strength of it. The case
itself still goes to the reviewers, because a name and a tag are evidence that
a distance of no value does not cancel. An earlier version ended such a case as
unresolved on the spot, and that discarded 311 cases, 222 of which shared a
brand token with the place beside them.

OSM data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import csv
import itertools
import json
import random
import re
import sqlite3
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from shapely import wkt as shapely_wkt
from shapely.geometry import Point

from . import db
from .create import _metres
from .osm_match import osm_url
from .run_paths import new_run_dir, reserve_output
from .settings import CONFIG_DIR

VERDICTS = ("duplicate", "distinct", "unresolved")

# A case no rule settled. These, and only these, go to the reviewers.
NO_RULE = "no rule matched"
BY_REVIEWERS = "reviewers"

# The hand checker named in CLAUDE.md. A row this person verified is reported
# to a person and never decided here, whatever the geometry says.
PROTECTED_BY = "Tharidu"

# Default inputs, the four files that hold every known case.
HELD_ALL = Path("data/runs/2026-11-10_19/hold_list/held_all.csv")
POSSIBLE_DUPLICATES = Path("data/runs/2026-11-05/discovery_new_places/possible_duplicates.csv")
HELD_STRICT = Path("data/runs/2026-11-05/discovery_new_places/held_car_parks_strict.csv")
HELD_NAMES = Path("data/runs/2026-11-05/discovery_new_places/held_car_parks_names.csv")

BATCH_SIZE = 25
SAMPLE_SIZE = 60
# A fixed seed, so the same bundle always draws the same sample for reference.
SAMPLE_SEED = 20261110

# Words that describe what a place is, not which place it is. "Car Park" shared
# between two names proves nothing, so these never count as a brand match.
GENERIC_WORDS = {
    "car", "park", "parking", "parks", "station", "stations", "centre",
    "center", "the", "and", "of", "at", "london", "limited", "ltd", "plc",
    "multi", "storey", "multistorey", "underground", "surface", "public",
    "free", "main", "upper", "lower", "north", "south", "east", "west",
    "street", "road", "lane", "avenue", "close", "way", "place", "square",
    "court", "yard", "estate", "retail", "shopping",
}


def _borough_words():
    """Every word of every borough name in the data. "Sutton Car Park" and
    "Sutton Station" share only the borough, which is not a brand."""
    with (CONFIG_DIR / "london.toml").open("rb") as stream:
        names = tomllib.load(stream)["boroughs"]
    return {word for name in names
            for word in re.split(r"[^a-z]+", name.lower()) if word}


BRAND_STOPWORDS = frozenset(GENERIC_WORDS | _borough_words())


def brand_tokens(name):
    """The words of a name that could identify a business or a landmark."""
    return {word for word in re.split(r"[^a-z]+", str(name or "").lower())
            if word and word not in BRAND_STOPWORDS}


def brands_overlap(name_a, name_b):
    """True only when both names keep a brand token and share one. A name with
    nothing but generic words never matches anything, in either direction."""
    tokens_a, tokens_b = brand_tokens(name_a), brand_tokens(name_b)
    return bool(tokens_a and tokens_b and (tokens_a & tokens_b))


def shared_brand(name_a, name_b):
    return ", ".join(sorted(brand_tokens(name_a) & brand_tokens(name_b)))


@dataclass
class NearPlace:
    """A place the database already holds, near a held candidate."""
    place_id: str
    name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    postcode: str = ""
    geo_precision: str = ""
    osm_id: str = ""
    verified_by: str = ""
    metres: float | None = None
    pin_inside_candidate: bool | None = None


@dataclass
class HeldCase:
    """One held candidate, its evidence and its verdict. The whole model."""
    case_id: str
    candidate_ref: str
    candidate_name: str
    source_file: str
    state: str = "pending"
    created_place_id: str = ""
    tags: dict = field(default_factory=dict)
    geometry: str = "absent"
    area_m2: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    near: list = field(default_factory=list)
    verdict: str = ""
    decided_by: str = ""
    evidence: str = ""


# ---------------------------------------------------------------- the loader

def _read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _text(row, column):
    return str(row.get(column) or "").strip()


def _number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _new_case(path, ref, name, latitude=None, longitude=None, near=()):
    stem = Path(path).stem
    return HeldCase(case_id=f"{stem}:{ref}", candidate_ref=ref, candidate_name=name,
                    source_file=stem, latitude=latitude, longitude=longitude,
                    near=list(near))


def read_held_all(path):
    """File 1: the step 2 hold list. One row per candidate, with its nearest
    place and the measured distance. Columns: source, source ref, Location
    Name, near place_id, near name, metres, reason."""
    cases = []
    for row in _read_csv(path):
        ref = _text(row, "source ref")
        if not ref:
            continue
        near = []
        place_id = _text(row, "near place_id")
        if place_id:
            near.append(NearPlace(place_id=place_id, name=_text(row, "near name"),
                                  metres=_number(row.get("metres"))))
        cases.append(_new_case(path, ref, _text(row, "Location Name"), near=near))
    return cases


def read_possible_duplicates(path):
    """File 2: the discovery duplicate report. It carries the candidate point
    and the existing place's geo precision. Columns: Category, Name, OSM ID,
    Lat, Lon, Existing Place ID, Existing Location Name, Existing Geo
    Precision, Match Reason."""
    cases = []
    for row in _read_csv(path):
        ref = _text(row, "OSM ID")
        if not ref:
            continue
        near = []
        place_id = _text(row, "Existing Place ID")
        if place_id:
            near.append(NearPlace(place_id=place_id,
                                  name=_text(row, "Existing Location Name"),
                                  geo_precision=_text(row, "Existing Geo Precision")))
        cases.append(_new_case(path, ref, _text(row, "Name"),
                               latitude=_number(row.get("Lat")),
                               longitude=_number(row.get("Lon")), near=near))
    return cases


def read_held_car_parks(path):
    """Files 3 and 4: the strict and name based hold lists. These name no
    existing place at all, so a case starts with no near place and the extract
    and the database supply the whole of its evidence. Columns: OSM ID, Name,
    Operator, Fee, Access, Borough, Lat, Lon."""
    cases = []
    for row in _read_csv(path):
        ref = _text(row, "OSM ID")
        if not ref:
            continue
        cases.append(_new_case(path, ref, _text(row, "Name"),
                               latitude=_number(row.get("Lat")),
                               longitude=_number(row.get("Lon"))))
    return cases


def merge_cases(*groups):
    """One case per candidate reference, with every near place appended. Nine
    references appear in two files. Two files naming one candidate is two
    readings of one car park, not two car parks, and both readings are
    evidence, so the near places join rather than replace."""
    merged, order = {}, []
    for case in itertools.chain(*groups):
        first = merged.get(case.candidate_ref)
        if first is None:
            merged[case.candidate_ref] = case
            order.append(case.candidate_ref)
            continue
        first.near.extend(case.near)
        if case.source_file not in first.source_file.split("+"):
            first.source_file = f"{first.source_file}+{case.source_file}"
        if first.latitude is None and case.latitude is not None:
            first.latitude, first.longitude = case.latitude, case.longitude
        if not first.candidate_name:
            first.candidate_name = case.candidate_name
    return [merged[ref] for ref in order]


def read_only_conn(path):
    """The database, opened read only. Nothing in this module may write to it,
    and an operating system level read only handle proves that rather than
    promising it. db.connect would run the schema script, which is a write."""
    uri = f"file:{Path(path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def reconcile(cases, conn):
    """Fill every case and near place from the database.

    A place already carrying the candidate's OpenStreetMap reference means the
    record exists: the case state becomes "created". The near places arrive from
    the source files as a Place ID and a name, which is not enough to judge
    anything, so the authoritative postcode, geo precision, reference, verifier
    and coordinate are read here."""
    headers, rows = db.current_rows(conn)
    by_osm_id, by_place_id = {}, {}
    for row in rows:
        place_id = str(row.get(db.PLACE_ID) or "").strip()
        if not place_id:
            continue
        by_place_id[place_id] = row
        osm_id = str(row.get("OSM ID") or "").strip()
        if osm_id:
            by_osm_id.setdefault(osm_id, place_id)
    for case in cases:
        place_id = by_osm_id.get(case.candidate_ref)
        if place_id:
            case.state, case.created_place_id = "created", place_id
        for near in case.near:
            row = by_place_id.get(near.place_id)
            if row is None:
                continue
            near.name = str(row.get("Location Name") or "").strip() or near.name
            near.postcode = str(row.get("Postcode") or "").strip()
            near.geo_precision = (str(row.get("Geo Precision") or "").strip()
                                  or near.geo_precision)
            near.osm_id = str(row.get("OSM ID") or "").strip()
            near.verified_by = str(row.get("Verified By") or "").strip()
            near.latitude = _number(row.get("Latitude"))
            near.longitude = _number(row.get("Longitude"))
    return cases


def state_counts(cases):
    """{source file stem: {"pending": n, "created": n}}. A case two files share
    is counted under both, because each file's own total is what a reader of
    that file wants to check."""
    counts = {}
    for case in cases:
        for stem in case.source_file.split("+"):
            tally = counts.setdefault(stem, {"pending": 0, "created": 0})
            tally[case.state] = tally.get(case.state, 0) + 1
    return counts


def load_cases(conn, held_all=HELD_ALL, possible_duplicates=POSSIBLE_DUPLICATES,
               held_strict=HELD_STRICT, held_names=HELD_NAMES):
    """Every known held case, merged by candidate reference and reconciled."""
    groups = []
    if held_all and Path(held_all).exists():
        groups.append(read_held_all(held_all))
    if possible_duplicates and Path(possible_duplicates).exists():
        groups.append(read_possible_duplicates(possible_duplicates))
    for path in (held_strict, held_names):
        if path and Path(path).exists():
            groups.append(read_held_car_parks(path))
    return reconcile(merge_cases(*groups), conn)


# ---------------------------------------------------------------- the evidence

def attach_extract(cases, pbf_path):
    """Attach the extract's own facts to each case: tags, geometry kind, area
    and a representative point. Returns the candidate polygons, which rule 5
    needs and a case record does not carry.

    A reference the extract does not hold keeps geometry "absent" and no tags.
    That is evidence too: it means the hold list is older than the extract."""
    from . import osm_places
    handler = osm_places.collect(pbf_path)
    features = {f"{feature['type']}/{feature['id']}": feature
                for feature in handler.features}
    polygons = {}
    for case in cases:
        feature = features.get(case.candidate_ref)
        if feature is None:
            case.geometry, case.tags = "absent", {}
            continue
        case.tags = dict(feature["tags"])
        case.geometry = feature["type"]
        case.area_m2 = float(feature["area_m2"] or 0.0)
        geom = feature["geom_ll"]
        point, _ = osm_places.point_for(None, geom)
        case.latitude, case.longitude = float(point.y), float(point.x)
        if geom.geom_type != "Point":
            polygons[case.candidate_ref] = geom
    attach_distances(cases, polygons)
    return polygons


def attach_distances(cases, polygons):
    """Measure every candidate to near place distance, and test whether the
    near place's own pin falls inside the candidate's polygon. A node candidate
    has no polygon, so the test has no answer and stays None rather than
    becoming a False that reads like a finding."""
    for case in cases:
        geom = polygons.get(case.candidate_ref)
        for near in case.near:
            if (case.latitude is not None and case.longitude is not None
                    and near.latitude is not None and near.longitude is not None):
                near.metres = round(_metres(case.latitude, case.longitude,
                                            near.latitude, near.longitude), 1)
                near.pin_inside_candidate = (
                    None if geom is None
                    else bool(geom.contains(Point(near.longitude, near.latitude))))
            else:
                near.pin_inside_candidate = None
    return cases


def polygon_path(bundle_path):
    path = Path(bundle_path)
    return path.with_name(f"{path.stem}_polygons.jsonl")


def write_bundle(cases, bundle_path, polygons=None):
    """Parsing a 100 MB extract takes minutes, so the evidence is written once
    and reloaded with --bundle. The candidate polygons go in a sibling file:
    a case record carries a point and an area, and rule 5 needs the shape."""
    bundle_path = Path(bundle_path)
    with open(bundle_path, "x", encoding="utf-8") as stream:
        for case in cases:
            stream.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")
    with open(polygon_path(bundle_path), "x", encoding="utf-8") as stream:
        for ref, geom in (polygons or {}).items():
            stream.write(json.dumps({"candidate_ref": ref, "wkt": geom.wkt}) + "\n")
    return bundle_path


def read_bundle(bundle_path):
    """(cases, polygons) from a written bundle. Reloading must leave rule 5
    able to fire, or a reloaded run would quietly decide fewer cases than the
    run that parsed the extract."""
    bundle_path = Path(bundle_path)
    cases = []
    for line in bundle_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        record["near"] = [NearPlace(**near) for near in record.get("near", [])]
        cases.append(HeldCase(**record))
    polygons = {}
    sibling = polygon_path(bundle_path)
    if sibling.exists():
        for line in sibling.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            polygons[record["candidate_ref"]] = shapely_wkt.loads(record["wkt"])
    return cases, polygons


# ---------------------------------------------------------------- the rules

@dataclass
class Context:
    """What a rule may read beyond its own case: the other cases in the set and
    their polygons. Rule 5 compares one candidate against another."""
    cases: list = field(default_factory=list)
    polygons: dict = field(default_factory=dict)


def is_postcode_centroid(near):
    return "postcode" in str(near.geo_precision or "").lower()


def distance_near(case):
    """The near places whose distance means something. A place geocoded to a
    postcode centroid sits at the middle of a postcode, which can be hundreds
    of metres from the building, so its distance is not evidence of anything."""
    return [near for near in case.near if not is_postcode_centroid(near)]


def already_same_ref(case, context):
    """A place already carries this exact OpenStreetMap reference, so there is
    nothing to create and no distance to measure.

    The candidate's own creation is not such a place. A case the database
    already holds as its own record, and which also names an older place
    nearby, carries the open question of whether that created record duplicates
    the older one. Settling it here on the strength of its own creation would
    throw that question away, so the case falls through to the other rules and
    to the reviewers instead."""
    for near in case.near:
        if near.osm_id and near.osm_id == case.candidate_ref:
            return ("duplicate", f"near place {near.place_id} already carries "
                                 f"OpenStreetMap reference {case.candidate_ref}.")
    if case.state == "created" and case.created_place_id:
        if [near for near in case.near if near.place_id != case.created_place_id]:
            return None
        return ("duplicate", "the database already holds this candidate as place "
                             f"{case.created_place_id}, created from OpenStreetMap "
                             f"reference {case.candidate_ref}: there is nothing "
                             "to create.")
    return None


def protected_row(case, context):
    """A person hand checked one of these rows. No geometry rule may overrule a
    hand check, so the case stops here and is reported to a person instead."""
    for near in case.near:
        if str(near.verified_by or "").strip().lower() == PROTECTED_BY.lower():
            return ("unresolved", f"near place {near.place_id} was hand checked by "
                                  f"{PROTECTED_BY}: this case is reported to a "
                                  "person and never decided here.")
    return None


def pin_inside_candidate_same_brand(case, context):
    """An existing place's own pin falls inside this candidate's polygon, and
    the two names share a brand token. Inside plus the same brand is the same
    car park, where inside alone would only be the same building."""
    for near in distance_near(case):
        if near.pin_inside_candidate and brands_overlap(case.candidate_name, near.name):
            return ("duplicate", f"the pin of place {near.place_id} ({near.name}) "
                                 f"falls inside candidate {case.candidate_ref} and "
                                 f"the two names share the brand "
                                 f"{shared_brand(case.candidate_name, near.name)}.")
    return None


def same_feature_twice(case, context):
    """Another candidate in this set is an area that contains this candidate's
    point, and the names share a brand token. One car park reached the hold
    list twice, once as an area and once as a point. The area is the better
    record, so the point is the duplicate."""
    if case.latitude is None or case.longitude is None:
        return None
    point = Point(case.longitude, case.latitude)
    for other in context.cases:
        if other.candidate_ref == case.candidate_ref:
            continue
        geom = context.polygons.get(other.candidate_ref)
        if geom is None or not geom.contains(point):
            continue
        if brands_overlap(case.candidate_name, other.candidate_name):
            return ("duplicate", f"candidate {other.candidate_ref} "
                                 f"({other.candidate_name}) is an area containing "
                                 f"this candidate's point and the two names share "
                                 f"the brand "
                                 f"{shared_brand(case.candidate_name, other.candidate_name)}: "
                                 "the area is the better record.")
    return None


# Ordered. The first match wins. Rule 1 reads a recorded fact and settles the
# case before any judgment is needed. Rule 2 then stops every hand checked row,
# so no geometry rule below it can overrule a person. No rule returns
# "distinct": creating a car park is a decision two reviewers make, never one
# a geometry test makes on its own.
RULES = (
    ("already_same_ref", already_same_ref),
    ("protected_row", protected_row),
    ("pin_inside_candidate_same_brand", pin_inside_candidate_same_brand),
    ("same_feature_twice", same_feature_twice),
)


def decide(cases, polygons=None):
    """Give every case a verdict, the rule that decided it and the evidence.

    No rule matching is not a failure. It is the common result and the honest
    one: the evidence on file does not settle the case, so two people read it."""
    context = Context(cases=list(cases), polygons=dict(polygons or {}))
    for case in cases:
        for name, rule in RULES:
            result = rule(case, context)
            if result is None:
                continue
            case.verdict, case.evidence = result
            case.decided_by = name
            break
        else:
            case.verdict, case.decided_by = "unresolved", NO_RULE
            nearest = min((near.metres for near in distance_near(case)
                           if near.metres is not None), default=None)
            case.evidence = (
                "no rule matched: " + (
                    f"the nearest usable place is {nearest} m away, which is "
                    "proximity and not proof." if nearest is not None
                    else "there is no usable distance to a place the database holds.")
                + " Two reviewers judge this case.")
    return cases


def protected_cases(cases):
    return [case for case in cases if case.decided_by == "protected_row"]


def review_cases(cases):
    return [case for case in cases if case.decided_by == NO_RULE]


# ---------------------------------------------------------------- the merge

REVIEW_HEADERS = ["case_id", "verdict", "confidence", "evidence"]
CONFIDENCES = ("high", "low")


def read_reviews(path):
    """{case_id: review} from one reviewer's CSV. A row that cannot be read is
    kept and marked, not dropped, because a malformed row must end as
    unresolved and say so rather than quietly disappear."""
    reviews = {}
    for row in _read_csv(path):
        case_id = _text(row, "case_id")
        if not case_id:
            continue
        verdict = _text(row, "verdict").lower()
        confidence = _text(row, "confidence").lower()
        problems = []
        if verdict not in VERDICTS:
            problems.append(f"verdict {verdict or '(blank)'!r} is not one of "
                            f"{', '.join(VERDICTS)}")
        if confidence not in CONFIDENCES:
            problems.append(f"confidence {confidence or '(blank)'!r} is not "
                            "high or low")
        reviews[case_id] = {"case_id": case_id, "verdict": verdict,
                            "confidence": confidence,
                            "evidence": _text(row, "evidence"),
                            "problems": problems}
    return reviews


def merge_verdict(review_a, review_b):
    """(verdict, evidence) from two reviews, either of which may be missing.

    Only full agreement at high confidence decides anything. Every other
    combination is unresolved, and the evidence names why. This matrix is the
    whole accuracy control: one reviewer alone, or one unsure reviewer, must
    never be able to mark a car park a duplicate."""
    missing = [name for name, review in (("a", review_a), ("b", review_b))
               if review is None]
    if missing:
        return ("unresolved", "reviewer " + " and ".join(missing)
                + " did not judge this case, so there is no agreement to read.")
    problems = []
    for name, review in (("a", review_a), ("b", review_b)):
        for problem in review["problems"]:
            problems.append(f"reviewer {name}: {problem}")
    if problems:
        return "unresolved", "a reviewer row could not be read. " + "; ".join(problems) + "."
    if review_a["verdict"] != review_b["verdict"]:
        return ("unresolved", f"the reviewers disagree: a said "
                              f"{review_a['verdict']}, b said {review_b['verdict']}.")
    verdict = review_a["verdict"]
    low = [name for name, review in (("a", review_a), ("b", review_b))
           if review["confidence"] != "high"]
    if low:
        return ("unresolved", f"both reviewers said {verdict}, but reviewer "
                              + " and ".join(low) + " was not confident.")
    if verdict == "unresolved":
        return ("unresolved", "both reviewers said the evidence does not settle "
                              "this case.")
    return verdict, f"both reviewers said {verdict} with high confidence."


def merge(cases, reviews_a, reviews_b):
    """(rows, counts). A case the rules decided is carried through unchanged.

    A reviewer never overrules a rule. Rule 1 reads a recorded fact and rule 2
    protects a hand check, so a reviewer who contradicts either is wrong about
    the case or judging a case they were never sent."""
    rows, counts = [], {
        "cases": len(cases), "carried through from the rules": 0,
        "merged from the reviewers": 0, "reviewer rows not used": 0,
    }
    for verdict in VERDICTS:
        counts[f"final {verdict}"] = 0
    used = set()
    for case in cases:
        review_a, review_b = reviews_a.get(case.case_id), reviews_b.get(case.case_id)
        if case.decided_by != NO_RULE:
            verdict, decided_by, evidence = case.verdict, case.decided_by, case.evidence
            counts["carried through from the rules"] += 1
        else:
            verdict, evidence = merge_verdict(review_a, review_b)
            decided_by = BY_REVIEWERS
            counts["merged from the reviewers"] += 1
        if review_a is not None:
            used.add(case.case_id)
        if review_b is not None:
            used.add(case.case_id)
        counts[f"final {verdict}"] += 1
        rows.append({
            "case_id": case.case_id, "candidate_ref": case.candidate_ref,
            "verdict": verdict, "decided_by": decided_by, "evidence": evidence,
            "reviewer_a": _review_text(review_a), "reviewer_b": _review_text(review_b),
        })
    counts["reviewer rows not used"] = len(
        (set(reviews_a) | set(reviews_b)) - used)
    return rows, counts


def _review_text(review):
    if review is None:
        return "(no row)"
    return f"{review['verdict'] or '(blank)'} / {review['confidence'] or '(blank)'}"


# ---------------------------------------------------------------- the outputs

VERDICT_HEADERS = ["case_id", "candidate_ref", "candidate_name", "source_file",
                   "state", "created_place_id", "geometry", "area_m2",
                   "latitude", "longitude", "near places", "nearest metres",
                   "verdict", "decided_by", "evidence"]
PROTECTED_HEADERS = ["case_id", "candidate_ref", "candidate_name",
                     "near place_id", "near name", "verified_by", "metres",
                     "evidence"]
SAMPLE_HEADERS = ["case_id", "candidate_ref", "candidate_name", "verdict",
                  "decided_by", "evidence", "openstreetmap"]
DECISION_HEADERS = ["case_id", "candidate_ref", "verdict", "decided_by",
                    "evidence", "reviewer_a", "reviewer_b"]
COUNT_HEADERS = ["count", "value"]


def _write_csv(path, rows, fieldnames):
    with open(path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_counts(path, counts):
    return _write_csv(path, [{"count": name, "value": value}
                             for name, value in counts.items()], COUNT_HEADERS)


def verdict_row(case):
    metres = [near.metres for near in case.near if near.metres is not None]
    return {
        "case_id": case.case_id, "candidate_ref": case.candidate_ref,
        "candidate_name": case.candidate_name, "source_file": case.source_file,
        "state": case.state, "created_place_id": case.created_place_id,
        "geometry": case.geometry, "area_m2": round(case.area_m2),
        "latitude": "" if case.latitude is None else f"{case.latitude:.6f}",
        "longitude": "" if case.longitude is None else f"{case.longitude:.6f}",
        "near places": " ".join(near.place_id for near in case.near),
        "nearest metres": min(metres) if metres else "",
        "verdict": case.verdict, "decided_by": case.decided_by,
        "evidence": case.evidence,
    }


def review_payload(case):
    """Only what a reviewer needs to judge the case. No verdict, no rule name
    and no hint of what the other reviewer thought: two reviewers who can read
    each other's answer are one reviewer, and the agreement proves nothing."""
    return {
        "case_id": case.case_id, "candidate_ref": case.candidate_ref,
        "candidate_name": case.candidate_name, "geometry": case.geometry,
        "area_m2": round(case.area_m2), "latitude": case.latitude,
        "longitude": case.longitude, "tags": case.tags,
        "state": case.state, "created_place_id": case.created_place_id,
        "near": [{"place_id": near.place_id, "name": near.name,
                  "postcode": near.postcode, "geo_precision": near.geo_precision,
                  "osm_id": near.osm_id, "metres": near.metres,
                  "pin_inside_candidate": near.pin_inside_candidate}
                 for near in case.near],
    }


def case_osm_url(case):
    kind, _, ident = case.candidate_ref.partition("/")
    if not ident:
        return ""
    return osm_url({"type": kind, "id": ident})


def counts_of(cases):
    counts = {"cases": len(cases)}
    for state in ("pending", "created"):
        counts[f"state {state}"] = sum(1 for case in cases if case.state == state)
    for verdict in VERDICTS:
        counts[f"verdict {verdict}"] = sum(1 for case in cases if case.verdict == verdict)
    for name, _ in RULES:
        counts[f"decided by {name}"] = sum(1 for case in cases if case.decided_by == name)
    counts[f"decided by {NO_RULE}"] = len(review_cases(cases))
    counts["geometry absent from the extract"] = sum(
        1 for case in cases if case.geometry == "absent")
    for stem, tally in sorted(state_counts(cases).items()):
        counts[f"{stem} pending"] = tally["pending"]
        counts[f"{stem} created"] = tally["created"]
    return counts


def write_review_batches(cases, out_dir, size=BATCH_SIZE):
    """A reviewer judges a batch at a sitting, so the batches are small and
    each is a complete, self contained file."""
    review_dir = Path(out_dir) / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    pending = review_cases(cases)
    paths = []
    for number, start in enumerate(range(0, len(pending), size), start=1):
        path = review_dir / f"batch_{number:02d}.json"
        path.write_text(json.dumps(
            [review_payload(case) for case in pending[start:start + size]],
            indent=2, ensure_ascii=False), encoding="utf-8")
        paths.append(path)
    return paths


def write_sample(cases, path, size=SAMPLE_SIZE, seed=SAMPLE_SEED):
    """A seeded sample of the cases the rules decided, with a link each, so a
    person can spot check the rules. For reference. It blocks nothing."""
    decided = [case for case in cases if case.decided_by != NO_RULE]
    chosen = random.Random(seed).sample(decided, min(size, len(decided)))
    return _write_csv(path, [
        {"case_id": case.case_id, "candidate_ref": case.candidate_ref,
         "candidate_name": case.candidate_name, "verdict": case.verdict,
         "decided_by": case.decided_by, "evidence": case.evidence,
         "openstreetmap": case_osm_url(case)} for case in chosen], SAMPLE_HEADERS)


def write_outputs(cases, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "rule_verdicts.csv",
               [verdict_row(case) for case in cases], VERDICT_HEADERS)
    protected = []
    for case in protected_cases(cases):
        for near in case.near:
            if str(near.verified_by or "").strip().lower() != PROTECTED_BY.lower():
                continue
            protected.append({
                "case_id": case.case_id, "candidate_ref": case.candidate_ref,
                "candidate_name": case.candidate_name, "near place_id": near.place_id,
                "near name": near.name, "verified_by": near.verified_by,
                "metres": "" if near.metres is None else near.metres,
                "evidence": case.evidence})
    _write_csv(out_dir / "protected_rows.csv", protected, PROTECTED_HEADERS)
    _write_counts(out_dir / "counts.csv", counts_of(cases))
    batches = write_review_batches(cases, out_dir)
    write_sample(cases, out_dir / "sample60.csv")
    return out_dir, batches


# ---------------------------------------------------------------- commands

def bundle_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="holds-bundle",
        description="Read only: gather the evidence on every held car park "
                    "candidate, apply the rule registry and write the reviewer "
                    "batches. Never writes to the database or the sheet.")
    parser.add_argument("--pbf", help="OpenStreetMap extract to read the "
                                      "candidate geometry from")
    parser.add_argument("--bundle", help="Reload a written bundle.jsonl instead "
                                         "of parsing the extract again")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", default=None)
    parser.add_argument("--held-all", default=str(HELD_ALL))
    parser.add_argument("--possible-duplicates", default=str(POSSIBLE_DUPLICATES))
    parser.add_argument("--held-strict", default=str(HELD_STRICT))
    parser.add_argument("--held-names", default=str(HELD_NAMES))
    args = parser.parse_args(argv)
    if not args.pbf and not args.bundle:
        parser.error("give --pbf to parse the extract or --bundle to reload one")

    if args.bundle:
        cases, polygons = read_bundle(args.bundle)
        print(f"Reloaded {len(cases)} cases from {args.bundle}")
    else:
        conn = read_only_conn(args.db)
        cases = load_cases(conn, args.held_all, args.possible_duplicates,
                           args.held_strict, args.held_names)
        for stem, tally in sorted(state_counts(cases).items()):
            print(f"{stem:34s} {tally['pending']} pending, {tally['created']} "
                  "already created")
        polygons = attach_extract(cases, args.pbf)
    decide(cases, polygons)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("holds")
    if not args.bundle:
        write_bundle(cases, out_dir / "bundle.jsonl", polygons)
    out_dir, batches = write_outputs(cases, out_dir)
    for name, value in counts_of(cases).items():
        print(f"{name:46s} {value}")
    print(f"\n{len(batches)} reviewer batches of at most {BATCH_SIZE} cases")
    print(f"Report: {out_dir}")
    return 0


def merge_main(argv=None):
    parser = argparse.ArgumentParser(
        prog="holds-merge",
        description="Merge two reviewers' verdicts. Only full agreement at high "
                    "confidence decides a case. Everything else is unresolved, "
                    "and a case the rules decided is carried through unchanged.")
    parser.add_argument("--a", required=True, help="reviewer A's CSV")
    parser.add_argument("--b", required=True, help="reviewer B's CSV")
    parser.add_argument("--bundle", required=True, help="the bundle.jsonl the "
                                                        "reviewers judged")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    cases, polygons = read_bundle(args.bundle)
    rows, counts = merge(cases, read_reviews(args.a), read_reviews(args.b))
    out_dir = reserve_output(args.out) if args.out else new_run_dir("holds_merge")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "decisions.csv", rows, DECISION_HEADERS)
    _write_counts(out_dir / "merge_counts.csv", counts)
    for name, value in counts.items():
        print(f"{name:34s} {value}")
    print(f"Report: {out_dir}")
    return 0
