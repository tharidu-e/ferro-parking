"""Tests for fill round 2: coverage counting, the category policy draft,
its R7 guard, and the second-reading consistency check."""
from datetime import date

import pytest

from ferro_parking import fill_round2 as r2
from ferro_parking import rules as rules_mod
from ferro_parking import page_fill

RULES = rules_mod.load_rules()
TODAY = date(2026, 11, 4)
POLICIES = r2.load_category_policies()


# ---- the draft policies load and name real dropdown values ------------------
def test_draft_policies_loaded_for_both_categories():
    assert "hospital" in POLICIES
    assert "petrol_station" in POLICIES


def test_hospital_policy_uses_real_dropdown_values_not_the_literal_brief():
    """The brief said "Price Status = Paid" for hospital; Paid is a Cost
    Type value, not a Price Status one, so this checks the corrected
    mapping, not the literal wording."""
    new = r2.category_policy_new_values("hospital", POLICIES, RULES, TODAY)
    assert new["Who Can Park"] == "Patients and visitors"
    assert new["Cost Type"] == "Paid"
    assert new["Price Status"] == "Chain policy (not store-specific)"
    assert new["Max Stay (mins)"] == "Not published"


def test_petrol_station_policy_uses_customers_only_not_bare_customers():
    new = r2.category_policy_new_values("petrol_station", POLICIES, RULES, TODAY)
    assert new["Who Can Park"] == "Customers only"
    assert new["Max Stay (mins)"] == "Not published"


def test_category_policy_always_sets_can_park_to_conditional():
    """The sheet has no "Yes, conditional" value; "Conditional" is the
    tri-state's real third option, and it must always be set here, never
    left as whatever stale guess the row already had."""
    for category in ("hospital", "petrol_station"):
        new = r2.category_policy_new_values(category, POLICIES, RULES, TODAY)
        assert new["Can Park? (Yes/No/Conditional)"] == "Conditional"


def test_unknown_category_has_no_policy():
    assert r2.category_policy_new_values("cinema", POLICIES, RULES, TODAY) is None


# ---- R7 guard -----------------------------------------------------------------
def test_r7_guard_passes_the_real_policies():
    for category in POLICIES:
        new = r2.category_policy_new_values(category, POLICIES, RULES, TODAY)
        assert r2.check_r7_guard(new, RULES) == []


@pytest.mark.parametrize("new_values,expected_hit", [
    ({"Cost Type": "Free"}, "Cost Type"),
    ({"Who Can Park": "Anyone"}, "Who Can Park"),
    ({"Who Can Park": "Anyone (paid)"}, "Who Can Park"),
    ({"Max Stay (mins)": "120"}, "Max Stay"),
])
def test_r7_guard_catches_a_bad_policy(new_values, expected_hit):
    violations = r2.check_r7_guard(new_values, RULES)
    assert violations
    assert expected_hit in violations[0]


def test_r7_guard_allows_the_cautious_values():
    cautious = {"Cost Type": "Paid", "Who Can Park": "Customers only",
                "Max Stay (mins)": "Not published"}
    assert r2.check_r7_guard(cautious, RULES) == []


def test_category_policy_new_values_raises_if_config_itself_breaks_r7():
    bad_policies = {"hospital": {"who_can_park": "Anyone", "rules_summary": "x"}}
    with pytest.raises(ValueError, match="R7"):
        r2.category_policy_new_values("hospital", bad_policies, RULES, TODAY)


def test_category_policy_decision_reason_names_a_route():
    """page_fill.consistency_checks requires "Route" in Decision Reason;
    a category policy row must satisfy that too."""
    new = r2.category_policy_new_values("hospital", POLICIES, RULES, TODAY)
    assert "Route" in new["Decision Reason"]
    assert page_fill.consistency_checks(new) == []


# ---- coverage table -----------------------------------------------------------
def row(**kw):
    r = {"Evidence Level": ""}
    r.update(kw)
    return r


def test_coverage_counts_filled_and_blank():
    rows = [row(**{"Who Can Park": "Customers only", "Evidence Level": "Verified"}),
            row(**{"Who Can Park": ""})]
    table = r2.coverage_table(rows)
    who = next(c for c in table if c["Column"] == "Who Can Park")
    assert who["Filled"] == 1
    assert who["Blank"] == 1
    assert who["By Evidence Level"] == {"Verified": 1}


@pytest.mark.parametrize("value", ["", "Not published", "Unknown"])
def test_coverage_treats_cautious_placeholders_as_not_filled(value):
    rows = [row(**{"Cost Type": value})]
    table = r2.coverage_table(rows)
    cost = next(c for c in table if c["Column"] == "Cost Type")
    assert cost["Filled"] == 0
    assert cost["Blank"] == 1


