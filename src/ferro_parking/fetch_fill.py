"""Run one registered fetcher over its routed rows and emit a plan file.

    python -m ferro_parking fetch-fill --key station --limit 20
    python -m ferro_parking fetch-fill --key puregym.com
    python -m ferro_parking fetch-fill --key marksandspencer.com   (cache only)

A dry run. It fetches pages, writes nothing to the sheet, and writes no change
to the database except the pages table, which is the page cache itself.

The report counts rows attempted, pages fetched, plan lines, silent pages and
blocked pages, and saves ten example rows with the quote and the URL.

A row the fetcher cannot answer stays unanswered. The next route run sends it
to the bot, or to no_evidence, by the ordinary rules.
"""
import argparse
import csv
import json

from . import db, fill, page_fill, plan as plan_mod
from .fill import LOCATION_NAME, PLACE_ID
from .run_paths import new_run_dir, reserve_output
from .sources.fetch import fetch, looks_like_a_challenge
from .sources.station import StationFetcher, station_slug
from .sources.venue import VenueFetcher

# Fetcher E is cache only: the pages are fetched so the evidence gate can read
# them, and no value is ever written from them.
CACHE_ONLY = {"marksandspencer.com"}

REGISTRY = {
    "station": StationFetcher(),
    "better.org.uk": VenueFetcher("better.org.uk"),
    "thegymgroup.com": VenueFetcher("thegymgroup.com"),
    "puregym.com": VenueFetcher("puregym.com"),
}

EXAMPLE_HEADERS = ["key", "Place ID", "Location Name", "url", "http status", "outcome",
                   "quote", "columns"]
UNRESOLVED_HEADERS = ["key", "Place ID", "Location Name", "reason"]
BLOCKED_HEADERS = ["key", "Place ID", "Location Name", "url", "reason"]

# validate_rows asks for both whenever Can Park? is Yes or Conditional, and it
# sees only the plan's own columns, so the row's values travel as context.
CONTEXT_COLUMNS = ("Brand", "Place Category")
DASHES = ("\u2013", "\u2014")


def rows_for(conn, key, stage_keys=True):
    """The routed rows this fetcher owns: the station stage for the station
    fetcher, else every routed row whose derived source key matches."""
    from . import route

    run_id, routing = db.latest_routing(conn)
    if run_id is None:
        raise SystemExit("No routing run in the database. Run route first.")
    _, rows = db.current_rows(conn)
    out = []
    for row in rows:
        place_id = (row.get(PLACE_ID) or "").strip()
        stage = routing.get(place_id)
        if stage is None or stage.startswith("skip"):
            continue
        if fill.is_named_person(row.get(fill.VERIFIED_BY)):
            continue
        if key == "station":
            if stage == "station" or (stage == "grok" and route.is_station(row)):
                out.append((row, stage))
        elif route.source_key(row) == key:
            out.append((row, stage))
    return out, run_id


def plan_lines(place_id, stage, values, notes, flags, row, quote, url, verified_by, today):
    """(lines, blocked_reason). fill-shaped values turned into plan lines, with
    Notes and Review Flag appended rather than replaced, exactly as page_fill
    does it."""
    extracted = dict(values)
    if notes:
        extracted["_notes"] = list(notes)
    if flags:
        extracted["_flags"] = list(flags)
    new = page_fill.build_row_values(row, extracted, today, {}, verified_by=verified_by)

    if new.get(fill.CAN_PARK) in ("Yes", "Conditional"):
        missing = [column for column in CONTEXT_COLUMNS
                   if not (new.get(column) or row.get(column) or "").strip()]
        if missing:
            return [], (f"the row has no {' and no '.join(missing)}, which the validator "
                        f"asks for on a Yes or Conditional row")
        for column in CONTEXT_COLUMNS:
            new.setdefault(column, row.get(column, ""))

    previous_urls = row.get(fill.SOURCE_URLS, "") or ""
    new[fill.SOURCE_URLS] = "; ".join(dict.fromkeys([url] + [part.strip() for part in previous_urls.split(";") if part.strip()]))

    # The sheet's own Notes sometimes holds an en dash, and appending to it
    # would fail the validator on text somebody else wrote. The parking fact
    # still lands in Evidence Detail, so the Notes line is simply left out.
    if "Notes" in new and any(dash in str(new["Notes"]) for dash in DASHES):
        del new["Notes"]

    lines = []
    for column in sorted(new, key=lambda name: (name == fill.VERIFICATION_RESULT, name)):
        value = new[column]
        if value is None or str(value).strip() == "":
            continue
        lines.append({"place_id": place_id, "column": column, "new_value": str(value),
                       "quote": quote, "source_url": url, "stage": stage,
                       "verified_by": verified_by})
    return lines, ""


