"""Tests for the tranche 1 sheet-write plan (selection, store car park
attach rule, hotel flag-only rule, duplicate checks)."""
from datetime import date

import pytest

from ferro_parking import rules as rules_mod
from ferro_parking import tranche1_write as w

RULES = rules_mod.load_rules()
TODAY = date(2026, 11, 4)


def ready_row(name, category, confidence, **kw):
    r = {"OSM Type": "node", "OSM Id": "1", "OSM Link": "", "Name": name,
         "Category": category, "Confidence": confidence, "Address (OSM)": "",
         "Postcode": "", "Borough": "London Borough of Example", "Lat": "51.5",
         "Lon": "-0.1", "Operator": "", "Access": "", "Fee": "", "Notes": ""}
    r.update(kw)
    return r


def sheet_row(name, brand="", place_id="PP-000001", lat="51.5", lon="-0.1"):
    return {"Place ID": place_id, "Location Name": name, "Brand": brand,
            "Type (as captured)": "", "Latitude": lat, "Longitude": lon, "OSM ID": ""}


# ---- confidence selection -----------------------------------------------------
@pytest.mark.parametrize("category,confidence,expected", [
    ("supermarket", "High", True), ("supermarket", "Medium", True), ("supermarket", "Low", False),
    ("car_park", "Low", True), ("retail_park", "Low", True),
    ("station", "Low", False), ("petrol_station", "Low", False), ("hospital", "Low", False),
])
def test_passes_confidence_selection(category, confidence, expected):
    assert w.passes_confidence_selection(ready_row("X", category, confidence)) is expected


# ---- category mapping -----------------------------------------------------------
def test_car_park_with_council_hint_maps_to_council_car_park():
    row = ready_row("Example", "car_park", "High", Operator="Ealing Council")
    assert w.place_category_for(row) == "Council car park"


def test_car_park_without_council_hint_maps_to_private_operator():
    row = ready_row("NCP London Bridge", "car_park", "High")
    assert w.place_category_for(row) == "Private / operator car park"


@pytest.mark.parametrize("category,place_category", [
    ("supermarket", "Supermarket - large format"), ("petrol_station", "Petrol station"),
    ("station", "Station"), ("hospital", "Hospital / health centre"),
    ("retail_park", "Shopping centre"),
])
def test_place_category_for_non_car_park(category, place_category):
    assert w.place_category_for(ready_row("X", category, "High")) == place_category


# ---- hotel flag-only / airport notes ---------------------------------------------
def test_hotel_car_park_gets_the_near_hotel_note():
    row = ready_row("Premier Inn Car Park", "car_park", "Medium", Notes="Hotel car park (not public)")
    assert w.notes_for(row) == "Near hotel, access to confirm"


def test_airport_parking_gets_the_prebooked_note_even_without_hotel_flag():
    row = ready_row("Purple Parking Heathrow", "car_park", "High")
    assert w.is_airport_parking(row) is True
    assert w.notes_for(row) == "Pre-booked airport parking"


def test_airport_note_wins_over_hotel_note_if_both_would_apply():
    row = ready_row("Meet and Greet Airport Parking", "car_park", "High",
                     Notes="Hotel car park (not public)")
    assert w.notes_for(row) == "Pre-booked airport parking"


def test_plain_car_park_gets_no_note():
    row = ready_row("Some Car Park", "car_park", "High")
    assert w.notes_for(row) == ""


def test_hotel_rule_never_sets_who_can_park_or_access():
    """build_sheet_row only ever writes the columns listed in the brief;
    Who Can Park and Access must never appear."""
    row = ready_row("Premier Inn Car Park", "car_park", "Medium", Notes="Hotel car park (not public)")
    built = w.build_sheet_row(row, "PP-005440", TODAY)
    assert "Who Can Park" not in built
    assert "Access" not in built
    assert built["Notes"] == "Near hotel, access to confirm"


