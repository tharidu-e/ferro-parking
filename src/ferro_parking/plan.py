"""Phase 3: plan files, applied to the database with a change log and an undo.

    python -m ferro_parking db-apply --plan PLAN.jsonl [--apply]
    python -m ferro_parking db-undo --run RUN_ID [--apply]
    python -m ferro_parking grok-import --results-csv RESULTS.csv

A plan file is JSON lines, one change per line:

    {"place_id": "PP-000001", "column": "Who Can Park",
     "new_value": "Customers only", "quote": "...", "source_url": "https://...",
     "stage": "default", "verified_by": "Policy script"}

db-apply is a dry run unless --apply is given. Any refusal blocks the whole
plan, and every refused line is listed in rejected.csv with its reason. The
refusals are:

- an unknown Place ID, or an unknown column
- a column another owner writes (hard rule 2), any other protected column,
  or a column outside fill.RESEARCH_COLUMNS
- a row whose Verified By names a person or a verifier the automation list does
  not declare (fill.lock_refusal)
- a finished row's own Verification Result, and any answer a finished row
  already holds (fill.finished_column_refusal). A blank cell on a finished row
  is still fillable, because routing sends a finished row back when it has a
  parking gap
- a row the latest routing run put on a different stage than the plan's own
- replacing a value that is already there, unless the plan's own Source Tier
  is strong and its Specificity is Site-specific. A placeholder is not an
  answer: "", "Unknown" and "Not yet checked" never count as a value, and
  "Not published" counts only once Verification Result is filled
- anything validation.validate_rows refuses on the plan entry

Nothing is deleted, ever. An applied change is a new row in the changes table,
and db-undo appends the reverse rows under a new run id rather than removing
anything.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db, fill, page_fill, validation
from .run_paths import new_run_dir, reserve_output

PLACE_ID = fill.PLACE_ID
VERIFICATION_RESULT = fill.VERIFICATION_RESULT

# Hard rule 2 of the db-router brief: another owner writes these four. They are
# imported as a read-only mirror and are never proposed or published.
OWNER_COLUMNS = set(db.SHEET_OWNED_COLUMNS.values())

LINE_FIELDS = ("place_id", "column", "new_value", "quote", "source_url", "stage", "verified_by")
# Page metadata pins the page version a quote came from, so a later fetch of
# the same URL cannot silently restate what the evidence claims. Only a page
# fetch can supply it, so a line carries these two fields only when it has
# them, and a planner that reads no page writes neither.
PAGE_FIELDS = ("retrieved_at", "page_hash")
REJECT_HEADERS = ["Place ID", "column", "new value", "reason"]
PLAN_HEADERS = ["Place ID", "column", "current value", "new value", "stage", "verified by"]


# ---------------------------------------------------------------- plan files

def read_plan(path):
    """Plan lines from a JSON lines file. Blank lines are skipped."""
    lines = []
    for number, text in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        text = text.strip()
        if not text:
            continue
        try:
            line = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path} line {number}: not JSON: {exc}") from exc
        if not isinstance(line, dict):
            raise ValueError(f"{path} line {number}: each line must be a JSON object")
        missing = {"place_id", "column", "new_value"} - set(line)
        if missing:
            raise ValueError(f"{path} line {number}: missing {sorted(missing)}")
        entry = {field: line.get(field, "") for field in LINE_FIELDS}
        entry.update({field: line[field] for field in PAGE_FIELDS if line.get(field)})
        lines.append(entry)
    return lines


def write_plan(path, lines):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        for line in lines:
            entry = {field: line.get(field, "") for field in LINE_FIELDS}
            entry.update({field: line[field] for field in PAGE_FIELDS if line.get(field)})
            stream.write(json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n")
    return len(lines)


# ---------------------------------------------------------------- checks

def _entry_value(lines_by_column, row, column):
    """The value a column will hold after this plan: the plan's own, else the
    row's current value."""
    if column in lines_by_column:
        return lines_by_column[column]["new_value"]
    return row.get(column, "")


def _plan_value(lines_by_column, column):
    """Only the plan's own value for a column, blank when the plan is silent."""
    line = lines_by_column.get(column)
    return line["new_value"] if line else ""


