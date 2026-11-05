"""Ferro PP: capture fill (rule R8). Fills a route A/B row from text PP
already captured from an official page, instead of fetching that page
again, when the sheet already holds enough of it.

The model reads each eligible row's captured text and produces one
structured record (see `FIELDS` below), with a scope ("site" / "chain" /
"none") and the exact quote behind every value. This module is the code
half: it decides which rows are even candidates, validates every record
against the dropdowns, the tariff templates, rules R4 and R7, and the
validator prompt's consistency checks, and turns a valid record into the
same plan.json / undo.json / dry_run.csv shape fill.py and page_fill.py use.

See docs/PP_Validator_prompt_v2_OSM.md (Part 2) and docs/PP_rules_and_pilot.md
(R1-R8) for the rules this module exists to apply.
"""
import argparse
import csv
import json
import re
from datetime import date
from pathlib import Path

from . import fill, page_fill, sheets
from . import rules as rules_mod

VERIFIED_BY = "Claude (capture check)"
CAPTURED_DATE_NOTE = "(as captured 30-31 Oct 2026, not re-fetched)"

CAPTURE_COLS = ["Type (as captured)", "Max Stay (as captured)", "Hours (as captured)",
                "Geo (as captured)", "Charges (as published)", "Enforcement Details", "Notes"]

STATUS_WORDS = ["UNCLEAR", "NOT PUBLISHED", "NOT STATED", "VERIFY", "TBC"]

# R9: Can Park? = No needs an explicit negative statement, not silence or
# capture shorthand ("N/A on site", "no parking facility listed").
NO_PARKING_PHRASES = rules_mod.load_rules().r9_explicit_no_parking_phrases

FIELDS = ["can_park", "who_can_park", "cost_type", "tariff_type", "tariff_detail",
          "max_stay_mins", "hours_osm_format", "hours_basis", "control_type",
          "operator", "pcn_gbp"]

FIELD_TO_COLUMN = {
    "can_park": fill.CAN_PARK,
    "who_can_park": fill.WHO_CAN_PARK,
    "cost_type": "Cost Type",
    "tariff_type": "Tariff Type",
    "tariff_detail": "Tariff Detail",
    "max_stay_mins": "Max Stay (mins)",
    "hours_osm_format": "Hours (OpenStreetMap opening_hours format)",
    "hours_basis": "Hours Basis",
    "control_type": "Parking Control Type (Cameras / Barrier / Patrol)",
    "operator": "Operator",
    "pcn_gbp": "PCN (Penalty Charge Notice) amount (£)",
}

ALLOWED_VALUES = {
    "can_park": {"Yes", "No", "Conditional", "Unknown"},
    "who_can_park": {"Anyone", "Anyone (paid)", "Customers only", "Guests only",
                      "Patients and visitors", "Permit holders", "Not applicable", "Unknown"},
    "cost_type": {"Free", "Free then paid", "Paid", "Not applicable", "Unknown"},
    "tariff_type": {"Free (time limit not published)", "Free with time limit",
                     "Free period, then hourly", "Hourly rate", "Flat rate per 24 hours",
                     "Flat rate per night", "Banded by stay length", "Not published",
                     "Not applicable"},
    "control_type": {"ANPR (Automatic Number Plate Recognition) camera", "Pay and display",
                      "Barrier", "Patrol", "Not published", "Not applicable"},
    "hours_basis": {"Car park hours", "Store hours", "Site hours", "Not published",
                     "Not applicable"},
}

# R7: a wrong Free or Anyone costs the driver money or a fine, so these need
# scope "site" (text about this exact location), never "chain" or "none".
RISKY_VALUES = {
    "cost_type": {"Free"},
    "who_can_park": {"Anyone", "Anyone (paid)"},
}

OPERATOR_SOURCE_HINTS = (
    "tfl.gov.uk", "nationalrail.co.uk", "gov.uk", "q-park", "ncp.co.uk",
    "apcoa", "eurocarparks", "horizonparking", "excelparking", "ringgo",
    "paybyphone", "council",
)


# ---------------------------------------------------------------- eligibility

