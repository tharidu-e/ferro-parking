"""Ferro PP: sync "ALL LONDON" (the original capture tab, read only, never
written) into "ALL LONDON (clean)" (the working tab).

ALL LONDON grows as new places are captured there; this module finds the
rows "ALL LONDON (clean)" does not have yet, maps each one onto the clean
layout, and flags likely duplicates. It never writes to the sheet; the
caller decides what to do with the mapped rows.

The column mapping below is read, not designed: it comes from comparing
real aligned row pairs between the two tabs (see map_row's docstring for
which fields are a direct, reliable copy and which are not).
"""
import csv
import re
from datetime import date
from pathlib import Path
from .run_paths import new_run_dir, reserve_output

from .settings import setting

ORIG_TAB = setting("original_tab")
CLEAN_TAB = setting("clean_tab")

# "ALL LONDON"'s own column headers, by clean-tab field name, for every
# field a direct copy reproduces reliably (checked against all 4773
# aligned row pairs; see sync_mapping_notes below for the fidelity of
# each one). Google Sheets' header for the name column is, confusingly,
# just "sheet".
DIRECT_FIELD_MAP = {
    "Location Name": "sheet",
    "Type (as captured)": "Type (Public/Private/Retail/Hotel/etc.)",
    "Borough": "Borough",
    "Charges (as published)": "Charges / Fees",
    "Max Stay (as captured)": "Max Stay",
    "Hours (as captured)": "Hours / Days Allowed",
    "Enforcement Details": "Enforcement / Penalties",
    "Source URLs (primary first)": "Source URL",
    "Notes": "Notes / Special Conditions",
    "Date Captured": "Date Captured",
    "Latitude": "Latitude",
    "Longitude": "Longitude",
    "Geo (as captured)": "Geo Source / Precision",
    # ALL LONDON's "Verified By" is who captured the row, not a second
    # reviewer; it becomes "Captured By" in the clean tab, which has its
    # own separate "Verified By" for the second-pass reviewer.
    "Captured By": "Verified By",
}

# Fields that LOOK like a direct copy (the two tabs happen to share
# similar column names, e.g. ALL LONDON has its own "Can Park?" and
# "Location Status") but were edited by hand often enough in the aligned
# rows (Rules Summary 58%, Notes 59% before trimming, Location Status's
# free text in particular) that copying them mechanically would carry
# that judgment call's shape without the judgment itself. These stay
# blank for a new row, same as every other research column (Cost Type,
# Tariff Type, Operator, Evidence Type, Brand, Place Category, Area Type,
# Geo Source, Geo Precision, and so on): a new row gets them from running
# the research pipeline on it, not from ALL LONDON's own rough pass.
RESEARCH_ONLY_FIELDS = (
    "Brand", "Place Category", "Area Type", "Can Park? (Yes/No/Conditional)",
    "Who Can Park", "Rules Summary", "Cost Type", "Price Status", "Tariff Type",
    "Tariff Detail", "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)",
    "Hours Basis", "Parking Control Type (Cameras / Barrier / Patrol)", "Operator",
    "PCN (Penalty Charge Notice) amount (£)", "Evidence Type",
    "Evidence Detail (what the source shows)", "Source Tier", "Specificity",
    "Rules Stated", "Prices Stated", "Evidence Age", "Agreeing Sources", "Conflict",
    "Verified By", "Verified Date", "Verification Result", "Change Made (Yes/No)",
    "Geo Source", "Geo Precision", "Review Flag", "Flag Status", "Decision Reason",
)

# Columns that hold a Sheets formula in the existing rows, so a new row
# needs the formula filled down, not a value written: Postcode Area reads
# the Postcode column, Confidence (1-5) reads several Evidence/Rules
# columns, and Total incl. Ferro Fee (£) reads Parking Charge (£).
FORMULA_COLUMNS = ("Postcode Area", "Confidence (1-5)", "Total incl. Ferro Fee (£)")

# Brandon's own four columns. Three (Free Stay Countdown, Ferro Autopay,
# Parking Charge) are plain hand-entered values in the existing rows, not
# formulas; Total incl. Ferro Fee (£) is the one formula among them (see
# FORMULA_COLUMNS). All four stay empty for a new row either way.
BRANDON_COLUMNS = ("Free Stay Countdown (mins)", "Ferro Autopay",
                    "Parking Charge (£)", "Total incl. Ferro Fee (£)")

FULL_POSTCODE_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b", re.I)
OUTWARD_ONLY_RE = re.compile(r"\b([A-Z]{1,2}\d[A-Z]?)\s*$", re.I)


