#!/usr/bin/env python3
"""Undo one round's writes, cell by cell, from its own log.

    python3 sheet_undo.py --log hospital1-writes.csv --round hospital1 [--apply]

Without --apply it plans and restores nothing.

It restores a cell only when that cell still holds the value the round wrote.
A cell somebody changed afterwards is left alone and reported, so undoing a
bad round never wipes good work done since. This is why the round log exists:
the sheet's version history can only restore the whole sheet to a moment.

    python3 sheet_undo.py --demo       runs the file's own checks
"""
import argparse
import csv
import sys

TAB = "ALL LONDON (clean)"


def plan_undo(log_rows, live, round_name):
    """(restores, skipped) for one round, newest write per cell first."""
    newest = {}
    for row in log_rows:
        if row.get("round") != round_name:
            continue
        newest[(row["Place ID"], row["column"])] = row
    restores, skipped = [], []
    for (place_id, column), row in sorted(newest.items()):
        live_row = live.get(place_id)
        if live_row is None:
            skipped.append(f"{place_id}: no such row in the sheet")
            continue
        current = str(live_row.get(column, "")).strip()
        if current != str(row["new value"]).strip():
            skipped.append(f"{place_id}: {column} now reads {current!r}, "
                           f"not what this round wrote. Left alone")
            continue
        restores.append({"Place ID": place_id, "column": column,
                         "old value": row["old value"], "new value": current})
    return restores, skipped


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def demo():
    """The file's own checks. Run with --demo."""
    log = [{"round": "r1", "Place ID": "PP-1", "column": "Cost Type",
            "old value": "", "new value": "Paid"},
           {"round": "r1", "Place ID": "PP-2", "column": "Cost Type",
            "old value": "", "new value": "Paid"},
           {"round": "r2", "Place ID": "PP-3", "column": "Cost Type",
            "old value": "", "new value": "Free"}]
    live = {"PP-1": {"Cost Type": "Paid"},
            "PP-2": {"Cost Type": "Free"},
            "PP-3": {"Cost Type": "Free"}}
    restores, skipped = plan_undo(log, live, "r1")
    assert [r["Place ID"] for r in restores] == ["PP-1"], restores
    assert restores[0]["old value"] == ""
    assert any("PP-2" in s and "Left alone" in s for s in skipped)
    assert plan_undo(log, live, "r3") == ([], [])
    print("self-check passed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--log")
    parser.add_argument("--round")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.demo:
        demo()
        return 0
    if not args.log or not args.round:
        parser.error("--log and --round are required")

    import sheets_client
    from sheet_write import live_rows
    service = sheets_client.get_service()
    _, live = live_rows(service)
    restores, skipped = plan_undo(read_csv(args.log), live, args.round)
    for line in skipped:
        print(line)
    print(f"{len(restores)} cells to restore, {len(skipped)} left alone.")
    if not args.apply:
        print("Planned only. Add --apply to restore.")
        return 0
    sheets_client.write_cells(service, TAB, live,
                              [{**r, "new value": r["old value"]} for r in restores])
    print(f"Restored {len(restores)} cells.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
