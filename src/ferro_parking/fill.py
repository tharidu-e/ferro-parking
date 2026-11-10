"""Ferro PP: Stage 2-3 fill (dry run) and the write/undo commands.

python -m ferro_parking fill --borough NAME
    Dry run only. Never writes to the sheet. Reads the newest
    data/runs/*/osm_results.csv and the live sheet, picks eligible route C
    rows for the named borough, and writes plan.json, undo.json,
    dry_run.csv and review.csv to data/runs/<today>/<borough>/.

python -m ferro_parking write PLAN.json [--apply]
python -m ferro_parking undo UNDO.json [--apply]
    Without --apply, print what would change. With --apply, write to the
    sheet: re-read the target cells first and abort if anything has moved
    since the plan/undo file was written, write, then read back and report
    any mismatch.
"""

import argparse
import csv
import glob
import json
import random
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

from .settings import setting
from .run_paths import new_run_dir, reserve_output
from . import rules as rules_mod
from . import sheets
from . import sync as sync_mod
from .osm_match import parse_maxstay

# ---------------------------------------------------------------- columns

CAN_PARK = "Can Park? (Yes/No/Conditional)"
WHO_CAN_PARK = "Who Can Park"
LOCATION_NAME = "Location Name"
BOROUGH = "Borough"
FERRO_AUTOPAY = "Ferro Autopay"
VERIFIED_BY = "Verified By"
VERIFIED_DATE = "Verified Date"
VERIFICATION_RESULT = "Verification Result"
CHANGE_MADE = "Change Made (Yes/No)"
NOTES = "Notes"
REVIEW_FLAG = "Review Flag"
FLAG_STATUS = "Flag Status"
GEO_PRECISION = "Geo Precision"
SOURCE_URLS = "Source URLs (primary first)"
STREET_ADDRESS = "Street Address"
POSTCODE = "Postcode"
PLACE_ID = "Place ID"

# Columns the fill step never writes: Brandon's four, the location identity,
# formulas, and every "as captured" / published-charges / enforcement column.
PROTECTED_COLUMNS = {
    "Postcode Area", "Confidence (1-5)", "Free Stay Countdown (mins)",
    "Ferro Autopay", "Parking Charge (£)", "Total incl. Ferro Fee (£)",
    "Captured By", "Date Captured", "Latitude", "Longitude", "Place ID",
    "Location Name", "Street Address", "Postcode", "Borough", "Location Status",
    "Geo Source", "Geo Precision", "Charges (as published)", "Enforcement Details",
    "Confidence", "Free Stay Countdown", "Parking Charge", "Total incl. Ferro Fee",
}
PROTECTED_SUFFIXES = ("(as captured)", "Charges (as published)", "Enforcement Details")


def assert_not_protected(new_values):
    for col in new_values:
        if col in PROTECTED_COLUMNS or col.casefold().startswith("geo") or col.endswith(PROTECTED_SUFFIXES):
            raise AssertionError(f"fill.py must never write the protected column {col!r}")


# ---------------------------------------------------------------- eligibility

def edited_within_2_years(osm_row, today):
    date_str = osm_row.get("Car Park Last Edited", "")
    try:
        edited = date.fromisoformat(date_str)
    except ValueError:
        return False
    return (today - edited).days <= 730


def check_eligibility(sheet_row, osm_row, borough, today, captured_can_park):
    """Name -> True (passes) / False (fails), for each of the 8 conditions.
    captured_can_park: {place_id: value}, ALL LONDON's own Can Park? read
    by Place ID (sync.captured_can_park_by_place_id), not the clean tab's
    own column, which a cleared or not-yet-researched row leaves blank."""
    return {
        "Borough matches": sheet_row.get(BOROUGH, "") == borough,
        "Route starts with C": osm_row.get("Route", "").strip().startswith("C"),
        "Car Park Link is adjacent or brand match":
            osm_row.get("Car Park Link", "") in ("Adjacent to place", "Name/operator matches brand"),
        "Car Park Last Edited within 2 years": edited_within_2_years(osm_row, today),
        "Verification Result blank": sheet_row.get(VERIFICATION_RESULT, "") == "",
        "Verified By blank or PP (validation)": sheet_row.get(VERIFIED_BY, "") in ("", "PP (validation)"),
        "Ferro Autopay not checked": sheet_row.get(FERRO_AUTOPAY, "") != "✅",
        "captured Can Park is not No":
            captured_can_park.get(sheet_row.get(PLACE_ID, ""), "") != "No",
    }


