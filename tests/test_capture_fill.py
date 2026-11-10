"""Tests for capture_fill.py: rule R8's status-word filter, the validator
(dropdowns, scope, rule R7, tariff templates), and the consistency checks
it shares with page_fill.py."""
from datetime import date

import pytest

from ferro_parking import capture_fill as cf

TODAY = date(2026, 11, 3)


def field(value, scope="site", quote="the page says so"):
    return {"value": value, "scope": scope, "quote": quote}


def full_record(**overrides):
    fields = {
        "can_park": field("Conditional"),
        "who_can_park": field("Customers only"),
        "cost_type": field("Free"),
        "tariff_type": field("Free (time limit not published)"),
        "tariff_detail": field("Free"),
        "max_stay_mins": field("Not published"),
        "hours_osm_format": field("Not published"),
        "hours_basis": field("Not published"),
        "control_type": field("Not published"),
        "operator": field("Not published"),
        "pcn_gbp": field("Not published"),
    }
    for name, value in overrides.items():
        fields[name] = value
    return {"place_id": "PP-1", "leave_for_grok": False, "reason": "", "fields": fields}


def sheet_row(**kw):
    base = {
        "Location Name": "Test Place", "Borough": "Greenwich",
        "Can Park? (Yes/No/Conditional)": "Conditional",
        "Source URLs (primary first)": "https://example.com/store",
        "Notes": "", "Review Flag": "", "Flag Status": "",
        "Geo Precision": "Building", "Verification Result": "", "Verified By": "",
        "Ferro Autopay": "", "Parking Charge (£)": "", "Place ID": "PP-1",
    }
    base.update(kw)
    return base


# ---- rule R8 status-word filter -----------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("UNCLEAR", True), ("Not published", True), ("VERIFY", True), ("TBC", True),
    ("", True), ("  ", True), ("UNCLEAR; not stated", True),
    ("Free parking for customers", False), ("UNCLEAR but Car Parking Available", False),
])
def test_is_status_only(text, expected):
    assert cf.is_status_only(text) == expected


def test_has_real_captured_text_true_when_one_column_has_content():
    row = sheet_row(**{"Notes": "Car Parking Available"})
    assert cf.has_real_captured_text(row) is True


def test_has_real_captured_text_false_when_every_column_is_a_status_word():
    row = sheet_row(**{"Notes": "UNCLEAR", "Charges (as published)": "Not stated"})
    assert cf.has_real_captured_text(row) is False


# ---- validator: dropdowns, scope, rule R7, tariff templates -------------------
def test_clean_record_has_no_violations():
    assert cf.validate_record(full_record()) == []


def test_invalid_dropdown_value_rejected():
    rec = full_record(cost_type=field("Half price"))
    assert any("not an allowed value" in v for v in cf.validate_record(rec))


def test_free_with_chain_scope_rejected_r7():
    rec = full_record(cost_type=field("Free", scope="chain"))
    assert any("scope 'site'" in v and "cost_type" in v for v in cf.validate_record(rec))


def test_anyone_with_none_scope_rejected_r7():
    rec = full_record(who_can_park=field("Anyone", scope="none"),
                       cost_type=field("Paid"), tariff_type=field("Not published"),
                       tariff_detail=field("Not published"))
    assert any("scope 'site'" in v and "who_can_park" in v for v in cf.validate_record(rec))


def test_numeric_max_stay_with_chain_scope_rejected():
    rec = full_record(max_stay_mins=field("60", scope="chain"),
                       tariff_type=field("Free with time limit"),
                       tariff_detail=field("Free for up to 60 mins"))
    assert any("max_stay_mins" in v for v in cf.validate_record(rec))


def test_free_with_site_scope_is_accepted():
    rec = full_record(cost_type=field("Free", scope="site"))
    assert cf.validate_record(rec) == []


def test_tariff_detail_must_match_template():
    rec = full_record(tariff_type=field("Hourly rate"), tariff_detail=field("cheap"))
    assert any("does not match the template" in v for v in cf.validate_record(rec))


def test_invalid_scope_value_rejected():
    rec = full_record(operator=field("Q-Park", scope="maybe"))
    assert any("invalid scope" in v for v in cf.validate_record(rec))


def test_can_park_no_requires_explicit_negative_phrase_r9():
    rec = full_record(can_park=field("No", quote="N/A on site, no parking facility listed"))
    assert any("R9" in v for v in cf.validate_record(rec))


def test_can_park_no_requires_explicit_negative_phrase_vue_eltham_r9():
    rec = full_record(can_park=field(
        "No", quote="Nearby car parks paid, tariff not stated on Vue page, not this venue's own car park"))
    assert any("R9" in v for v in cf.validate_record(rec))


def test_can_park_no_accepted_with_network_rail_wording():
    rec = full_record(can_park=field(
        "No", quote="There is no public car park at the station (Network Rail station guide)"))
    assert not any("R9" in v for v in cf.validate_record(rec))


def test_can_park_no_accepted_with_an_explicit_negative_statement():
    rec = full_record(can_park=field("No", quote="The store page states there is no customer parking"))
    assert not any("R9" in v for v in cf.validate_record(rec))


