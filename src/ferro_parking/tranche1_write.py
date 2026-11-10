"""
Ferro PP: prepare the tranche 1 write to "ALL LONDON (clean)".

Dry run by default: takes tranche1_ready.csv (tranche1.py's output),
selects which rows actually get added, checks each one against a fresh
export of the live sheet, and writes the plan. It never writes to the
sheet itself; python -m ferro_parking tranche1-write-apply does that, and
only with --apply.

python -m ferro_parking tranche1-write data/runs/<date>/tranche1/tranche1_ready.csv
Options:
  --out DIR   output directory (default: data/runs/<today>/tranche1_write)

python -m ferro_parking tranche1-write-apply PLAN.csv [--apply]
    Without --apply, prints what would be appended. With --apply: adds
    the OSM ID column if the sheet does not have one yet, saves an undo
    file, appends the rows, re-exports, and verifies every new row
    matches the plan, aborting on any mismatch (reuses sync.py's
    apply_append/verify_append, the same append-at-the-bottom machinery
    sync-apply already uses).
"""
import argparse
import csv
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from shapely.geometry import Point
from shapely.strtree import STRtree

from . import rules as rules_mod
from . import sheets
from . import sync as sync_mod
from .osm_match import brand_key, contains_word, norm, to_m

FIRST_NEW_PLACE_NUM = 5440   # the first new row is PP-005440

# ---------------------------------------------------------------- category mapping

# "ALL LONDON (clean)"'s Place Category is a dropdown: only these exact
# values are allowed (CLAUDE.md). retail_park has no literal option, so it
# maps to the closest existing one; that is a judgement call, not a fact,
# and is reported as such.
CATEGORY_TO_PLACE_CATEGORY = {
    "supermarket": "Supermarket - large format",
    "petrol_station": "Petrol station",
    "station": "Station",
    "hospital": "Hospital / health centre",
    "retail_park": "Shopping centre",
}
COUNCIL_HINTS = ("council", "borough", "corporation", "tfl", "transport for london")


def place_category_for(row):
    if row["Category"] == "car_park":
        text = norm(f"{row.get('Operator', '')} {row.get('Name', '')}")
        return "Council car park" if any(h in text for h in COUNCIL_HINTS) else "Private / operator car park"
    return CATEGORY_TO_PLACE_CATEGORY.get(row["Category"], "Other")


# ---------------------------------------------------------------- confidence selection

# High and Medium are always kept. Low is dropped by default; car_park and
# retail_park are the two named exceptions. Excluding Low supermarkets is
# already the effect of that default, named explicitly in the brief anyway.
LOW_CONFIDENCE_EXCEPTIONS = {"car_park", "retail_park"}


def passes_confidence_selection(row):
    if row["Confidence"] in ("High", "Medium"):
        return True
    return row["Confidence"] == "Low" and row["Category"] in LOW_CONFIDENCE_EXCEPTIONS


# ---------------------------------------------------------------- hotel / airport notes

AIRPORT_PHRASES = ("purple parking", "meet and greet", "airport parking", "park and fly")
HOTEL_CAR_PARK_FLAG = "Hotel car park (not public)"   # tranche1.py's Notes value for this


def is_airport_parking(row):
    text = norm(f"{row.get('Name', '')} {row.get('Operator', '')}")
    return any(phrase in text for phrase in AIRPORT_PHRASES)


def notes_for(row):
    if is_airport_parking(row):
        return "Pre-booked airport parking"
    if row.get("Notes") == HOTEL_CAR_PARK_FLAG:
        return "Near hotel, access to confirm"
    return ""


# ---------------------------------------------------------------- point indexing

def row_point_m(lat, lon):
    try:
        return to_m(Point(float(lon), float(lat)))
    except (TypeError, ValueError):
        return None


def build_point_index(rows, lat_key, lon_key):
    """A spatial index over rows that have coordinates. Returns
    (tree_or_None, points, valid_idx): points[i] is rows[i]'s point (or
    None), valid_idx maps the tree's own result positions back to indices
    into rows."""
    points = [row_point_m(r.get(lat_key, ""), r.get(lon_key, "")) for r in rows]
    valid_idx = [i for i, p in enumerate(points) if p is not None]
    tree = STRtree([points[i] for i in valid_idx]) if valid_idx else None
    return tree, points, valid_idx


