"""Local SQLite store for the parking sheet: lossless import, derived tables, export.

    python -m ferro_parking db-import --sheet-csv data/raw/all_london_clean.csv
    python -m ferro_parking db-export --out data/runs/<date>/db/export.csv
    python -m ferro_parking db-rebuild

Every import keeps each sheet row exactly as read, in the raw table, as one
JSON object per Place ID per import. Nothing is ever lost. The typed tables
places and parking are derived from raw plus the applied rows of the changes
log, and nothing edits them directly. db-rebuild recomputes them.

A cell the database never changed always reads back the sheet's own value, so
re-importing a fresh export is safe. Where the database does own a change, the
newest applied change wins, and a sheet value that matches neither that
change's old nor new value is reported as a conflict for Phase 7's drift check.

No row is ever deleted. A Place ID that disappears from a later export keeps
its earlier raw rows and its derived row, and the import report names it.
"""
import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .run_paths import new_run_dir, reserve_output

DB_PATH = Path("data/db/ferro_parking.sqlite")
PLACE_ID = "Place ID"
PLACE_ID_RE = re.compile(r"^PP-(\d+)$")

# The four columns another owner writes. Imported as a read-only mirror,
# never proposed, never published. See hard rule 2 of the db-router brief.
SHEET_OWNED_COLUMNS = {
    "free_stay_countdown_mins": "Free Stay Countdown (mins)",
    "ferro_autopay": "Ferro Autopay",
    "parking_charge_gbp": "Parking Charge (£)",
    "total_incl_ferro_fee_gbp": "Total incl. Ferro Fee (£)",
}

PLACES_COLUMNS = {
    "place_id": PLACE_ID,
    "name": "Location Name",
    "brand": "Brand",
    "category": "Place Category",
    "type_as_captured": "Type (as captured)",
    "area_type": "Area Type",
    "street_address": "Street Address",
    "postcode": "Postcode",
    "postcode_area": "Postcode Area",
    "borough": "Borough",
    "latitude": "Latitude",
    "longitude": "Longitude",
    "geo_source": "Geo Source",
    "geo_precision": "Geo Precision",
    "osm_id": "OSM ID",
    "location_status": "Location Status",
}

PARKING_COLUMNS = {
    "place_id": PLACE_ID,
    "can_park": "Can Park? (Yes/No/Conditional)",
    "who_can_park": "Who Can Park",
    "cost_type": "Cost Type",
    "price_status": "Price Status",
    "tariff_type": "Tariff Type",
    "tariff_detail": "Tariff Detail",
    "max_stay_mins": "Max Stay (mins)",
    "hours": "Hours (OpenStreetMap opening_hours format)",
    "hours_basis": "Hours Basis",
    "control_type": "Parking Control Type (Cameras / Barrier / Patrol)",
    "operator": "Operator",
    "pcn_amount": "PCN (Penalty Charge Notice) amount (£)",
    "verification_result": "Verification Result",
    "evidence_level": "Evidence Level",
    "evidence_type": "Evidence Type",
    "specificity": "Specificity",
    "source_urls": "Source URLs (primary first)",
    "rules_summary": "Rules Summary",
    "decision_reason": "Decision Reason",
    "verified_by": "Verified By",
    "verified_date": "Verified Date",
}

