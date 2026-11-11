"""Mark one place a duplicate of another. Nothing is deleted.

    python -m ferro_parking db-duplicate --duplicate PP-X --keep PP-Y [--apply]
    python -m ferro_parking db-duplicate --duplicate PP-X --clear [--apply]

The same car park reaches the sheet twice when two capture rounds name it
differently. Both rows then claim to be a real place, both route for research,
and both would publish. This command records which row stands and which one
repeats it.

It never deletes a row and never frees a Place ID. It writes `duplicate_of` on
the repeating row, which `route.classify` already reads to give that row the
stage `skip_duplicate`, and it logs the change in the `changes` table so the
record of who decided what is in one place. `--clear` reverses it.

The row that stands is the one to keep deciding, not the newest one. A row
carrying published charges, a verified evidence level or the payment columns
holds work that the thinner row does not, so read both rows before choosing.
This command does not choose for you.

Refusals, each of which blocks the whole command:

- either Place ID is unknown to the database
- the two Place IDs are the same
- the row that stands is itself marked a duplicate, which would leave a chain
- the repeating row was verified by a named person, whose work is never
  overruled here
- the repeating row is an active created record, which `db-create-undo`
  retires instead, because its authoritative row lives in `created`
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db, fill
from .run_paths import new_run_dir, reserve_output

COLUMN = "Duplicate Of"


def _row(rows, place_id):
    return next((row for row in rows
                 if str(row.get(db.PLACE_ID) or "").strip() == place_id), None)


def check(conn, duplicate, keep, clear=False):
    """(plan, refusals). plan is empty when anything is refused."""
    duplicate = str(duplicate or "").strip()
    keep = str(keep or "").strip()
    _, rows = db.current_rows(conn)
    marks = db.duplicate_of_map(conn)
    refusals = []

    def refuse(reason):
        refusals.append({"place_id": duplicate, "reason": reason})

    repeating = _row(rows, duplicate)
    if not duplicate:
        refuse("--duplicate is required")
    elif repeating is None:
        refuse(f"{duplicate} is unknown to the database")
    if not clear:
        if not keep:
            refuse("--keep is required unless --clear is given")
        elif _row(rows, keep) is None:
            refuse(f"{keep} is unknown to the database")
        elif keep == duplicate:
            refuse("a place cannot be a duplicate of itself")
        elif marks.get(keep):
            refuse(f"{keep} is itself marked a duplicate of {marks[keep]}: "
                   "marking this row would leave a chain")
    if repeating is not None:
        verified_by = str(repeating.get("Verified By") or "").strip()
        if fill.is_named_person(verified_by):
            refuse(f"{duplicate} was verified by {verified_by!r}, a named "
                   "person: report the issue instead")
        created = conn.execute(
            "SELECT active FROM created WHERE place_id = ?", (duplicate,)).fetchone()
        if created is not None and created["active"]:
            refuse(f"{duplicate} is an active created record: db-create-undo "
                   "retires it, which keeps its authoritative row in created")
    if refusals:
        return [], refusals

    old = marks.get(duplicate, "")
    new = "" if clear else keep
    if old == new:
        return [], [{"place_id": duplicate,
                     "reason": f"{COLUMN} is already {new or '(blank)'!r}: "
                               "nothing to change"}]
    return [{"place_id": duplicate, "column_name": COLUMN, "old_value": old,
             "new_value": new, "stands": keep,
             "duplicate name": str(repeating.get("Location Name") or ""),
             "stands name": str((_row(rows, keep) or {}).get("Location Name") or "")}], []


def apply_plan(conn, plan, run_id, apply=False):
    report = {"run_id": run_id, "changes": len(plan), "applied": 0, "rows": plan}
    if not plan or not apply:
        return report
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for line in plan:
            conn.execute("UPDATE places SET duplicate_of = ? WHERE place_id = ?",
                         (line["new_value"], line["place_id"]))
            conn.execute(
                "INSERT INTO changes (run_id, place_id, column_name, old_value,"
                " new_value, stage, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, line["place_id"], COLUMN, line["old_value"],
                 line["new_value"], "duplicate", now))
            report["applied"] += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="db-duplicate",
        description="Record that one place repeats another. Nothing is deleted "
                    "and no Place ID is freed. Dry run unless --apply.")
    parser.add_argument("--duplicate", required=True,
                        help="the Place ID of the row that repeats another")
    parser.add_argument("--keep", default=None,
                        help="the Place ID of the row that stands")
    parser.add_argument("--clear", action="store_true",
                        help="clear the mark on --duplicate instead of setting it")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    plan, refusals = check(conn, args.duplicate, args.keep, clear=args.clear)
    run_id = f"duplicate-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    report = apply_plan(conn, plan, run_id, apply=args.apply)
    report["refusals"] = refusals

    out_dir = reserve_output(args.out) if args.out else new_run_dir("db_duplicate")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if plan:
        undo = [{"duplicate": line["place_id"], "restore": line["old_value"]}
                for line in plan]
        (out_dir / "undo.json").write_text(json.dumps(undo, indent=2), encoding="utf-8")

    for line in refusals:
        print(f"refused: {line['place_id']} {line['reason']}")
    for line in plan:
        print(f"{line['place_id']} ({line['duplicate name']}) repeats "
              f"{line['new_value'] or '(cleared)'} ({line['stands name']})")
    mode = "applied" if args.apply and plan else "dry run"
    print(f"{mode}: run {run_id}, {len(plan)} changes, {report['applied']} applied, "
          f"{len(refusals)} refused")
    print(f"Report: {out_dir}")
    return 1 if refusals else 0