def query_nearby(tree, points, valid_idx, point, radius_m):
    """Indices into the original row list within radius_m of point."""
    if tree is None or point is None:
        return []
    return [valid_idx[pos] for pos in tree.query(point.buffer(radius_m))]


# ---------------------------------------------------------------- store car park -> attach to existing

CHAIN_BRAND_RADIUS_M = 200


def chain_brand_match(candidate, sheet_rows, sheet_tree, sheet_points, sheet_valid_idx, rules):
    """A sheet row of a known chain brand (rules.r3_own_brand_names, the
    same list R3 uses for "this operator is the store itself") within
    CHAIN_BRAND_RADIUS_M whose brand also appears in this car park's own
    name or operator text. Returns that sheet row, or None. No separate
    brand list: one list of known chains serves both rules."""
    text = norm(f"{candidate.get('Name', '')} {candidate.get('Operator', '')}")
    brand = next((b for b in rules.r3_own_brand_names if contains_word(text, b)), None)
    if not brand:
        return None
    point = row_point_m(candidate.get("Lat", ""), candidate.get("Lon", ""))
    for idx in query_nearby(sheet_tree, sheet_points, sheet_valid_idx, point, CHAIN_BRAND_RADIUS_M):
        row = sheet_rows[idx]
        if brand_key(row) == brand or contains_word(norm(row.get("Location Name", "")), brand):
            return row
    return None


# ---------------------------------------------------------------- duplicate check

DUPLICATE_RADIUS_M = 100


def duplicate_in_sheet(candidate, sheet_rows, sheet_tree, sheet_points, sheet_valid_idx):
    """A sheet row this candidate duplicates: same OSM ID (an "OSM ID"
    column from an earlier tranche's write), or the same name within
    DUPLICATE_RADIUS_M. Returns (sheet_row, reason) or (None, None)."""
    osm_id = f"{candidate['OSM Type']}/{candidate['OSM Id']}"
    for row in sheet_rows:
        if row.get("OSM ID", "") == osm_id:
            return row, "same OSM ID"

    point = row_point_m(candidate.get("Lat", ""), candidate.get("Lon", ""))
    name = norm(candidate.get("Name", ""))
    if not name:
        return None, None
    for idx in query_nearby(sheet_tree, sheet_points, sheet_valid_idx, point, DUPLICATE_RADIUS_M):
        row = sheet_rows[idx]
        if norm(row.get("Location Name", "")) == name:
            d = round(point.distance(sheet_points[idx]))
            return row, f"same name within {d} m"
    return None, None


# ---------------------------------------------------------------- the plan

def build_sheet_row(candidate, place_id, today):
    return {
        "Place ID": place_id,
        "Location Name": candidate.get("Name", ""),
        "Place Category": place_category_for(candidate),
        "Street Address": candidate.get("Address (OSM)", ""),
        "Postcode": candidate.get("Postcode", ""),
        "Borough": candidate.get("Borough", ""),
        "Latitude": candidate.get("Lat", ""),
        "Longitude": candidate.get("Lon", ""),
        "Captured By": "OSM discovery",
        "Date Captured": today.isoformat(),
        "Evidence Level": "",
        "Verification Result": "",
        "Notes": notes_for(candidate),
        "OSM ID": f"{candidate['OSM Type']}/{candidate['OSM Id']}",
    }


