"""Ferro PP: rule R10's policy-fill. A dry run only command: cautious
chain-policy rows for large and convenience chain branches and for gym
chains, and cautious presumed-no-parking rows for small venues (R10's
categories, and a convenience-format branch with no car park evidence)
with no OSM car park nearby.

python -m ferro_parking policy-fill --borough NAME

Eligible: Verification Result blank. For each eligible row:
  a) a known chain (rules.toml) in a large format; a convenience format
     with car park evidence (an OSM car park within
     rules.r10_nearby_car_park_radius_m, or "customer car park" /
     "customer parking" in the name); or a gym chain with an OSM car
     park within that radius: a cautious chain-policy row (Evidence
     Level "Chain policy").
  b) a small venue (R10's categories, or a convenience-format branch
     with no car park evidence) with no OSM car park within that
     radius: Can Park? No, Evidence Level "Presumed".
  c) everything else, including a gym chain with no nearby OSM car
     park (never presumed no parking for a gym; it may simply not be
     mapped): skipped, logged as "needs research".

This command never sets Free, Anyone, Anyone (paid), or a max stay (rule
R7): only cautious values. See docs/PP_rules_and_pilot.md (R10) and
page_fill.py's consistency_checks, which this module's output must also
satisfy.
"""
import argparse
import csv
import json
from datetime import date
from pathlib import Path
from .run_paths import new_run_dir, reserve_output

from . import discovery, fill, page_fill, rules as rules_mod, sheets
from .osm_match import contains_word as _contains_word

PLACE_ID = fill.PLACE_ID
LOCATION_NAME = fill.LOCATION_NAME
CAN_PARK = fill.CAN_PARK
WHO_CAN_PARK = fill.WHO_CAN_PARK
NOTES = fill.NOTES
REVIEW_FLAG = fill.REVIEW_FLAG
FLAG_STATUS = fill.FLAG_STATUS
VERIFIED_BY_COLUMN = fill.VERIFIED_BY
VERIFIED_BY_VALUE = "Policy script"

GOOGLE_THIRD_PARTY_SOURCE_TIER = "Google search / third-party"
CHAIN_OFFICIAL_SOURCE_TIER = "Official site - text"

FAST_FOOD_DRIVE_THRU_HINTS = ("drive-thru", "drive thru", "drivethru")

# Gym chains: not a retail large/convenience format, so format_for never
# matches them; checked against Location Name and Type (as captured)
# together since the brand sometimes sits in Type as a parenthetical
# ("Leisure centre (Better)") rather than leading the name.
GYM_CHAIN_NAMES = ("puregym", "the gym group", "virgin active", "nuffield health",
                    "better", "everyone active")

CUSTOMER_CAR_PARK_NAME_HINTS = ("customer car park", "customer parking")

_discovery_categories = None


def is_car_park_row(sheet_row):
    """A row that is itself a car park (Place Category "Council car
    park" / "Private / operator car park", or a "car park" / "parking"
    keyword with no category set) never gets the chain or small-venue
    logic below: that logic reads the row's own name against R10's
    retail brand and venue-category lists, and a car park named after
    the brand next to it ("Waitrose Car Park", "McDonald's car park")
    is not a shop needing a nearby-parking check."""
    global _discovery_categories
    if _discovery_categories is None:
        _discovery_categories = discovery.load_categories()
    return discovery.classify_sheet_row(sheet_row, _discovery_categories) == "car_park"

# Fast-food and casual chain brands: Type often reads "Restaurant (KFC)"
# or "Cafe (Costa)" rather than "Fast food", so the drive-thru/own-site
# guard must trigger on the brand itself, not only on the category text
# saying "fast food".
FAST_FOOD_BRAND_NAMES = ("kfc", "mcdonalds", "burger king", "nandos", "popeyes", "subway",
                          "greggs", "five guys", "wendys", "taco bell", "pizza hut",
                          "dominos", "papa johns", "costa", "starbucks", "pret")


# ---------------------------------------------------------------- eligibility

def candidate_rows(sheet_rows, osm_rows, borough):
    """Every row for one borough with Verification Result blank, paired
    with its osm_results.csv row (for Car Park Distance (m)). A row with
    no matching OSM row still counts eligible; has_nearby_car_park then
    reads as no car park found."""
    by_place_id = {r.get(PLACE_ID, ""): r for r in osm_rows if r.get("Place ID")}
    out = []
    for sheet_row in sheet_rows:
        if sheet_row.get("Borough", "") != borough:
            continue
        if sheet_row.get("Verification Result", "") != "":
            continue
        place_id = sheet_row.get(PLACE_ID, "")
        out.append((sheet_row, by_place_id.get(place_id, {})))
    return out


