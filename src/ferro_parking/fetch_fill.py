"""Run one registered fetcher over its routed rows and emit a plan file.

    python -m ferro_parking fetch-fill --key station --limit 20
    python -m ferro_parking fetch-fill --key puregym.com
    python -m ferro_parking fetch-fill --key storelocator.asda.com
    python -m ferro_parking fetch-fill --key marksandspencer.com   (cache only)

A dry run. It fetches pages, writes nothing to the sheet, and writes no change
to the database except the pages table, which is the page cache itself.

The report counts rows attempted, pages fetched, plan lines, silent pages,
blocked pages, network requests, cache hits, failed requests and the measured
pages per minute, and saves ten example rows with the quote and the URL.

A row the fetcher cannot answer stays unanswered. The next route run sends it
to the bot, or to no_evidence, by the ordinary rules.
"""
import argparse
import csv
import json
import time

from . import db, fill, page_fill, plan as plan_mod
from .fill import LOCATION_NAME, PLACE_ID
from .run_paths import new_run_dir, reserve_output
from .sources.fetch import fetch, looks_like_a_challenge
from .sources.station import StationFetcher, station_slug
from .sources.venue import StoreFetcher, VenueFetcher, official_store_urls

# Cache only: the pages are fetched so the evidence gate can read them, and no
# value is ever written from them. marksandspencer.com left this set on 11
# November 2026, once the facility-list rule could read its store pages.
CACHE_ONLY = set()

# Brand store fetchers. The routing source key of these rows is
# openstreetmap.org, because the identity match is their only source url, so
# the fetcher owns them by Brand instead, the way the station fetcher owns the
# station rows it finds on the grok stage. The key is the host whose pages it
# reads, and it never follows a url on another host.
BRAND_HOSTS = {
    "storelocator.asda.com": "Asda",
    "www.lidl.co.uk": "Lidl",
    # An M&S store page carries "Store information / Facilities / Car parking"
    # for that store. Its rows reach the fetcher by their own source key.
    "marksandspencer.com": "M&S",
}

# Measured on 11 November 2026 and not built. A probe of each host is in
# data/runs/2026-11-11_29/probe/. Registering one of these would move its rows
# off the grok stage to a fetcher that can answer nothing.
SKIPPED_HOSTS = {
    "stores.sainsburys.co.uk":
        "the store page answers 200 with 15 characters of text, because it "
        "renders in the browser. The only parking text the brand publishes is "
        "chain-wide: most car parks, two hours free, see the signs in store. "
        "Rules R7, R9 and R10 refuse that for one store.",
    "www.tesco.com":
        "every request answers 403 Access Denied with a bot challenge, "
        "including robots.txt. A challenge is recorded, never worked around.",
    "cityoflondon.gov.uk":
        "the pages read are area pages. One covers every car park in an "
        "8,000-acre forest, so a value from it is area-wide and not evidence "
        "for one site. Another states that the site has no car park.",
    "royalparks.org.uk":
        "the only parking text is a question heading and a sentence about "
        "other car parks. Neither states anything about the site.",
    "tkmaxx.com":
        "all three probed pages were blocked.",
    "primark.com":
        "all three probed pages were blocked.",
    "toolstation.com":
        "the pages read carry no parking statement at all.",
    "all.accor.com":
        "the pages read carry no parking statement at all.",
    "iceland.co.uk":
        "the pages read carry no parking statement at all.",
    "kfc.co.uk":
        "the pages read carry no parking statement at all.",
    "mcdonalds.com":
        "the pages read carry no parking statement at all.",
    "nandos.co.uk":
        "the pages read carry no parking statement at all.",
    "screwfix.com":
        "the pages read carry no parking statement at all.",
    "euro car parks":
        "these are public operator car parks. The venue reader writes Who Can "
        "Park Customers only, which is wrong for a public pay car park, so "
        "these rows need a reader of their own.",
    "ncp":
        "these are public operator car parks. See the euro car parks note.",
}

REGISTRY = {
    "station": StationFetcher(),
    "better.org.uk": VenueFetcher("better.org.uk"),
    "thegymgroup.com": VenueFetcher("thegymgroup.com"),
    "puregym.com": VenueFetcher("puregym.com"),
    "nuffieldhealth.com": VenueFetcher("nuffieldhealth.com"),
    **{host: StoreFetcher(brand, host) for host, brand in BRAND_HOSTS.items()},
}