# ---- not-yet-checked plan ------------------------------------------------------
def test_not_yet_checked_only_touches_evidence_level():
    rows = [{"Place ID": "PP-1", "Verification Result": "", "Evidence Level": ""}]
    plan = r2.build_not_yet_checked_plan(rows, already_planned=set())
    assert list(plan["PP-1"][1].keys()) == ["Evidence Level"]
    assert plan["PP-1"][1]["Evidence Level"] == "Not yet checked"


def test_not_yet_checked_skips_already_planned_rows():
    rows = [{"Place ID": "PP-1", "Verification Result": "", "Evidence Level": ""}]
    plan = r2.build_not_yet_checked_plan(rows, already_planned={"PP-1"})
    assert plan == {}


def test_not_yet_checked_skips_rows_with_an_evidence_level_already():
    rows = [{"Place ID": "PP-1", "Verification Result": "", "Evidence Level": "Presumed"}]
    plan = r2.build_not_yet_checked_plan(rows, already_planned=set())
    assert plan == {}


# ---- second reading -----------------------------------------------------------
def test_second_reading_passes_a_clean_plan():
    good = {"Who Can Park": "Customers only", "Cost Type": "Unknown",
            "Decision Reason": "Route C: ..."}
    plan = {"PP-1": ({"Place ID": "PP-1", "Location Name": "X"}, good)}
    clean, failures = r2.second_reading(plan, "osm_fill")
    assert clean == plan
    assert failures == []


# ---- osm_fill: an empty-looking fill falls through, not kept -----------------
def test_osm_fill_with_no_real_value_is_not_kept():
    empty = {"Who Can Park": "Unknown", "Cost Type": "Unknown", "Price Status": "Not published",
             "Tariff Type": "Not published", "Tariff Detail": "Not published",
             "Max Stay (mins)": "Not published", "Operator": "Not published"}
    assert r2.osm_fill_has_real_value(empty) is False


def test_osm_fill_with_one_real_value_is_kept():
    has_one = {"Who Can Park": "Customers only", "Cost Type": "Unknown"}
    assert r2.osm_fill_has_real_value(has_one) is True


def test_osm_fill_blank_values_also_count_as_empty():
    assert r2.osm_fill_has_real_value({}) is False


# ---- hospital car park proximity gate ------------------------------------------
def test_hospital_car_park_check_true_within_radius():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    geoms = [to_m(Point(-0.1, 51.5))]
    check = r2.build_hospital_car_park_check(geoms)
    row = {"Latitude": "51.5010", "Longitude": "-0.1"}   # ~111 m away
    assert check(row) is True


def test_hospital_car_park_check_false_beyond_radius():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    geoms = [to_m(Point(-0.1, 51.5))]
    check = r2.build_hospital_car_park_check(geoms)
    row = {"Latitude": "51.5050", "Longitude": "-0.1"}   # ~556 m away
    assert check(row) is False


def test_hospital_car_park_check_true_inside_polygon():
    from shapely.geometry import Polygon
    from ferro_parking.osm_match import to_m
    square = Polygon([(-0.101, 51.499), (-0.099, 51.499), (-0.099, 51.501), (-0.101, 51.501)])
    check = r2.build_hospital_car_park_check([to_m(square)])
    row = {"Latitude": "51.500", "Longitude": "-0.100"}
    assert check(row) is True


def test_category_policy_plan_skips_hospital_without_nearby_car_park():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-1", "Location Name": "Royal Free Hospital", "Notes": "",
             "Verification Result": "", "Place Category": "Hospital / health centre",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: False,
                                                       osm_by_place_id={})
    assert plan == {}
    assert restricted == 0


def test_category_policy_plan_includes_hospital_with_nearby_car_park():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-1", "Location Name": "Royal Free Hospital", "Notes": "",
             "Verification Result": "", "Place Category": "Hospital / health centre",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, _restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                        hospital_car_park_check=lambda row: True,
                                                        osm_by_place_id={})
    assert "PP-1" in plan


def test_category_policy_plan_petrol_station_has_no_proximity_gate():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-2", "Location Name": "Shell Brixton", "Notes": "",
             "Verification Result": "", "Place Category": "Petrol station",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, _restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                        hospital_car_park_check=lambda row: False,
                                                        osm_by_place_id={})
    assert "PP-2" in plan


# ---- category policy: restricted-access rows are skipped ----------------------
def test_category_policy_skips_blue_badge_car_park():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-3", "Location Name": "Guy's Hospital Car Park (Blue Badge only)",
             "Notes": "", "Verification Result": "", "Place Category": "Hospital / health centre",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: True,
                                                       osm_by_place_id={})
    assert plan == {}
    assert restricted == 1


