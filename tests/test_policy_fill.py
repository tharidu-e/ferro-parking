"""Tests for policy_fill.py (rule R10): branches a (chain policy), b
(presumed no parking), c (needs research), and that rule R7 is never
broken by this command (no Free, no Anyone, no max stay)."""
from datetime import date

from ferro_parking import policy_fill as pf
from ferro_parking import rules as rules_mod

TODAY = date(2026, 11, 4)
RULES = rules_mod.load_rules()


def sheet_row(**kw):
    base = {
        "Location Name": "Tesco Acton Superstore", "Borough": "Ealing",
        "Place Category": "Supermarket", "Type (as captured)": "Retail - Supermarket",
        "Verification Result": "", "Notes": "", "Review Flag": "", "Flag Status": "",
        "Source URLs (primary first)": "", "Hours (as captured)": "", "Place ID": "PP-1",
    }
    base.update(kw)
    return base


def osm_row(distance="", raw_tags="", place_match=""):
    return {"Place ID": "PP-1", "Car Park Distance (m)": distance, "OSM Raw Tags": raw_tags,
            "OSM Place Match": place_match}


# ---- branch a: chain policy, large format --------------------------------
def test_large_format_tesco_gets_chain_policy():
    branch, result, reason = pf.classify(sheet_row(), osm_row(), RULES)
    assert branch == "a"
    fields, notes, flags = result
    assert fields[pf.CAN_PARK] == "Conditional"
    assert fields[pf.WHO_CAN_PARK] == "Customers only"
    assert fields["Cost Type"] == "Unknown"
    assert fields["Price Status"] == "Chain policy (not store-specific)"
    assert fields["Tariff Type"] == "Not published"
    assert fields["Max Stay (mins)"] == "Not published"
    assert fields["Specificity"] == "Chain-wide"
    assert fields["Evidence Level"] == "Chain policy"
    assert any("Max stay set per store" in n for n in notes)


def test_large_format_lidl_has_no_who_can_park_override_falls_back_to_category_default():
    row = sheet_row(**{"Location Name": "Lidl East Acton"})
    branch, result, reason = pf.classify(row, osm_row(), RULES)
    assert branch == "a"
    fields, notes, flags = result
    assert fields[pf.WHO_CAN_PARK] == "Customers only"
    assert any("90 minutes" in n for n in notes)


def test_morrisons_gets_operator_from_chain_rule():
    row = sheet_row(**{"Location Name": "Morrisons Southwark"})
    branch, result, reason = pf.classify(row, osm_row(), RULES)
    assert branch == "a"
    fields, notes, flags = result
    assert fields["Operator"] == "Euro Car Parks"


def test_chain_source_tier_is_official_when_chain_name_in_source_url():
    row = sheet_row(**{"Source URLs (primary first)": "https://www.tesco.com/store-locator/x"})
    branch, result, reason = pf.classify(row, osm_row(), RULES)
    fields, notes, flags = result
    assert fields["Source Tier"] == pf.CHAIN_OFFICIAL_SOURCE_TIER


def test_chain_source_tier_is_never_operator_council_site():
    row = sheet_row(**{"Source URLs (primary first)": "https://www.tesco.com/store-locator/x"})
    branch, result, reason = pf.classify(row, osm_row(), RULES)
    fields, notes, flags = result
    assert fields["Source Tier"] != "Operator / council site"
    assert fields["Specificity"] == "Chain-wide"


def test_chain_source_tier_is_third_party_with_no_chain_url():
    branch, result, reason = pf.classify(sheet_row(), osm_row(), RULES)
    fields, notes, flags = result
    assert fields["Source Tier"] == pf.GOOGLE_THIRD_PARTY_SOURCE_TIER


def test_hours_basis_store_hours_when_captured_text_says_so():
    row = sheet_row(**{"Hours (as captured)": "Store hours Mon-Sat 07:00-22:00"})
    branch, result, reason = pf.classify(row, osm_row(), RULES)
    fields, notes, flags = result
    assert fields["Hours Basis"] == "Store hours"


# ---- Waitrose: a convenience format, not a large one ----------------------
def test_plain_waitrose_is_convenience_not_large():
    row = sheet_row(**{"Location Name": "Waitrose Nine Elms"})
    assert RULES.format_for(row["Location Name"]) == "convenience"
    # No car park evidence: R10 fix, a convenience format with none falls
    # through to presumed no parking, not needs-research.
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_waitrose_and_partners_is_convenience():
    row = sheet_row(**{"Location Name": "Waitrose & Partners Clapham"})
    assert RULES.format_for(row["Location Name"]) == "convenience"