def split_address(address):
    """Split ALL LONDON's combined "Address / Postcode" into (street,
    postcode), the way the clean tab's Street Address and Postcode were
    built. Checked against all 4773 aligned rows: exact on postcode 99.4%
    of the time, on street address 95.2%; the rest are source rows with
    an ambiguous or annotated postcode (two postcode districts, a
    parenthetical note) that a person already had to read individually."""
    address = (address or "").strip()
    match = FULL_POSTCODE_RE.search(address)
    if match:
        postcode = re.sub(r"\s+", " ", match.group(1).upper())
        street = address[:match.start()] + " " + address[match.end():]
        street = re.sub(r"\s*\([^)]*\)\s*", " ", street)
        street = re.sub(r"\s+", " ", street).strip().rstrip(", ").strip()
        return street, postcode
    match = OUTWARD_ONLY_RE.search(address)
    if match:
        return address[:match.start()].rstrip(", ").strip(), match.group(1).upper()
    return address, ""


# ALL LONDON's free-text Location Status does not reduce to a pure
# function of the text: the aligned rows show the same kind of phrase
# ("UNCLEAR ...", "Open (...)") landing on different clean values
# depending on what a reviewer actually knew. This covers only the
# handful of values every row in the "new" range for this sync actually
# has (all 667 are plain "Open"); anything else is a judgment call this
# function declines to make and reports as "Unknown" instead of guessing.
LOCATION_STATUS_MAP = {
    "open": "Open",
    "closed": "Closed",
    "temporarily closed": "Temporarily closed",
    "active": "Open",
}


def map_location_status(value):
    return LOCATION_STATUS_MAP.get((value or "").strip().lower(), "Unknown")


def map_row(orig_row):
    """Map one ALL LONDON row onto the clean tab's field names. Returns a
    dict of only the fields this module can fill reliably; every other
    clean column (RESEARCH_ONLY_FIELDS, the formula and Brandon columns)
    is left out, for the caller to leave blank or fill down as a formula."""
    mapped = {clean_field: orig_row.get(orig_field, "")
              for clean_field, orig_field in DIRECT_FIELD_MAP.items()}
    street, postcode = split_address(orig_row.get("Address / Postcode", ""))
    mapped["Street Address"] = street
    mapped["Postcode"] = postcode
    mapped["Location Status"] = map_location_status(
        orig_row.get("Location Status (Open / Closed)", ""))
    return mapped


def normalize_name(name):
    """Lowercase, trailing-parenthetical-stripped form of a location name,
    for duplicate matching. The trailing parenthetical is often a
    disambiguating note ("(Ealing Council, ref A02)") that does not
    appear on both sides of a true duplicate pair."""
    name = (name or "").strip().lower()
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    return re.sub(r"\s+", " ", name).strip()


def normalize_postcode(postcode):
    return re.sub(r"\s+", "", (postcode or "").strip().upper())


EARTH_RADIUS_M = 6371000