# "column" is a reserved word in SQLite, so the changes and published tables
# spell it column_name. Plan files and CSV reports still say "column".
SCHEMA = """
CREATE TABLE IF NOT EXISTS imports (
    import_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    header_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS raw (
    import_id INTEGER NOT NULL REFERENCES imports(import_id),
    place_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (import_id, place_id)
);
CREATE INDEX IF NOT EXISTS raw_place_id ON raw(place_id);
CREATE TABLE IF NOT EXISTS places (
    place_id TEXT PRIMARY KEY, name TEXT, brand TEXT, category TEXT,
    type_as_captured TEXT, area_type TEXT, street_address TEXT, postcode TEXT,
    postcode_area TEXT, borough TEXT, latitude TEXT, longitude TEXT,
    geo_source TEXT, geo_precision TEXT, osm_id TEXT, location_status TEXT,
    duplicate_of TEXT
);
CREATE TABLE IF NOT EXISTS parking (
    place_id TEXT PRIMARY KEY, can_park TEXT, who_can_park TEXT, cost_type TEXT,
    price_status TEXT, tariff_type TEXT, tariff_detail TEXT, max_stay_mins TEXT,
    hours TEXT, hours_basis TEXT, control_type TEXT, operator TEXT,
    pcn_amount TEXT, verification_result TEXT, evidence_level TEXT,
    evidence_type TEXT, specificity TEXT, source_urls TEXT, rules_summary TEXT,
    decision_reason TEXT, verified_by TEXT, verified_date TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, place_id TEXT NOT NULL, field TEXT, value TEXT, quote TEXT,
    source_url TEXT, source_tier TEXT, stage TEXT, recorded_at TEXT,
    retrieved_at TEXT, page_hash TEXT
);
CREATE INDEX IF NOT EXISTS evidence_place_id ON evidence(place_id);
CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY, fetched_at TEXT, http_status INTEGER,
    text_hash TEXT, text_path TEXT
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL, place_id TEXT NOT NULL, column_name TEXT NOT NULL,
    old_value TEXT, new_value TEXT, stage TEXT, applied_at TEXT
);
CREATE INDEX IF NOT EXISTS changes_cell ON changes(place_id, column_name);
CREATE TABLE IF NOT EXISTS routing (
    run_id TEXT NOT NULL, place_id TEXT NOT NULL, stage TEXT NOT NULL,
    reason TEXT, PRIMARY KEY (run_id, place_id)
);
CREATE TABLE IF NOT EXISTS sheet_owned (
    place_id TEXT PRIMARY KEY, free_stay_countdown_mins TEXT,
    ferro_autopay TEXT, parking_charge_gbp TEXT, total_incl_ferro_fee_gbp TEXT
);
CREATE TABLE IF NOT EXISTS published (
    place_id TEXT NOT NULL, column_name TEXT NOT NULL, value TEXT,
    published_at TEXT, PRIMARY KEY (place_id, column_name)
);
CREATE TABLE IF NOT EXISTS created (
    place_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    deactivated_run_id TEXT,
    deactivated_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS created_source_ref ON created(source, source_ref);
"""


# Columns added after the first databases existed. CREATE TABLE IF NOT EXISTS
# leaves an older table alone, so each one is added in place instead.
ADDED_COLUMNS = (("evidence", "retrieved_at", "TEXT"), ("evidence", "page_hash", "TEXT"))


def connect(path=DB_PATH):
    """Open the database, creating the file and the schema if needed."""
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, column, kind in ADDED_COLUMNS:
        held = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in held:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.commit()
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- import

def read_sheet_csv(csv_path):
    """(headers, rows) from a sheet export. Raises on an unusable file."""
    with open(csv_path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        headers = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    if PLACE_ID not in headers:
        raise ValueError(f"{csv_path}: no {PLACE_ID!r} column")
    seen, blank = set(), 0
    for row in rows:
        place_id = (row.get(PLACE_ID) or "").strip()
        if not place_id:
            blank += 1
            continue
        if place_id in seen:
            raise ValueError(f"{csv_path}: duplicate {PLACE_ID} {place_id!r}")
        seen.add(place_id)
    if blank:
        raise ValueError(f"{csv_path}: {blank} rows have a blank {PLACE_ID}")
    # A short row read by DictReader leaves None, which is not the sheet's
    # own empty string. Normalise once, here, so raw never stores a null.
    for row in rows:
        for header in headers:
            if row.get(header) is None:
                row[header] = ""
    return headers, rows


def latest_import_id(conn):
    row = conn.execute("SELECT MAX(import_id) AS id FROM imports").fetchone()
    return row["id"]


def raw_rows(conn, import_id):
    """{place_id: (row_index, row_dict)} for one import."""
    cursor = conn.execute(
        "SELECT place_id, row_index, json FROM raw WHERE import_id = ?", (import_id,))
    return {r["place_id"]: (r["row_index"], json.loads(r["json"])) for r in cursor}


def import_sheet_csv(conn, csv_path):
    """Load one sheet export. Returns the import_id and a difference report."""
    headers, rows = read_sheet_csv(csv_path)
    previous_id = latest_import_id(conn)
    previous = raw_rows(conn, previous_id) if previous_id else {}
    now = _now()
    cursor = conn.execute(
        "INSERT INTO imports (source_path, imported_at, row_count, header_json)"
        " VALUES (?, ?, ?, ?)",
        (str(csv_path), now, len(rows), json.dumps(headers)))
    import_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO raw (import_id, place_id, row_index, json, imported_at)"
        " VALUES (?, ?, ?, ?, ?)",
        [(import_id, row[PLACE_ID].strip(), index, json.dumps(row, sort_keys=True), now)
         for index, row in enumerate(rows)])
    conn.executemany(
        "INSERT OR REPLACE INTO sheet_owned (place_id, " + ", ".join(SHEET_OWNED_COLUMNS) + ")"
        " VALUES (?, ?, ?, ?, ?)",
        [tuple([row[PLACE_ID].strip()] + [row.get(header, "") for header in SHEET_OWNED_COLUMNS.values()])
         for row in rows])
    report = _import_report(conn, previous, rows, headers, previous_id, import_id)
    rebuild(conn, import_id)
    conn.commit()
    return import_id, report