def build_plan(ready_rows, sheet_rows, rules, today, start_num=FIRST_NEW_PLACE_NUM,
                hold_low_categories=()):
    """Runs every tranche1_ready.csv row through confidence selection,
    the outside-London check, the store-car-park attach rule, and the
    duplicate check, in that order; whatever is left to actually add is
    then split by the optional hold-back (specific categories' Low
    confidence rows go to held_rows instead of plan_rows). Holding a row
    back is the last cut, so it never changes who gets attached to an
    existing store or flagged as a duplicate: those are about the place
    itself, not about whether today's batch includes it. Returns a dict
    of the result lists plus the final plan rows (already carrying their
    new Place IDs)."""
    sheet_tree, sheet_points, sheet_valid_idx = build_point_index(sheet_rows, "Latitude", "Longitude")

    excluded_outside_london, attach_to_existing, duplicates_skipped, held_rows = [], [], [], []
    after_confidence = [r for r in ready_rows if passes_confidence_selection(r)]

    after_borough = []
    for row in after_confidence:
        if row.get("Borough"):
            after_borough.append(row)
        else:
            excluded_outside_london.append(row)

    after_chain_attach = []
    for row in after_borough:
        match = (chain_brand_match(row, sheet_rows, sheet_tree, sheet_points, sheet_valid_idx, rules)
                 if row["Category"] == "car_park" else None)
        if match:
            attach_to_existing.append((row, match))
        else:
            after_chain_attach.append(row)

    after_dedup, seen_osm_ids = [], set()
    for row in after_chain_attach:
        osm_id = (row["OSM Type"], row["OSM Id"])
        if osm_id in seen_osm_ids:
            duplicates_skipped.append((row, "duplicate within this batch", None))
            continue
        dup_row, reason = duplicate_in_sheet(row, sheet_rows, sheet_tree, sheet_points, sheet_valid_idx)
        if dup_row is not None:
            duplicates_skipped.append((row, reason, dup_row))
            continue
        seen_osm_ids.add(osm_id)
        after_dedup.append(row)

    final_rows = []
    for row in after_dedup:
        if row["Confidence"] == "Low" and row["Category"] in hold_low_categories:
            held_rows.append(row)
        else:
            final_rows.append(row)

    plan_rows = []
    for i, row in enumerate(final_rows):
        place_id = f"PP-{start_num + i:06d}"
        plan_rows.append({**build_sheet_row(row, place_id, today),
                           "Category": row["Category"], "Confidence": row["Confidence"],
                           "OSM Link": row.get("OSM Link", "")})

    return {
        "plan_rows": plan_rows,
        "excluded_outside_london": excluded_outside_london,
        "attach_to_existing": attach_to_existing,
        "duplicates_skipped": duplicates_skipped,
        "held_rows": held_rows,
    }


# ---------------------------------------------------------------- outputs

PLAN_COLUMNS = ["Place ID", "Location Name", "Place Category", "Street Address", "Postcode",
                "Borough", "Latitude", "Longitude", "Captured By", "Date Captured",
                "Evidence Level", "Verification Result", "Notes", "OSM ID",
                "Category", "Confidence", "OSM Link"]


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _outside_london_row(row):
    return {"OSM Type": row["OSM Type"], "OSM Id": row["OSM Id"], "OSM Link": row.get("OSM Link", ""),
            "Name": row.get("Name", ""), "Category": row["Category"],
            "Lat": row.get("Lat", ""), "Lon": row.get("Lon", "")}


def _attach_row(pair):
    row, matched = pair
    return {"OSM Type": row["OSM Type"], "OSM Id": row["OSM Id"], "OSM Link": row.get("OSM Link", ""),
            "Name": row.get("Name", ""), "Category": row["Category"],
            "Lat": row.get("Lat", ""), "Lon": row.get("Lon", ""),
            "Matched Place ID": matched.get("Place ID", ""),
            "Matched Sheet Row Name": matched.get("Location Name", "")}


def _duplicate_row(triple):
    row, reason, existing = triple
    return {"OSM Type": row["OSM Type"], "OSM Id": row["OSM Id"], "OSM Link": row.get("OSM Link", ""),
            "Name": row.get("Name", ""), "Category": row["Category"],
            "Lat": row.get("Lat", ""), "Lon": row.get("Lon", ""), "Reason": reason,
            "Existing Place ID": (existing or {}).get("Place ID", ""),
            "Existing Name": (existing or {}).get("Location Name", "")}


