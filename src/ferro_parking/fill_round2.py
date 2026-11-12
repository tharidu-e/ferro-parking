"""
Ferro PP: fill round 2. Dry run only.

Assumes clear_unverified.py has run (or, for this dry run, simulates its
effect in memory): clear_unverified always writes before any fill write,
never after, so this round's coverage baseline reflects that state, not
the live sheet's stale pre-validation guesses.

Fills parking details on every row with a blank Verification Result (the
pre-existing unfinished rows and the tranche 1 rows just appended), in
four passes, in this order:
  1. osm_fill    fill.py's Route C pass (OSM car park tags). A row where
     every parking column comes back Unknown, Not published, or blank
     answers nothing, so it is not kept here: it falls through to a
     later pass, or to not_yet_checked.
  2. capture_fill  capture_fill.py's Route A/B pass (text PP already
     captured on the sheet; capture_extract.py's pattern match, not a
     model read).
  3. policy_fill  policy_fill.py's R10 chain/presumed-no-parking pass.
  4. category_policy  a draft category policy (config/rules.toml
     [category_policies]), for hospital and petrol_station rows the
     first three passes left untouched. The hospital policy only
     applies when an OSM car park is within 150 m or inside the
     hospital's own mapped polygon; other hospitals fall through to
     not_yet_checked. Both categories always set Can Park? to
     "Conditional" (the sheet's real third dropdown value), replacing
     any stale guess rather than leaving it.
A row still blank after all four gets Evidence Level = "Not yet checked"
only; no parking column is touched for it.

Every pass 1-4's planned new-value dict is run through page_fill's
consistency checks ("the second reading") before being kept. fill.py's
own pass has never had this check run on it before; a row that fails
is held out of the plan and reported as a second-reading failure,
the same fallback capture_fill.py and policy_fill.py already give their
own failures. The "Not yet checked" pass is exempt: it never marks a
row finished (Verification Result stays blank), so the check's own
premise ("before you mark a row finished") does not apply to it.

READ-ONLY. Dry run only: never writes to the sheet.

python -m ferro_parking fill-round2
Options:
  --out DIR   output directory (default: data/runs/<today>/fill_round2)

OSM data (c) OpenStreetMap contributors, ODbL.
"""
import argparse
import csv
import sys
import tomllib
from collections import Counter
from datetime import date
from pathlib import Path

import osmium
from shapely import wkb
from shapely.geometry import Point

from . import capture_extract, capture_fill, clear_unverified, fill, page_fill, policy_fill, sheets
from . import rules as rules_mod
from . import sync as sync_mod
from .discovery import classify_sheet_row, load_categories, row_point_m
from .osm_match import contains_word, norm, to_m

PLACE_ID = fill.PLACE_ID
LOCATION_NAME = fill.LOCATION_NAME
WHO_CAN_PARK = fill.WHO_CAN_PARK
VERIFICATION_RESULT = fill.VERIFICATION_RESULT
EVIDENCE_LEVEL = "Evidence Level"
NOT_YET_CHECKED = "Not yet checked"

# ---------------------------------------------------------------- coverage

PARKING_DETAIL_COLUMNS = [
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type", "Price Status",
    "Tariff Type", "Tariff Detail", "Max Stay (mins)",
    "Hours (OpenStreetMap opening_hours format)", "Hours Basis",
    "Parking Control Type (Cameras / Barrier / Patrol)", "Operator",
    "PCN (Penalty Charge Notice) amount (£)", "Evidence Type", "Source Tier", "Rules Summary",
]
# A column reading one of these has not really been answered, for coverage
# purposes: "Not published" and "Unknown" are a deliberate cautious value
# (rule R7), not an unfilled cell, but they are not an answer either.
NOT_REALLY_FILLED = {"", "Not published", "Unknown"}