def _import_report(conn, previous, rows, headers, previous_id, import_id):
    owned = owned_changes(conn)
    current = {row[PLACE_ID].strip(): row for row in rows}
    changed_cells, conflicts = [], []
    for place_id, row in current.items():
        if place_id not in previous:
            continue
        before = previous[place_id][1]
        for header in headers:
            was, now_value = before.get(header, ""), row.get(header, "")
            if was != now_value:
                changed_cells.append({"Place ID": place_id, "column": header,
                                       "previous import": was, "this import": now_value})
    for (place_id, header), change in owned.items():
        if place_id not in current:
            continue
        sheet_value = current[place_id].get(header, "")
        if sheet_value not in (change["old_value"], change["new_value"]):
            conflicts.append({"Place ID": place_id, "column": header,
                               "database value": change["new_value"],
                               "sheet value": sheet_value,
                               "reason": "sheet matches neither the old nor the new database value"})
    return {
        "previous_import_id": previous_id,
        "import_id": import_id,
        "rows": len(rows),
        "headers": len(headers),
        "new_place_ids": sorted(set(current) - set(previous)),
        "missing_place_ids": sorted(set(previous) - set(current)),
        "changed_cells": changed_cells,
        "conflicts": conflicts,
    }


# ---------------------------------------------------------------- effective values

def owned_changes(conn):
    """{(place_id, column): change row} for the newest applied change per cell."""
    cursor = conn.execute(
        "SELECT place_id, column_name, old_value, new_value, MAX(id) AS id FROM changes"
        " WHERE applied_at IS NOT NULL GROUP BY place_id, column_name")
    return {(r["place_id"], r["column_name"]): dict(r) for r in cursor}


def created_rows(conn, headers):
    """Active records the database created itself, oldest first, overlaid with
    the newest applied change per cell. These have no import: a record created
    from OpenStreetMap exists only here, so every reader that unions them in
    keeps working after the next sheet import."""
    owned = owned_changes(conn)
    out = []
    for record in conn.execute(
            "SELECT place_id, json FROM created WHERE active = 1 ORDER BY rowid"):
        row = json.loads(record["json"])
        row = {header: row.get(header, "") for header in headers}
        for header in headers:
            change = owned.get((record["place_id"], header))
            if change is not None:
                row[header] = change["new_value"]
        out.append(row)
    return out


def created_source_refs(conn, source):
    """{source_ref: place_id} for one source, active and inactive. A second
    create run reads this and proposes nothing it already created, so a
    repeated or interrupted run adds no duplicate."""
    return {row["source_ref"]: row["place_id"] for row in conn.execute(
        "SELECT source_ref, place_id FROM created WHERE source = ?", (source,))}