def is_status_only(text):
    """True if `text` holds nothing but status words and punctuation."""
    remaining = (text or "").strip()
    if not remaining:
        return True
    for word in STATUS_WORDS:
        remaining = re.sub(re.escape(word), "", remaining, flags=re.I)
    remaining = re.sub(r"[\s;:,.\-()]", "", remaining)
    return len(remaining) == 0


def has_real_captured_text(sheet_row):
    return any(not is_status_only(sheet_row.get(col, "")) for col in CAPTURE_COLS)


def candidate_rows(sheet_rows, osm_rows, borough):
    """Route A/B rows for one borough with real captured text to work from."""
    out = []
    for sheet_row, osm_row in page_fill.candidate_rows_ab(sheet_rows, osm_rows, borough):
        if has_real_captured_text(sheet_row):
            out.append((sheet_row, osm_row))
    return out


# ---------------------------------------------------------------- record validation

def check_tariff_template(tariff_type, detail):
    templates = {
        "Free (time limit not published)": lambda d: d == "Free",
        "Free with time limit": lambda d: bool(re.match(r"^Free for (up to )?\d+\s*(min|mins|hour|hours|hr|hrs)", d, re.I)),
        "Free period, then hourly": lambda d: "then" in d.lower() and "£" in d,
        "Hourly rate": lambda d: bool(re.match(r"^£\d+(\.\d{2})? per hour$", d)),
        "Flat rate per 24 hours": lambda d: bool(re.match(r"^£\d+(\.\d{2})? per (24 hours|day)", d, re.I)),
        "Flat rate per night": lambda d: bool(re.match(r"^£\d+(\.\d{2})? per night$", d)),
        "Banded by stay length": lambda d: ";" in d and "£" in d,
        "Not published": lambda d: d == "Not published",
        "Not applicable": lambda d: d == "Not applicable",
    }
    check = templates.get(tariff_type)
    if check is None:
        return [f"tariff_type {tariff_type!r} is not an allowed value"]
    if not check(detail):
        return [f"tariff_detail {detail!r} does not match the template for tariff_type {tariff_type!r}"]
    return []


def validate_record(record):
    """Field-level checks on the model's record alone: dropdown values,
    scope values, rule R7 (Free/Anyone/max stay need scope "site"), and the
    tariff template. Returns a list of violated check descriptions."""
    violations = []
    fields = record.get("fields", {})
    for name in FIELDS:
        if name not in fields:
            violations.append(f"missing field {name!r}")
            continue
        entry = fields[name]
        value, scope = entry.get("value"), entry.get("scope")
        if scope not in ("site", "chain", "none"):
            violations.append(f"{name}: invalid scope {scope!r}")
        if name in ALLOWED_VALUES and value not in ALLOWED_VALUES[name]:
            violations.append(f"{name}: {value!r} is not an allowed value")
        if name in RISKY_VALUES and value in RISKY_VALUES[name] and scope != "site":
            violations.append(f"{name}: {value!r} needs scope 'site' under rule R7, got {scope!r}")

    max_stay = fields.get("max_stay_mins", {})
    if re.match(r"^\d+$", str(max_stay.get("value", ""))) and max_stay.get("scope") != "site":
        violations.append("max_stay_mins: a numeric max stay needs scope 'site' under rules R4 and R7")

    tariff_type = fields.get("tariff_type", {}).get("value")
    tariff_detail = fields.get("tariff_detail", {}).get("value", "")
    if tariff_type is not None:
        violations.extend(check_tariff_template(tariff_type, tariff_detail))

    can_park = fields.get("can_park", {})
    if can_park.get("value") == "No":
        quote = (can_park.get("quote") or "").lower()
        # Word-boundary match: "no car park" must not match inside "no car
        # parking listed", which is capture shorthand, not an explicit denial.
        has_explicit_phrase = any(re.search(r"\b" + re.escape(phrase) + r"\b", quote)
                                   for phrase in NO_PARKING_PHRASES)
        if can_park.get("scope") != "site" or not has_explicit_phrase:
            violations.append("R9: silence is not No")

    return violations


# ---------------------------------------------------------------- building the plan

def source_tier_for(sheet_row, osm_row):
    url = (sheet_row.get("Source URLs (primary first)", "") or "").lower() + " " + \
          (osm_row.get("OSM Website", "") or "").lower()
    if any(hint in url for hint in OPERATOR_SOURCE_HINTS):
        return "Operator / council site"
    return "Official site - text"