def has_nearby_car_park(osm_row, rules):
    try:
        distance = float(osm_row.get("Car Park Distance (m)", ""))
    except (TypeError, ValueError):
        return False
    return distance <= rules.r10_nearby_car_park_radius_m


def name_confirms_car_park(sheet_row):
    """The name itself states a car park exists ("Aldi ... - customer car
    park"), which counts regardless of what OSM shows nearby."""
    name = (sheet_row.get(LOCATION_NAME, "") or "").lower()
    return any(_contains_word(name, hint) for hint in CUSTOMER_CAR_PARK_NAME_HINTS)


def has_car_park_evidence(sheet_row, osm_row, rules):
    return has_nearby_car_park(osm_row, rules) or name_confirms_car_park(sheet_row)


def gym_chain_for(sheet_row):
    text = f"{sheet_row.get(LOCATION_NAME, '')} {sheet_row.get('Type (as captured)', '')}".lower()
    for name in GYM_CHAIN_NAMES:
        if _contains_word(text, name):
            return name
    return None


# ---------------------------------------------------------------- categories

def is_drive_thru(sheet_row, osm_row):
    """Checked against Type (as captured), Location Name, and the OSM
    drive_through tag, since a drive-thru is not always named in Type:
    the chain name alone ("McDonald's Peggy Bedford (Drive-Thru)") or the
    OSM tag can be the only place it shows up."""
    text = f"{sheet_row.get('Type (as captured)', '')} {sheet_row.get(LOCATION_NAME, '')}".lower()
    if any(_contains_word(text, h) for h in FAST_FOOD_DRIVE_THRU_HINTS):
        return True
    tags = fill.parse_tags(osm_row.get("OSM Raw Tags", ""))
    return tags.get("drive_through") == "yes"


FAST_FOOD_OWN_SITE_HINTS = ("drive", "retail park", "retail centre")


def is_fast_food_own_site(sheet_row, osm_row):
    """A fast food row needs research, not presumed no parking, when it
    reads as its own standalone site rather than a shopfront sharing a
    building with other shops: its name or Type names a drive(-thru),
    a retail park, or a retail centre, or OSM maps the place itself with
    its own building area (a way or relation) instead of a plain point."""
    text = f"{sheet_row.get('Type (as captured)', '')} {sheet_row.get(LOCATION_NAME, '')}".lower()
    if any(_contains_word(text, h) for h in FAST_FOOD_OWN_SITE_HINTS):
        return True
    match_url = osm_row.get("OSM Place Match", "") or ""
    return "/way/" in match_url or "/relation/" in match_url


def is_known_fast_food_brand(sheet_row):
    """A known fast-food/casual chain brand, checked against Type and
    Location Name together: Type often reads "Restaurant (KFC)" rather
    than "Fast food", which would otherwise match "restaurant" in R10's
    categories and skip the drive-thru/own-site guard entirely."""
    text = f"{sheet_row.get('Type (as captured)', '')} {sheet_row.get(LOCATION_NAME, '')}"
    text = text.lower().replace("'", "")
    return any(_contains_word(text, b) for b in FAST_FOOD_BRAND_NAMES)


def small_venue_category(sheet_row, osm_row, rules):
    """R10's small venue categories, matched against Place Category and
    Type (as captured) together; a fast food category or a known
    fast-food brand only counts without a drive-thru and without its own
    OSM building area, which has its own parking either way."""
    category_text = f"{sheet_row.get('Place Category', '')} {sheet_row.get('Type (as captured)', '')}"
    low = category_text.lower()
    if _contains_word(low, "fast food") or is_known_fast_food_brand(sheet_row):
        return not is_drive_thru(sheet_row, osm_row) and not is_fast_food_own_site(sheet_row, osm_row)
    return any(_contains_word(low, c) for c in rules.r10_small_venue_categories if c != "fast food")


# ---------------------------------------------------------------- branch a: chain policy

def chain_source_tier(chain_key, sheet_row):
    """"Official site - text" when the chain's own domain is in Source
    URLs, never "Operator / council site" (that tier is for an operator
    or council's own site-specific page, not a chain's general policy
    page)."""
    urls = (sheet_row.get("Source URLs (primary first)", "") or "").lower()
    if chain_key and chain_key.replace(" ", "") in urls.replace(" ", ""):
        return CHAIN_OFFICIAL_SOURCE_TIER
    return GOOGLE_THIRD_PARTY_SOURCE_TIER