def is_eligible(checks):
    return all(checks.values())


# ---------------------------------------------------------------- OSM tags

def parse_tags(raw):
    tags = {}
    for part in (raw or "").split(";"):
        part = part.strip()
        if part and "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip()] = v.strip()
    return tags


def way_id_from_url(url):
    m = re.search(r"openstreetmap\.org/(\w+/\d+)", url or "")
    return m.group(1) if m else (url or "")


# ---------------------------------------------------------------- derivation (R1, R3, R4, R7)

def category_default(sheet_row, rules):
    """R1: a store's car park is for its customers, unless it is a hotel or hospital."""
    category = f"{sheet_row.get('Place Category', '')} {sheet_row.get('Type (as captured)', '')}".lower()
    if "hotel" in category:
        return rules.r1_category_defaults.get("hotel", "Guests only")
    if "hospital" in category:
        return rules.r1_category_defaults.get("hospital", "Patients and visitors")
    return rules.r1_category_defaults.get("store", "Customers only")


def derive_who_can_park(tags, sheet_row, rules, notes):
    acc = tags.get("access", "")
    if acc in ("customers", "destination"):
        return "Customers only"
    if acc in ("private", "permit", "residents", "no"):
        notes.append(f"OSM access={acc}: may not be usable by drivers, check")
        return "Unknown"
    if acc in ("yes", "public", "permissive"):
        notes.append(f"OSM access={acc} (public): needs a strong site-specific "
                      "source to raise above Unknown (rule R7)")
        return "Unknown"
    return category_default(sheet_row, rules)


def derive_cost(tags, notes):
    """Rule R7: an OSM tag alone never sets Cost Type Free, on any access
    value. fill.py never reads the official page or a sign, so it never
    has the site-specific evidence Free needs; fee=no only ever becomes
    a note, never a value a reader could mistake for confirmed."""
    fee = tags.get("fee", "")
    if fee == "yes":
        return {"Cost Type": "Paid", "Price Status": "Not published",
                "Tariff Type": "Not published", "Tariff Detail": "Not published"}
    if fee == "no":
        notes.append("OSM tags this as free, not confirmed (rule R7)")
    return {"Cost Type": "Unknown", "Price Status": "Not published",
            "Tariff Type": "Not published", "Tariff Detail": "Not published"}


def apply_chain_rules(location_name, cost, notes, rules):
    """R6 chain rules as hints only; R7 blocks a chain from setting Free/Anyone
    directly. derive_cost never returns Free itself (rule R7), so there is no
    "chain says Paid, OSM says free" conflict left to flag here any more."""
    chain = rules.chain_for(location_name)
    if not chain:
        return None
    who = chain.get("who_can_park")
    if who in rules.r7_risky_who_can_park:
        notes.append(f'Chain rule says Who Can Park "{who}" (hint only, needs '
                      "site-specific evidence, rule R7)")
    cost_type = chain.get("cost_type")
    if cost_type in rules.r7_risky_cost_types:
        notes.append(f'Chain rule says Cost Type "{cost_type}" (hint only, needs '
                      "site-specific evidence, rule R7)")
    return chain


def derive_operator(tags, rules, chain, notes):
    """R3: an OSM operator tag equal to the store itself is the landowner, not
    the parking company; fall back to the R6 chain's operator if it names one."""
    op = tags.get("operator", "")
    if op and rules.is_own_brand_operator(op):
        notes.append(f'OSM operator "{op}" is the store itself, not the parking company (rule R3)')
        return (chain or {}).get("operator", "Not published")
    return op or "Not published"


def derive_can_park(sheet_row, flags, captured_can_park):
    captured = captured_can_park.get(sheet_row.get(PLACE_ID, ""), "")
    changed = captured != "Conditional"
    if changed:
        flags.append(f"Can Park changed from {captured or 'blank'} to Conditional (OSM)")
    return "Conditional", ("Yes" if changed else "No")


def evidence_age(osm_row, today):
    edited = date.fromisoformat(osm_row["Car Park Last Edited"])
    return "Under 12 months" if (today - edited).days < 365 else "1-2 years"


def evidence_detail(osm_row, tags):
    shown = "; ".join(f"{k}={tags[k]}" for k in ("access", "fee", "maxstay", "operator") if tags.get(k))
    return (f"OSM car park ({way_id_from_url(osm_row.get('OSM Car Park', ''))}, "
            f"edited {osm_row.get('Car Park Last Edited', '')}, "
            f"{osm_row.get('Car Park Distance (m)', '')} m from the store) shows \"{shown}\"")