def test_plain_waitrose_with_nearby_car_park_gets_chain_policy():
    row = sheet_row(**{"Location Name": "Waitrose Nine Elms"})
    branch, result, reason = pf.classify(row, osm_row(distance="15"), RULES)
    assert branch == "a"


# ---- branch a: convenience format needs a nearby OSM car park ------------
def test_convenience_format_with_nearby_car_park_gets_chain_policy():
    row = sheet_row(**{"Location Name": "Tesco Express Baker Street"})
    branch, result, reason = pf.classify(row, osm_row(distance="25"), RULES)
    assert branch == "a"


def test_convenience_format_without_nearby_car_park_is_presumed_no_parking():
    row = sheet_row(**{"Location Name": "Tesco Express Baker Street"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_convenience_format_car_park_too_far_is_still_presumed_no_parking():
    row = sheet_row(**{"Location Name": "Co-op Food Camden"})
    branch, result, reason = pf.classify(row, osm_row(distance="80"), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


# ---- branch b: small venue, no nearby OSM car park ------------------------
def test_small_venue_with_no_nearby_car_park_is_presumed_no_parking():
    row = sheet_row(**{"Location Name": "The Red Lion", "Place Category": "Pub",
                        "Type (as captured)": "Pub"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_small_venue_with_a_nearby_car_park_is_needs_research():
    row = sheet_row(**{"Location Name": "The Red Lion", "Place Category": "Pub",
                        "Type (as captured)": "Pub"})
    branch, result, reason = pf.classify(row, osm_row(distance="10"), RULES)
    assert branch == "c"


def test_fast_food_drive_thru_named_in_type_is_not_a_small_venue():
    row = sheet_row(**{"Location Name": "McDonald's North Acton",
                        "Place Category": "Fast food",
                        "Type (as captured)": "Fast food restaurant (drive-thru)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_fast_food_drive_thru_named_in_location_name_is_not_a_small_venue():
    row = sheet_row(**{"Location Name": "McDonald's Peggy Bedford (Drive-Thru)",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_fast_food_drive_thru_tagged_in_osm_is_not_a_small_venue():
    row = sheet_row(**{"Location Name": "KFC Hayes", "Place Category": "Fast food",
                        "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance="", raw_tags="drive_through=yes"), RULES)
    assert branch == "c"


def test_fast_food_without_drive_thru_is_a_small_venue():
    row = sheet_row(**{"Location Name": "McDonald's Baker Street",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_fast_food_as_its_own_osm_building_way_needs_research():
    row = sheet_row(**{"Location Name": "McDonald's Example Road",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance="", place_match=
                                          "https://www.openstreetmap.org/way/123"), RULES)
    assert branch == "c"


def test_fast_food_as_an_osm_point_stays_a_small_venue():
    row = sheet_row(**{"Location Name": "McDonald's Example Road",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance="", place_match=
                                          "https://www.openstreetmap.org/node/123"), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_fast_food_named_retail_park_needs_research():
    row = sheet_row(**{"Location Name": "KFC Lombardy Retail Park",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_fast_food_named_retail_centre_needs_research():
    row = sheet_row(**{"Location Name": "Burger King Hayes Retail Centre",
                        "Place Category": "Fast food", "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


# ---- fix: brand-named Restaurant/Cafe rows get the fast food guard too ----
def test_restaurant_kfc_without_drive_thru_is_a_small_venue():
    # "Restaurant (KFC)" matches R10's own "restaurant" category and would
    # otherwise skip the drive-thru/own-site guard entirely.
    row = sheet_row(**{"Location Name": "KFC Yiewsley - High Street",
                        "Place Category": "Restaurant (KFC)", "Type (as captured)": "Restaurant (KFC)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_restaurant_mcdonalds_with_drive_thru_in_name_needs_research():
    row = sheet_row(**{"Location Name": "McDonald's Peggy Bedford (Drive-Thru)",
                        "Place Category": "Restaurant (McDonald's)",
                        "Type (as captured)": "Restaurant (McDonald's)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_restaurant_burger_king_as_its_own_osm_building_needs_research():
    row = sheet_row(**{"Location Name": "Burger King Example Road",
                        "Place Category": "Restaurant (Burger King)",
                        "Type (as captured)": "Restaurant (Burger King)"})
    branch, result, reason = pf.classify(row, osm_row(distance="", place_match=
                                          "https://www.openstreetmap.org/way/456"), RULES)
    assert branch == "c"


def test_restaurant_nandos_without_drive_thru_is_a_small_venue():
    row = sheet_row(**{"Location Name": "Nando's Wood Green",
                        "Place Category": "Restaurant (Nando's)",
                        "Type (as captured)": "Restaurant (Nando's)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_cafe_costa_in_a_retail_park_needs_research():
    row = sheet_row(**{"Location Name": "Costa Lombardy Retail Park",
                        "Place Category": "Cafe (Costa)", "Type (as captured)": "Cafe (Costa)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_is_known_fast_food_brand_matches_every_named_brand():
    brands = ("KFC", "McDonald's", "Burger King", "Nando's", "Popeyes", "Subway",
              "Greggs", "Five Guys", "Wendy's", "Taco Bell", "Pizza Hut", "Domino's",
              "Papa John's", "Costa", "Starbucks", "Pret")
    for brand in brands:
        row = sheet_row(**{"Location Name": f"{brand} Example Street",
                            "Place Category": f"Restaurant ({brand})",
                            "Type (as captured)": f"Restaurant ({brand})"})
        assert pf.is_known_fast_food_brand(row), brand


def test_drive_thru_mentioned_only_in_place_category_is_not_enough():
    # R10's fix: only Type, Location Name, or an OSM tag count, not Place
    # Category, since that field is not where a drive-thru is confirmed.
    row = sheet_row(**{"Location Name": "McDonald's Example Road",
                        "Place Category": "Fast food (drive-thru)",
                        "Type (as captured)": "Fast food restaurant"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_public_car_park_is_not_misread_as_a_pub():
    # "Public Car Park" contains the substring "pub"; a plain substring
    # check would wrongly call this a small venue and mark it No parking.
    row = sheet_row(**{"Location Name": "Oaklands Gate Car Park (Hillingdon Council)",
                        "Place Category": "", "Type (as captured)": "Public Car Park (Council)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


# ---- fix b: Location Name confirming a car park overrides the OSM check --
def test_customer_car_park_in_name_gets_chain_policy_with_no_nearby_osm_park():
    row = sheet_row(**{"Location Name": "Aldi 90-100 Edgware Road, London (W2 2EA) "
                                         "– customer car park"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "a"


def test_customer_parking_in_name_also_counts():
    row = sheet_row(**{"Location Name": "Tesco Express Somewhere - customer parking"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "a"


# ---- fix c: gym chains need an OSM car park, never presumed no parking ---
def test_puregym_with_nearby_car_park_gets_chain_policy():
    row = sheet_row(**{"Location Name": "PureGym London Bayswater",
                        "Place Category": "Gym", "Type (as captured)": "Gym"})
    branch, result, reason = pf.classify(row, osm_row(distance="20"), RULES)
    assert branch == "a"


def test_puregym_with_no_nearby_car_park_needs_research_not_presumed():
    row = sheet_row(**{"Location Name": "PureGym London Bayswater",
                        "Place Category": "Gym", "Type (as captured)": "Gym"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "gym chain" in reason


def test_better_leisure_centre_named_as_a_type_parenthetical_is_a_gym_chain():
    row = sheet_row(**{"Location Name": "Woolwich Waves", "Place Category": "Leisure centre",
                        "Type (as captured)": "Leisure centre (Better)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "gym chain" in reason


def test_virgin_active_without_nearby_car_park_is_not_presumed_no_parking():
    row = sheet_row(**{"Location Name": "Virgin Active Chelsea", "Place Category": "Gym",
                        "Type (as captured)": "Gym"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


# ---- branch c: everything else --------------------------------------------
def test_unrecognised_store_is_needs_research():
    row = sheet_row(**{"Location Name": "Generic Hardware Store",
                        "Place Category": "DIY store", "Type (as captured)": "Retail"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "not a recognised chain format" in reason


# ---- a row that is itself a car park never gets shop/small-venue logic ----
# Regression for the 2026-11-05 Grok pre-fill: 13 car-park rows whose name
# contained a retail brand word were misread as that brand's shop, three
# of them (these three) wrongly landing on Can Park? No.
def test_waitrose_car_park_is_not_presumed_no_parking():
    row = sheet_row(**{"Location Name": "Waitrose Car Park", "Place Category": "Private / operator car park",
                        "Type (as captured)": "Car park", "Place ID": "PP-007014"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "itself a car park" in reason


def test_mcdonalds_car_park_is_not_a_fast_food_small_venue():
    row = sheet_row(**{"Location Name": "McDonald's car park", "Place Category": "Private / operator car park",
                        "Type (as captured)": "Car park", "Place ID": "PP-007140"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "itself a car park" in reason


def test_waitrose_sheen_car_park_is_not_presumed_no_parking():
    row = sheet_row(**{"Location Name": "Waitrose Sheen Car Park", "Place Category": "Council car park",
                        "Type (as captured)": "Car park", "Place ID": "PP-007151"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert "itself a car park" in reason


def test_car_park_named_after_a_large_format_chain_is_not_chain_policy():
    """Without the guard this would match "large format" (fmt == "large")
    and return branch "a", not "c": a car park is not the shop itself."""
    row = sheet_row(**{"Location Name": "Morrisons Car Park", "Place Category": "Private / operator car park",
                        "Type (as captured)": "Car park"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_car_park_matched_only_by_keyword_is_also_not_a_small_venue():
    """Place Category blank, Type (as captured) carries the "car park"
    keyword instead; discovery.classify_sheet_row's keyword fallback must
    still catch this as a car park, not a shop."""
    row = sheet_row(**{"Location Name": "Aldi Car Park", "Place Category": "",
                        "Type (as captured)": "Car park (Aldi)"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"


def test_actual_aldi_shop_is_unaffected_by_the_car_park_guard():
    """A shop named "Aldi", not a car park, keeps going through the
    normal convenience/large-format logic."""
    row = sheet_row(**{"Location Name": "Aldi Ealing", "Place Category": "Supermarket - large format",
                        "Type (as captured)": "Retail - Supermarket"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "a"


# ---- finish_record passes the shared validator ----------------------------
def test_finish_record_chain_policy_passes_consistency_checks():
    branch, result, reason = pf.classify(sheet_row(), osm_row(), RULES)
    fields, notes, flags = result
    new, violations = pf.finish_record(sheet_row(), fields, notes, flags, TODAY)
    assert violations is None
    assert "Route" in new["Decision Reason"]
    assert new["Review Flag"]
    assert new["Flag Status"] == "Open"


# ---- every dict key must be a real sheet column, not the value by mistake --
REAL_COLUMN_NAMES = {
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type", "Price Status",
    "Tariff Type", "Tariff Detail", "Max Stay (mins)",
    "Hours (OpenStreetMap opening_hours format)", "Hours Basis", "Operator",
    "Specificity", "Source Tier", "Evidence Type", "Evidence Level",
    "Verification Result", "Verified By", "Verified Date", "Decision Reason",
    "Evidence Detail (what the source shows)", "Rules Summary", "Notes",
    "Review Flag", "Flag Status", "Parking Control Type (Cameras / Barrier / Patrol)",
    "PCN (Penalty Charge Notice) amount (£)",
}


def test_chain_policy_fields_never_uses_a_value_as_a_column_name():
    branch, result, reason = pf.classify(sheet_row(), osm_row(), RULES)
    fields, _, _ = result
    assert set(fields) <= REAL_COLUMN_NAMES, set(fields) - REAL_COLUMN_NAMES
    assert fields["Verified By"] == "Policy script"
    assert "Policy script" not in fields


def test_presumed_no_parking_fields_never_uses_a_value_as_a_column_name():
    row = sheet_row(**{"Location Name": "The Red Lion", "Place Category": "Pub",
                        "Type (as captured)": "Pub"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_finish_record_presumed_no_parking_passes_consistency_checks():
    row = sheet_row(**{"Location Name": "The Red Lion", "Place Category": "Pub",
                        "Type (as captured)": "Pub"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason


def test_r7_never_violated_across_every_known_chain():
    chains_to_try = ["Tesco Acton Superstore", "Sainsbury's Superstore Example",
                      "Lidl East Acton", "Aldi Example Store", "Asda Example Superstore",
                      "Morrisons Southwark"]
    for name in chains_to_try:
        row = sheet_row(**{"Location Name": name})
        branch, result, reason = pf.classify(row, osm_row(), RULES)
        if branch != "a":
            continue
        fields, _, _ = result
        assert fields["Cost Type"] != "Free", name
        assert fields[pf.WHO_CAN_PARK] not in ("Anyone", "Anyone (paid)"), name
        assert fields["Max Stay (mins)"] == "Not published", name


def test_r7_small_venue_never_sets_a_risky_value():
    row = sheet_row(**{"Location Name": "Corner Cafe", "Place Category": "Cafe",
                        "Type (as captured)": "Cafe"})
    branch, result, reason = pf.classify(row, osm_row(distance=""), RULES)
    assert branch == "c"
    assert result is None
    assert "Map absence" in reason

