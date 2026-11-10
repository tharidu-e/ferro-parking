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
import collections
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .osm_match import norm
from .run_paths import new_run_dir

PLACE_ID = db.PLACE_ID

# A pin this close to a place the database already holds is a possible
# duplicate, not proof. Different businesses, levels and adjacent car parks sit
# within metres of each other, so the record is held for a person instead of
# being created or discarded.
DUPLICATE_RADIUS_M = 30.0
METRES_PER_DEGREE_LAT = 111_320.0
# One grid cell is about 110 m across, so a 30 m search reads the nine cells
# around a point and never scans every existing place.
GRID_DEGREES = 0.001

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
SKIP_HEADERS = ["source", "source ref", "place_id", "reason"]
HELD_HEADERS = ["source", "source ref", "Location Name", "near place_id",
                "near name", "metres", "reason"]


def _metres(lat_a, lon_a, lat_b, lon_b):
    """Flat-earth distance, which is accurate enough over tens of metres."""
    scale_lon = METRES_PER_DEGREE_LAT * math.cos(math.radians((lat_a + lat_b) / 2))
    return math.hypot((lon_a - lon_b) * scale_lon,
                      (lat_a - lat_b) * METRES_PER_DEGREE_LAT)


class ExistingPlaces:
    """The places the database already holds, indexed for a duplicate test.

    Built once per plan. A record is a duplicate of one of these when it names
    the same OpenStreetMap feature, and a possible duplicate when its pin lands
    within DUPLICATE_RADIUS_M of one."""

    def __init__(self, rows, exclude=()):
        exclude = set(exclude)
        self.by_osm_id = {}
        self.grid = collections.defaultdict(list)
        for row in rows:
            place_id = (row.get(PLACE_ID) or "").strip()
            if not place_id or place_id in exclude:
                continue
            osm_id = (row.get("OSM ID") or "").strip()
            if osm_id:
                self.by_osm_id.setdefault(osm_id, place_id)
            try:
                lat = float(str(row.get("Latitude", "")).strip())
                lon = float(str(row.get("Longitude", "")).strip())
            except ValueError:
                continue
            self.grid[(round(lat, 3), round(lon, 3))].append(
                (place_id, row.get("Location Name", ""), lat, lon))

    def add(self, place_id, name, osm_id, lat, lon):
        """Index a record this plan just accepted, so a second candidate on the
        same spot is held instead of becoming a twin of the first."""
        if osm_id:
            self.by_osm_id.setdefault(osm_id.strip(), place_id)
        self.grid[(round(lat, 3), round(lon, 3))].append((place_id, name, lat, lon))

    def same_osm_feature(self, osm_id):
        return self.by_osm_id.get((osm_id or "").strip()) if osm_id else None

    def nearest(self, lat, lon):
        """(place_id, name, metres) for the closest place, or None."""
        best, best_metres = None, None
        key_lat, key_lon = round(lat, 3), round(lon, 3)
        for step_lat in (-GRID_DEGREES, 0.0, GRID_DEGREES):
            for step_lon in (-GRID_DEGREES, 0.0, GRID_DEGREES):
                cell = (round(key_lat + step_lat, 3), round(key_lon + step_lon, 3))
                for place_id, name, other_lat, other_lon in self.grid.get(cell, ()):
                    metres = _metres(lat, lon, other_lat, other_lon)
                    if best_metres is None or metres < best_metres:
                        best, best_metres = (place_id, name), metres
        if best is None:
            return None
        return best[0], best[1], best_metres


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
    """(accepted, skipped, held, rejected). A non-empty rejected list blocks the
    whole plan. skipped lists records the database already holds, by this
    source's own reference or by the OpenStreetMap reference on an existing
    place. held lists records whose pin lands within DUPLICATE_RADIUS_M of a
    place the database already holds, which is a possible duplicate and needs a
    person. Neither skipped nor held blocks the plan, and neither is created."""
    headers, rows = db.current_rows(conn)
    if not headers:
        raise ValueError("nothing imported yet: run db-import first")
    header_set = set(headers)
    inactive = {row["place_id"] for row in conn.execute(
        "SELECT place_id FROM created WHERE active = 0")}
    places = ExistingPlaces(rows, exclude=inactive)
    accepted, skipped, held, rejected = [], [], [], []
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
        twin = places.same_osm_feature(row.get("OSM ID"))
        if twin:
            skipped.append({"source": source, "source ref": ref, "place_id": twin,
                            "reason": f"place {twin} already names this "
                                      "OpenStreetMap feature"})
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
        near = places.nearest(float(str(row["Latitude"]).strip()),
                              float(str(row["Longitude"]).strip()))
        if near and near[2] <= DUPLICATE_RADIUS_M:
            held.append({"source": source, "source ref": ref,
                         "Location Name": row.get("Location Name", ""),
                         "near place_id": near[0], "near name": near[1],
                         "metres": round(near[2]),
                         "reason": f"within {round(near[2])} m of place {near[0]}: "
                                   "a possible duplicate, not proof"})
            continue
        seen_refs[(source, ref)] = True
        places.add("(this plan)", row.get("Location Name", ""),
                   row.get("OSM ID", ""),
                   float(str(row["Latitude"]).strip()),
                   float(str(row["Longitude"]).strip()))
        accepted.append({"source": source, "source_ref": ref, "row": dict(row)})
    return accepted, skipped, held, rejected