def build_source_urls(osm_row, sheet_row):
    osm_url = osm_row.get("OSM Car Park", "")
    existing = [u.strip() for u in (sheet_row.get(SOURCE_URLS, "") or "").split(";") if u.strip()]
    return " ; ".join([osm_url] + [u for u in existing if u != osm_url])


def osm_notes_fragment(tags, extra_notes):
    parts = []
    for k in ("capacity", "capacity:disabled", "capacity:parent", "capacity:charging"):
        if tags.get(k):
            parts.append(f"{k}={tags[k]}")
    if tags.get("parking"):
        parts.append(f"parking={tags['parking']}")
    if tags.get("maxstay"):
        # R4: an OSM max stay is never shown on its own, it goes to Notes only
        parsed = parse_maxstay(tags["maxstay"]) or tags["maxstay"]
        suffix = "" if parsed == "No limit" else " mins (not confirmed; rule R4)"
        parts.append(f"OSM says max stay {parsed}{suffix}")
    if tags.get("opening_hours"):
        parts.append(f"OSM hours: {tags['opening_hours']}")
    parts.extend(extra_notes)
    return "; ".join(parts)


def merged_notes(sheet_row, tags, extra_notes):
    fragment = osm_notes_fragment(tags, extra_notes)
    if not fragment:
        return None
    existing = sheet_row.get(NOTES, "") or ""
    return f"{existing}{' | ' if existing else ''}OSM: {fragment}"


def merged_review_flag(sheet_row, new_flags):
    if not new_flags:
        return None
    existing = sheet_row.get(REVIEW_FLAG, "") or ""
    return f"{existing}{'; ' if existing else ''}{'; '.join(new_flags)}"


def rules_summary(who_can_park, cost):
    subject = {"Customers only": "Customer car park", "Guests only": "Guest car park"}.get(
        who_can_park, "Car park")
    cost_phrase = {"Free": "free", "Paid": "paid, price not published",
                   "Unknown": "cost unknown"}.get(cost["Cost Type"], cost["Cost Type"].lower())
    return f"{subject}, {cost_phrase}. Source: OpenStreetMap, not yet confirmed by the store. Check signs on site."


def decision_reason(osm_row, tags, who_can_park, cost):
    shown = "; ".join(f"{k}={tags[k]}" for k in ("access", "fee", "maxstay", "operator") if tags.get(k))
    return (f"Route C: OSM car park ({way_id_from_url(osm_row.get('OSM Car Park', ''))}, "
            f"edited {osm_row.get('Car Park Last Edited', '')}) shows \"{shown}\". "
            f"Rules R1, R3, R4 and R7 applied: Who Can Park {who_can_park}, Cost Type {cost['Cost Type']}. "
            "Draft only: max stay and hours are not published, and OSM is a weak source.")


def derive_values(sheet_row, osm_row, rules, today, captured_can_park):
    """The full set of column -> new value for one eligible row. Only
    includes a column when this run actually changes it."""
    tags = parse_tags(osm_row.get("OSM Raw Tags", ""))
    notes_extra, flags = [], []
    can_park, change_made = derive_can_park(sheet_row, flags, captured_can_park)
    who_can_park = derive_who_can_park(tags, sheet_row, rules, notes_extra)
    cost = derive_cost(tags, notes_extra)
    chain = apply_chain_rules(sheet_row.get(LOCATION_NAME, ""), cost, notes_extra, rules)
    operator = derive_operator(tags, rules, chain, notes_extra)

    new = {
        CAN_PARK: can_park,
        CHANGE_MADE: change_made,
        WHO_CAN_PARK: who_can_park,
        **cost,
        "Max Stay (mins)": "Not published",
        "Hours (OpenStreetMap opening_hours format)": "Not published",
        "Hours Basis": "Not published",
        "Operator": operator,
        "Parking Control Type (Cameras / Barrier / Patrol)": "Not published",
        "PCN (Penalty Charge Notice) amount (£)": "Not published",
        "Evidence Type": "OpenStreetMap only",
        "Evidence Detail (what the source shows)": evidence_detail(osm_row, tags),
        SOURCE_URLS: build_source_urls(osm_row, sheet_row),
        "Source Tier": "OpenStreetMap",
        "Specificity": "Site-specific",
        "Rules Stated": "Yes" if (tags.get("access") or tags.get("maxstay")) else "No",
        "Prices Stated": "Yes" if cost["Cost Type"] == "Free" else "No",
        "Evidence Age": evidence_age(osm_row, today),
        "Agreeing Sources": 0,
        "Conflict": "No",
        "Rules Summary": rules_summary(who_can_park, cost),
        "Decision Reason": decision_reason(osm_row, tags, who_can_park, cost),
        VERIFIED_BY: "OSM script",
        VERIFIED_DATE: today.isoformat(),
    }
    notes = merged_notes(sheet_row, tags, notes_extra)
    if notes is not None:
        new[NOTES] = notes
    review_flag = merged_review_flag(sheet_row, flags)
    if review_flag is not None:
        new[REVIEW_FLAG] = review_flag
        new[FLAG_STATUS] = "Open"
    assert_not_protected(new)
    return new


