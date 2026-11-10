"""Create new authoritative records in the database, and undo a create run.

    python -m ferro_parking db-create --plan PLAN.jsonl [--apply]
    python -m ferro_parking db-create-undo --run RUN_ID [--apply]

A create plan is JSON lines, one record per line:

    {"source": "osm", "source_ref": "way/12345",
     "row": {"Location Name": "Hill Street Car Park", "Borough": "Sutton", ...}}

db-create is a dry run unless --apply is given. Creation establishes identity
only. A created record may fill the columns in CREATE_COLUMNS and nothing else,
so no create plan can state who can park, what it costs or how long a driver
may stay. Those answers come later, from research, through db-apply.

A source_ref this source already created is skipped, not refused, so a repeated
or interrupted run adds no second record. Any other refusal blocks the whole
plan. db-create-undo deactivates a run's records. It never deletes a row and
never frees a Place ID for reuse.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .run_paths import new_run_dir

PLACE_ID = db.PLACE_ID

# The only columns a created record may fill. Creation establishes identity.
# It does not establish parking permission, so every parking answer, every
# evidence field and all four owner payment columns stay blank and are refused
# here rather than being silently dropped.
CREATE_COLUMNS = {
    PLACE_ID, "Location Name", "Place Category", "Street Address", "Postcode",
    "Borough", "Latitude", "Longitude", "Geo Source", "Geo Precision",
    "Captured By", "Date Captured", "Source URLs (primary first)", "OSM ID",
    "Notes",
}

PLAN_HEADERS = ["Place ID", "source", "source ref", "Location Name", "Borough",
                "Place Category", "Latitude", "Longitude"]
REJECT_HEADERS = ["source", "source ref", "column", "value", "reason"]


def read_plan(path):
    records = []
    for number, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        text = text.strip()
        if not text:
            continue
        record = json.loads(text)
        for key in ("source", "source_ref", "row"):
            if key not in record:
                raise ValueError(f"line {number}: missing {key!r}")
        if not isinstance(record["row"], dict):
            raise ValueError(f"line {number}: 'row' must be an object")
        records.append(record)
    return records


def check_plan(conn, records):
    """(accepted, skipped, rejected). A non-empty rejected list blocks the
    whole plan. skipped lists records this source already created."""
    headers, _ = db.current_rows(conn)
    if not headers:
        raise ValueError("nothing imported yet: run db-import first")
    header_set = set(headers)
    accepted, skipped, rejected = [], [], []
    seen_refs = {}
    existing = {}
    for record in records:
        source = str(record["source"]).strip()
        ref = str(record["source_ref"]).strip()
        row = record["row"]

        def refuse(column, value, reason):
            rejected.append({"source": source, "source ref": ref, "column": column,
                             "value": value, "reason": reason})

        if not source or not ref:
            refuse("", "", "source and source_ref are both required")
            continue
        if source not in existing:
            existing[source] = db.created_source_refs(conn, source)
        if ref in existing[source]:
            skipped.append({"source": source, "source ref": ref,
                            "place_id": existing[source][ref],
                            "reason": "already created by an earlier run"})
            continue
        if (source, ref) in seen_refs:
            refuse("", "", f"{ref!r} appears twice in this plan")
            continue
        bad = False
        for column, value in row.items():
            if column not in header_set:
                refuse(column, value, f"unknown column {column!r}")
                bad = True
            elif column not in CREATE_COLUMNS:
                refuse(column, value,
                       f"{column!r} is not a creation column: creation establishes "
                       "identity, not parking permission")
                bad = True
        if not str(row.get("Location Name", "")).strip():
            refuse("Location Name", "", "a created record needs a Location Name")
            bad = True
        if str(row.get(PLACE_ID, "")).strip():
            refuse(PLACE_ID, row.get(PLACE_ID), "the database allocates the Place ID")
            bad = True
        for column in ("Latitude", "Longitude"):
            text = str(row.get(column, "")).strip()
            if not text:
                refuse(column, "", f"a created record needs a {column}")
                bad = True
                continue
            try:
                float(text)
            except ValueError:
                refuse(column, text, f"{column} is not a number")
                bad = True
        if bad:
            continue
        seen_refs[(source, ref)] = True
        accepted.append({"source": source, "source_ref": ref, "row": dict(row)})
    return accepted, skipped, rejected


def _allocate(conn, count):
    """count fresh Place IDs, read under the write lock the caller holds."""
    start = int(db.PLACE_ID_RE.match(db.next_place_id(conn)).group(1))
    return [f"PP-{start + offset:06d}" for offset in range(count)]


def apply_plan(conn, records, run_id, apply=False):
    accepted, skipped, rejected = check_plan(conn, records)
    report = {"run_id": run_id, "records": len(records), "accepted": len(accepted),
              "skipped": skipped, "rejected": rejected, "created": 0, "rows": []}
    if rejected or not apply:
        if not rejected:
            for record in accepted:
                report["rows"].append({"Place ID": "(allocated at apply)", **_row_summary(record)})
        return report

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn.execute("BEGIN IMMEDIATE")
        place_ids = _allocate(conn, len(accepted))
        for place_id, record in zip(place_ids, accepted):
            row = dict(record["row"])
            row[PLACE_ID] = place_id
            conn.execute(
                "INSERT INTO created (place_id, run_id, source, source_ref, json,"
                " created_at, active) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (place_id, run_id, record["source"], record["source_ref"],
                 json.dumps(row, ensure_ascii=False), now))
            report["created"] += 1
            report["rows"].append({"Place ID": place_id, **_row_summary(record)})
        db.rebuild(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return report


def _row_summary(record):
    row = record["row"]
    return {"source": record["source"], "source ref": record["source_ref"],
            "Location Name": row.get("Location Name", ""),
            "Borough": row.get("Borough", ""),
            "Place Category": row.get("Place Category", ""),
            "Latitude": row.get("Latitude", ""), "Longitude": row.get("Longitude", "")}


def undo_run(conn, run_id, apply=False):
    """Deactivate every record one create run made. Nothing is deleted and no
    Place ID is freed. A record another run has since changed is refused, so an
    undo never discards newer evidence."""
    records = [dict(row) for row in conn.execute(
        "SELECT place_id, source, source_ref, active FROM created WHERE run_id = ?"
        " ORDER BY rowid", (run_id,))]
    report = {"run_id": run_id, "records": len(records), "deactivated": 0,
              "already_inactive": 0, "refused": [], "rows": []}
    if not records:
        report["refused"].append({"place_id": "", "reason": f"no create run {run_id!r}"})
        return report
    changed = {row["place_id"] for row in conn.execute(
        "SELECT DISTINCT place_id FROM changes WHERE place_id IN ("
        + ", ".join("?" * len(records)) + ")", [r["place_id"] for r in records])}
    todo = []
    for record in records:
        if not record["active"]:
            report["already_inactive"] += 1
            continue
        if record["place_id"] in changed:
            report["refused"].append({
                "place_id": record["place_id"],
                "reason": "a later run changed this record: undo would discard newer evidence"})
            continue
        todo.append(record)
        report["rows"].append({"Place ID": record["place_id"], "source": record["source"],
                               "source ref": record["source_ref"]})
    if report["refused"] or not apply:
        return report
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    undo_id = f"undo-{run_id}"
    try:
        conn.execute("BEGIN IMMEDIATE")
        for record in todo:
            conn.execute(
                "UPDATE created SET active = 0, deactivated_run_id = ?, deactivated_at = ?"
                " WHERE place_id = ?", (undo_id, now, record["place_id"]))
            report["deactivated"] += 1
        db.rebuild(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return report


def _write_csv(path, rows, fieldnames):
    with open(path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _run_id(prefix):
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="db-create")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    records = read_plan(args.plan)
    conn = db.connect(args.db)
    run_id = _run_id("create")
    report = apply_plan(conn, records, run_id, apply=args.apply)
    out_dir = Path(args.out) if args.out else new_run_dir("db_create")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "plan.csv", report["rows"], PLAN_HEADERS)
    if report["rejected"]:
        _write_csv(out_dir / "rejected.csv", report["rejected"], REJECT_HEADERS)
    if report["skipped"]:
        _write_csv(out_dir / "skipped.csv", report["skipped"],
                   ["source", "source ref", "place_id", "reason"])
    (out_dir / "report.json").write_text(json.dumps(
        {k: v for k, v in report.items() if k != "rows"}, indent=2), encoding="utf-8")
    mode = "applied" if args.apply and not report["rejected"] else "dry run"
    print(f"{mode}: run {run_id}, {report['records']} records in the plan, "
          f"{report['accepted']} accepted, {len(report['skipped'])} already created, "
          f"{len(report['rejected'])} refused, {report['created']} created")
    print(f"Report: {out_dir}")
    if report["rejected"]:
        for line in report["rejected"][:10]:
            print(f"  refused {line['source ref']}: {line['reason']}")
        return 1
    return 0


def undo_main(argv=None):
    parser = argparse.ArgumentParser(prog="db-create-undo")
    parser.add_argument("--run", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    report = undo_run(conn, args.run, apply=args.apply)
    mode = "applied" if args.apply and not report["refused"] else "dry run"
    print(f"{mode}: run {args.run}, {report['records']} records, "
          f"{report['deactivated']} deactivated, "
          f"{report['already_inactive']} already inactive, "
          f"{len(report['refused'])} refused")
    for line in report["refused"][:10]:
        print(f"  refused {line['place_id']}: {line['reason']}")
    return 1 if report["refused"] else 0