EXAMPLE_HEADERS = ["key", "Place ID", "Location Name", "url", "http status", "outcome",
                   "quote", "columns"]
UNRESOLVED_HEADERS = ["key", "Place ID", "Location Name", "reason"]
BLOCKED_HEADERS = ["key", "Place ID", "Location Name", "url", "reason"]

# validate_rows asks for both whenever Can Park? is Yes or Conditional, and it
# sees only the plan's own columns, so the row's values travel as context.
CONTEXT_COLUMNS = ("Brand", "Place Category")
DASHES = ("\u2013", "\u2014")

# This pipeline's own bookkeeping. The page does not state any of it, so these
# columns carry no quote, no URL and no page metadata, and the evidence table
# then holds one row per field a page actually stated.
BOOKKEEPING_COLUMNS = frozenset({
    "Source Tier", "Specificity", "Evidence Type", "Evidence Level", "Evidence Age",
    "Rules Stated", "Prices Stated", "Conflict", "Decision Reason", "Review Flag",
    "Flag Status", "Verification Result", "Change Made (Yes/No)",
    fill.VERIFIED_BY, fill.VERIFIED_DATE, fill.SOURCE_URLS,
})

# A value that asserts nothing. The page did not state it, so it carries no
# quote either: "Cost Type: Unknown" means this reader did not find a price.
ABSTENTIONS = frozenset({"Unknown", "Not published", "Not applicable", "Not yet checked"})


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
        elif key in BRAND_HOSTS and stage == "grok" and (
                row.get("Brand") or "").strip() == BRAND_HOSTS[key]:
            out.append((row, stage))
    return out, run_id


def page_metadata(conn, url):
    """(retrieved_at, page_hash) for the cached page, or two blanks.

    The pages table is keyed by URL and a later fetch replaces the row, so the
    values are copied into each plan line while they still describe the page
    the quote came from."""
    row = conn.execute(
        "SELECT fetched_at, text_hash FROM pages WHERE url = ?", (url,)).fetchone()
    if row is None:
        return "", ""
    return row["fetched_at"] or "", row["text_hash"] or ""


