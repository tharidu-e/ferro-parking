#!/usr/bin/env python3
"""Write a round's answers into the sheet, one cell at a time, with a log.

One file, standard library plus the Google client the bot already uses. It
replaces the old chain of grok-import, db-apply and publish.

    python3 sheet_write.py --round hospital1 --results results.csv \
        --queue queue.csv --log hospital1-writes.csv [--apply]

Without --apply it plans and writes nothing. Every run prints the same counts.

What it guarantees, so that no rule in a prompt has to:

* It reads the live cell immediately before writing and writes only when that
  cell is blank, "Unknown" or "Not yet checked". An answer is never replaced.
* It refuses an identity or payment column outright.
* It refuses a Place ID that is not in the round's queue.
* It stops the whole round when the plan is larger than --max-cells.
* It appends one line per write to the log: round, Place ID, column, old
  value, new value, time, URL and quote. sheet_undo.py reads that file.

    python3 sheet_write.py --demo      runs the file's own checks
"""
import argparse
import csv
import datetime
import sys

TAB = "ALL LONDON (clean)"
PLACE_ID = "Place ID"

# A bot never writes identity or money. The sheet's protected ranges hold this
# too; this is the second layer, so a misconfigured range cannot be the only
# guard.
NEVER_WRITE = {
    "Place ID", "Location Name", "Street Address", "Postcode", "Postcode Area",
    "Borough", "Latitude", "Longitude", "Geo Source", "Geo Precision",
    "Geo (as captured)", "Postcode (derived from pin)",
    "Pin to postcode distance (m)", "Ferro Autopay", "Parking Charge (£)",
    "Total incl. Ferro Fee (£)", "Verified By", "Verified Date",
    "Type (as captured)", "Charges (as published)", "Max Stay (as captured)",
    "Hours (as captured)",
}

PLACEHOLDERS = {"", "Unknown", "Not yet checked"}
LOG_HEADERS = ["round", "Place ID", "column", "old value", "new value", "time",
               "url", "quote"]


def writable(live_value):
    """True when the live cell may receive a value."""
    return str(live_value or "").strip() in PLACEHOLDERS


def plan_row(place_id, new_values, live_row, queue):
    """(writes, refusals) for one row, against the live sheet row."""
    writes, refusals = [], []
    if place_id not in queue:
        return [], [f"{place_id}: not in this round's queue"]
    for column, value in new_values.items():
        value = str(value or "").strip()
        if not value:
            continue
        if column in NEVER_WRITE:
            refusals.append(f"{place_id}: {column} is never written by a bot")
            continue
        live = live_row.get(column, "")
        if str(live).strip() == value:
            continue
        if not writable(live):
            refusals.append(f"{place_id}: {column} already reads {str(live).strip()!r}")
            continue
        writes.append({"Place ID": place_id, "column": column,
                       "old value": str(live).strip(), "new value": value})
    return writes, refusals


def build_plan(results, live, queue, max_cells):
    writes, refusals = [], []
    for row in results:
        place_id = str(row.get(PLACE_ID, "")).strip()
        live_row = live.get(place_id)
        if live_row is None:
            refusals.append(f"{place_id}: no such row in the sheet")
            continue
        row_writes, row_refusals = plan_row(place_id, row, live_row, queue)
        writes.extend(row_writes)
        refusals.extend(row_refusals)
    if len(writes) > max_cells:
        raise SystemExit(f"Stopping: the plan writes {len(writes)} cells, over the "
                         f"limit of {max_cells}. Raise --max-cells only on purpose.")
    return writes, refusals


