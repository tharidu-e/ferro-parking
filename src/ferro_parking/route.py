"""Phase 2: send every unfinished row to the cheapest stage that can answer it.

    python -m ferro_parking route

Reads the local database, gives each Place ID exactly one stage, writes the
routing table and data/runs/<date>/route/routing.csv, and prints the counts.
No sheet access and no network.

Decision order, first match wins:

1. skip_named      Verified By starts with "Tharidu". Hand-checked, never touched.
2. skip_missing    The newest import no longer lists this Place ID.
3. skip_duplicate  duplicate_of is set.
4. skip_onsite     Verification Result is "Needs on-site check".
5. skip_done       Verification Result is filled, unless rule 6 applies.
6. priority 2      A public car park that says you can park, but does not say
                   who can park or what it costs.
7. priority 1      Verification Result is blank.

A routed row then gets its stage from its derived source key: a registered
fetcher for that key, else grok for a public car park, else default. No
fetcher is registered yet, so the fetcher stage stays empty. The key is still
computed and reported, because Phase 5 picks its first fetchers from it.

"Known" comes from readiness.known, so blank, Unknown and Not published all
read as not known. The bucket reasons come from triage_blanks.bucket.
"""
import argparse
import csv
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import car_park_evidence, db, discovery, readiness
from .discover import source_urls
from . import fill
from .fill import CAN_PARK, LOCATION_NAME, PLACE_ID, SOURCE_URLS, VERIFICATION_RESULT, VERIFIED_BY
from .osm_match import brand_key, contains_word, norm
from .run_paths import new_run_dir, reserve_output
from .triage_blanks import bucket

ON_SITE = "Needs on-site check"
PUBLIC_CAR_PARK_CATEGORIES = ("Council car park", "Private / operator car park")
STATION_CATEGORY = "Station"

# A row named "Kings Mall Car Park" or "Westfield London - Car Parks A, B & C"
# is a car park whatever its Place Category says, and 181 such rows carry a
# blank category. "car parks" is listed on its own because contains_word
# matches whole words, and the plural is one.
CAR_PARK_NAME_WORDS = ("car park", "car parks", "parking")

# brand_key falls back to the first two words of the name, which on a car park
# row is the car park's own wording rather than a brand: "Beckton Gateway Car
# Park" gives "beckton gateway", but "Sainsbury's Car Park" gives "sainsburys
# car" and a bare "Car Park" gives "car park". Trailing words from this list
# are dropped so the Phase 5 fan-out counts read as brands.
KEY_TRAILING_NOISE = ("car", "park", "parking", "station", "carpark")
UNBRANDED = "unbranded"

# No fetcher exists yet. Phase 5 registers one key per fetcher here.
from .fetch_fill import REGISTRY as FETCHERS

HEADERS = ["Place ID", "name", "stage", "priority", "source key", "reason"]

_categories = None


def categories():
    global _categories
    if _categories is None:
        _categories = discovery.load_categories()
    return _categories


# ---------------------------------------------------------------- row reading

def name_says_car_park(row):
    """The Location Name itself says this place is a car park."""
    name = norm(row.get(LOCATION_NAME, ""))
    return any(contains_word(name, word) for word in CAR_PARK_NAME_WORDS)


def is_public_car_park(row):
    """The row is itself a car park open to the public: one of the two car park
    categories, or a Type that says car park. This is the test the priority 2
    rule uses, and it does not read the name."""
    if (row.get("Place Category") or "").strip() in PUBLIC_CAR_PARK_CATEGORIES:
        return True
    return contains_word(norm(row.get("Type (as captured)", "")), "car park")


def is_public_car_park_for_stage(row):
    """The same test plus the name, used only to choose a stage. A row named
    "Kings Mall Car Park" belongs with the car parks whatever its category
    says. The name never decides whether a row is routed at all: a finished
    row stays finished."""
    return is_public_car_park(row) or name_says_car_park(row)