def evidence_type_for(record):
    fields = record["fields"]
    known = lambda f: fields[f]["value"] not in ("Not published", "Unknown", "")
    if known("who_can_park") and known("cost_type"):
        return "Official site: clear answer"
    return "Official site: partial info"


def evidence_detail_for(record):
    quotes = []
    for name in FIELDS:
        quote = record["fields"][name].get("quote", "")
        if quote and quote not in quotes:
            quotes.append(quote)
    body = ". ".join(quotes) if quotes else "No quoted text"
    return f"{body} {CAPTURED_DATE_NOTE}"


def specificity_for(record):
    scopes = {record["fields"][name]["scope"] for name in FIELDS}
    if "site" in scopes:
        return "Site-specific"
    if "chain" in scopes:
        return "Chain-wide"
    return "Site-specific"


def decision_reason(record, source_tier):
    route = "Route A" if source_tier == "Operator / council site" else "Route B"
    return (f"{route}: capture fill (rule R8) from text already captured from the official "
            f"page. {evidence_detail_for(record)}")


def rules_summary(new):
    subject = {"Customers only": "Customer car park", "Guests only": "Guest car park",
               "Anyone": "Car park", "Anyone (paid)": "Car park"}.get(new.get(fill.WHO_CAN_PARK), "Car park")
    cost_phrase = {"Free": "free", "Paid": "paid, price not published",
                   "Unknown": "cost unknown"}.get(new.get("Cost Type"), str(new.get("Cost Type", "")).lower())
    return f"{subject}, {cost_phrase}. Source: text already captured from the official page."


def price_status_for(record):
    """R8: chain-wide captured text gives Price Status "Chain policy", never
    "Published", even when a price is quoted. "Published" also needs an
    actual price in tariff_detail: knowing a car park is paid is not the
    same as knowing what it charges (the Q-Park "prebook only" rows)."""
    cost_entry = record["fields"]["cost_type"]
    if cost_entry["value"] == "Not applicable":
        return "Not applicable"
    if cost_entry["scope"] == "chain":
        return "Chain policy (not store-specific)"
    tariff_detail = record["fields"]["tariff_detail"]["value"]
    if tariff_detail not in ("Not published", "Not applicable", ""):
        return "Published"
    return "Not published"


def decide_verification_result(new, source_tier):
    known = lambda v: v not in ("Not published", "Unknown", "", None)
    all_known = (known(new.get("Max Stay (mins)")) and
                 known(new.get("Hours (OpenStreetMap opening_hours format)")) and
                 known(new.get(fill.WHO_CAN_PARK)))
    if all_known and source_tier in page_fill.STRONG_SOURCE_TIERS:
        return "Confirmed"
    return "Confirmed, details not published"


def record_to_new(sheet_row, osm_row, record, today, captured_can_park):
    """Turn a validated record into the sheet's new-value dict, matching
    fill.py's and page_fill.py's conventions (Notes/Review Flag appended,
    protected columns never touched, Verification Result written last)."""
    extracted = {FIELD_TO_COLUMN[name]: record["fields"][name]["value"] for name in FIELDS}

    source_tier = source_tier_for(sheet_row, osm_row)
    extracted["Source Tier"] = source_tier
    extracted["Price Status"] = price_status_for(record)
    extracted["Specificity"] = specificity_for(record)
    extracted["Evidence Type"] = evidence_type_for(record)
    extracted["Evidence Detail (what the source shows)"] = evidence_detail_for(record)
    extracted["Evidence Age"] = "Under 12 months"
    extracted["Agreeing Sources"] = 0
    extracted["Conflict"] = "No"
    extracted["Rules Stated"] = "Yes" if any(
        record["fields"][f]["value"] not in ("Not published", "Not applicable", "Unknown")
        for f in ("who_can_park", "max_stay_mins", "hours_osm_format")) else "No"
    extracted["Prices Stated"] = "Yes" if extracted["Cost Type"] == "Free" else "No"
    extracted["Decision Reason"] = decision_reason(record, source_tier)
    extracted["Verification Result"] = decide_verification_result(extracted, source_tier)

    if record.get("notes_append"):
        extracted["_notes"] = list(record["notes_append"])

    autopay_price_text = record["fields"]["tariff_detail"]["value"]
    flag = page_fill.autopay_price_flag(sheet_row, autopay_price_text)
    if flag:
        extracted["_flags"] = [flag]

    extracted["Rules Summary"] = rules_summary(extracted)

    new = page_fill.build_row_values(sheet_row, extracted, today, captured_can_park,
                                      verified_by=VERIFIED_BY)
    return new