def haversine_m(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * atan2(sqrt(a), sqrt(1 - a))


def find_duplicates(new_rows, clean_rows, radius_m=100):
    """For each new ALL LONDON row, look for a likely duplicate already
    in the clean tab: the same normalized name and postcode, or the same
    Brand within radius_m metres. Returns a list of
    (new_row, clean_row, reason) triples; callers flag these, they never
    get appended automatically."""
    by_name_postcode = {}
    by_brand = {}
    for row in clean_rows:
        key = (normalize_name(row.get("Location Name", "")),
               normalize_postcode(row.get("Postcode", "")))
        if key[1]:
            by_name_postcode.setdefault(key, []).append(row)
        brand = (row.get("Brand", "") or "").strip().lower()
        if brand:
            by_brand.setdefault(brand, []).append(row)

    duplicates = []
    for new_row in new_rows:
        name = normalize_name(new_row.get("sheet", ""))
        _, postcode = split_address(new_row.get("Address / Postcode", ""))
        key = (name, normalize_postcode(postcode))
        matched_ids = set()
        if key[1]:
            for clean_row in by_name_postcode.get(key, []):
                duplicates.append((new_row, clean_row, "same name and postcode"))
                matched_ids.add(id(clean_row))

        type_text = (new_row.get("Type (Public/Private/Retail/Hotel/etc.)", "") or "")
        brand_match = re.search(r"\(([^()]+)\)\s*$", type_text)
        brand = (brand_match.group(1) if brand_match else type_text).strip().lower()
        try:
            new_lat = float(new_row.get("Latitude", ""))
            new_lon = float(new_row.get("Longitude", ""))
        except (TypeError, ValueError):
            continue
        for clean_row in by_brand.get(brand, []):
            if id(clean_row) in matched_ids:
                continue
            try:
                lat = float(clean_row.get("Latitude", ""))
                lon = float(clean_row.get("Longitude", ""))
            except (TypeError, ValueError):
                continue
            distance = haversine_m(new_lat, new_lon, lat, lon)
            if distance <= radius_m:
                duplicates.append((new_row, clean_row,
                                    f"same brand within {distance:.0f} m"))
    return duplicates


def _load_tabs(service):
    # sheets.read_tab corrects the clean tab's corrupted A1 header
    # ("Location Name" replaced by a stray note) on every read.
    from . import sheets
    clean_headers, clean_rows = sheets.read_tab(service, tab=CLEAN_TAB)
    orig_headers, orig_rows = sheets.read_tab(service, tab=ORIG_TAB)
    return clean_headers, clean_rows, orig_headers, orig_rows


def identity_key(row):
    mapped = map_row(row) if "sheet" in row else row
    name = normalize_name(mapped.get("Location Name", ""))
    postcode = normalize_postcode(mapped.get("Postcode", ""))
    if not name or not postcode:
        return None
    return name, postcode


def join_tabs(clean_rows, orig_rows):
    """Prove a unique identity for every existing clean row or abort."""
    by_id, by_identity = {}, {}
    for original in orig_rows:
        pid, key = original.get("Place ID"), identity_key(original)
        if pid:
            by_id.setdefault(pid, []).append(original)
        if key:
            by_identity.setdefault(key, []).append(original)
    pairs, used = [], set()
    for clean in clean_rows:
        matches = by_id.get(clean.get("Place ID"), [])
        if not matches:
            matches = by_identity.get(identity_key(clean), [])
            if any(row.get("Place ID") and row["Place ID"] != clean.get("Place ID") for row in matches):
                raise ValueError("WARNING: conflicting Place IDs; alignment cannot be proven")
        if len(matches) != 1 or id(matches[0]) in used:
            raise ValueError("WARNING: tab alignment cannot be proven uniquely by Place ID or name+postcode")
        used.add(id(matches[0]))
        pairs.append((clean, matches[0]))
    return pairs


def check_alignment(clean_rows, orig_rows):
    pairs = join_tabs(clean_rows, orig_rows)
    return len(pairs), []


def captured_can_park_by_place_id(clean_rows, orig_rows):
    return {clean["Place ID"]: original.get("Can Park? (Yes/No/Conditional)", "")
            for clean, original in join_tabs(clean_rows, orig_rows) if clean.get("Place ID")}


def load_captured_can_park(service):
    from . import sheets
    _, clean_rows = sheets.read_tab(service, tab=CLEAN_TAB)
    _, orig_rows = sheets.read_tab(service, tab=ORIG_TAB)
    return captured_can_park_by_place_id(clean_rows, orig_rows)


def main(argv=None):
    import argparse
    from . import sheets

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    service = sheets.get_service()
    clean_headers, clean_rows, orig_headers, orig_rows = _load_tabs(service)

    print(f"{CLEAN_TAB}: {len(clean_rows)} rows, {len(clean_headers)} columns")
    print(f"{ORIG_TAB}: {len(orig_rows)} rows, {len(orig_headers)} columns")

    aligned_count, mismatches = check_alignment(clean_rows, orig_rows)
    print(f"aligned rows checked: {aligned_count + len(mismatches)}, "
          f"name mismatches: {len(mismatches)}")
    for c, o in mismatches:
        print(f"  mismatch: clean row {c['_sheet_row']} {c.get('Location Name','')!r} "
              f"vs {ORIG_TAB} row {o['_sheet_row']} {o.get('sheet','')!r}")
    if len(mismatches) > 5:
        print("More than a handful of mismatches. Stopping before the append plan.")
        return 1

    matched_originals = {id(original) for _, original in join_tabs(clean_rows, orig_rows)}
    new_rows = [row for row in orig_rows if id(row) not in matched_originals]
    print(f"new rows in {ORIG_TAB}: {len(new_rows)}")

    duplicates = find_duplicates(new_rows, clean_rows)
    dup_ids = {id(nr) for nr, _, _ in duplicates}
    print(f"likely duplicates flagged: {len(duplicates)}")

    max_num = 0
    for row in clean_rows:
        m = re.match(r"PP-(\d+)$", row.get("Place ID", "").strip())
        if m:
            max_num = max(max_num, int(m.group(1)))

    clean_columns = ["Location Name" if i == 0 else h for i, h in enumerate(clean_headers)]
    clean_columns.remove("Place ID")
    fieldnames = ["Place ID"] + clean_columns

    append_rows, duplicate_rows = [], []
    next_num = max_num + 1
    for nr in new_rows:
        if id(nr) in dup_ids:
            continue
        mapped = map_row(nr)
        mapped["Place ID"] = f"PP-{next_num:06d}"
        next_num += 1
        append_rows.append(mapped)
    for nr, cr, reason in duplicates:
        duplicate_rows.append({
            "ALL LONDON row": nr["_sheet_row"], "ALL LONDON name": nr.get("sheet", ""),
            "Clean row": cr.get("_sheet_row", ""), "Clean Place ID": cr.get("Place ID", ""),
            "Clean name": cr.get("Location Name", ""), "Reason": reason,
        })

    out_dir = reserve_output(args.out) if args.out else new_run_dir("sync")
    with open(out_dir / "append_plan.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in append_rows:
            w.writerow({c: row.get(c, "") for c in fieldnames})
    with open(out_dir / "duplicates.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ALL LONDON row", "ALL LONDON name", "Clean row",
                                           "Clean Place ID", "Clean name", "Reason"])
        w.writeheader()
        w.writerows(duplicate_rows)

    print(f"append plan: {len(append_rows)} rows, Place ID {append_rows[0]['Place ID']} to "
          f"{append_rows[-1]['Place ID']}" if append_rows else "append plan: 0 rows")
    print(f"wrote {out_dir}/append_plan.csv and {out_dir}/duplicates.csv")
    print("No writes were made to the sheet.")
    return 0


# ---------------------------------------------------------------- applying the plan

# Of FORMULA_COLUMNS, only these two get filled down for a new row;
# "Total incl. Ferro Fee (£)" is also one of Brandon's four and stays
# empty along with the other three.
FORMULAS_TO_FILL_DOWN = ("Postcode Area", "Confidence (1-5)")

CELL_REF_RE = re.compile(r"([A-Z]{1,3})(\d+)")


def shift_formula_row(formula, old_row, new_row):
    """Copy a formula down from old_row to new_row: every cell reference
    at old_row becomes the same column at new_row; a reference to any
    other row (there are none in Postcode Area or Confidence (1-5), but
    this stays correct if that ever changes) is left alone."""
    def replace(match):
        col, row = match.group(1), int(match.group(2))
        return f"{col}{new_row}" if row == old_row else match.group(0)
    return CELL_REF_RE.sub(replace, formula)


def load_append_plan(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def row_values(plan_row, headers):
    """One row's values in sheet column order. Brandon's four columns and
    the two filled-down formula columns are left blank here; the caller
    writes the formulas into the latter two separately, with
    valueInputOption USER_ENTERED, not as plain values."""
    skip = set(BRANDON_COLUMNS) | set(FORMULAS_TO_FILL_DOWN)
    return [("" if h in skip else plan_row.get(h, "")) for h in headers]


def apply_append(service, headers, clean_rows, append_plan_rows, formula_row_num,
                  spreadsheet_id=None, tab=None):
    """Appends append_plan_rows right after the sheet's current last row,
    writes the main values in one range update, then fills down the
    Postcode Area and Confidence (1-5) formulas by copying the pattern
    read from formula_row_num. Returns the (first, last) new sheet row
    numbers. Caller is responsible for every safety check beforehand
    (idempotency, row count, duplicate exclusion) and for verifying the
    result afterward."""
    from . import sheets
    spreadsheet_id = spreadsheet_id or sheets.SPREADSHEET_ID
    tab = tab or CLEAN_TAB

    first_row = clean_rows[-1]["_sheet_row"] + 1
    last_row = first_row + len(append_plan_rows) - 1
    last_col = sheets.col_letter(len(headers) - 1)

    values = [row_values(row, headers) for row in append_plan_rows]
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id, range=f"{tab}!A{first_row}:{last_col}{last_row}",
        valueInputOption="RAW", body={"values": values}).execute()

    for formula_col in FORMULAS_TO_FILL_DOWN:
        col_letter = sheets.col_letter(headers.index(formula_col))
        template = sheets.read_formula(service, formula_row_num, formula_col, headers,
                                        spreadsheet_id, tab)
        formulas = [[shift_formula_row(template, formula_row_num, r)]
                    for r in range(first_row, last_row + 1)]
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=f"{tab}!{col_letter}{first_row}:{col_letter}{last_row}",
            valueInputOption="USER_ENTERED", body={"values": formulas}).execute()

    return first_row, last_row


