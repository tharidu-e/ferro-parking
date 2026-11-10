"""Phase 5: probe a source key before anybody builds a fetcher for it.

    python -m ferro_parking probe --key nationalrail.co.uk --limit 3
    python -m ferro_parking probe --all-keys

Takes a few routed rows for one source key, finds each branch page, fetches it
once per second per domain, and reports the HTTP status, whether the page
states parking for that branch, and the exact quotes. The page text is cached
in the pages table and saved as a test fixture, so a fetcher built later is
tested without the network.

This command reads pages. It writes no plan and no row.
"""
import argparse
import csv
import re
from pathlib import Path

from . import db
from .fill import LOCATION_NAME, PLACE_ID
from .run_paths import new_run_dir, reserve_output
from .sources.fetch import SourceUrlFetcher, fetch, looks_like_a_challenge

FIXTURE_DIR = Path("tests/fixtures/pages")

# The keys the Phase 2 counts put at the top of the grok, station and default
# stages, in the order the brief lists them.
BRIEF_KEYS = ["nationalrail.co.uk", "better.org.uk", "puregym.com", "thegymgroup.com",
              "marksandspencer.com", "screwfix.com", "iceland.co.uk", "mcdonalds.com",
              "kfc.co.uk", "nandos.co.uk", "euro car parks", "ncp"]

TABLE_HEADERS = ["key", "routed rows", "pages fetched OK", "pages blocked",
                 "pages that state parking", "example quote"]
DETAIL_HEADERS = ["key", "Place ID", "Location Name", "url", "http status",
                  "states parking", "quote", "fixture"]


def routed_rows_for_key(conn, key, limit=3):
    """A few routed rows whose derived source key is this one."""
    from . import route

    run_id, routing = db.latest_routing(conn)
    if run_id is None:
        raise SystemExit("No routing run in the database. Run route first.")
    skipped = {stage for stage in set(routing.values()) if stage.startswith("skip")}
    _, rows = db.current_rows(conn)
    out = []
    for row in rows:
        place_id = (row.get(PLACE_ID) or "").strip()
        stage = routing.get(place_id)
        if stage is None or stage in skipped:
            continue
        if route.source_key(row) != key:
            continue
        out.append(row)
    return out


def fixture_name(key, place_id):
    safe = re.sub(r"[^a-z0-9.]+", "_", key.lower()).strip("_")
    return f"{safe}/{place_id}.txt"


def save_fixture(key, place_id, text, fixture_dir=FIXTURE_DIR, limit=20000):
    """The page text as a committed fixture, so a later fetcher is tested on
    it without the network. Trimmed, because a fixture is for reading."""
    path = Path(fixture_dir) / fixture_name(key, place_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text[:limit], encoding="utf-8")
    return path


def probe_key(conn, key, limit=3, fixture_dir=FIXTURE_DIR, fetcher=None):
    """(summary, details) for one key. Fetches at most `limit` pages."""
    fetcher = fetcher or SourceUrlFetcher(key)
    candidates = routed_rows_for_key(conn, key, limit)
    details = []
    for row in candidates:
        if len([d for d in details if d["url"]]) >= limit:
            break
        place_id = (row.get(PLACE_ID) or "").strip()
        url = fetcher.branch_url(row)
        if not url:
            details.append({"key": key, "Place ID": place_id,
                             "Location Name": row.get(LOCATION_NAME, ""), "url": "",
                             "http status": "", "states parking": "no page to read",
                             "quote": "", "fixture": ""})
            continue
        status, text, _ = fetch(url, conn)
        blocked = status in (0, 401, 403, 429) or (status == 200 and looks_like_a_challenge(text))
        quotes = [] if blocked else fetcher.quotes(text, row)
        fixture = save_fixture(key, place_id, text, fixture_dir) if text else ""
        details.append({
            "key": key, "Place ID": place_id, "Location Name": row.get(LOCATION_NAME, ""),
            "url": url, "http status": status,
            "states parking": "blocked" if blocked else ("yes" if quotes else "no"),
            "quote": quotes[0][:300] if quotes else "",
            "fixture": str(fixture),
        })
    tried = [d for d in details if d["url"]]
    summary = {
        "key": key,
        "routed rows": len(candidates),
        "pages fetched OK": sum(1 for d in tried if d["states parking"] in ("yes", "no")),
        "pages blocked": sum(1 for d in tried if d["states parking"] == "blocked"),
        "pages that state parking": sum(1 for d in tried if d["states parking"] == "yes"),
        "example quote": next((d["quote"] for d in tried if d["quote"]), ""),
    }
    return summary, details


def print_table(summaries):
    widths = [max(len(str(row[header])) for row in [dict(zip(TABLE_HEADERS, TABLE_HEADERS))] + summaries)
              for header in TABLE_HEADERS]
    widths[-1] = min(widths[-1], 60)

    def line(values):
        cells = []
        for value, width in zip(values, widths):
            text = str(value)
            if len(text) > width:
                text = text[:width - 3] + "..."
            cells.append(text.ljust(width))
        print("  ".join(cells).rstrip())

    line(TABLE_HEADERS)
    line(["-" * width for width in widths])
    for row in summaries:
        line([row[header] for header in TABLE_HEADERS])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", action="append", default=[])
    parser.add_argument("--all-keys", action="store_true",
                        help="Probe every key the Phase 5 brief lists.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--fixture-dir", default=str(FIXTURE_DIR))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    keys = BRIEF_KEYS if args.all_keys else args.key
    if not keys:
        raise SystemExit("Give at least one --key, or --all-keys.")

    conn = db.connect(args.db)
    summaries, details = [], []
    for key in keys:
        summary, key_details = probe_key(conn, key, args.limit, Path(args.fixture_dir))
        summaries.append(summary)
        details.extend(key_details)
        print(f"probed {key}: {summary['pages fetched OK']} read, "
              f"{summary['pages blocked']} blocked, "
              f"{summary['pages that state parking']} state parking")

    out_dir = reserve_output(args.out) if args.out else new_run_dir("probe")
    for name, headers, rows in (("summary.csv", TABLE_HEADERS, summaries),
                                 ("pages.csv", DETAIL_HEADERS, details)):
        with open(out_dir / name, "x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

    print()
    print_table(summaries)
    print(f"\nPer page detail: {out_dir / 'pages.csv'}")
    print(f"Fixtures saved under {args.fixture_dir}/")
    print("No fetcher is built yet. Choose the keys worth one.")
    return 0