@pytest.mark.parametrize("word", ["disabled", "staff", "permit", "residents"])
def test_category_policy_skips_each_restricted_word(word):
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-4", "Location Name": f"Shell Brixton ({word} only)", "Notes": "",
             "Verification Result": "", "Place Category": "Petrol station",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: True,
                                                       osm_by_place_id={})
    assert plan == {}
    assert restricted == 1


def test_category_policy_checks_the_matched_osm_car_park_name_too():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-5", "Location Name": "Royal Free Hospital", "Notes": "",
             "Verification Result": "", "Place Category": "Hospital / health centre",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    osm_by_place_id = {"PP-5": {"OSM Car Park Name": "Staff Car Park", "OSM Raw Tags": ""}}
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: True,
                                                       osm_by_place_id=osm_by_place_id)
    assert plan == {}
    assert restricted == 1


def test_restricted_word_on_a_row_outside_the_policy_categories_is_not_counted():
    """A supermarket (no category policy exists for it) whose name happens
    to mention "staff" must not inflate restricted_count: it was never
    going to get a category policy fill either way."""
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-7", "Location Name": "Tesco Staff Car Park", "Notes": "",
             "Verification Result": "", "Place Category": "Supermarket - large format",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: True,
                                                       osm_by_place_id={})
    assert plan == {}
    assert restricted == 0


def test_category_policy_plain_name_is_not_restricted():
    categories = r2.load_categories()
    rows = [{"Place ID": "PP-6", "Location Name": "Royal Free Hospital", "Notes": "",
             "Verification Result": "", "Place Category": "Hospital / health centre",
             "Latitude": "51.5", "Longitude": "-0.1"}]
    plan, restricted = r2.build_category_policy_plan(rows, set(), categories, POLICIES, RULES, TODAY,
                                                       hospital_car_park_check=lambda row: True,
                                                       osm_by_place_id={})
    assert "PP-6" in plan
    assert restricted == 0


# ---- clear_unverified runs first ------------------------------------------------
def test_apply_clear_unverified_blanks_stale_values_on_unfinished_rows():
    rows = [{"Place ID": "PP-1", "_sheet_row": 2, "Verification Result": "",
             "Can Park? (Yes/No/Conditional)": "Yes", "Who Can Park": "", "Rules Summary": "",
             "Cost Type": "", "Price Status": "", "Tariff Type": "", "Tariff Detail": "",
             "Max Stay (mins)": "", "Hours (OpenStreetMap opening_hours format)": "",
             "Hours Basis": "", "Parking Control Type (Cameras / Barrier / Patrol)": "",
             "Operator": "", "PCN (Penalty Charge Notice) amount (£)": ""}]
    cleared = r2.apply_clear_unverified(rows)
    assert cleared[0]["Can Park? (Yes/No/Conditional)"] == ""


def test_apply_clear_unverified_leaves_finished_rows_alone():
    rows = [{"Place ID": "PP-1", "_sheet_row": 2, "Verification Result": "Confirmed",
             "Can Park? (Yes/No/Conditional)": "Yes"}]
    cleared = r2.apply_clear_unverified(rows)
    assert cleared[0]["Can Park? (Yes/No/Conditional)"] == "Yes"


# ---- write plan files (fill.py's generic plan/undo shape) --------------------
def test_to_write_plan_shape():
    plan = {"PP-1": ({"_sheet_row": 42, "Location Name": "X", "Who Can Park": ""},
                     {"Who Can Park": "Customers only"})}
    plan_list, undo_list = r2.to_write_plan(plan)
    assert plan_list == [{"sheet_row": 42, "place_id": "PP-1", "name": "X",
                          "new": {"Who Can Park": "Customers only"}}]
    assert undo_list == [{"sheet_row": 42, "place_id": "PP-1", "old": {"Who Can Park": ""}}]


def test_write_pass_files_round_trips_through_json(tmp_path):
    import json
    plan = {"PP-1": ({"_sheet_row": 2, "Location Name": "X", "Evidence Level": ""},
                     {"Evidence Level": "Not yet checked"})}
    plan_path, undo_path = r2.write_pass_files(plan, tmp_path / "not_yet_checked")
    assert json.loads(plan_path.read_text())[0]["place_id"] == "PP-1"
    assert json.loads(undo_path.read_text())[0]["old"] == {"Evidence Level": ""}


def test_second_reading_holds_out_a_failing_plan():
    bad = {"Cost Type": "Free", "Tariff Type": "Not published"}   # Free but tariff says not published
    plan = {"PP-1": ({"Place ID": "PP-1", "Location Name": "X"}, bad)}
    clean, failures = r2.second_reading(plan, "osm_fill")
    assert clean == {}
    assert len(failures) == 1
    assert failures[0]["Fill Type"] == "osm_fill"
    assert failures[0]["Place ID"] == "PP-1"
