"""Ferro PP: rule R10's Evidence Level column.

Two one-time, interactive steps, each dry run by default:

python -m ferro_parking evidence-level-column [--apply]
    Appends the header "Evidence Level" after the sheet's last column,
    with a Verified / Chain policy / Presumed / Reported dropdown. Never inserts a
    column in the middle. Without --apply, only reports where it would go.

python -m ferro_parking evidence-level-backfill [--apply]
    For every finished row (Verification Result not blank) with no
    Evidence Level yet, sets "Chain policy" when Specificity is
    "Chain-wide" or Price Status is "Chain policy (not store-specific)",
    else "Verified". Without --apply, writes plan.json, undo.json, and
    dry_run.csv to data/runs/<today>/evidence_level_backfill/ and prints
    the count; apply it with the normal `write` command once approved.
"""
import argparse
import json
from datetime import date
from pathlib import Path

from . import fill, sheets

COLUMN = "Evidence Level"
VALUES = ["Verified", "Chain policy", "Presumed", "Reported"]


def plan_add_column(headers):
    """Dry run report: where the column would go and its dropdown values.
    Read only, no sheet access beyond the headers already passed in."""
    return {
        "header": COLUMN,
        "position_index": len(headers),
        "position_letter": sheets.col_letter(len(headers)),
        "after_column": headers[-1] if headers else None,
        "dropdown_values": VALUES,
    }


def add_column(service, headers, spreadsheet_id=sheets.SPREADSHEET_ID, tab=sheets.TAB):
    """Writes ONLY the new header cell and its dropdown validation. Never
    touches any existing column or row."""
    if COLUMN in headers:
        raise ValueError(f"{COLUMN!r} already exists in {tab!r}")
    sheet_id = sheets.get_sheet_id(service, spreadsheet_id, tab)
    col_index = len(headers)
    letter = sheets.col_letter(col_index)

    # The grid itself has no column at col_index yet (its dimensions stop
    # at the current last column), so one more column must be appended
    # before any cell past the edge can be written to.
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "appendDimension": {"sheetId": sheet_id, "dimension": "COLUMNS", "length": 1},
        }]}).execute()

    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{tab}!{letter}1",
        valueInputOption="RAW", body={"values": [[COLUMN]]}).execute()

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id, "startRowIndex": 1,
                    "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
                },
                "rule": {
                    "condition": {"type": "ONE_OF_LIST",
                                  "values": [{"userEnteredValue": v} for v in VALUES]},
                    "strict": True, "showCustomUi": True,
                },
            },
        }]}).execute()


def backfill_value(sheet_row):
    """R10's backfill rule for a finished row: Specificity "Chain-wide" or
    Price Status "Chain policy (not store-specific)" gives "Chain policy";
    anything else finished gives "Verified"."""
    if (sheet_row.get("Specificity", "") == "Chain-wide"
            or sheet_row.get("Price Status", "") == "Chain policy (not store-specific)"):
        return "Chain policy"
    return "Verified"


def build_backfill_plan(sheet_rows):
    plan, undo, dry_run_rows = [], [], []
    for row in sheet_rows:
        if row.get("Verification Result", "") == "":
            continue
        if row.get(COLUMN, ""):
            continue
        new_value = backfill_value(row)
        sheet_row_num = row["_sheet_row"]
        place_id = row.get(fill.PLACE_ID, "")
        name = row.get(fill.LOCATION_NAME, "")
        plan.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name,
                     "new": {COLUMN: new_value}})
        undo.append({"sheet_row": sheet_row_num, "place_id": place_id,
                     "old": {COLUMN: row.get(COLUMN, "")}})
        dry_run_rows.append({"Sheet Row": sheet_row_num, "Place ID": place_id,
                             "Location Name": name, "Column": COLUMN,
                             "Current value": row.get(COLUMN, ""), "New value": new_value})
    return plan, undo, dry_run_rows


def column_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    service = sheets.get_service()
    headers = sheets.get_headers(service)
    report = plan_add_column(headers)

    print(f"{len(headers)} columns currently; last column is "
          f"{report['after_column']!r} at {sheets.col_letter(len(headers) - 1)}.")
    print(f"New column {report['header']!r} would go at {report['position_letter']} "
          f"(index {report['position_index']}), right after {report['after_column']!r}.")
    print(f"Dropdown values: {', '.join(report['dropdown_values'])}")

    if not args.apply:
        print("Dry run only. Rerun with --apply to write the header and dropdown.")
        return 0

    add_column(service, headers)
    print(f"Wrote header {report['header']!r} at {report['position_letter']}1 "
          f"and its dropdown. No other cell was touched.")
    return 0


def backfill_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    if COLUMN not in headers:
        print(f"{COLUMN!r} does not exist yet. Run evidence-level-column --apply first.")
        return 1

    plan, undo, dry_run_rows = build_backfill_plan(sheet_rows)
    out_dir = (Path(args.out) if args.out
               else Path("data/runs") / date.today().isoformat() / "evidence_level_backfill")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo, indent=1))
    fill.write_csv(out_dir / "dry_run.csv",
                    ["Sheet Row", "Place ID", "Location Name", "Column",
                     "Current value", "New value"], dry_run_rows)

    chain_count = sum(1 for e in plan if e["new"][COLUMN] == "Chain policy")
    print(f"Finished rows needing {COLUMN}: {len(plan)}")
    print(f"  Chain policy: {chain_count}")
    print(f"  Verified: {len(plan) - chain_count}")
    print(f"Outputs in {out_dir}/. Dry run only: apply with "
          f"`python -m ferro_parking write {out_dir}/plan.json --apply`.")
    return 0
