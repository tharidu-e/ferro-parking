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

from . import db, discovery, readiness
from .discover import source_urls
from .fill import CAN_PARK, LOCATION_NAME, PLACE_ID, SOURCE_URLS, VERIFICATION_RESULT, VERIFIED_BY
from .osm_match import brand_key, contains_word, norm
from .run_paths import new_run_dir, reserve_output
from .triage_blanks import bucket

# The only named person on the sheet. Agent labels such as "PP (validation)",
# "Policy script", "Grok (discovery)" and "Claude (capture check)" are not
# people, so their rows stay routable.
NAMED_VERIFIER_PREFIX = "Tharidu"

ON_SITE = "Needs on-site check"
PUBLIC_CAR_PARK_CATEGORIES = ("Council car park", "Private / operator car park")

# No fetcher exists yet. Phase 5 registers one key per fetcher here.
FETCHERS = {}

HEADERS = ["Place ID", "name", "stage", "priority", "source key", "reason"]

_categories = None


def categories():
    global _categories
    if _categories is None:
        _categories = discovery.load_categories()
    return _categories


# ---------------------------------------------------------------- row reading

def is_public_car_park(row):
    """The row is itself a car park open to the public, by the brief's test:
    one of the two car park categories, or a Type that says car park."""
    if (row.get("Place Category") or "").strip() in PUBLIC_CAR_PARK_CATEGORIES:
        return True
    return contains_word(norm(row.get("Type (as captured)", "")), "car park")


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


def source_key(row):
    """Operator first, then the first Source URL's domain, then the brand
    parsed from the name. Empty when the row gives none of the three."""
    operator = (row.get("Operator") or "").strip()
    if operator and operator not in ("Not published", "Not applicable", "Unknown"):
        return norm(operator)
    domain = first_source_domain(row.get(SOURCE_URLS, ""))
    if domain:
        return domain
    return brand_key(row)


def has_parking_gap(row):
    """Priority 2's gap: the row says you can park but not who or at what cost."""
    return not readiness.known(row.get("Who Can Park")) or not readiness.known(row.get("Cost Type"))


# ---------------------------------------------------------------- the decision

def classify(row, missing, duplicates, fetchers=None):
    """(stage, priority, source_key, reason) for one row. Exactly one stage."""
    fetchers = FETCHERS if fetchers is None else fetchers
    place_id = (row.get(PLACE_ID) or "").strip()
    verified_by = (row.get(VERIFIED_BY) or "").strip()
    result = (row.get(VERIFICATION_RESULT) or "").strip()

    if verified_by.startswith(NAMED_VERIFIER_PREFIX):
        return "skip_named", "", "", f"Verified By is {verified_by!r}, a named person"
    if place_id in missing:
        return "skip_missing", "", "", "missing from the newest import"
    if duplicates.get(place_id):
        return "skip_duplicate", "", "", f"marked a duplicate of {duplicates[place_id]}"
    if result == ON_SITE:
        return "skip_onsite", "", "", "Verification Result is Needs on-site check"

    public = is_public_car_park(row)
    gap = public and row.get(CAN_PARK) in ("Yes", "Conditional") and has_parking_gap(row)

    if result and not gap:
        return "skip_done", "", "", f"Verification Result is {result!r}"

    if gap:
        priority, why = "2", "public car park with no Who Can Park or Cost Type"
    else:
        priority, why = "1", "Verification Result is blank"

    key = source_key(row)
    group, bucket_reason = bucket(row, categories())
    if key and key in fetchers:
        return f"fetcher:{key}", priority, key, f"{why}; fetcher for {key}"
    if public:
        return "grok", priority, key, f"{why}; public car park, no fetcher ({bucket_reason})"
    return "default", priority, key, f"{why}; customer venue ({bucket_reason})"


def route_rows(rows, missing, duplicates, fetchers=None):
    """One routing record per row, in the order given."""
    out = []
    for row in rows:
        stage, priority, key, reason = classify(row, missing, duplicates, fetchers)
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
    return {
        "per_stage": Counter(record["stage"] for record in records),
        "per_priority": Counter(record["priority"] or "skipped" for record in records),
        "grok_keys": Counter(record["source key"] for record in routed
                             if record["stage"] == "grok" and record["source key"]),
        "default_keys": Counter(record["source key"] for record in routed
                                if record["stage"] == "default" and record["source key"]),
        "no_key": Counter(record["stage"] for record in routed if not record["source key"]),
        "routed": len(routed),
        "stations_routed": stations,
    }


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
    for title, key in (("grok", "grok_keys"), ("default", "default_keys")):
        print(f"\nTop 30 source keys within {title}")
        for name, count in report[key].most_common(30):
            print(f"  {name}: {count}")
    print("\nRouted rows with no source key")
    for stage, count in sorted(report["no_key"].items()):
        print(f"  {stage}: {count}")
    if not report["no_key"]:
        print("  none")
    print(f"\nRouted rows in the Station category: {report['stations_routed']}")
    print("Station has no dedicated stage yet.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assign every row one research stage.")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    headers, rows = db.current_rows(conn)
    if not rows:
        raise SystemExit("Nothing imported yet. Run db-import first.")
    missing = db.missing_place_ids(conn)
    duplicates = db.duplicate_of_map(conn)
    records = route_rows(rows, missing, duplicates)

    run_id = "route-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_routing(conn, run_id, records)
    out_dir = reserve_output(args.out) if args.out else new_run_dir("route")
    with open(out_dir / "routing.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(records)

    print_report(counts(records, rows))
    print(f"\nRun {run_id}. Output: {out_dir / 'routing.csv'}")
    return 0