def column_refusal(column, headers):
    """Why this column may never be written, or None."""
    if column not in headers:
        return f"unknown column {column!r}"
    if column in OWNER_COLUMNS:
        return f"{column!r} belongs to another owner and is never written"
    try:
        fill.assert_not_protected({column})
    except AssertionError:
        return f"{column!r} is a protected column"
    if column not in fill.RESEARCH_COLUMNS:
        return f"{column!r} is outside the research allowlist"
    return None


# A placeholder is not an answer, so writing over it replaces nothing.
ALWAYS_PLACEHOLDER = {"", "Unknown", "Not yet checked"}
# "Not published" is a placeholder only while the row is unfinished. Once
# Verification Result is filled, somebody decided that nothing is published,
# and that is an answer.
UNFINISHED_PLACEHOLDER = {"Not published"}


def is_placeholder(value, row):
    value = (value or "").strip()
    if value in ALWAYS_PLACEHOLDER:
        return True
    if value in UNFINISHED_PLACEHOLDER:
        return not (row.get(VERIFICATION_RESULT) or "").strip()
    return False


def replacement_refusal(lines_by_column, row, column):
    """Why this line may not overwrite a value that is already there, or None.

    The evidence has to come from the plan itself. The row's existing Source
    Tier and Specificity belong to the value being replaced, so they cannot
    vouch for the new one."""
    current = (row.get(column, "") or "").strip()
    if is_placeholder(current, row):
        return None
    if str(lines_by_column[column]["new_value"]).strip() == current:
        return None  # the same value again changes nothing, so it replaces nothing
    tier = _plan_value(lines_by_column, "Source Tier")
    specificity = _plan_value(lines_by_column, "Specificity")
    if tier in page_fill.STRONG_SOURCE_TIERS and specificity == "Site-specific":
        return None
    return (f"replaces {current!r} without strong site-specific evidence "
            f"(Source Tier {tier!r}, Specificity {specificity!r})")


def check_plan(conn, lines):
    """(entries, rejected). entries are fill-shaped plan entries, one per Place
    ID, ready for validation.validate_rows. rejected lists every refused line
    with its reason. A non-empty rejected list blocks the whole plan."""
    headers, rows = db.current_rows(conn)
    by_place_id = {(row.get(PLACE_ID) or "").strip(): row for row in rows}
    header_set = set(headers)
    routing_run, routing = db.latest_routing(conn)

    rejected, grouped = [], {}
    for line in lines:
        place_id = (line["place_id"] or "").strip()
        column = line["column"]

        def refuse(reason):
            rejected.append({"Place ID": place_id, "column": column,
                              "new value": line["new_value"], "reason": reason})

        row = by_place_id.get(place_id)
        if row is None:
            refuse(f"unknown Place ID {place_id!r}")
            continue
        if routing_run is None:
            refuse("no routing run in the database: run route first")
            continue
        stage = routing.get(place_id)
        if stage != line["stage"]:
            refuse(f"routing run {routing_run} put this row on stage {stage!r}, "
                   f"not the plan's {line['stage']!r}")
            continue
        reason = column_refusal(column, header_set)
        if reason:
            refuse(reason)
            continue
        locked = fill.lock_refusal(row)
        if locked:
            refuse(locked)
            continue
        if column in grouped.get(place_id, {}):
            refuse(f"the plan sets {column!r} twice for this Place ID")
            continue
        grouped.setdefault(place_id, {})[column] = line

    for place_id, lines_by_column in grouped.items():
        row = by_place_id[place_id]
        for column, line in lines_by_column.items():
            for reason in (fill.finished_column_refusal(row, column, line["new_value"]),
                           replacement_refusal(lines_by_column, row, column)):
                if reason:
                    rejected.append({"Place ID": place_id, "column": column,
                                      "new value": line["new_value"], "reason": reason})

    entries = []
    for place_id, lines_by_column in grouped.items():
        row = by_place_id[place_id]
        entries.append({
            "place_id": place_id,
            "name": row.get(fill.LOCATION_NAME, ""),
            "postcode": row.get(fill.POSTCODE, ""),
            "new": {column: line["new_value"] for column, line in lines_by_column.items()},
            "_lines": lines_by_column,
            "_row": row,
            "old": {column: row.get(column, "") for column in lines_by_column},
        })

    for entry in entries:
        for failure in validation.validate_rows([{k: v for k, v in entry.items()
                                                   if not k.startswith("_")}], plan=True):
            if validation.is_warning(failure):
                continue
            rejected.append({"Place ID": entry["place_id"], "column": failure["field"],
                              "new value": failure["value"],
                              "reason": f"{failure['rule']}: {failure['message']}"})
    return entries, rejected