def car_park_by_name_only(row):
    """True when only the name says car park. These rows moved to grok when the
    name test was added, so the report shows examples of them."""
    if (row.get("Place Category") or "").strip() in PUBLIC_CAR_PARK_CATEGORIES:
        return False
    if contains_word(norm(row.get("Type (as captured)", "")), "car park"):
        return False
    return name_says_car_park(row)


def is_station(row):
    """A station row: the Station category, or a Type that says station car
    park. Checked before grok and default, because a station car park is
    neither a customer venue nor an ordinary public car park."""
    if (row.get("Place Category") or "").strip() == STATION_CATEGORY:
        return True
    return contains_word(norm(row.get("Type (as captured)", "")), "station car park")


def first_source_domain(value):
    """The host of the first usable Source URL, lower case, without www.
    Order matters here, so this walks the raw field and hands each candidate
    to discover.source_urls, which owns what counts as a usable URL."""
    for item in re.split(r";|\s+", value or ""):
        item = item.strip()
        if item and source_urls(item):
            host = urlsplit(item).netloc.lower()
            return host[4:] if host.startswith("www.") else host
    return ""


def strip_key_noise(key):
    """Drop trailing car park wording from a fallback key."""
    words = key.split()
    while words and words[-1] in KEY_TRAILING_NOISE:
        words.pop()
    return " ".join(words)


def source_key(row):
    """Operator first, then the first Source URL's domain, then the brand
    parsed from the name. "unbranded" when the row gives none of the three."""
    operator = (row.get("Operator") or "").strip()
    if operator and operator not in ("Not published", "Not applicable", "Unknown"):
        return norm(operator)
    domain = first_source_domain(row.get(SOURCE_URLS, ""))
    if domain:
        return domain
    return strip_key_noise(brand_key(row)) or UNBRANDED


def has_parking_gap(row):
    """Priority 2's gap: the row says you can park but not who or at what cost."""
    return not readiness.known(row.get("Who Can Park")) or not readiness.known(row.get("Cost Type"))


# ---------------------------------------------------------------- the decision

def mapped_car_park_50m(osm_row):
    """None means the fresh match did not cover the row, so absence is unknown."""
    if osm_row is None:
        return None
    try:
        distance = float(osm_row.get("Car Park Distance (m)", ""))
        return 0 <= distance <= 50
    except (ValueError, TypeError):
        return False


def station_override(row, osm_row, conn):
    from .sources.station import StationFetcher, NO_SPACES, denial_conflict
    from .sources.station_list import load
    from .sources.fetch import cached, looks_like_a_challenge
    lookup = load()
    if lookup is None:
        return None
    url = StationFetcher(lookup).branch_url(row)
    if not url:
        return "not National Rail: no exact match in the official station list"
    if conn is not None:
        page = cached(conn, url)
        if page and page[0] == 404:
            return "not National Rail: official station page did not resolve"
        if page and page[0] == 200 and not looks_like_a_challenge(page[1]) and NO_SPACES.search(page[1]):
            mapped = mapped_car_park_50m(osm_row)
            if denial_conflict({**row, "_mapped_car_park_50m": mapped is not False}):
                return "Station page says no parking but the row shows a car park: confirm"
    return None