def plan_lines(place_id, stage, values, notes, flags, row, quote, url, verified_by, today,
               retrieved_at="", page_hash=""):
    """(lines, blocked_reason). fill-shaped values turned into plan lines, with
    Notes and Review Flag appended rather than replaced, exactly as page_fill
    does it.

    The quote, the url and the page metadata go only to a column the fetcher
    itself read from the page. page_fill derives further columns, and those are
    this pipeline's own reasoning rather than anything the page stated."""
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
                        f"asks for on a Yes or Conditional row"), []
        for column in CONTEXT_COLUMNS:
            new.setdefault(column, row.get(column, ""))

    previous_urls = row.get(fill.SOURCE_URLS, "") or ""
    new[fill.SOURCE_URLS] = "; ".join(dict.fromkeys([url] + [part.strip() for part in previous_urls.split(";") if part.strip()]))

    # The sheet's own Notes sometimes holds an en dash, and appending to it
    # would fail the validator on text somebody else wrote. The parking fact
    # still lands in Evidence Detail, so the Notes line is simply left out.
    if "Notes" in new and any(dash in str(new["Notes"]) for dash in DASHES):
        del new["Notes"]

    lines, kept_back = [], []
    for column in sorted(new, key=lambda name: (name == fill.VERIFICATION_RESULT, name)):
        value = new[column]
        if value is None or str(value).strip() == "":
            continue
        # Routing sends a finished row back when it has a parking gap, so the
        # blank cell is filled and everything the row already answered stays.
        # The value becomes the row's own, which db-apply counts as no change.
        # Dropping the column instead would hide it from validate_rows, which
        # sees only the plan's own columns and then asks for it.
        if fill.finished_column_refusal(row, column, value):
            kept_back.append(column)
            value = row.get(column, "")
            if str(value).strip() == "":
                continue
        stated = (column in values and column not in BOOKKEEPING_COLUMNS
                  and str(value).strip() not in ABSTENTIONS)
        lines.append({"place_id": place_id, "column": column, "new_value": str(value),
                       "quote": quote if stated else "",
                       "source_url": url if stated else "",
                       "stage": stage, "verified_by": verified_by,
                       "retrieved_at": retrieved_at if stated else "",
                       "page_hash": page_hash if stated else ""})
    return lines, "", kept_back


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
    finished_rows = []
    counts = {"rows attempted": 0, "pages fetched": 0, "plan lines": 0,
              "silent pages": 0, "blocked pages": 0, "unresolved names": 0,
              "rows with values": 0, "rows held for a person": 0,
              "columns a finished row keeps": 0, "rows db-apply refused": 0,
              "network requests": 0, "cache hits": 0, "failed requests": 0,
              "seconds": 0.0, "pages per minute": 0.0}
    started = time.monotonic()

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

        status, text, from_cache = fetch(url, conn)
        counts["cache hits" if from_cache else "network requests"] += 1
        # Status 0 means the request itself failed, so nothing was served.
        if status == 0:
            counts["failed requests"] += 1
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
            retrieved_at, page_hash = page_metadata(conn, url)
            row_lines, held, kept_back = plan_lines(
                place_id, stage, values, notes, flags, row, quote, url,
                getattr(fetcher, "verified_by", "Code (page fetch)"), today,
                retrieved_at, page_hash)
            if kept_back:
                counts["columns a finished row keeps"] += len(kept_back)
                finished_rows.append({"key": key, "Place ID": place_id,
                                       "Location Name": row.get(LOCATION_NAME, ""),
                                       "url": url,
                                       "reason": "the row is finished, so it keeps "
                                                 + ", ".join(sorted(kept_back))})
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

    # A second reading by the applier itself. One refused line blocks a whole
    # plan, and a finished row can be refused for text somebody else wrote,
    # such as an en dash or a dropdown value the rules no longer list. Those
    # rows are reported for a person instead of blocking every other row.
    refused_by = {}
    for reject in plan_mod.check_plan(conn, lines)[1]:
        refused_by.setdefault(reject["Place ID"], []).append(
            f"{reject['column']}: {reject['reason']}")
    if refused_by:
        by_place = {place: row for row, _ in candidates
                    for place in [(row.get(PLACE_ID) or "").strip()]}
        for place_id, reasons in sorted(refused_by.items()):
            counts["rows db-apply refused"] += 1
            counts["rows with values"] -= 1
            blocked_rows.append({
                "key": key, "Place ID": place_id,
                "Location Name": (by_place.get(place_id) or {}).get(LOCATION_NAME, ""),
                "url": "", "reason": "; ".join(reasons[:3])})
        lines = [line for line in lines if line["place_id"] not in refused_by]
        counts["plan lines"] = len(lines)

    counts["seconds"] = round(time.monotonic() - started, 1)
    read = counts["network requests"] + counts["cache hits"]
    counts["pages per minute"] = round(read / counts["seconds"] * 60, 1) if counts["seconds"] else 0.0
    return lines, {"key": key, "routing_run": run_id, "counts": counts,
                   "examples": sorted(examples, key=lambda e: (e["outcome"] != "values", e["outcome"] == "not National Rail"))[:10], "unresolved": unresolved,
                   "held": blocked_rows, "finished": finished_rows, "osm_source": osm_source}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run one fetcher and emit a plan. Dry run.")
    parser.add_argument("--key", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    if args.key in SKIPPED_HOSTS:
        raise SystemExit(f"{args.key} is not built: {SKIPPED_HOSTS[args.key]}")
    if args.key == "station":
        from .sources.station_list import load
        REGISTRY["station"] = StationFetcher(load(conn))
    if args.key in BRAND_HOSTS:
        REGISTRY[args.key] = StoreFetcher(BRAND_HOSTS[args.key], args.key,
                                          official_store_urls(conn, args.key))
    lines, report = run(conn, args.key, args.limit)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("fetch_fill")
    plan_mod.write_plan(out_dir / "plan.jsonl", lines)
    for name, headers, rows in (("examples.csv", EXAMPLE_HEADERS, report["examples"]),
                                 ("unresolved.csv", UNRESOLVED_HEADERS, report["unresolved"]),
                                 ("held.csv", BLOCKED_HEADERS, report["held"]),
                                 ("finished.csv", BLOCKED_HEADERS, report["finished"])):
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
    print(f"Columns a finished row keeps: {out_dir / 'finished.csv'}")
    print(f"Plan: {out_dir / 'plan.jsonl'}")
    print("Dry run only. Check it with db-apply, which needs --apply to write.")
    return 0