def coverage_table(rows):
    """[{"Column", "Filled", "Blank", "By Evidence Level"}, ...]"""
    out = []
    for col in PARKING_DETAIL_COLUMNS:
        filled = [r for r in rows if (r.get(col, "") or "").strip() not in NOT_REALLY_FILLED]
        by_level = Counter((r.get(EVIDENCE_LEVEL, "").strip() or "(blank)") for r in filled)
        out.append({"Column": col, "Filled": len(filled), "Blank": len(rows) - len(filled),
                    "By Evidence Level": dict(by_level)})
    return out


# ---------------------------------------------------------------- clear_unverified first

def apply_clear_unverified(sheet_rows):
    """Simulates clear_unverified.py's effect in memory, never writes:
    this round's coverage baseline must reflect the state the sheet is in
    once clear_unverified actually runs, since that write always comes
    before any fill write, never after."""
    plan, _undo, _dry_run_rows = clear_unverified.build_plan(sheet_rows)
    cleared_by_place_id = {e["place_id"]: e["new"] for e in plan}
    return [{**row, **cleared_by_place_id.get(row.get(PLACE_ID, ""), {})} for row in sheet_rows]


# ---------------------------------------------------------------- hospital car park proximity

HOSPITAL_CAR_PARK_RADIUS_M = 150


class _CarParkCollector(osmium.SimpleHandler):
    """Every amenity=parking feature's geometry, named or not: all that
    matters here is "is one within range", not what it is called."""

    def __init__(self):
        super().__init__()
        self._wkb = osmium.geom.WKBFactory()
        self.geoms = []

    def node(self, n):
        if n.tags.get("amenity") == "parking":
            self.geoms.append(to_m(Point(n.location.lon, n.location.lat)))

    def area(self, a):
        if a.tags.get("amenity") != "parking":
            return
        try:
            geom = wkb.loads(self._wkb.create_multipolygon(a), hex=True)
        except Exception:
            return
        self.geoms.append(to_m(geom))


def load_car_park_geoms(pbf_path):
    collector = _CarParkCollector()
    collector.apply_file(pbf_path, locations=True)
    return collector.geoms


def build_hospital_car_park_check(car_park_geoms, radius_m=HOSPITAL_CAR_PARK_RADIUS_M):
    """A callable(row) -> True if an OSM car park is within radius_m of
    the row's point, or its mapped polygon contains that point."""
    from shapely.strtree import STRtree
    tree = STRtree(car_park_geoms) if car_park_geoms else None

    def check(row):
        if tree is None:
            return False
        point = row_point_m(row)
        if point is None:
            return False
        for idx in tree.query(point.buffer(radius_m)):
            geom = car_park_geoms[idx]
            if geom.geom_type != "Point" and geom.contains(point):
                return True
            if point.distance(geom) <= radius_m:
                return True
        return False
    return check


# ---------------------------------------------------------------- category policy draft

CATEGORY_POLICY_FIELDS = {
    "who_can_park": WHO_CAN_PARK, "cost_type": "Cost Type", "price_status": "Price Status",
    "max_stay_mins": "Max Stay (mins)", "rules_summary": "Rules Summary",
}