def classify(row, missing, duplicates, fetchers=None, osm_rows=None, conn=None):
    """(stage, priority, source_key, reason) for one row. Exactly one stage."""
    fetchers = FETCHERS if fetchers is None else fetchers
    osm_rows = osm_rows or {}
    place_id = (row.get(PLACE_ID) or "").strip()
    verified_by = (row.get(VERIFIED_BY) or "").strip()
    result = (row.get(VERIFICATION_RESULT) or "").strip()

    if fill.is_named_person(verified_by):
        return "skip_named", "", "", f"Verified By is {verified_by!r}, a named person"
    if place_id in missing:
        return "skip_missing", "", "", "missing from the newest import"
    if duplicates.get(place_id):
        return "skip_duplicate", "", "", f"marked a duplicate of {duplicates[place_id]}"
    if result == ON_SITE:
        return "skip_onsite", "", "", "Verification Result is Needs on-site check"

    gap = (is_public_car_park(row) and row.get(CAN_PARK) in ("Yes", "Conditional")
           and has_parking_gap(row))

    if result and not gap:
        return "skip_done", "", "", f"Verification Result is {result!r}"

    if gap:
        priority, why = "2", "public car park with no Who Can Park or Cost Type"
    else:
        priority, why = "1", "Verification Result is blank"

    key = source_key(row)
    _, bucket_reason = bucket(row, categories())
    if key != UNBRANDED and key in fetchers and key != "station":
        return f"fetcher:{key}", priority, key, f"{why}; fetcher for {key}"
    if is_station(row):
        override = station_override(row, osm_rows.get(place_id), conn)
        if override:
            return "grok", priority, key, f"{why}; {override}"
        return "station", priority, key, f"{why}; National Rail station research"
    if is_public_car_park_for_stage(row):
        return "grok", priority, key, f"{why}; public car park, no fetcher ({bucket_reason})"
    evidence, _, _ = car_park_evidence.evidence_for(row, osm_rows.get(place_id), conn)
    if evidence is None:
        return ("no_evidence", priority, key,
                f"{why}; no evidence that this venue has a car park, so no category "
                f"default and no bot queue ({bucket_reason})")
    return "default", priority, key, f"{why}; customer venue with {evidence} ({bucket_reason})"


def route_rows(rows, missing, duplicates, fetchers=None, osm_rows=None, conn=None):
    """One routing record per row, in the order given."""
    out = []
    for row in rows:
        stage, priority, key, reason = classify(row, missing, duplicates, fetchers,
                                                 osm_rows, conn)
        out.append({
            "Place ID": (row.get(PLACE_ID) or "").strip(),
            "name": row.get(LOCATION_NAME, ""),
            "stage": stage,
            "priority": priority,
            "source key": key,
            "reason": reason,
        })
    return out


# ---------------------------------------------------------------- reporting

def counts(records, rows):
    """Printable counts. rows is needed for the Station category count, which
    reads the sheet row rather than the routing record."""
    by_place_id = {(row.get(PLACE_ID) or "").strip(): row for row in rows}
    routed = [record for record in records if record["priority"]]
    stations = sum(1 for record in routed
                   if discovery.classify_sheet_row(by_place_id[record["Place ID"]], categories()) == "station")
    def keys_for(stage):
        return Counter(record["source key"] for record in routed
                       if record["stage"] == stage and record["source key"] != UNBRANDED)

    movers = [{"Place ID": record["Place ID"], "name": by_place_id[record["Place ID"]].get(LOCATION_NAME, ""),
                "stage": record["stage"],
                "Place Category": by_place_id[record["Place ID"]].get("Place Category", "") or "(blank)",
                "Type (as captured)": by_place_id[record["Place ID"]].get("Type (as captured)", "") or "(blank)"}
               for record in routed
               if car_park_by_name_only(by_place_id[record["Place ID"]])]
    return {
        "name_only_car_parks": movers,
        "no_evidence_keys": keys_for("no_evidence"),
        "per_stage": Counter(record["stage"] for record in records),
        "per_priority": Counter(record["priority"] or "skipped" for record in records),
        "grok_keys": keys_for("grok"),
        "default_keys": keys_for("default"),
        "station_keys": keys_for("station"),
        "no_key": Counter(record["stage"] for record in routed
                          if record["source key"] == UNBRANDED),
        "routed": len(routed),
        "stations_routed": stations,
        "station_stage": sum(1 for record in routed if record["stage"] == "station"),
    }


PROPOSAL_HEADERS = ["Place ID", "issue", "column", "current value", "suggestion"]


