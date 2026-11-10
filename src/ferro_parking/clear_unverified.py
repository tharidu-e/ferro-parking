"""Ferro PP: clear every unverified parking answer from
"ALL LONDON (clean)", so nothing unverified is visible in the sheet.

python -m ferro_parking clear-unverified
    Dry run only. Writes plan.json (every cleared cell, set to blank)
    and undo.json (every current value) to
    data/runs/<today>/clear_unverified/ for every row with
    Verification Result blank. Apply with the normal write command once
    approved. --apply additionally requires --confirm-wipe and uses the
    existing writer after reporting the affected row count.

Only CLEARED_COLUMNS are touched. Every other column, every row with a
Verification Result already set, and the "ALL LONDON" tab are left alone.
"""
import argparse
import csv
import json
from datetime import date
from pathlib import Path
from .run_paths import new_run_dir

CLEARED_COLUMNS = [
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Rules Summary", "Cost Type",
    "Price Status", "Tariff Type", "Tariff Detail", "Max Stay (mins)",
    "Hours (OpenStreetMap opening_hours format)", "Hours Basis",
    "Parking Control Type (Cameras / Barrier / Patrol)", "Operator",
    "PCN (Penalty Charge Notice) amount (£)",
]


def eligible_rows(sheet_rows):
    return [r for r in sheet_rows if r.get("Verification Result", "") == "" and r.get("Verified By", "") in ("", "PP (validation)")]


def build_plan(sheet_rows):
    """Returns (plan, undo, dry_run_rows). A row with nothing to clear
    (every CLEARED_COLUMNS cell already blank) is left out of all three:
    it needs no write."""
    plan, undo, dry_run_rows = [], [], []
    for row in eligible_rows(sheet_rows):
        old = {col: row.get(col, "") for col in CLEARED_COLUMNS}
        if not any(old.values()):
            continue
        sheet_row_num = row["_sheet_row"]
        place_id = row.get("Place ID", "")
        name = row.get("Location Name", "")
        new = {col: "" for col in CLEARED_COLUMNS}
        plan.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name, "new": new})
        undo.append({"sheet_row": sheet_row_num, "place_id": place_id, "old": old})
        for col in CLEARED_COLUMNS:
            dry_run_rows.append({"Sheet Row": sheet_row_num, "Place ID": place_id,
                                  "Location Name": name, "Column": col,
                                  "Current value": old[col], "New value": ""})
    return plan, undo, dry_run_rows


def main(argv=None):
    from . import sheets

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm-wipe", action="store_true")
    args = ap.parse_args(argv)
    if args.apply and not args.confirm_wipe:
        ap.error("--apply requires --confirm-wipe")
    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    plan, undo, dry_run_rows = build_plan(sheet_rows)

    non_blank_by_column = {col: 0 for col in CLEARED_COLUMNS}
    for entry in undo:
        for col, value in entry["old"].items():
            if value:
                non_blank_by_column[col] += 1

    print(f"Rows affected: {len(plan)}")
    out_dir = new_run_dir("clear_unverified")
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo, indent=1))
    with open(out_dir / "dry_run.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["Sheet Row", "Place ID", "Location Name", "Column",
                                           "Current value", "New value"])
        w.writeheader()
        w.writerows(dry_run_rows)

    eligible = eligible_rows(sheet_rows)
    print(f"Rows with Verification Result blank: {len(eligible)}")
    print(f"Rows affected (at least one column to clear): {len(plan)}")
    print("Non-blank cells per column:")
    for col in CLEARED_COLUMNS:
        print(f"  {non_blank_by_column[col]:5d}  {col}")
    print(f"\nOutputs in {out_dir}/.")
    if not args.apply:
        print("Dry run only, nothing written to the sheet.")
    if args.apply:
        from .fill import write_main
        return write_main([str(out_dir / "plan.json"), "--apply", "--confirm-wipe"])
    return 0