def chain_who_can_park(chain, sheet_row, rules):
    who = (chain or {}).get("who_can_park")
    if who and who not in rules.r7_risky_who_can_park:
        return who
    return fill.category_default(sheet_row, rules)


def chain_cost_type(chain):
    cost_type = (chain or {}).get("cost_type")
    return "Paid" if cost_type == "Paid" else "Unknown"


def chain_hours_basis(sheet_row):
    captured = (sheet_row.get("Hours (as captured)", "") or "").lower()
    return "Store hours" if "store hours" in captured else "Not published"


def chain_policy_fields(sheet_row, chain_key, chain, rules):
    who_can_park = chain_who_can_park(chain, sheet_row, rules)
    cost_type = chain_cost_type(chain)
    new = {
        CAN_PARK: "Conditional",
        WHO_CAN_PARK: who_can_park,
        "Cost Type": cost_type,
        "Price Status": "Chain policy (not store-specific)",
        "Tariff Type": "Not published",
        "Tariff Detail": "Not published",
        "Max Stay (mins)": "Not published",
        "Hours (OpenStreetMap opening_hours format)": "Not published",
        "Hours Basis": chain_hours_basis(sheet_row),
        "Operator": (chain or {}).get("operator", "Not published"),
        "Specificity": "Chain-wide",
        "Source Tier": chain_source_tier(chain_key, sheet_row),
        "Evidence Type": "Official site: partial info",
        "Evidence Level": "Chain policy",
        "Verification Result": "Confirmed, details not published",
        VERIFIED_BY_COLUMN: VERIFIED_BY_VALUE,
        "Verified Date": None,  # filled in by caller with today's date
        "Decision Reason": f"Route-independent policy fill (rule R10): large or convenience "
                            f"chain format ({chain_key or 'unrecognised chain'}), no "
                            "site-specific evidence read.",
    }
    hint = (chain or {}).get("hint")
    extra_notes = [f"Chain rule ({chain_key}): {hint}"] if hint else []
    extra_flags = ["Chain policy presumed: confirm store-specific details on arrival"]
    return new, extra_notes, extra_flags


# ---------------------------------------------------------------- branch b: presumed no parking

def presumed_no_parking_fields():
    new = {CAN_PARK: "No", "Evidence Level": "Presumed", "Source Tier": "OpenStreetMap",
           "Evidence Detail (what the source shows)":
               "No car park mapped in OpenStreetMap within 40 m of the venue",
           "Rules Summary": "No parking listed (none mapped nearby). Check on arrival.",
           "Verification Result": "Confirmed, details not published",
           VERIFIED_BY_COLUMN: VERIFIED_BY_VALUE, "Verified Date": None,
           "Decision Reason": "Route-independent policy fill (rule R10): small venue "
                               "category, no OpenStreetMap car park within 40 m."}
    for col in page_fill.NOT_APPLICABLE_IF_NO_PARKING:
        new[col] = "Not applicable"
    extra_flags = ["Presumed no parking: confirm on arrival"]
    return new, [], extra_flags


# ---------------------------------------------------------------- classify

def classify(sheet_row, osm_row, rules):
    """Returns ("a" | "b" | "c", fields_dict | None, reason | None).
    fields_dict is None for "c" (needs research)."""
    if is_car_park_row(sheet_row):
        return "c", None, "row is itself a car park, not a shop or small venue"

    location_name = sheet_row.get(LOCATION_NAME, "")
    fmt = rules.format_for(location_name)
    chain_key_words = rules_mod.norm_chain_key(location_name).split()
    chain = None
    chain_key = None
    for n in (2, 1):
        key = " ".join(chain_key_words[:n])
        if key in rules.r6_chains:
            chain, chain_key = rules.r6_chains[key], key
            break

    if fmt == "large" or (fmt == "convenience" and has_car_park_evidence(sheet_row, osm_row, rules)):
        fields, extra_notes, extra_flags = chain_policy_fields(sheet_row, chain_key, chain, rules)
        return "a", (fields, extra_notes, extra_flags), None

    # A convenience-format branch with no car park evidence is, under
    # R10, a small venue: presumed no parking, not left for research.
    if fmt == "convenience":
        return "c", None, "Map absence is not evidence of no parking; official source needed"

    gym = gym_chain_for(sheet_row)
    if gym:
        if has_nearby_car_park(osm_row, rules):
            fields, extra_notes, extra_flags = chain_policy_fields(sheet_row, gym, rules.r6_chains.get(gym), rules)
            return "a", (fields, extra_notes, extra_flags), None
        return "c", None, f"gym chain ({gym}), no OSM car park within 40 m"

    if small_venue_category(sheet_row, osm_row, rules) and not has_nearby_car_park(osm_row, rules):
        return "c", None, "Map absence is not evidence of no parking; official source needed"

    return "c", None, "not a recognised chain format or small venue pattern"