def review_proposals(rows, records):
    """Routed rows the router cannot identify, for a person to look at. Nothing
    here is ever written back: Location Name is a protected column, so a fix is
    always a proposal (hard rule 3 of the db-router brief)."""
    routed = {record["Place ID"] for record in records if record["priority"]}
    out = []
    for row in rows:
        place_id = (row.get(PLACE_ID) or "").strip()
        if place_id not in routed:
            continue
        if not (row.get(LOCATION_NAME) or "").strip():
            out.append({
                "Place ID": place_id,
                "issue": "blank Location Name, so the row has no brand fallback key",
                "column": LOCATION_NAME,
                "current value": "",
                "suggestion": "name the place by hand, or mark the row a duplicate",
            })
    return out


def write_routing(conn, run_id, records):
    conn.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason) VALUES (?, ?, ?, ?)",
        [(run_id, record["Place ID"], record["stage"], record["reason"]) for record in records])
    conn.commit()


def print_report(report):
    print(f"{sum(report['per_stage'].values())} rows, {report['routed']} routed\n")
    print("Per stage")
    for stage, count in sorted(report["per_stage"].items(), key=lambda item: (-item[1], item[0])):
        print(f"  {stage}: {count}")
    print("\nPer priority")
    for priority, count in sorted(report["per_priority"].items()):
        print(f"  {priority}: {count}")
    for title, key in (("station", "station_keys"), ("grok", "grok_keys"),
                       ("default", "default_keys"), ("no_evidence", "no_evidence_keys")):
        print(f"\nTop 30 source keys within {title}")
        for name, count in report[key].most_common(30):
            print(f"  {name}: {count}")
        if not report[key]:
            print("  none")
    print(f"\nRouted rows with no usable source key, grouped as {UNBRANDED!r}")
    for stage, count in sorted(report["no_key"].items()):
        print(f"  {stage}: {count}")
    if not report["no_key"]:
        print("  none")
    print(f"\nRouted rows in the Station category: {report['stations_routed']}")
    print(f"Routed rows on the station stage: {report['station_stage']}")

    movers = report["name_only_car_parks"]
    print(f"\nRouted rows that are car parks by name alone: {len(movers)}")
    print("Their Place Category and Type do not say car park, so only the name moves them.")
    for mover in movers[:20]:
        print(f"  {mover['Place ID']} -> {mover['stage']}: {mover['name'][:52]!r} "
              f"(category {mover['Place Category']}, type {mover['Type (as captured)']})")
    if len(movers) > 20:
        print(f"  and {len(movers) - 20} more, all in routing.csv")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assign every row one research stage.")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--osm-results", default=None)
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    from . import category_default
    conn = db.connect(args.db)
    headers, rows = db.current_rows(conn)
    if not rows:
        raise SystemExit("Nothing imported yet. Run db-import first.")
    missing = db.missing_place_ids(conn)
    duplicates = db.duplicate_of_map(conn)
    osm_rows, osm_source = category_default.load_osm_rows(args.osm_results)
    records = route_rows(rows, missing, duplicates, osm_rows=osm_rows, conn=conn)

    run_id = "route-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_routing(conn, run_id, records)
    out_dir = reserve_output(args.out) if args.out else new_run_dir("route")
    with open(out_dir / "routing.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(records)
    proposals = review_proposals(rows, records)
    with open(out_dir / "proposals.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=PROPOSAL_HEADERS)
        writer.writeheader()
        writer.writerows(proposals)

    print(f"OSM results used: {osm_source or 'none found'}")
    print(f"Cached pages in the database: "
          f"{conn.execute('SELECT COUNT(*) AS n FROM pages').fetchone()['n']}\n")
    print_report(counts(records, rows))
    print(f"\n{len(proposals)} rows need a person to look at them: {out_dir / 'proposals.csv'}")
    print(f"Run {run_id}. Output: {out_dir / 'routing.csv'}")
    return 0