# ---------------------------------------------------------------- apply

def _unchanged(row, column, line):
    """A plan line that restates the value already there. It is context for the
    validator, which only sees the plan's own columns, and not a change: the
    change log never records a row whose old value equals its new one."""
    return str(line["new_value"]).strip() == (row.get(column, "") or "").strip()


def _ordered_columns(new):
    """Verification Result last, so a row is never finished before its other
    values are in place."""
    return sorted(new, key=lambda column: (column == VERIFICATION_RESULT, column))


def apply_plan(conn, lines, run_id, apply=False):
    """Check the plan and, with apply=True, write it to the database. Returns a
    report. A single refusal blocks every line."""
    entries, rejected = check_plan(conn, lines)
    report = {
        "run_id": run_id,
        "lines": len(lines),
        "places": len(entries),
        "rejected": rejected,
        "applied": 0,
        "unchanged": 0,
        "dry_run_rows": [],
        "evidence": 0,
    }
    for entry in entries:
        row = entry["_row"]
        for column in _ordered_columns(entry["new"]):
            line = entry["_lines"][column]
            if _unchanged(row, column, line):
                report["unchanged"] += 1
                continue
            report["dry_run_rows"].append({
                "Place ID": entry["place_id"], "column": column,
                "current value": row.get(column, ""), "new value": line["new_value"],
                "stage": line["stage"], "verified by": line["verified_by"]})
    if rejected or not apply:
        return report

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for entry in entries:
        row = entry["_row"]
        for column in _ordered_columns(entry["new"]):
            line = entry["_lines"][column]
            if _unchanged(row, column, line):
                continue
            conn.execute(
                "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
                " stage, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (run_id, entry["place_id"], column, row.get(column, ""),
                 line["new_value"], line["stage"], now))
            report["applied"] += 1
            if line["quote"] or line["source_url"]:
                conn.execute(
                    "INSERT INTO evidence (run_id, place_id, field, value, quote, source_url,"
                    " source_tier, stage, recorded_at, retrieved_at, page_hash)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (run_id, entry["place_id"], column, line["new_value"], line["quote"],
                     line["source_url"], _entry_value(entry["_lines"], row, "Source Tier"),
                     line["stage"], now, line.get("retrieved_at", ""),
                     line.get("page_hash", "")))
                report["evidence"] += 1
    conn.commit()
    db.rebuild(conn)
    return report


# ---------------------------------------------------------------- undo

def undo_run(conn, run_id, apply=False):
    """Append the reverse of every applied change in one run, under the run id
    "undo-<run_id>". Nothing is deleted. Returns a report.

    One locked or drifted value blocks the whole undo, the same way one refused
    line blocks a whole apply."""
    undo_id = f"undo-{run_id}"
    rows = [dict(row) for row in conn.execute(
        "SELECT place_id, column_name, old_value, new_value FROM changes"
        " WHERE run_id = ? AND applied_at IS NOT NULL ORDER BY id", (run_id,))]
    already = conn.execute(
        "SELECT COUNT(*) AS n FROM changes WHERE run_id = ?", (undo_id,)).fetchone()["n"]
    # An undo is a mutation, so the locks apply to it as well. A row a person
    # checked since the run keeps what it holds now, and so does a cell
    # somebody else changed after the run wrote it.
    _, current = db.current_rows(conn)
    by_place_id = {(row.get(PLACE_ID) or "").strip(): row for row in current}
    refused = []
    for row in rows:
        row_now = by_place_id.get(row["place_id"])
        reason = fill.lock_refusal(row_now)
        if reason is None and row_now is None:
            reason = f"Place ID {row['place_id']!r} is no longer in the database"
        held = "" if row_now is None else str(row_now.get(row["column_name"], "") or "").strip()
        if reason is None and held != str(row["new_value"] or "").strip():
            reason = (f"the run wrote {row['new_value']!r} but the cell now holds "
                      f"{held!r}, so a later change would be lost")
        if reason:
            refused.append({"Place ID": row["place_id"], "column": row["column_name"],
                            "new value": row["old_value"], "reason": reason})
    report = {"run_id": run_id, "undo_run_id": undo_id, "changes": len(rows),
              "already_undone": bool(already), "restored": 0, "rejected": refused,
              "dry_run_rows": [{"Place ID": row["place_id"], "column": row["column_name"],
                                 "current value": row["new_value"],
                                 "new value": row["old_value"]} for row in rows]}
    if not rows or already or refused or not apply:
        return report
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Reverse order, so a column the run set more than once ends on its
    # oldest value. Verification Result goes back first, before the values
    # it vouches for are taken away.
    ordered = sorted(rows, key=lambda row: row["column_name"] != VERIFICATION_RESULT)
    for row in reversed(ordered):
        conn.execute(
            "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
            " stage, applied_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (undo_id, row["place_id"], row["column_name"], row["new_value"],
             row["old_value"], "undo", now))
        report["restored"] += 1
    conn.commit()
    db.rebuild(conn)
    return report