def effective_rows(conn, import_id=None):
    """(headers, rows) as the database now reads: the newest raw row per Place
    ID, in its imported order, overlaid with the newest applied change per
    cell. A cell the database never changed keeps the sheet's own value."""
    import_id = import_id or latest_import_id(conn)
    if not import_id:
        return [], []
    headers = json.loads(conn.execute(
        "SELECT header_json FROM imports WHERE import_id = ?", (import_id,)).fetchone()["header_json"])
    rows = []
    for index, row in sorted(raw_rows(conn, import_id).values(), key=lambda pair: pair[0]):
        rows.append((index, row))
    owned = owned_changes(conn)
    out = []
    for _, row in rows:
        row = dict(row)
        for header in headers:
            change = owned.get((row[PLACE_ID].strip(), header))
            if change is not None:
                row[header] = change["new_value"]
        out.append(row)
    return headers, out + created_rows(conn, headers)


def missing_place_ids(conn):
    """Place IDs an earlier import had and the newest import does not. The
    rows stay in the database, so the router can skip them by name."""
    import_id = latest_import_id(conn)
    if not import_id:
        return set()
    current = {row["place_id"] for row in conn.execute(
        "SELECT place_id FROM raw WHERE import_id = ?", (import_id,))}
    everything = {row["place_id"] for row in conn.execute("SELECT DISTINCT place_id FROM raw")}
    return everything - current


def current_rows(conn):
    """(headers, rows) for every Place ID the database has ever imported, each
    at its newest raw row, overlaid with the newest applied change per cell.

    effective_rows covers one import, which is what db-export needs to stay
    byte-identical. This covers the whole store, including a Place ID the
    newest export dropped, which the router has to see so it can skip it."""
    import_id = latest_import_id(conn)
    if not import_id:
        return [], []
    headers = json.loads(conn.execute(
        "SELECT header_json FROM imports WHERE import_id = ?", (import_id,)).fetchone()["header_json"])
    cursor = conn.execute(
        "SELECT r.place_id, r.import_id, r.row_index, r.json FROM raw r"
        " JOIN (SELECT place_id, MAX(import_id) AS newest FROM raw GROUP BY place_id) newest"
        "   ON newest.place_id = r.place_id AND newest.newest = r.import_id")
    newest = [(r["import_id"], r["row_index"], r["place_id"], json.loads(r["json"])) for r in cursor]
    newest.sort(key=lambda item: (-item[0], item[1]))
    owned = owned_changes(conn)
    out = []
    for _, _, place_id, row in newest:
        row = dict(row)
        for header in headers:
            change = owned.get((place_id, header))
            if change is not None:
                row[header] = change["new_value"]
        out.append(row)
    return headers, out + created_rows(conn, headers)


def latest_routing(conn):
    """(run_id, {place_id: stage}) for the newest route run, or (None, {})."""
    row = conn.execute(
        "SELECT run_id FROM routing ORDER BY rowid DESC LIMIT 1").fetchone()
    if row is None:
        return None, {}
    run_id = row["run_id"]
    return run_id, {r["place_id"]: r["stage"] for r in conn.execute(
        "SELECT place_id, stage FROM routing WHERE run_id = ?", (run_id,))}


def duplicate_of_map(conn):
    """{place_id: duplicate_of} for every row the database marked a duplicate."""
    return {row["place_id"]: row["duplicate_of"] for row in conn.execute(
        "SELECT place_id, duplicate_of FROM places WHERE duplicate_of IS NOT NULL"
        " AND duplicate_of != ''")}


def next_place_id(conn):
    """The next unused Place ID, from every import ever loaded and every record
    the database created. A deactivated created record still holds its ID, so
    an undo never frees an ID for reuse."""
    highest = 0
    for sql in ("SELECT DISTINCT place_id FROM raw",
                "SELECT DISTINCT place_id FROM created"):
        for row in conn.execute(sql):
            match = PLACE_ID_RE.match(row["place_id"])
            if match:
                highest = max(highest, int(match.group(1)))
    return f"PP-{highest + 1:06d}"


# ---------------------------------------------------------------- derived tables

def _derived_values(mapping, row):
    return [row.get(header, "") for header in mapping.values()]