# ---------------------------------------------------------------- outputs

def google_maps_search_url(sheet_row):
    query = " ".join(x for x in (sheet_row.get(LOCATION_NAME, ""), sheet_row.get(STREET_ADDRESS, ""),
                                  sheet_row.get(POSTCODE, "")) if x)
    return f"https://www.google.com/maps/search/?api=1&query={quote(query)}"


def satellite_url(osm_row):
    lat, lon = osm_row.get("Suggested Lat"), osm_row.get("Suggested Lon")
    if not (lat and lon):
        return ""
    return f"https://www.google.com/maps/@?api=1&map_action=map&center={lat},{lon}&zoom=19&basemap=satellite"


def sheet_row_link(sheet_row_num):
    return (f"https://docs.google.com/spreadsheets/d/{sheets.SPREADSHEET_ID}/edit"
            f"#gid={setting('clean_gid')}&range=A{sheet_row_num}")


def review_answer(new):
    bits = [new[CAN_PARK], new[WHO_CAN_PARK], new["Cost Type"]]
    if new["Tariff Detail"] not in ("Not published", "Free"):
        bits.append(new["Tariff Detail"])
    if new["Operator"] != "Not published":
        bits.append(f"operator {new['Operator']}")
    return ", ".join(bits)


def build_plan_undo_review(eligible, rules, today, captured_can_park):
    """eligible: list of (sheet_row, osm_row). Returns (plan, undo, dry_run_rows, review_rows)."""
    plan, undo, dry_run_rows, review_rows = [], [], [], []
    for sheet_row, osm_row in eligible:
        sheet_row_num = sheet_row["_sheet_row"]
        place_id = sheet_row.get(PLACE_ID, "")
        name = sheet_row.get(LOCATION_NAME, "")
        new = derive_values(sheet_row, osm_row, rules, today, captured_can_park)
        old = {col: sheet_row.get(col, "") for col in new}
        plan.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name, "new": new})
        undo.append({"sheet_row": sheet_row_num, "place_id": place_id, "old": old})
        for col, value in new.items():
            dry_run_rows.append({"Sheet Row": sheet_row_num, "Place ID": place_id,
                                  "Location Name": name, "Column": col,
                                  "Current value": old[col], "New value": value})
        review_rows.append({
            "Check first": "", "Sheet Row": sheet_row_num, "Place": name,
            "Postcode": sheet_row.get(POSTCODE, ""),
            "Sheet row link": sheet_row_link(sheet_row_num),
            "Store page": osm_row.get("Official URL (sheet)", ""),
            "OSM car park": osm_row.get("OSM Car Park", ""),
            "Google Maps": google_maps_search_url(sheet_row),
            "Satellite view of car park": satellite_url(osm_row),
            "OSM tags used": osm_row.get("OSM Raw Tags", ""),
            "Answer": review_answer(new),
            "Verdict (correct / wrong / can't tell)": "",
            "Notes": "",
        })
    check_first = set(random.sample(range(len(review_rows)), min(5, len(review_rows))))
    for i in check_first:
        review_rows[i]["Check first"] = "Yes"
    return plan, undo, dry_run_rows, review_rows


# ---------------------------------------------------------------- fill command

def latest_osm_results():
    paths = sorted(glob.glob("data/runs/*/osm_results.csv"))
    if not paths:
        raise SystemExit("No data/runs/*/osm_results.csv found. Run `python -m ferro_parking match` first.")
    return paths[-1]