def run(ready_csv_path, out_dir, today=None, categories=None, hold_low_categories=()):
    today = today or date.today()
    rules = rules_mod.load_rules()

    with open(ready_csv_path, newline="", encoding="utf-8") as f:
        ready_rows = list(csv.DictReader(f))

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)

    plan = build_plan(ready_rows, sheet_rows, rules, today, hold_low_categories=hold_low_categories)
    plan["before_count"] = len(ready_rows)
    plan["excluded_low_confidence"] = (len(ready_rows) - len(plan["plan_rows"])
                                        - len(plan["excluded_outside_london"])
                                        - len(plan["attach_to_existing"])
                                        - len(plan["duplicates_skipped"])
                                        - len(plan["held_rows"]))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(out_dir / "write_plan.csv", PLAN_COLUMNS, plan["plan_rows"])
    _write_csv(out_dir / "excluded_outside_london.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Lat", "Lon"],
               [_outside_london_row(r) for r in plan["excluded_outside_london"]])
    _write_csv(out_dir / "attach_to_existing.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Lat", "Lon",
                "Matched Place ID", "Matched Sheet Row Name"],
               [_attach_row(p) for p in plan["attach_to_existing"]])
    _write_csv(out_dir / "duplicates_skipped.csv",
               ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Lat", "Lon",
                "Reason", "Existing Place ID", "Existing Name"],
               [_duplicate_row(t) for t in plan["duplicates_skipped"]])
    if hold_low_categories:
        _write_csv(out_dir / "held_low_car_parks.csv",
                   ["OSM Type", "OSM Id", "OSM Link", "Name", "Category", "Lat", "Lon",
                    "Borough", "Operator", "Access", "Fee"],
                   [_outside_london_row(r) | {"Borough": r.get("Borough", ""),
                                               "Operator": r.get("Operator", ""),
                                               "Access": r.get("Access", ""), "Fee": r.get("Fee", "")}
                    for r in plan["held_rows"]])

    plan["out_dir"] = out_dir
    plan["headers"] = headers
    plan["sheet_rows"] = sheet_rows
    return plan


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("ready_csv")
    ap.add_argument("--out", default=None)
    ap.add_argument("--hold-low-categories", default="",
                     help="comma-separated categories whose Low confidence rows are held "
                          "back to held_low_car_parks.csv instead of being added now")
    args = ap.parse_args(argv)

    today = date.today()
    if args.out is None:
        args.out = Path("data") / "runs" / today.isoformat() / "tranche1_write"
    hold_low_categories = {c.strip() for c in args.hold_low_categories.split(",") if c.strip()}

    plan = run(args.ready_csv, args.out, today, hold_low_categories=hold_low_categories)
    plan_rows = plan["plan_rows"]
    by_cat_conf = Counter((r["Category"], r["Confidence"]) for r in plan_rows)
    print(f"Candidates from {args.ready_csv}: {plan['before_count']}")
    print(f"Excluded, Low confidence outside the car_park/retail_park exception: "
          f"{plan['excluded_low_confidence']}")
    print(f"Excluded, outside all 33 London boundaries: {len(plan['excluded_outside_london'])}")
    if hold_low_categories:
        print(f"Held back for later ({', '.join(sorted(hold_low_categories))}, Low confidence): "
              f"{len(plan['held_rows'])}")
    print(f"Attached to an existing store's row (not added): {len(plan['attach_to_existing'])}")
    print(f"Skipped as duplicates of an existing sheet row: {len(plan['duplicates_skipped'])}")
    print(f"\nPlanned new rows: {len(plan_rows)}")
    print("\nBy category and confidence:")
    for (cat, conf), count in sorted(by_cat_conf.items()):
        print(f"  {cat:<18}{conf:<8}{count}")

    print("\nFirst 10 planned rows:")
    for row in plan_rows[:10]:
        print(f"  {row['Place ID']}  {row['Category']:<14}{row['Confidence']:<8}{row['Location Name']}")

    if plan_rows:
        print(f"\nPlace ID range: {plan_rows[0]['Place ID']} to {plan_rows[-1]['Place ID']}")
    print(f"Undo file that will be saved on approval: {Path(args.out) / 'undo.json'}")
    print(f"\nOutputs in {args.out}/. No writes were made to the sheet. Dry run only.")
    return 0


