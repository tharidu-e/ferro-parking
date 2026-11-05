"""Ferro PP: Stage 2b, routes A and B (official page read as text).

Unlike fill.py (route C, values derived from OSM tags), a route A/B row's
values come from reading one web page and making a judgment call, so this
module only holds what is mechanical: which rows are eligible, which URL to
read, how to assemble the final column values from what was read, and the
validator prompt's consistency checks run on the result before it is kept.

See docs/PP_Validator_prompt_v2_OSM.md (Part 2) and docs/PP_rules_and_pilot.md
(R1-R7) for the rules this module exists to apply.
"""
import re

from . import fill

PLACE_ID = fill.PLACE_ID
CAN_PARK = fill.CAN_PARK
WHO_CAN_PARK = fill.WHO_CAN_PARK
NOTES = fill.NOTES
REVIEW_FLAG = fill.REVIEW_FLAG
FLAG_STATUS = fill.FLAG_STATUS
VERIFIED_BY = "Claude (page check)"

STRONG_SOURCE_TIERS = {
    "Official site - text", "Operator / council site",
    "Official site - logo or icon", "Google Maps - tariff photo",
}


def candidate_rows_ab(sheet_rows, osm_rows, borough):
    """Route A/B rows for one borough, eligible the same way the validator
    prompt's order of work defines "unfinished": blank Verification Result,
    and Verified By blank or "PP (validation)" (not someone else's hand check)."""
    by_place_id = {r[PLACE_ID]: r for r in sheet_rows if r.get(PLACE_ID)}
    out = []
    for osm_row in osm_rows:
        sheet_row = by_place_id.get(osm_row.get("Place ID", ""))
        if sheet_row is None:
            continue
        if sheet_row.get("Borough", "") != borough:
            continue
        if osm_row.get("Route", "").strip()[:1] not in ("A", "B"):
            continue
        if sheet_row.get("Verification Result", "") != "":
            continue
        if sheet_row.get("Verified By", "") not in ("", "PP (validation)"):
            continue
        out.append((sheet_row, osm_row))
    return out


def page_url(sheet_row, osm_row):
    """The page to read: the first URL in Source URLs, else OSM Website."""
    for part in (sheet_row.get("Source URLs (primary first)", "") or "").split(";"):
        part = part.strip()
        if part.startswith("http"):
            return part
    return osm_row.get("OSM Website", "") or ""


def autopay_price_flag(sheet_row, first_price_text):
    """R: compare the first price found with Parking Charge (£); never edit
    that protected column, just flag a difference. "First price found"
    means exactly that even when the text names several, a banded tariff
    detail included: stripping every non-digit character from the whole
    string instead would run every band's price together into one number."""
    if sheet_row.get("Ferro Autopay", "") != "✅" or not first_price_text:
        return None
    sheet_price = (sheet_row.get("Parking Charge (£)", "") or "").strip()
    if not sheet_price:
        return None
    found_match = re.search(r"£\s?(\d+(?:\.\d+)?)", first_price_text)
    found = found_match.group(1) if found_match else ""
    sheet_num = re.sub(r"[^0-9.]", "", sheet_price)
    if found and sheet_num and found != sheet_num:
        return f"Autopay price differs: sheet £{sheet_num}, source £{found}"
    return None