# ---------------------------------------------------------------- assembling a row

def finish_record(sheet_row, fields, extra_notes, extra_flags, today):
    new, notes_list, flags_list = dict(fields), list(extra_notes), list(extra_flags)
    new["Verified Date"] = today.isoformat()

    if notes_list:
        existing = sheet_row.get(NOTES, "") or ""
        new[NOTES] = f"{existing}{' | ' if existing else ''}{'; '.join(notes_list)}"
    if flags_list:
        existing = sheet_row.get(REVIEW_FLAG, "") or ""
        new[REVIEW_FLAG] = f"{existing}{'; ' if existing else ''}{'; '.join(flags_list)}"
        new[FLAG_STATUS] = "Open"

    fill.assert_not_protected(new)
    violations = page_fill.consistency_checks(new)
    return (new, None) if not violations else (None, violations)


# ---------------------------------------------------------------- plan building

def build_plan(eligible, rules, today):
    plan, undo, dry_run_rows = [], [], []
    counts = {"a": 0, "b": 0, "c": 0}
    needs_research = []
    for sheet_row, osm_row in eligible:
        branch, result, reason = classify(sheet_row, osm_row, rules)
        counts[branch] += 1
        if branch == "c":
            needs_research.append((sheet_row.get(PLACE_ID, ""), sheet_row.get(LOCATION_NAME, ""), reason))
            continue
        fields, extra_notes, extra_flags = result
        new, violations = finish_record(sheet_row, fields, extra_notes, extra_flags, today)
        if new is None:
            counts[branch] -= 1
            counts["c"] += 1
            needs_research.append((sheet_row.get(PLACE_ID, ""), sheet_row.get(LOCATION_NAME, ""),
                                    "failed consistency check: " + "; ".join(violations)))
            continue
        sheet_row_num = sheet_row["_sheet_row"]
        place_id = sheet_row.get(PLACE_ID, "")
        name = sheet_row.get(LOCATION_NAME, "")
        old = {col: sheet_row.get(col, "") for col in new}
        plan.append({"sheet_row": sheet_row_num, "place_id": place_id, "name": name, "new": new})
        undo.append({"sheet_row": sheet_row_num, "place_id": place_id, "old": old})
        for col, value in new.items():
            dry_run_rows.append({"Sheet Row": sheet_row_num, "Place ID": place_id,
                                 "Location Name": name, "Column": col,
                                 "Current value": old[col], "New value": value})
    return plan, undo, dry_run_rows, counts, needs_research


# ---------------------------------------------------------------- command

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--borough", required=True)
    ap.add_argument("--osm-results", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    today = date.today()
    rules = rules_mod.load_rules()
    osm_path = args.osm_results or fill.latest_osm_results()
    with open(osm_path, newline="", encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    eligible = candidate_rows(sheet_rows, osm_rows, args.borough)

    plan, undo, dry_run_rows, counts, needs_research = build_plan(eligible, rules, today)

    out_dir = reserve_output(args.out) if args.out else new_run_dir(Path("policy_fill") / args.borough)
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=1))
    (out_dir / "undo.json").write_text(json.dumps(undo, indent=1))
    fill.write_csv(out_dir / "dry_run.csv",
                    ["Sheet Row", "Place ID", "Location Name", "Column", "Current value", "New value"],
                    dry_run_rows)
    with open(out_dir / "exceptions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Place ID", "Location Name", "Reason"])
        w.writerows(needs_research)

    print(f"Borough: {args.borough}")
    print(f"Eligible rows: {len(eligible)}")
    print(f"a) chain policy: {counts['a']}")
    print(f"b) presumed no parking: {counts['b']}")
    print(f"c) needs research (skipped): {counts['c']}")
    print(f"\nOutputs in {out_dir}/. Dry run only, nothing written to the sheet.")
    return 0


if __name__ == "__main__":
    main()