def verify_append(service, headers, append_plan_rows, pre_write_rows, first_row, last_row):
    """Re-reads the tab and checks: the new rows now hold exactly what
    the plan said, and every row that existed before is unchanged.
    Returns a list of mismatch descriptions (empty means clean)."""
    from . import sheets
    _, post_rows = sheets.read_tab(service)
    mismatches = []

    post_by_row = {r["_sheet_row"]: r for r in post_rows}
    for plan_row, sheet_row_num in zip(append_plan_rows, range(first_row, last_row + 1)):
        live = post_by_row.get(sheet_row_num)
        if live is None:
            mismatches.append(f"row {sheet_row_num}: missing after write")
            continue
        for col in headers:
            if col in BRANDON_COLUMNS or col in FORMULAS_TO_FILL_DOWN:
                continue
            if str(live.get(col, "")) != str(plan_row.get(col, "")):
                mismatches.append(f"row {sheet_row_num} {col!r}: wanted "
                                   f"{plan_row.get(col, '')!r}, got {live.get(col, '')!r}")

    for old_row in pre_write_rows:
        sheet_row_num = old_row["_sheet_row"]
        live = post_by_row.get(sheet_row_num)
        if live is None:
            mismatches.append(f"row {sheet_row_num}: an existing row went missing")
            continue
        for col, old_value in old_row.items():
            if col == "_sheet_row":
                continue
            if str(live.get(col, "")) != str(old_value):
                mismatches.append(f"existing row {sheet_row_num} {col!r} changed: "
                                   f"was {old_value!r}, now {live.get(col, '')!r}")
    return mismatches