def append_log(path, round_name, writes, url_by_place, quote_by_place):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    new_file = True
    try:
        with open(path, encoding="utf-8") as stream:
            new_file = not stream.read(1)
    except FileNotFoundError:
        pass
    with open(path, "a", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=LOG_HEADERS)
        if new_file:
            writer.writeheader()
        for write in writes:
            writer.writerow({**write, "round": round_name, "time": now,
                             "url": url_by_place.get(write["Place ID"], ""),
                             "quote": quote_by_place.get(write["Place ID"], "")})


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def live_rows(service):
    """{Place ID: row} from the live tab, with the sheet row number kept."""
    from googleapiclient.discovery import build  # noqa: F401  (import check only)
    values = service.spreadsheets().values().get(
        spreadsheetId=service.spreadsheet_id, range=TAB).execute().get("values", [])
    headers, rows = values[0], values[1:]
    out = {}
    for index, row in enumerate(rows, start=2):
        row = row + [""] * (len(headers) - len(row))
        record = dict(zip(headers, row))
        record["_sheet_row"] = index
        out[record[PLACE_ID].strip()] = record
    return headers, out


def demo():
    """The file's own checks. Run with --demo."""
    live = {"PP-1": {"Place ID": "PP-1", "Who Can Park": "", "Cost Type": "Unknown",
                     "Hours (OpenStreetMap opening_hours format)": "24/7",
                     "Location Name": "Example"}}
    queue = {"PP-1"}
    result = {"Place ID": "PP-1", "Who Can Park": "Anyone (paid)", "Cost Type": "Paid",
              "Hours (OpenStreetMap opening_hours format)": "Mo-Fr 08:00-18:00",
              "Location Name": "Renamed", "Rules Summary": ""}
    writes, refusals = plan_row("PP-1", result, live["PP-1"], queue)
    columns = {w["column"] for w in writes}
    assert columns == {"Who Can Park", "Cost Type"}, columns
    assert any("Location Name is never written" in r for r in refusals)
    assert any("already reads '24/7'" in r for r in refusals)
    assert plan_row("PP-2", result, live["PP-1"], queue)[1] == [
        "PP-2: not in this round's queue"]
    assert writable("") and writable("Unknown") and writable("Not yet checked")
    assert not writable("Paid")
    # A rerun writes nothing, because the live cell now holds the value.
    after = {**live["PP-1"], "Who Can Park": "Anyone (paid)", "Cost Type": "Paid"}
    assert plan_row("PP-1", result, after, queue)[0] == []
    try:
        build_plan([result], live, queue, max_cells=1)
    except SystemExit as stop:
        assert "over the limit" in str(stop)
    else:
        raise AssertionError("the volume limit did not stop the plan")
    print("self-check passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--round")
    parser.add_argument("--results")
    parser.add_argument("--queue")
    parser.add_argument("--log")
    parser.add_argument("--max-cells", type=int, default=3000)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        demo()
        return 0
    for name in ("round", "results", "queue", "log"):
        if not getattr(args, name):
            parser.error(f"--{name} is required")

    results = read_csv(args.results)
    queue = {str(r.get("Ref") or r.get(PLACE_ID, "")).strip() for r in read_csv(args.queue)}
    import sheets_client  # the bot's own thin wrapper around the Sheets API
    service = sheets_client.get_service()
    _, live = live_rows(service)
    writes, refusals = build_plan(results, live, queue, args.max_cells)

    for refusal in refusals:
        print(refusal)
    print(f"{len(writes)} cells to write across "
          f"{len({w['Place ID'] for w in writes})} rows, {len(refusals)} refusals.")
    if not args.apply:
        print("Planned only. Add --apply to write.")
        return 0

    url_by_place = {str(r.get(PLACE_ID, "")).strip(): r.get("Source URLs (primary first)",
                                                            r.get("Source URLs", ""))
                    for r in results}
    quote_by_place = {str(r.get(PLACE_ID, "")).strip():
                      r.get("Evidence Detail (what the source shows)",
                            r.get("Evidence Detail", "")) for r in results}
    sheets_client.write_cells(service, TAB, live, writes)
    append_log(args.log, args.round, writes, url_by_place, quote_by_place)
    print(f"Wrote {len(writes)} cells. Log: {args.log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