def rebuild(conn, import_id=None):
    """Recompute places and parking from raw plus the applied changes. Never
    deletes a row: a Place ID missing from the newest import keeps its last
    derived values, and the import report names it."""
    headers, rows = effective_rows(conn, import_id)
    if not rows:
        return {"places": 0, "parking": 0}
    conn.executemany(
        "INSERT INTO places (" + ", ".join(PLACES_COLUMNS) + ") VALUES ("
        + ", ".join("?" * len(PLACES_COLUMNS)) + ") ON CONFLICT(place_id) DO UPDATE SET "
        + ", ".join(f"{name} = excluded.{name}" for name in PLACES_COLUMNS if name != "place_id"),
        [_derived_values(PLACES_COLUMNS, row) for row in rows])
    conn.executemany(
        "INSERT INTO parking (" + ", ".join(PARKING_COLUMNS) + ") VALUES ("
        + ", ".join("?" * len(PARKING_COLUMNS)) + ") ON CONFLICT(place_id) DO UPDATE SET "
        + ", ".join(f"{name} = excluded.{name}" for name in PARKING_COLUMNS if name != "place_id"),
        [_derived_values(PARKING_COLUMNS, row) for row in rows])
    # A deactivated created record must leave the derived tables, or a count of
    # places keeps reporting it. Its authoritative row in created stays, so
    # nothing is lost and its Place ID is never freed. Imported rows are never
    # removed here: a Place ID a newer import dropped keeps its last values.
    conn.execute("DELETE FROM places WHERE place_id IN"
                 " (SELECT place_id FROM created WHERE active = 0)")
    conn.execute("DELETE FROM parking WHERE place_id IN"
                 " (SELECT place_id FROM created WHERE active = 0)")
    conn.commit()
    return {"places": len(rows), "parking": len(rows)}


# ---------------------------------------------------------------- export

def export_csv(conn, out_path):
    """Write the sheet's own 60 columns, in the sheet's header order and row
    order, so every full-export reader keeps working on the result."""
    headers, rows = effective_rows(conn)
    if not headers:
        raise ValueError("nothing imported yet: run db-import first")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})
    return len(rows)


# ---------------------------------------------------------------- commands

def _write_csv(path, rows, fieldnames):
    with open(path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def import_main(argv=None):
    parser = argparse.ArgumentParser(description="Load a sheet export into the database.")
    parser.add_argument("--sheet-csv", required=True)
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--out", help="Report directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = connect(args.db)
    import_id, report = import_sheet_csv(conn, args.sheet_csv)
    out_dir = reserve_output(args.out) if args.out else new_run_dir("db_import")
    _write_csv(out_dir / "changed_cells.csv", report["changed_cells"],
               ["Place ID", "column", "previous import", "this import"])
    _write_csv(out_dir / "conflicts.csv", report["conflicts"],
               ["Place ID", "column", "database value", "sheet value", "reason"])
    _write_csv(out_dir / "place_id_changes.csv",
               [{"Place ID": pid, "state": "new in this import"} for pid in report["new_place_ids"]]
               + [{"Place ID": pid, "state": "missing from this import"} for pid in report["missing_place_ids"]],
               ["Place ID", "state"])

    print(f"Import {import_id}: {report['rows']} rows, {report['headers']} columns, "
          f"from {args.sheet_csv}")
    if report["previous_import_id"] is None:
        print("First import. Nothing to compare against.")
    else:
        print(f"Compared with import {report['previous_import_id']}: "
              f"{len(report['new_place_ids'])} new Place IDs, "
              f"{len(report['missing_place_ids'])} missing, "
              f"{len(report['changed_cells'])} changed cells, "
              f"{len(report['conflicts'])} conflicts")
    print(f"Next free Place ID: {next_place_id(conn)}")
    print(f"Reports in {out_dir}/")
    return 1 if report["conflicts"] else 0


def export_main(argv=None):
    parser = argparse.ArgumentParser(description="Write the database back out as a sheet CSV.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args(argv)
    conn = connect(args.db)
    count = export_csv(conn, args.out)
    print(f"Wrote {count} rows to {args.out}")
    return 0


def rebuild_main(argv=None):
    parser = argparse.ArgumentParser(description="Recompute the derived places and parking tables.")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args(argv)
    conn = connect(args.db)
    counts = rebuild(conn)
    print(f"Rebuilt {counts['places']} places rows and {counts['parking']} parking rows")
    return 0