def load_category_policies(path=rules_mod.DEFAULT_PATH):
    """config/rules.toml's [category_policies] section: a draft, read
    directly here, not through rules.Rules (which never sees it)."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("category_policies", {})


def check_r7_guard(new_values, rules):
    """Violation strings if these category-policy values would break rule
    R7 (never Free, Anyone, or a concrete max stay from a category
    guess, only ever a cautious default). [] means clean."""
    violations = []
    cost = new_values.get("Cost Type")
    if cost in rules.r7_risky_cost_types:
        violations.append(f"Cost Type {cost!r} is risky under R7, not allowed from a category policy")
    who = new_values.get(WHO_CAN_PARK)
    if who in rules.r7_risky_who_can_park:
        violations.append(f"Who Can Park {who!r} is risky under R7, not allowed from a category policy")
    max_stay = str(new_values.get("Max Stay (mins)", ""))
    if max_stay and max_stay not in ("Not published", "No limit"):
        violations.append(f"Max Stay (mins) {max_stay!r} is a concrete value, not allowed from a category policy")
    return violations


def category_policy_new_values(category, policies, rules, today):
    """The new-value dict for one category policy, or None if this
    category has no draft policy. Raises if the policy itself breaks R7
    (a bug in config/rules.toml, not in a particular row)."""
    policy = policies.get(category)
    if not policy:
        return None
    new = {CATEGORY_POLICY_FIELDS[k]: v for k, v in policy.items() if k in CATEGORY_POLICY_FIELDS}
    violations = check_r7_guard(new, rules)
    if violations:
        raise ValueError(f"category policy {category!r} fails the R7 guard: {violations}")
    new[EVIDENCE_LEVEL] = policy.get("evidence_level", "Chain policy")
    # The sheet's real dropdown has no "Yes, conditional" value: "Conditional"
    # is the tri-state's actual third option, and a category guess, with no
    # site-specific evidence, is never stronger than that. Always set here,
    # never left as whatever stale guess the row already carried.
    new[fill.CAN_PARK] = "Conditional"
    new["Decision Reason"] = (f"Route: category policy ({category}), no site-specific evidence. "
                               "Rule R7: cautious defaults only, no Free / Anyone / max stay.")
    new[fill.VERIFIED_BY] = "Category policy script"
    new[fill.VERIFIED_DATE] = today.isoformat()
    new[VERIFICATION_RESULT] = "Confirmed, details not published"
    fill.assert_not_protected(new)
    return new


# ---------------------------------------------------------------- the four passes

def unfinished_rows(sheet_rows):
    return [r for r in sheet_rows if (r.get(VERIFICATION_RESULT, "") or "") == ""]


# fill.py always sets Can Park? to "Conditional" and the bookkeeping columns
# (Change Made, Evidence Type, Source Tier, Specificity, Rules Stated,
# Prices Stated, Evidence Age, Agreeing Sources, Conflict, Decision Reason,
# Verified By/Date, Verification Result) regardless of what OSM actually
# said; those never count as a "real value" here, only the columns below do.
OSM_FILL_REAL_VALUE_COLUMNS = [
    WHO_CAN_PARK, "Cost Type", "Price Status", "Tariff Type", "Tariff Detail",
    "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)", "Hours Basis",
    "Parking Control Type (Cameras / Barrier / Patrol)", "Operator",
    "PCN (Penalty Charge Notice) amount (£)",
]
OSM_FILL_EMPTY_LIKE = {"", "Unknown", "Not published"}


def osm_fill_has_real_value(new):
    """False when every one of OSM_FILL_REAL_VALUE_COLUMNS is Unknown,
    Not published, or blank: OSM found this place, but told us nothing
    about parking at all, so this row reads better as Not yet checked
    than as a "fill" that answers nothing."""
    return any((new.get(col, "") or "") not in OSM_FILL_EMPTY_LIKE
               for col in OSM_FILL_REAL_VALUE_COLUMNS)


def build_osm_fill_plan(sheet_rows, osm_rows, rules, today, captured_can_park):
    by_place_id = {r[PLACE_ID]: r for r in sheet_rows if r.get(PLACE_ID)}
    plan, empty = {}, {}
    for osm_row in osm_rows:
        sheet_row = by_place_id.get(osm_row.get("Place ID", ""))
        if sheet_row is None or sheet_row.get(VERIFICATION_RESULT, "") != "":
            continue
        checks = fill.check_eligibility(sheet_row, osm_row, sheet_row.get("Borough", ""), today,
                                         captured_can_park)
        if fill.is_eligible(checks):
            new = fill.derive_values(sheet_row, osm_row, rules, today, captured_can_park)
            place_id = sheet_row[PLACE_ID]
            if osm_fill_has_real_value(new):
                plan[place_id] = (sheet_row, new)
            else:
                empty[place_id] = (sheet_row, new)
    return plan, empty


def build_capture_fill_plan(sheet_rows, osm_rows, boroughs, today, captured_can_park):
    plan = {}
    for borough in boroughs:
        candidates = capture_fill.candidate_rows(sheet_rows, osm_rows, borough)
        if not candidates:
            continue
        by_place_id = {sr[PLACE_ID]: (sr, osm_row) for sr, osm_row in candidates}
        for record in capture_extract.build_records(candidates):
            place_id = record.get("place_id", "")
            if record.get("leave_for_grok") or place_id not in by_place_id:
                continue
            sheet_row, osm_row = by_place_id[place_id]
            new, violations = capture_fill.finish_record(sheet_row, osm_row, record, today,
                                                           captured_can_park)
            if new is not None:
                plan[place_id] = (sheet_row, new)
    return plan


def build_policy_fill_plan(sheet_rows, osm_rows, boroughs, rules, today):
    plan = {}
    for borough in boroughs:
        eligible = policy_fill.candidate_rows(sheet_rows, osm_rows, borough)
        if not eligible:
            continue
        by_place_id = {sr[PLACE_ID]: sr for sr, _ in eligible}
        entries, _undo, _dry_run_rows, _counts, _needs_research = policy_fill.build_plan(
            eligible, rules, today)
        for entry in entries:
            plan[entry["place_id"]] = (by_place_id[entry["place_id"]], entry["new"])
    return plan


# A car park, or a row, that is really for a restricted group, not the
# general "patients and visitors" / "customers" the category policy
# assumes, names one of these in its own name, Notes, or the matched OSM
# car park's own name/tags (a hospital's "Blue Badge only" bay, a petrol
# station's staff-only yard).
CATEGORY_POLICY_RESTRICTED_WORDS = ("blue badge", "disabled", "staff", "permit", "residents")


def category_policy_is_restricted(row, osm_row):
    text = norm(" ".join([
        row.get(LOCATION_NAME, ""), row.get("Notes", ""),
        (osm_row or {}).get("OSM Car Park Name", ""), (osm_row or {}).get("OSM Raw Tags", ""),
    ]))
    return any(contains_word(text, word) for word in CATEGORY_POLICY_RESTRICTED_WORDS)


def build_category_policy_plan(sheet_rows, already_planned, categories, policies, rules, today,
                                hospital_car_park_check, osm_by_place_id):
    """hospital_car_park_check(row) -> bool gates the hospital policy only
    (an OSM car park within HOSPITAL_CAR_PARK_RADIUS_M or inside its
    polygon); a hospital failing that check is left for not_yet_checked,
    not given the category policy. petrol_station has no such gate.
    category_policy_is_restricted applies to both: a restricted-access row
    (Blue Badge, disabled, staff, permit, residents) never gets the
    general policy, whichever category it is."""
    plan, restricted_count = {}, 0
    for row in unfinished_rows(sheet_rows):
        place_id = row.get(PLACE_ID, "")
        if place_id in already_planned:
            continue
        category = classify_sheet_row(row, categories)
        if category not in policies:
            continue
        if category == "hospital" and not hospital_car_park_check(row):
            continue
        if category_policy_is_restricted(row, osm_by_place_id.get(place_id)):
            restricted_count += 1
            continue
        new = category_policy_new_values(category, policies, rules, today)
        if new is not None:
            plan[place_id] = (row, new)
    return plan, restricted_count


def build_not_yet_checked_plan(sheet_rows, already_planned):
    plan = {}
    for row in unfinished_rows(sheet_rows):
        place_id = row.get(PLACE_ID, "")
        if place_id in already_planned or (row.get(EVIDENCE_LEVEL, "") or "").strip():
            continue
        plan[place_id] = (row, {EVIDENCE_LEVEL: NOT_YET_CHECKED})
    return plan


# ---------------------------------------------------------------- second reading

def second_reading(plan, fill_type):
    """Splits one pass's plan into (clean, failures): a row whose planned
    values fail page_fill.consistency_checks is held out, exactly like
    capture_fill.py and policy_fill.py already hold out their own
    failures, and reported instead of applied."""
    clean, failures = {}, []
    for place_id, (row, new) in plan.items():
        changed = {column for column, value in new.items()
                   if str(value) != str(row.get(column, ""))}
        metadata_only = bool(changed) and changed <= {"Place Category", "Brand"}
        violations = page_fill.consistency_checks(new, metadata_only=metadata_only)
        if violations:
            failures.append({"Place ID": place_id, "Location Name": row.get(LOCATION_NAME, ""),
                              "Fill Type": fill_type, "Violations": "; ".join(violations)})
        else:
            clean[place_id] = (row, new)
    return clean, failures


# ---------------------------------------------------------------- write plan files

def to_write_plan(plan):
    """plan: {place_id: (row, new)}, in fill.py's generic plan/undo shape
    (plan.json / undo.json), so `python -m ferro_parking write` can apply
    any one pass with its own abort-on-change check and read-back verify,
    the same machinery fill.py's own Route C write already uses."""
    plan_list, undo_list = [], []
    for place_id, (row, new) in plan.items():
        sheet_row_num = row.get("_sheet_row")
        name = row.get(LOCATION_NAME, "")
        old = {col: row.get(col, "") for col in new}
        plan_list.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name, "new": new})
        undo_list.append({"sheet_row": sheet_row_num, "place_id": place_id, "old": old})
    return plan_list, undo_list