def compare_updates(headers, before_rows, after_headers, after_rows, plan):
    """Independent full-export update comparison, including unchanged formulas.

    Caller exports with FORMULA rendering so calculated confidence changes do
    not disguise formula edits or create false mismatches on derived values.
    """
    from . import sheets
    mismatches = []
    if headers != after_headers:
        mismatches.append("Headers changed")
    before_ids = [r.get("Place ID", "") for r in before_rows]
    after_ids = [r.get("Place ID", "") for r in after_rows]
    if before_ids != after_ids or len(set(before_ids)) != len(before_ids):
        mismatches.append("Place IDs duplicated, added, removed or reordered")
    after = {r.get("Place ID", ""): r for r in after_rows}
    changes = {e["place_id"]: e["new"] for e in plan}
    for row in before_rows:
        pid = row.get("Place ID", "")
        live = after.get(pid, {})
        for column in headers:
            expected = changes.get(pid, {}).get(column, row.get(column, ""))
            if column in changes.get(pid, {}):
                expected = sheets._cell_value(column, expected)
            if str(expected) != str(live.get(column, "")):
                mismatches.append(f"{pid}: {column} differs")
    return mismatches


def apply_main(argv=None):
    import argparse
    from . import sheets

    ap = argparse.ArgumentParser()
    ap.add_argument("--append-plan", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    append_plan_rows = load_append_plan(args.append_plan)
    print(f"Append plan: {len(append_plan_rows)} rows "
          f"({append_plan_rows[0]['Place ID']} to {append_plan_rows[-1]['Place ID']}).")

    service = sheets.get_service()
    headers, clean_rows = sheets.read_tab(service)
    last_row = clean_rows[-1]["_sheet_row"]
    expected_first_new_row = last_row + 1

    existing_ids = {r.get("Place ID", "") for r in clean_rows}
    already_done = [r["Place ID"] for r in append_plan_rows if r["Place ID"] in existing_ids]
    if already_done:
        print(f"Already applied: {len(already_done)} of these Place IDs are in the sheet "
              f"already (e.g. {already_done[0]}). Stopping, nothing written.")
        return 1

    if not args.apply:
        print(f"Would append rows {expected_first_new_row} to "
              f"{expected_first_new_row + len(append_plan_rows) - 1}.")
        print("Dry run only. Rerun with --apply to write.")
        return 0

    first_row, written_last_row = apply_append(service, headers, clean_rows, append_plan_rows,
                                                formula_row_num=last_row)
    print(f"Wrote rows {first_row} to {written_last_row}.")

    mismatches = verify_append(service, headers, append_plan_rows, clean_rows, first_row,
                                written_last_row)
    if mismatches:
        print(f"STOP: {len(mismatches)} mismatch(es) found on independent verification:")
        for m in mismatches[:20]:
            print(f"  {m}")
        return 1

    print(f"Verified: {written_last_row - 1} data rows now in {CLEAN_TAB}, every appended "
          "cell matches the plan, no existing row changed.")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