def write_csv(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--borough", required=True)
    ap.add_argument("--osm-results", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    today = date.today()
    rules = rules_mod.load_rules()
    osm_path = args.osm_results or latest_osm_results()
    with open(osm_path, newline="", encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    by_place_id = {r[PLACE_ID]: r for r in sheet_rows if r.get(PLACE_ID)}
    captured_can_park = sync_mod.load_captured_can_park(service)

    fail_counts = {}
    eligible = []
    for osm_row in osm_rows:
        sheet_row = by_place_id.get(osm_row.get("Place ID", ""))
        if sheet_row is None:
            continue
        checks = check_eligibility(sheet_row, osm_row, args.borough, today, captured_can_park)
        for name, passed in checks.items():
            if not passed:
                fail_counts[name] = fail_counts.get(name, 0) + 1
        if is_eligible(checks):
            eligible.append((sheet_row, osm_row))

    plan, undo, dry_run_rows, review_rows = build_plan_undo_review(eligible, rules, today, captured_can_park)

    out_dir = reserve_output(args.out) if args.out else new_run_dir(args.borough)
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo, indent=1))
    write_csv(out_dir / "dry_run.csv",
              ["Sheet Row", "Place ID", "Location Name", "Column", "Current value", "New value"],
              dry_run_rows)
    write_csv(out_dir / "review.csv",
              ["Check first", "Sheet Row", "Place", "Postcode", "Sheet row link", "Store page",
               "OSM car park", "Google Maps", "Satellite view of car park", "OSM tags used",
               "Answer", "Verdict (correct / wrong / can't tell)", "Notes"],
              review_rows)

    print(f"Borough: {args.borough}")
    print(f"Eligible rows: {len(eligible)}")
    print("Failed conditions (independent counts, a row can fail more than one):")
    for name, count in fail_counts.items():
        print(f"  {name}: {count}")
    print(f"\nOutputs in {out_dir}/")
    return 0


# ---------------------------------------------------------------- write / undo

def _load_json(path):
    return json.loads(Path(path).read_text())


def write_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("plan_path")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--confirm-wipe", action="store_true")
    args = ap.parse_args(argv)

    plan = _load_json(args.plan_path)
    validate_write_columns(plan)
    wipe = any(value == "" for entry in plan for value in entry["new"].values())
    print(f"Rows in plan: {len(plan)}")
    if args.apply and wipe and not args.confirm_wipe:
        raise SystemExit("Clearing cells requires --confirm-wipe in addition to --apply")
    undo_path = Path(args.plan_path).parent / "undo.json"
    undo_by_row = {e["sheet_row"]: e for e in _load_json(undo_path)}

    service = sheets.get_service()
    headers = sheets.get_headers(service)
    return _apply_write(service, headers, plan, undo_by_row, args.apply)


def _apply_write(service, headers, plan, undo_by_row, apply):
    validate_write_columns(plan)
    to_check = [(e["sheet_row"], col) for e in plan for col in e["new"]]
    to_check += [(e["sheet_row"], col) for e in plan for col in (PLACE_ID, VERIFIED_BY, VERIFICATION_RESULT)]
    current = sheets.read_cells(service, to_check, headers)

    aborted = []
    for entry in plan:
        sheet_row, place_id = entry["sheet_row"], entry["place_id"]
        if current.get((sheet_row, PLACE_ID)) != place_id:
            aborted.append((sheet_row, place_id, "Place ID changed; rebuild plan"))
            continue
        if current.get((sheet_row, VERIFICATION_RESULT), "") or current.get((sheet_row, VERIFIED_BY), "") not in ("", "PP (validation)"):
            aborted.append((sheet_row, place_id, "finished or personally verified row"))
            continue
        undo_entry = undo_by_row.get(sheet_row)
        if undo_entry is None or undo_entry["place_id"] != place_id:
            aborted.append((sheet_row, place_id, "no matching undo entry"))
            continue
        for col in entry["new"]:
            live = current.get((sheet_row, col), "")
            expected = undo_entry["old"].get(col, "")
            if str(live) != str(expected):
                aborted.append((sheet_row, place_id, f"{col} changed since the plan was made "
                                                       f"(sheet has {live!r}, expected {expected!r})"))
                break
        else:
            verification = current.get((sheet_row, VERIFICATION_RESULT), "")
            if verification not in ("", undo_entry["old"].get(VERIFICATION_RESULT, "")):
                aborted.append((sheet_row, place_id, "Verification Result is no longer blank"))

    aborted_rows = {a[0] for a in aborted}
    to_write = [e for e in plan if e["sheet_row"] not in aborted_rows]
    cells = [(e["sheet_row"], col, value) for e in to_write for col, value in e["new"].items()]

    if not apply:
        print(f"Would write {len(cells)} cells across {len(to_write)} rows.")
        for sheet_row, place_id, reason in aborted:
            print(f"Would abort row {sheet_row} ({place_id}): {reason}")
        return 0

    for sheet_row, place_id, reason in aborted:
        print(f"Aborted row {sheet_row} ({place_id}): {reason}")
    if cells:
        sheets.write_cells(service, headers, cells)
    readback = sheets.read_cells(service, [(r, c) for r, c, _ in cells], headers)
    mismatches = [(r, c, v, readback.get((r, c)))
                  for r, c, v in cells if str(readback.get((r, c))) != str(v)]
    print(f"Wrote {len(cells)} cells across {len(to_write)} rows, {len(aborted)} aborted.")
    for r, c, wanted, got in mismatches:
        print(f"Mismatch row {r} column {c!r}: wrote {wanted!r}, read back {got!r}")
    return 1 if mismatches else 0


def undo_main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("undo_path")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    undo_entries = _load_json(args.undo_path)
    service = sheets.get_service()
    headers = sheets.get_headers(service)
    return _apply_undo(service, headers, undo_entries, args.apply)


def _apply_undo(service, headers, undo_entries, apply):
    place_ids = sheets.read_cells(
        service, [(e["sheet_row"], PLACE_ID) for e in undo_entries], headers)
    aborted, to_restore = [], []
    for entry in undo_entries:
        live_id = place_ids.get((entry["sheet_row"], PLACE_ID), "")
        if live_id != entry["place_id"]:
            aborted.append((entry["sheet_row"], entry["place_id"],
                            f"Place ID at that row is now {live_id!r}"))
            continue
        to_restore.append(entry)

    cells = [(e["sheet_row"], col, value) for e in to_restore for col, value in e["old"].items()]
    if not apply:
        print(f"Would restore {len(cells)} cells across {len(to_restore)} rows.")
        for sheet_row, place_id, reason in aborted:
            print(f"Would abort row {sheet_row} ({place_id}): {reason}")
        return 0

    for sheet_row, place_id, reason in aborted:
        print(f"Aborted row {sheet_row} ({place_id}): {reason}")
    if cells:
        sheets.write_cells(service, headers, cells)
    readback = sheets.read_cells(service, [(r, c) for r, c, _ in cells], headers)
    mismatches = [(r, c, v, readback.get((r, c)))
                  for r, c, v in cells if str(readback.get((r, c))) != str(v)]
    print(f"Restored {len(cells)} cells across {len(to_restore)} rows, {len(aborted)} aborted.")
    for r, c, wanted, got in mismatches:
        print(f"Mismatch row {r} column {c!r}: wrote {wanted!r}, read back {got!r}")
    return 1 if mismatches else 0

# Explicit research schema. Unknown future headers are denied by default.
RESEARCH_COLUMNS = {
    CAN_PARK, WHO_CAN_PARK, CHANGE_MADE, NOTES, REVIEW_FLAG, FLAG_STATUS,
    SOURCE_URLS, VERIFIED_BY, VERIFIED_DATE, VERIFICATION_RESULT,
    'Brand', 'Place Category', 'Area Type', 'Cost Type', 'Price Status',
    'Tariff Type', 'Tariff Detail', 'Max Stay (mins)',
    'Hours (OpenStreetMap opening_hours format)', 'Hours Basis', 'Operator',
    'Parking Control Type (Cameras / Barrier / Patrol)',
    'PCN (Penalty Charge Notice) amount (£)', 'Evidence Type',
    'Evidence Detail (what the source shows)', 'Source Tier', 'Specificity',
    'Rules Stated', 'Prices Stated', 'Evidence Age', 'Agreeing Sources',
    'Conflict', 'Rules Summary', 'Decision Reason', 'Evidence Level',
}


def validate_write_columns(plan):
    for entry in plan:
        assert_not_protected(entry['new'])
        unknown = set(entry['new']) - RESEARCH_COLUMNS
        if unknown:
            raise ValueError(f'Plan contains columns outside research allowlist: {sorted(unknown)}')


if __name__ == "__main__":
    main()