def test_no_car_parking_listed_does_not_match_no_car_park_r9():
    # "no car parking listed" must not satisfy the phrase "no car park" by
    # plain substring overlap: it is capture shorthand, not a denial.
    rec = full_record(can_park=field("No", quote="N/A on site (no car parking listed)"))
    assert any("R9" in v for v in cf.validate_record(rec))


def test_can_park_no_accepted_with_hotel_and_hospital_wording():
    for quote in ("N/A, no hotel parking", "N/A, no on-site hotel parking",
                  "N/A, no off-street hospital parking"):
        rec = full_record(can_park=field("No", quote=quote))
        assert cf.validate_record(rec) == [], quote


def test_can_park_no_accepted_with_no_on_site_car_park_wording():
    rec = full_record(can_park=field("No", quote="N/A, no on-site car park (hospital page)"))
    assert cf.validate_record(rec) == []


def test_can_park_no_rejected_for_no_customer_car_park_listed_shorthand():
    # Same "no X listed" shape as "no parking facility listed": a listing's
    # absence, not an explicit denial, so it stays rejected under R9.
    rec = full_record(can_park=field("No", quote="N/A on site (no customer car park listed)"))
    assert any("R9" in v for v in cf.validate_record(rec))


def test_can_park_no_rejected_when_scope_is_not_site_even_with_the_phrase():
    rec = full_record(can_park=field("No", scope="chain", quote="Chain policy: no customer parking"))
    assert any("R9" in v for v in cf.validate_record(rec))


def test_missing_field_rejected():
    rec = full_record()
    del rec["fields"]["operator"]
    assert any("missing field" in v for v in cf.validate_record(rec))


# ---- end to end: finish_record -------------------------------------------------
def osm_row(**kw):
    base = {"Route": "A. Operator or council page (text only)", "OSM Website": "",
            "Place ID": "PP-1", "Car Park Last Edited": "2026-01-01"}
    base.update(kw)
    return base


def captured(value="Conditional", place_id="PP-1"):
    """ALL LONDON's own Can Park?, by Place ID."""
    return {place_id: value}


def test_finish_record_builds_a_valid_new_dict():
    rec = full_record()
    new, violations = cf.finish_record(sheet_row(), osm_row(), rec, TODAY, captured())
    assert violations is None
    assert new["Cost Type"] == "Free"
    assert new["Verified By"] == cf.VERIFIED_BY
    assert new["Verified Date"] == "2026-11-03"


def test_finish_record_appends_notes_append_without_replacing_existing_notes():
    # capture_extract's hotel branch uses this to carry a valet detail or a
    # trailing condition that does not fit any of the eleven fields: it
    # must land in Notes alongside whatever Notes already said, not replace it.
    rec = full_record()
    rec["notes_append"] = ["Valet only."]
    row = sheet_row()
    row["Notes"] = "Existing note."
    new, violations = cf.finish_record(row, osm_row(), rec, TODAY, captured())
    assert violations is None
    assert new["Notes"] == "Existing note. | Valet only."


def test_finish_record_rejects_on_shared_consistency_check():
    # Can Park? No means every other parking column must be Not applicable;
    # validate_record does not check this, page_fill.consistency_checks does.
    rec = full_record(can_park=field("No", quote="the store page states there is no customer parking"),
                       who_can_park=field("Customers only"))
    new, violations = cf.finish_record(sheet_row(), osm_row(), rec, TODAY, captured())
    assert new is None
    assert any("Who Can Park" in v for v in violations)


def test_price_status_chain_policy_for_chain_scope():
    rec = full_record(cost_type=field("Paid", scope="chain"))
    assert cf.price_status_for(rec) == "Chain policy (not store-specific)"


def test_price_status_published_for_site_scope():
    rec = full_record(cost_type=field("Free", scope="site"))
    assert cf.price_status_for(rec) == "Published"


def test_price_status_not_published_when_cost_confirmed_but_price_is_not():
    # Paid confirmed (it is a commercial car park) but the actual tariff is
    # not published (Q-Park "prebook only" pattern): Price Status must stay
    # Not published, not Published, even though Cost Type is known.
    rec = full_record(cost_type=field("Paid", scope="site"),
                       tariff_detail=field("Not published", scope="site"))
    assert cf.price_status_for(rec) == "Not published"


def test_tfl_source_counts_as_operator_council_site():
    row = sheet_row(**{"Source URLs (primary first)": "https://api.tfl.gov.uk/Place/CarParks_1"})
    assert cf.source_tier_for(row, osm_row()) == "Operator / council site"


def test_autopay_price_mismatch_flagged():
    row = sheet_row(**{"Ferro Autopay": "✅", "Parking Charge (£)": "5.00"})
    rec = full_record(cost_type=field("Paid", scope="site"),
                       tariff_type=field("Hourly rate"),
                       tariff_detail=field("£6.00 per hour", scope="site"))
    new, violations = cf.finish_record(row, osm_row(), rec, TODAY, captured())
    assert violations is None
    assert "Autopay price differs" in new["Review Flag"]
    assert new["Flag Status"] == "Open"