def build_row_values(sheet_row, extracted, today, captured_can_park, verified_by=VERIFIED_BY):
    """Assemble the full set of column values for one row from what was
    read on the page (`extracted`, a dict of the same column names), plus
    the bookkeeping columns: Change Made, Notes/Review Flag appended (never
    replaced), Verified By/Date. Asserts no protected column is touched.
    captured_can_park: {place_id: value}, ALL LONDON's own Can Park? by
    Place ID (sync.captured_can_park_by_place_id), not the clean tab's
    own column, which a cleared or not-yet-researched row leaves blank."""
    new = dict(extracted)

    captured = captured_can_park.get(sheet_row.get(PLACE_ID, ""), "")
    new[fill.CHANGE_MADE] = "Yes" if extracted.get(CAN_PARK, captured) != captured else "No"

    extra_notes = extracted.pop("_notes", []) if "_notes" in extracted else []
    if "_notes" in new:
        del new["_notes"]
    if extra_notes:
        existing = sheet_row.get(NOTES, "") or ""
        new[NOTES] = f"{existing}{' | ' if existing else ''}{'; '.join(extra_notes)}"
    elif NOTES in new and new[NOTES] == sheet_row.get(NOTES, ""):
        del new[NOTES]

    new_flags = extracted.pop("_flags", []) if "_flags" in extracted else []
    if "_flags" in new:
        del new["_flags"]
    if new_flags:
        existing = sheet_row.get(REVIEW_FLAG, "") or ""
        new[REVIEW_FLAG] = f"{existing}{'; ' if existing else ''}{'; '.join(new_flags)}"
        new[FLAG_STATUS] = "Open"

    new[fill.VERIFIED_BY] = verified_by
    new[fill.VERIFIED_DATE] = today.isoformat()
    if not sheet_row.get(fill.GEO_PRECISION) and "Geo Precision" not in new:
        new["Geo Precision"] = "Building"

    fill.assert_not_protected(new)
    return new


# ---------------------------------------------------------------- consistency checks

NOT_APPLICABLE_IF_NO_PARKING = [
    WHO_CAN_PARK, "Cost Type", "Price Status", "Tariff Type", "Tariff Detail",
    "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)", "Hours Basis",
    "Parking Control Type (Cameras / Barrier / Patrol)", "Operator",
    "PCN (Penalty Charge Notice) amount (£)",
]


def consistency_checks(new):
    """Violated consistency check names from PP_Validator_prompt_v2_OSM.md
    ("Consistency checks before you mark a row finished"), run on the final
    new-value dict before it is kept. Empty list means the row is clean."""
    violations = []

    if new.get(CAN_PARK) == "No":
        for col in NOT_APPLICABLE_IF_NO_PARKING:
            if col in new and new[col] != "Not applicable":
                violations.append(f"Can Park? No but {col} is {new[col]!r}, not Not applicable")

    cost = new.get("Cost Type")
    tariff = new.get("Tariff Type", "")
    if cost == "Free" and not tariff.startswith("Free"):
        violations.append(f"Cost Type Free but Tariff Type is {tariff!r}")
    if cost == "Free then paid" and tariff not in ("Free period, then hourly", "Banded by stay length"):
        violations.append(f"Cost Type Free then paid but Tariff Type is {tariff!r}")

    if new.get("Price Status") == "Published":
        detail = new.get("Tariff Detail", "")
        if "£" not in detail and "free" not in detail.lower():
            violations.append(f"Price Status Published but Tariff Detail is {detail!r}")

    if tariff == "Free with time limit" and not re.match(r"^\d+$", new.get("Max Stay (mins)", "")):
        violations.append("Tariff Type Free with time limit but Max Stay (mins) is not a number")

    if new.get("Source Tier") == "None found":
        for col, want in (("Can Park? (Yes/No/Conditional)", "Unknown"), ("Evidence Type", "No info found"),
                           ("Verification Result", "No evidence")):
            if new.get(col) != want:
                violations.append(f"Source Tier None found but {col} is {new.get(col)!r}, expected {want!r}")

    if new.get("Verification Result") == "No evidence" and new.get("Source Tier") != "None found":
        violations.append("Verification Result No evidence but Source Tier is not None found")

    if new.get(REVIEW_FLAG) and not new.get(FLAG_STATUS):
        violations.append("Review Flag set but Flag Status is blank")

    if new.get(CAN_PARK) == "Yes" and new.get("Source Tier") not in STRONG_SOURCE_TIERS:
        violations.append(f"Can Park? Yes but Source Tier is {new.get('Source Tier')!r}, not a strong source")

    if not new.get("Decision Reason") or "Route" not in new.get("Decision Reason", ""):
        violations.append("Decision Reason missing or does not name the route")

    return violations