# ---------------------------------------------------------------- apply (not run this turn)

OSM_ID_COLUMN = "OSM ID"


def ensure_grid_has_column(service, spreadsheet_id, sheet_id, needed_columns):
    """Grows the tab's grid by one column if its current grid is too
    narrow to hold a column at index needed_columns - 1 (0-based). A
    fixed-size grid (this tab's is capped at 59 columns) rejects a write
    past its edge outright, so the column has to exist first."""
    meta = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id, fields="sheets.properties").execute()
    for sheet in meta["sheets"]:
        if sheet["properties"]["sheetId"] == sheet_id:
            current = sheet["properties"]["gridProperties"]["columnCount"]
            break
    else:
        raise ValueError(f"No sheet with id {sheet_id!r}")
    if current >= needed_columns:
        return
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"appendDimension": {
            "sheetId": sheet_id, "dimension": "COLUMNS",
            "length": needed_columns - current}}]}).execute()


def ensure_osm_id_column(service, headers, spreadsheet_id=None, tab=None):
    """Appends the "OSM ID" header at the end of the sheet if it is not
    already there (CLAUDE.md: new columns only at the end). Returns the
    possibly-updated headers list."""
    if OSM_ID_COLUMN in headers:
        return headers
    spreadsheet_id = spreadsheet_id or sheets.SPREADSHEET_ID
    tab = tab or sheets.TAB
    sheet_id = sheets.get_sheet_id(service, spreadsheet_id, tab)
    ensure_grid_has_column(service, spreadsheet_id, sheet_id, len(headers) + 1)
    col = sheets.col_letter(len(headers))
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{tab}!{col}1",
        valueInputOption="RAW", body={"values": [[OSM_ID_COLUMN]]}).execute()
    return headers + [OSM_ID_COLUMN]


def apply_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_csv")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    with open(args.plan_csv, newline="", encoding="utf-8") as f:
        plan_rows = list(csv.DictReader(f))
    if plan_rows:
        print(f"Plan: {len(plan_rows)} rows ({plan_rows[0]['Place ID']} to {plan_rows[-1]['Place ID']}).")
    else:
        print("Plan: 0 rows. Nothing to do.")
        return 0

    service = sheets.get_service()
    headers, clean_rows = sheets.read_tab(service)
    last_row = clean_rows[-1]["_sheet_row"]
    expected_first_new_row = last_row + 1

    existing_ids = {r.get("Place ID", "") for r in clean_rows}
    already_done = [r["Place ID"] for r in plan_rows if r["Place ID"] in existing_ids]
    if already_done:
        print(f"Already applied: {len(already_done)} of these Place IDs are in the sheet "
              f"already (e.g. {already_done[0]}). Stopping, nothing written.")
        return 1

    if not args.apply:
        print(f"Would append rows {expected_first_new_row} to "
              f"{expected_first_new_row + len(plan_rows) - 1}.")
        print("Dry run only. Rerun with --apply to write.")
        return 0

    headers = ensure_osm_id_column(service, headers)
    undo_path = Path(args.plan_csv).parent / "undo.json"
    undo_path.write_text(json.dumps({
        "first_row": expected_first_new_row,
        "last_row": expected_first_new_row + len(plan_rows) - 1,
        "place_ids": [r["Place ID"] for r in plan_rows],
    }, indent=1))
    print(f"Undo file saved: {undo_path} "
          "(records the appended range for a manual row delete if ever needed; "
          "this script never deletes sheet rows itself)")

    first_row, written_last_row = sync_mod.apply_append(
        service, headers, clean_rows, plan_rows, formula_row_num=last_row)
    print(f"Wrote rows {first_row} to {written_last_row}.")

    mismatches = sync_mod.verify_append(service, headers, plan_rows, clean_rows, first_row, written_last_row)
    if mismatches:
        print(f"STOP: {len(mismatches)} mismatch(es) found on independent verification:")
        for m in mismatches[:20]:
            print(f"  {m}")
        return 1
    print(f"Verified: {written_last_row - first_row + 1} new rows now in {sheets.TAB}, "
          "every appended cell matches the plan, no existing row changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