def finish_record(sheet_row, osm_row, record, today, captured_can_park):
    """Validate a model record and, if valid, return (new, None). If not,
    return (None, violations)."""
    violations = validate_record(record)
    if violations:
        return None, violations
    new = record_to_new(sheet_row, osm_row, record, today, captured_can_park)
    shared_violations = page_fill.consistency_checks(new)
    if shared_violations:
        return None, shared_violations
    return new, None


# ---------------------------------------------------------------- command

DRY_RUN_COLS = ["Sheet Row", "Place ID", "Location Name", "Column", "Current value", "New value"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--borough", required=True)
    ap.add_argument("--osm-results", default=None)
    ap.add_argument("--extracted", default=None)
    args = ap.parse_args(argv)

    today = date.today()
    osm_path = args.osm_results or fill.latest_osm_results()
    with open(osm_path, newline="", encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    from . import sync as sync_mod

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    candidates = candidate_rows(sheet_rows, osm_rows, args.borough)
    by_place_id = {sr[fill.PLACE_ID]: (sr, osm_row) for sr, osm_row in candidates}
    captured_can_park = sync_mod.load_captured_can_park(service)

    out_dir = Path("data/runs") / today.isoformat() / "capture" / args.borough
    extracted_path = Path(args.extracted) if args.extracted else out_dir / "extracted.jsonl"

    if not extracted_path.exists():
        from . import capture_extract
        out_dir.mkdir(parents=True, exist_ok=True)
        records = capture_extract.write_extracted(candidates, extracted_path)
        n_grok = sum(1 for r in records if r["leave_for_grok"])
        print(f"{len(candidates)} eligible rows for {args.borough}.")
        print(f"No extracted file at {extracted_path}: generated it with capture_extract.")
        print(f"Classified as leave_for_grok: {n_grok}")
        print(f"Classified as fillable: {len(records) - n_grok}")

    records = [json.loads(line) for line in extracted_path.read_text().splitlines() if line.strip()]
    records_by_place_id = {r["place_id"]: r for r in records}

    unaccounted = sorted(set(by_place_id) - set(records_by_place_id))
    if unaccounted:
        print(f"Warning: {len(unaccounted)} eligible rows have no record in {extracted_path}: "
              f"{unaccounted[:10]}")

    plan, undo, dry_run_rows, left_for_grok = [], [], [], []
    for place_id, record in records_by_place_id.items():
        if place_id not in by_place_id:
            continue
        sheet_row, osm_row = by_place_id[place_id]
        if record.get("leave_for_grok"):
            left_for_grok.append((place_id, record.get("reason", "")))
            continue
        new, violations = finish_record(sheet_row, osm_row, record, today, captured_can_park)
        if new is None:
            left_for_grok.append((place_id, "; ".join(violations)))
            continue
        old = {col: sheet_row.get(col, "") for col in new}
        sheet_row_num = sheet_row["_sheet_row"]
        name = sheet_row.get(fill.LOCATION_NAME, "")
        plan.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name, "new": new})
        undo.append({"sheet_row": sheet_row_num, "place_id": place_id, "old": old})
        for col, value in new.items():
            dry_run_rows.append({"Sheet Row": sheet_row_num, "Place ID": place_id,
                                  "Location Name": name, "Column": col,
                                  "Current value": old[col], "New value": value})

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo, indent=1))
    fill.write_csv(out_dir / "dry_run.csv", DRY_RUN_COLS, dry_run_rows)
    with open(out_dir / "left_for_grok.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Place ID", "Reason"])
        for pid, reason in left_for_grok:
            w.writerow([pid, reason])

    print(f"Borough: {args.borough}")
    print(f"Eligible rows: {len(candidates)}")
    print(f"Records valid and in the plan: {len(plan)}")
    print(f"Left for Grok: {len(left_for_grok)}")
    print(f"\nOutputs in {out_dir}/")
    return 0


if __name__ == "__main__":
    main()