def write_pass_files(plan, out_dir):
    import json
    plan_list, undo_list = to_write_plan(plan)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan.json").write_text(json.dumps(plan_list, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo_list, indent=1))
    return out_dir / "plan.json", out_dir / "undo.json"


# ---------------------------------------------------------------- main

FILL_TYPES = ("osm_fill", "capture_fill", "policy_fill", "category_policy", "not_yet_checked")


def run(service=None, osm_results_path=None, pbf_path=None, categories=None, today=None):
    today = today or date.today()
    rules = rules_mod.load_rules()
    categories = categories if categories is not None else load_categories()
    policies = load_category_policies()

    service = service or sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    captured_can_park = sync_mod.load_captured_can_park(service)

    # clear_unverified always writes before any fill write, so this round's
    # baseline must already reflect that, not the live sheet's stale guesses.
    sheet_rows = apply_clear_unverified(sheet_rows)

    baseline_rows = unfinished_rows(sheet_rows)
    boroughs = sorted({r.get("Borough", "") for r in baseline_rows})

    with open(osm_results_path, newline="", encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    car_park_geoms = load_car_park_geoms(pbf_path)
    hospital_car_park_check = build_hospital_car_park_check(car_park_geoms)
    osm_by_place_id = {r.get("Place ID", ""): r for r in osm_rows if r.get("Place ID")}

    plans, failures = {}, []
    already = set()

    raw, osm_fill_empty = build_osm_fill_plan(sheet_rows, osm_rows, rules, today, captured_can_park)
    plans["osm_fill"], f1 = second_reading(raw, "osm_fill")
    failures += f1
    already |= set(plans["osm_fill"])

    raw = build_capture_fill_plan(sheet_rows, osm_rows, boroughs, today, captured_can_park)
    raw = {pid: v for pid, v in raw.items() if pid not in already}
    plans["capture_fill"], f2 = second_reading(raw, "capture_fill")
    failures += f2
    already |= set(plans["capture_fill"])

    raw = build_policy_fill_plan(sheet_rows, osm_rows, boroughs, rules, today)
    raw = {pid: v for pid, v in raw.items() if pid not in already}
    plans["policy_fill"], f3 = second_reading(raw, "policy_fill")
    failures += f3
    already |= set(plans["policy_fill"])

    raw, restricted_count = build_category_policy_plan(sheet_rows, already, categories, policies,
                                                         rules, today, hospital_car_park_check,
                                                         osm_by_place_id)
    plans["category_policy"], f4 = second_reading(raw, "category_policy")
    failures += f4
    already |= set(plans["category_policy"])

    plans["not_yet_checked"] = build_not_yet_checked_plan(sheet_rows, already)

    overlaid = []
    for row in baseline_rows:
        place_id = row.get(PLACE_ID, "")
        new = None
        for fill_type in FILL_TYPES:
            if place_id in plans[fill_type]:
                new = plans[fill_type][place_id][1]
                break
        overlaid.append({**row, **new} if new else row)

    return {
        "baseline_rows": baseline_rows, "overlaid_rows": overlaid,
        "coverage_before": coverage_table(baseline_rows),
        "coverage_after": coverage_table(overlaid),
        "plans": plans, "second_reading_failures": failures,
        "osm_fill_empty_count": len(osm_fill_empty),
        "category_policy_restricted_count": restricted_count,
        "sheet_rows": sheet_rows, "headers": headers,
    }


def _plan_dry_run_rows(plan, fill_type):
    out = []
    for place_id, (row, new) in plan.items():
        for col, value in new.items():
            out.append({"Fill Type": fill_type, "Place ID": place_id,
                        "Location Name": row.get(LOCATION_NAME, ""), "Column": col,
                        "Current value": row.get(col, ""), "New value": value})
    return out


def _write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--osm-results", required=True)
    ap.add_argument("--pbf", required=True, help="OSM extract, for the hospital car park proximity check")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    today = date.today()
    out_dir = Path(args.out) if args.out else Path("data") / "runs" / today.isoformat() / "fill_round2"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = run(osm_results_path=args.osm_results, pbf_path=args.pbf, today=today)

    _write_csv(out_dir / "coverage_before.csv", ["Column", "Filled", "Blank", "By Evidence Level"],
               result["coverage_before"])
    _write_csv(out_dir / "coverage_after.csv", ["Column", "Filled", "Blank", "By Evidence Level"],
               result["coverage_after"])
    for fill_type in FILL_TYPES:
        _write_csv(out_dir / f"{fill_type}_plan.csv",
                   ["Fill Type", "Place ID", "Location Name", "Column", "Current value", "New value"],
                   _plan_dry_run_rows(result["plans"][fill_type], fill_type))
    _write_csv(out_dir / "second_reading_failures.csv",
               ["Place ID", "Location Name", "Fill Type", "Violations"],
               result["second_reading_failures"])

    # A plan.json / undo.json per pass, in fill.py's generic write format,
    # so each can be applied with its own abort-check and verify via
    # `python -m ferro_parking write <pass>/plan.json --apply`. Not for
    # capture_fill: that pass is never written by this command.
    for fill_type in FILL_TYPES:
        if fill_type == "capture_fill":
            continue
        write_pass_files(result["plans"][fill_type], out_dir / fill_type)

    print(f"Baseline unfinished rows: {len(result['baseline_rows'])}")
    for fill_type in FILL_TYPES:
        print(f"  {fill_type:<18}{len(result['plans'][fill_type])} rows")
    osm_fill_total = len(result['plans']['osm_fill']) + result['osm_fill_empty_count']
    print(f"  (of {osm_fill_total} osm_fill candidates, {result['osm_fill_empty_count']} had no real "
          f"value in any parking column and fell through to a later pass or not_yet_checked instead)")
    print(f"  (category_policy skipped {result['category_policy_restricted_count']} restricted-access "
          f"rows: Blue Badge, disabled, staff, permit or residents; sent to not_yet_checked instead)")
    print(f"Second-reading failures (held out of the plan): {len(result['second_reading_failures'])}")
    print(f"\nOutputs in {out_dir}/. Dry run only, nothing written to the sheet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