def run(conn, key, limit=None, today=None, fetcher=None):
    """(lines, report). Fetches at most `limit` pages."""
    from datetime import date

    today = today or date.today()
    cache_only = key in CACHE_ONLY
    fetcher = fetcher or REGISTRY.get(key)
    if fetcher is None and not cache_only:
        raise SystemExit(f"No fetcher registered for {key!r}. "
                         f"Registered: {', '.join(sorted(REGISTRY))}, "
                         f"cache only: {', '.join(sorted(CACHE_ONLY))}")
    if cache_only and fetcher is None:
        from .sources.fetch import SourceUrlFetcher
        fetcher = SourceUrlFetcher(key)

    candidates, run_id = rows_for(conn, key)
    if limit:
        candidates = candidates[:limit]

    lines, examples, unresolved, blocked_rows = [], [], [], []
    counts = {"rows attempted": 0, "pages fetched": 0, "plan lines": 0,
              "silent pages": 0, "blocked pages": 0, "unresolved names": 0,
              "rows with values": 0, "rows held for a person": 0}

    from .category_default import load_osm_rows
    from .route import mapped_car_park_50m
    osm_rows, osm_source = load_osm_rows()
    for row, stage in candidates:
        row = dict(row)
        if key == "station":
            mapped = mapped_car_park_50m(osm_rows.get(row.get(PLACE_ID)))
            row["_mapped_car_park_50m"] = mapped is not False
        place_id = (row.get(PLACE_ID) or "").strip()
        counts["rows attempted"] += 1
        url = fetcher.branch_url(row)
        if not url:
            counts["unresolved names"] += 1
            unresolved.append({"key": key, "Place ID": place_id,
                                "Location Name": row.get(LOCATION_NAME, ""),
                                "reason": "not National Rail" if key == "station" else "no official branch URL"})
            examples.append({"key": key, "Place ID": place_id, "Location Name": row.get(LOCATION_NAME, ""),
                                 "url": "", "http status": "", "outcome": "not National Rail" if key == "station" else "unresolved",
                                 "quote": "", "columns": ""})
            continue

        status, text, _ = fetch(url, conn)
        blocked = (status != 200 and status != 404) or (status == 200 and looks_like_a_challenge(text))
        if blocked:
            counts["blocked pages"] += 1
            outcome = "blocked"
            values, notes, flags, quote = {}, [], [], ""
        elif status == 404:
            counts["unresolved names"] += 1
            unresolved.append({"key": key, "Place ID": place_id,
                                "Location Name": row.get(LOCATION_NAME, ""),
                                "reason": f"{url} answered 404, so the name did not resolve"})
            continue
        else:
            counts["pages fetched"] += 1
            if cache_only:
                outcome = "cached only"
                values, notes, flags, quote = {}, [], [], ""
            else:
                result = fetcher.values(text, row)
                values, notes, flags, quote = (result if len(result) == 4
                                                else (result[0], result[1], [], result[2]))
                if values.get(fill.REVIEW_FLAG):
                    flags.append(values.pop(fill.REVIEW_FLAG))
                if values:
                    outcome = "values"
                    counts["rows with values"] += 1
                else:
                    outcome = "silent"
                    counts["silent pages"] += 1

        row_lines = []
        if values:
            row_lines, held = plan_lines(
                place_id, stage, values, notes, flags, row, quote, url,
                getattr(fetcher, "verified_by", "Code (page fetch)"), today)
            if held:
                counts["rows with values"] -= 1
                counts["rows held for a person"] += 1
                blocked_rows.append({"key": key, "Place ID": place_id,
                                      "Location Name": row.get(LOCATION_NAME, ""),
                                      "url": url, "reason": held})
                outcome = "held"
            lines.extend(row_lines)
            counts["plan lines"] += len(row_lines)
        examples.append({
                "key": key, "Place ID": place_id, "Location Name": row.get(LOCATION_NAME, ""),
                "url": url, "http status": status, "outcome": outcome,
                "quote": quote,
                "columns": ", ".join(sorted({line["column"] for line in row_lines})),
            })

    return lines, {"key": key, "routing_run": run_id, "counts": counts,
                   "examples": sorted(examples, key=lambda e: (e["outcome"] != "values", e["outcome"] == "not National Rail"))[:10], "unresolved": unresolved,
                   "held": blocked_rows, "osm_source": osm_source}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one fetcher and emit a plan. Dry run.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    if args.key == "station":
        from .sources.station_list import load
        REGISTRY["station"] = StationFetcher(load(conn))
    lines, report = run(conn, args.key, args.limit)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("fetch_fill")
    plan_mod.write_plan(out_dir / "plan.jsonl", lines)
    for name, headers, rows in (("examples.csv", EXAMPLE_HEADERS, report["examples"]),
                                 ("unresolved.csv", UNRESOLVED_HEADERS, report["unresolved"]),
                                 ("held.csv", BLOCKED_HEADERS, report["held"])):
        with open(out_dir / name, "x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    with (out_dir / "summary.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=True)

    print(f"Fetcher {args.key!r}, routing run {report['routing_run']}")
    for name, count in report["counts"].items():
        print(f"  {name}: {count}")
    print(f"\nTen examples: {out_dir / 'examples.csv'}")
    print(f"Unresolved names: {out_dir / 'unresolved.csv'}")
    print(f"Rows held for a person: {out_dir / 'held.csv'}")
    print(f"Plan: {out_dir / 'plan.jsonl'}")
    print("Dry run only. Check it with db-apply, which needs --apply to write.")
    return 0