# ---- store car park -> attach to existing ---------------------------------------
def test_store_named_car_park_near_matching_brand_is_attached_not_added():
    sheet_rows = [sheet_row("Tesco Hackney", brand="Tesco", place_id="PP-000042",
                             lat="51.5000", lon="-0.1000")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("Tesco Customer Car Park", "car_park", "High", Lat="51.5005", Lon="-0.1005")
    match = w.chain_brand_match(candidate, sheet_rows, tree, points, valid, RULES)
    assert match is not None
    assert match["Place ID"] == "PP-000042"


def test_store_named_car_park_beyond_200m_is_not_attached():
    sheet_rows = [sheet_row("Tesco Hackney", brand="Tesco", place_id="PP-000042",
                             lat="51.5000", lon="-0.1000")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("Tesco Customer Car Park", "car_park", "High", Lat="51.5050", Lon="-0.1050")
    assert w.chain_brand_match(candidate, sheet_rows, tree, points, valid, RULES) is None


def test_car_park_with_no_chain_brand_in_its_name_is_not_attached():
    sheet_rows = [sheet_row("Tesco Hackney", brand="Tesco", place_id="PP-000042",
                             lat="51.5000", lon="-0.1000")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("Hackney Multi-Storey Car Park", "car_park", "High", Lat="51.5001", Lon="-0.1001")
    assert w.chain_brand_match(candidate, sheet_rows, tree, points, valid, RULES) is None


def test_ikea_car_park_is_attached_too_not_hardcoded_to_supermarkets():
    sheet_rows = [sheet_row("IKEA Wembley", place_id="PP-000099", lat="51.5500", lon="-0.2900")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("IKEA Car Park", "car_park", "High", Lat="51.5501", Lon="-0.2901")
    match = w.chain_brand_match(candidate, sheet_rows, tree, points, valid, RULES)
    assert match is not None and match["Place ID"] == "PP-000099"


# ---- duplicate check --------------------------------------------------------------
def test_duplicate_by_name_within_100m():
    sheet_rows = [sheet_row("Lidl Kingston", place_id="PP-000001", lat="51.4000", lon="-0.3000")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("Lidl Kingston", "supermarket", "High", Lat="51.40005", Lon="-0.30005")
    dup, reason = w.duplicate_in_sheet(candidate, sheet_rows, tree, points, valid)
    assert dup["Place ID"] == "PP-000001"
    assert "same name" in reason


def test_no_duplicate_beyond_100m():
    sheet_rows = [sheet_row("Lidl Kingston", place_id="PP-000001", lat="51.4000", lon="-0.3000")]
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("Lidl Kingston", "supermarket", "High", Lat="51.4100", Lon="-0.3100")
    dup, reason = w.duplicate_in_sheet(candidate, sheet_rows, tree, points, valid)
    assert dup is None


def test_duplicate_by_osm_id_regardless_of_distance():
    sheet_rows = [sheet_row("Something Else", place_id="PP-000002", lat="51.9000", lon="-0.9000")]
    sheet_rows[0]["OSM ID"] = "node/123"
    tree, points, valid = w.build_point_index(sheet_rows, "Latitude", "Longitude")
    candidate = ready_row("A Different Name", "supermarket", "High")
    candidate["OSM Type"], candidate["OSM Id"] = "node", "123"
    dup, reason = w.duplicate_in_sheet(candidate, sheet_rows, tree, points, valid)
    assert dup["Place ID"] == "PP-000002"
    assert reason == "same OSM ID"


# ---- end to end build_plan ---------------------------------------------------------
def test_build_plan_place_ids_continue_from_5440():
    rows = [ready_row("A", "supermarket", "High", Lat="51.1", Lon="-0.1", **{"OSM Id": "1"}),
            ready_row("B", "supermarket", "High", Lat="51.2", Lon="-0.2", **{"OSM Id": "2"})]
    plan = w.build_plan(rows, [], RULES, TODAY)
    assert [r["Place ID"] for r in plan["plan_rows"]] == ["PP-005440", "PP-005441"]


def test_build_plan_drops_rows_with_no_borough():
    rows = [ready_row("A", "supermarket", "High", Borough="")]
    plan = w.build_plan(rows, [], RULES, TODAY)
    assert plan["plan_rows"] == []
    assert len(plan["excluded_outside_london"]) == 1


def test_build_plan_excludes_low_supermarket():
    rows = [ready_row("A", "supermarket", "Low")]
    plan = w.build_plan(rows, [], RULES, TODAY)
    assert plan["plan_rows"] == []


def test_build_plan_keeps_low_car_park():
    rows = [ready_row("A", "car_park", "Low")]
    plan = w.build_plan(rows, [], RULES, TODAY)
    assert len(plan["plan_rows"]) == 1


# ---- holding back a category's Low confidence rows for later ---------------------
def test_held_low_category_is_not_added_and_not_counted_as_excluded():
    rows = [ready_row("A", "car_park", "Low", **{"OSM Id": "1"}),
            ready_row("B", "car_park", "High", **{"OSM Id": "2"})]
    plan = w.build_plan(rows, [], RULES, TODAY, hold_low_categories={"car_park"})
    assert len(plan["plan_rows"]) == 1                 # only the High one
    assert plan["plan_rows"][0]["Location Name"] == "B"
    assert len(plan["held_rows"]) == 1
    assert plan["held_rows"][0]["Name"] == "A"
    assert plan["excluded_outside_london"] == []        # held, not "excluded"


def test_holding_back_car_parks_does_not_touch_other_categories():
    rows = [ready_row("A", "car_park", "Low", **{"OSM Id": "1"}),
            ready_row("B", "retail_park", "Low", **{"OSM Id": "2"})]
    plan = w.build_plan(rows, [], RULES, TODAY, hold_low_categories={"car_park"})
    assert [r["Location Name"] for r in plan["plan_rows"]] == ["B"]
    assert [r["Name"] for r in plan["held_rows"]] == ["A"]


def test_no_hold_categories_means_nothing_is_held():
    rows = [ready_row("A", "car_park", "Low")]
    plan = w.build_plan(rows, [], RULES, TODAY)
    assert plan["held_rows"] == []
    assert len(plan["plan_rows"]) == 1


def test_held_rows_do_not_consume_a_place_id():
    rows = [ready_row("A", "car_park", "Low", **{"OSM Id": "1"}),
            ready_row("B", "car_park", "High", **{"OSM Id": "2"})]
    plan = w.build_plan(rows, [], RULES, TODAY, hold_low_categories={"car_park"})
    assert plan["plan_rows"][0]["Place ID"] == "PP-005440"