def _allocate(conn, count):
    """count fresh Place IDs, read under the write lock the caller holds."""
    start = int(db.PLACE_ID_RE.match(db.next_place_id(conn)).group(1))
    return [f"PP-{start + offset:06d}" for offset in range(count)]


def apply_plan(conn, records, run_id, apply=False):
    accepted, skipped, held, rejected = check_plan(conn, records)
    report = {"run_id": run_id, "records": len(records), "accepted": len(accepted),
              "skipped": skipped, "held": held, "rejected": rejected,
              "created": 0, "rows": []}
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


def reactivate_run(conn, run_id, apply=False):
    """Bring back the records one create run made, after an undo and a fix.

    The guards run again, so a record that now duplicates a place the database
    holds stays deactivated. Each record keeps the Place ID it already has, so
    nothing is allocated twice and the audit trail stays in one row."""
    records = [dict(row) for row in conn.execute(
        "SELECT place_id, source, source_ref, json, active FROM created"
        " WHERE run_id = ? ORDER BY rowid", (run_id,))]
    report = {"run_id": run_id, "records": len(records), "reactivated": 0,
              "already_active": 0, "skipped": [], "held": [], "rows": []}
    if not records:
        report["skipped"].append({"source": "", "source ref": "", "place_id": "",
                                  "reason": f"no create run {run_id!r}"})
        return report
    headers, rows = db.current_rows(conn)
    mine = {record["place_id"] for record in records}
    places = ExistingPlaces(rows, exclude=mine)
    todo = []
    for record in records:
        if record["active"]:
            report["already_active"] += 1
            continue
        row = json.loads(record["json"])
        osm_id = (row.get("OSM ID") or "").strip()
        twin = places.same_osm_feature(osm_id)
        if twin:
            report["skipped"].append({
                "source": record["source"], "source ref": record["source_ref"],
                "place_id": twin,
                "reason": f"place {twin} already names this OpenStreetMap feature"})
            continue
        try:
            lat = float(str(row.get("Latitude", "")).strip())
            lon = float(str(row.get("Longitude", "")).strip())
        except ValueError:
            report["skipped"].append({
                "source": record["source"], "source ref": record["source_ref"],
                "place_id": record["place_id"], "reason": "no usable coordinate"})
            continue
        near = places.nearest(lat, lon)
        if near and near[2] <= DUPLICATE_RADIUS_M:
            report["held"].append({
                "source": record["source"], "source ref": record["source_ref"],
                "Location Name": row.get("Location Name", ""),
                "near place_id": near[0], "near name": near[1],
                "metres": round(near[2]),
                "reason": f"within {round(near[2])} m of place {near[0]}: "
                          "a possible duplicate, not proof"})
            continue
        places.add(record["place_id"], row.get("Location Name", ""), osm_id, lat, lon)
        todo.append(record)
        report["rows"].append({"Place ID": record["place_id"],
                               "source": record["source"],
                               "source ref": record["source_ref"],
                               "Location Name": row.get("Location Name", ""),
                               "Borough": row.get("Borough", ""),
                               "Place Category": row.get("Place Category", ""),
                               "Latitude": row.get("Latitude", ""),
                               "Longitude": row.get("Longitude", "")})
    if not apply:
        return report
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        conn.execute("BEGIN IMMEDIATE")
        for record in todo:
            conn.execute(
                "UPDATE created SET active = 1, deactivated_run_id = NULL,"
                " deactivated_at = NULL, created_at = ? WHERE place_id = ?",
                (now, record["place_id"]))
            report["reactivated"] += 1
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
        _write_csv(out_dir / "skipped.csv", report["skipped"], SKIP_HEADERS)
    if report["held"]:
        _write_csv(out_dir / "held.csv", report["held"], HELD_HEADERS)
    (out_dir / "report.json").write_text(json.dumps(
        {k: v for k, v in report.items() if k != "rows"}, indent=2), encoding="utf-8")
    mode = "applied" if args.apply and not report["rejected"] else "dry run"
    print(f"{mode}: run {run_id}, {report['records']} records in the plan, "
          f"{report['accepted']} accepted, {len(report['skipped'])} already held, "
          f"{len(report['held'])} held as possible duplicates, "
          f"{len(report['rejected'])} refused, {report['created']} created")
    print(f"Report: {out_dir}")
    if report["rejected"]:
        for line in report["rejected"][:10]:
            print(f"  refused {line['source ref']}: {line['reason']}")
        return 1
    return 0


def redo_main(argv=None):
    parser = argparse.ArgumentParser(prog="db-create-redo")
    parser.add_argument("--run", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", default=None)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    report = reactivate_run(conn, args.run, apply=args.apply)
    out_dir = Path(args.out) if args.out else new_run_dir("db_create_redo")
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "plan.csv", report["rows"], PLAN_HEADERS)
    if report["skipped"]:
        _write_csv(out_dir / "skipped.csv", report["skipped"], SKIP_HEADERS)
    if report["held"]:
        _write_csv(out_dir / "held.csv", report["held"], HELD_HEADERS)
    (out_dir / "report.json").write_text(json.dumps(
        {k: v for k, v in report.items() if k != "rows"}, indent=2), encoding="utf-8")
    mode = "applied" if args.apply else "dry run"
    print(f"{mode}: run {args.run}, {report['records']} records, "
          f"{len(report['rows'])} eligible, {report['reactivated']} reactivated, "
          f"{report['already_active']} already active, "
          f"{len(report['skipped'])} skipped, "
          f"{len(report['held'])} held as possible duplicates")
    print(f"Report: {out_dir}")
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