# ---------------------------------------------------------------- grok results

def grok_results_to_plan(conn, results_csv, stage="grok", today=None):
    """Turn an export of the bot's results tab into plan lines, by handing the
    database rows and the results rows to the existing grok_import.build_plan.
    Returns (lines, result) where result is that function's own report."""
    from . import grok_import

    headers, rows = db.current_rows(conn)
    with open(results_csv, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        result_headers = list(reader.fieldnames or [])
        results = [dict(row) for row in reader]
    result = grok_import.build_plan(headers, rows, result_headers, results, today=today)

    # build_plan writes the bot's whole answer, which includes Location Status
    # (a protected column) and sometimes a blank Notes or Review Flag. Those
    # can never be applied, and leaving them in would block the whole plan, so
    # they are dropped here and listed instead.
    header_set = set(headers)
    lines, dropped = [], []
    for entry in result["plan"]:
        new = entry["new"]
        for column in _ordered_columns(new):
            value = new[column]
            reason = column_refusal(column, header_set)
            if reason is None and (value is None or str(value).strip() == ""):
                reason = "the bot gave no value for this column"
            if reason:
                dropped.append({"Place ID": entry["place_id"], "column": column,
                                 "new value": value, "reason": reason})
                continue
            lines.append({
                "place_id": entry["place_id"],
                "column": column,
                "new_value": value,
                "quote": new.get("Evidence Detail (what the source shows)", ""),
                "source_url": new.get("Source URLs (primary first)", ""),
                "stage": stage,
                "verified_by": new.get(fill.VERIFIED_BY, ""),
            })
    result["dropped_columns"] = dropped
    result["proposals"] = closed_proposals(result["plan"], dropped)
    return lines, result


CLOSED_STATUSES = ("Closed", "Temporarily closed")
PROPOSAL_HEADERS = ["Place ID", "issue", "column", "current value", "proposed value",
                    "quote", "source url"]


def closed_proposals(plan_entries, dropped):
    """Location Status is protected, so a bot report that a place is closed can
    never be applied. It matters too much to lose, so a dropped Closed or
    Temporarily closed value becomes a proposal, with its quote and source."""
    by_place_id = {entry["place_id"]: entry["new"] for entry in plan_entries}
    out = []
    for row in dropped:
        if row["column"] != "Location Status":
            continue
        value = str(row["new value"]).strip()
        if value not in CLOSED_STATUSES:
            continue
        new = by_place_id.get(row["Place ID"], {})
        out.append({
            "Place ID": row["Place ID"],
            "issue": f"the bot reports this place {value.lower()}",
            "column": "Location Status",
            "current value": "",
            "proposed value": value,
            "quote": new.get("Evidence Detail (what the source shows)", ""),
            "source url": new.get("Source URLs (primary first)", ""),
        })
    return out


# ---------------------------------------------------------------- commands

def _write_csv(path, rows, fieldnames):
    with open(path, "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _run_id(prefix):
    return prefix + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def apply_main(argv=None):
    parser = argparse.ArgumentParser(description="Apply a plan file to the database.")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    parser.add_argument("--run-id", help="Run id for the change log. Defaults to a timestamp.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    lines = read_plan(args.plan)
    run_id = args.run_id or _run_id("apply")
    report = apply_plan(conn, lines, run_id, apply=args.apply)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("db_apply")
    _write_csv(out_dir / "dry_run.csv", report["dry_run_rows"], PLAN_HEADERS)
    _write_csv(out_dir / "rejected.csv", report["rejected"], REJECT_HEADERS)

    print(f"Plan {args.plan}: {report['lines']} lines across {report['places']} Place IDs")
    if report["rejected"]:
        print(f"REFUSED: {len(report['rejected'])} lines. The whole plan is blocked.")
        for reject in report["rejected"][:10]:
            print(f"  {reject['Place ID']} {reject['column']}: {reject['reason']}")
        if len(report["rejected"]) > 10:
            print(f"  and {len(report['rejected']) - 10} more")
        print(f"Reports in {out_dir}/")
        return 1
    if args.apply:
        print(f"Applied {report['applied']} changes and {report['evidence']} evidence rows "
              f"under run {run_id}")
    else:
        print(f"Dry run: would apply {len(report['dry_run_rows'])} changes. "
              f"Nothing written. Add --apply to write.")
    if report["unchanged"]:
        print(f"{report['unchanged']} lines restate the value already there and change nothing.")
    print(f"Reports in {out_dir}/")
    return 0


def undo_main(argv=None):
    parser = argparse.ArgumentParser(description="Undo one run of applied changes.")
    parser.add_argument("--run", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    report = undo_run(conn, args.run, apply=args.apply)
    out_dir = reserve_output(args.out) if args.out else new_run_dir("db_undo")
    _write_csv(out_dir / "undo.csv", report["dry_run_rows"],
               ["Place ID", "column", "current value", "new value"])
    _write_csv(out_dir / "rejected.csv", report.get("rejected", []), REJECT_HEADERS)

    if not report["changes"]:
        print(f"Run {args.run} has no applied changes. Nothing to undo.")
        return 1
    if report["already_undone"]:
        print(f"Run {args.run} was already undone as {report['undo_run_id']}. Nothing done.")
        return 1
    if report.get("rejected"):
        print(f"REFUSED: {len(report['rejected'])} values are locked. The whole undo is blocked.")
        for reject in report["rejected"][:10]:
            print(f"  {reject['Place ID']} {reject['column']}: {reject['reason']}")
        print(f"Reports in {out_dir}/")
        return 1
    if args.apply:
        print(f"Restored {report['restored']} values under run {report['undo_run_id']}")
    else:
        print(f"Dry run: would restore {report['changes']} values. "
              f"Nothing written. Add --apply to write.")
    print(f"Report in {out_dir}/")
    return 0


def grok_import_main(argv=None):
    parser = argparse.ArgumentParser(description="Turn a bot results export into a plan file.")
    parser.add_argument("--results-csv", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    lines, result = grok_results_to_plan(conn, args.results_csv)
    out_dir = reserve_output(args.out) if args.out else new_run_dir("grok_import")
    write_plan(out_dir / "plan.jsonl", lines)
    _write_csv(out_dir / "skipped.csv",
               [{"Place ID": row["Place ID"], "Location Name": row["Location Name"],
                 "reason": "; ".join(row["Reasons"])} for row in result["skipped"]],
               ["Place ID", "Location Name", "reason"])
    _write_csv(out_dir / "rejects.csv",
               [{"Place ID": row["Place ID"], "Location Name": row["Location Name"],
                 "reason": "; ".join(row["Reasons"])} for row in result["rejects"]],
               ["Place ID", "Location Name", "reason"])
    _write_csv(out_dir / "dropped_columns.csv", result["dropped_columns"], REJECT_HEADERS)
    _write_csv(out_dir / "proposals.csv", result["proposals"], PROPOSAL_HEADERS)

    report = result["report"]
    print(f"{report['source_rows']} result rows: {report['accepted']} accepted, "
          f"{report['skipped']} skipped, {report['rejected']} rejected")
    print(f"{len(result['dropped_columns'])} columns dropped as unwritable or blank: "
          f"{out_dir / 'dropped_columns.csv'}")
    print(f"{len(result['proposals'])} places the bot reports closed, for your review: "
          f"{out_dir / 'proposals.csv'}")
    print(f"{len(lines)} plan lines written to {out_dir / 'plan.jsonl'}")
    print("Check it with db-apply, which is a dry run unless you add --apply.")
    return 0
