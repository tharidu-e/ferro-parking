"""Tests for page_fill.py: the routes A/B eligibility filter, page URL
choice, the Autopay price check, Notes/Review Flag appending, the
protected-column assert, and the validator prompt's consistency checks."""
from datetime import date

import pytest

from ferro_parking import page_fill as pf

TODAY = date(2026, 11, 2)


def sheet_row(**kw):
    base = {
        "Location Name": "Test Place", "Borough": "Greenwich",
        "Can Park? (Yes/No/Conditional)": "Conditional",
        "Source URLs (primary first)": "https://example.com/store ; https://other.example.com",
        "Notes": "", "Review Flag": "", "Flag Status": "",
        "Geo Precision": "Building", "Verification Result": "", "Verified By": "",
        "Ferro Autopay": "", "Parking Charge (£)": "", "Place ID": "PP-1",
    }
    base.update(kw)
    return base


def osm_row(route, **kw):
    base = {"Route": route, "OSM Website": "", "Place ID": "PP-1"}
    base.update(kw)
    return base


# ---- eligibility filter ------------------------------------------------------
def test_candidate_picks_route_a_and_b_only():
    rows = [sheet_row(Place_ID="PP-1", **{"Place ID": "PP-1"}),
            sheet_row(Place_ID="PP-2", **{"Place ID": "PP-2"}),
            sheet_row(Place_ID="PP-3", **{"Place ID": "PP-3"})]
    osms = [osm_row("A. Operator or council page (text only)", **{"Place ID": "PP-1"}),
            osm_row("C. OSM car park + official page check", **{"Place ID": "PP-2"}),
            osm_row("B. Branch page + chain rule", **{"Place ID": "PP-3"})]
    out = pf.candidate_rows_ab(rows, osms, "Greenwich")
    ids = {s["Place ID"] for s, o in out}
    assert ids == {"PP-1", "PP-3"}


def test_candidate_excludes_already_finished_rows():
    rows = [sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed"})]
    osms = [osm_row("A. x", **{"Place ID": "PP-1"})]
    assert pf.candidate_rows_ab(rows, osms, "Greenwich") == []


def test_candidate_excludes_rows_verified_by_a_person():
    rows = [sheet_row(**{"Place ID": "PP-1", "Verified By": "Tharidu"})]
    osms = [osm_row("A. x", **{"Place ID": "PP-1"})]
    assert pf.candidate_rows_ab(rows, osms, "Greenwich") == []


def test_candidate_filters_by_borough():
    rows = [sheet_row(**{"Place ID": "PP-1", "Borough": "Camden"})]
    osms = [osm_row("A. x", **{"Place ID": "PP-1"})]
    assert pf.candidate_rows_ab(rows, osms, "Greenwich") == []


# ---- page URL -----------------------------------------------------------------
def test_page_url_prefers_first_http_source_url():
    assert pf.page_url(sheet_row(), osm_row("A. x")) == "https://example.com/store"


def test_page_url_falls_back_to_osm_website():
    sr = sheet_row(**{"Source URLs (primary first)": ""})
    assert pf.page_url(sr, osm_row("A. x", **{"OSM Website": "https://store.example.com"})) \
        == "https://store.example.com"


# ---- Autopay price check -------------------------------------------------------
def test_autopay_price_flag_on_mismatch():
    sr = sheet_row(**{"Ferro Autopay": "✅", "Parking Charge (£)": "2.50"})
    assert pf.autopay_price_flag(sr, "£3.00 per hour") == "Autopay price differs: sheet £2.50, source £3.00"


def test_autopay_price_flag_none_when_matching():
    sr = sheet_row(**{"Ferro Autopay": "✅", "Parking Charge (£)": "2.50"})
    assert pf.autopay_price_flag(sr, "£2.50 per hour") is None


def test_autopay_price_flag_none_when_not_autopay():
    sr = sheet_row(**{"Ferro Autopay": "", "Parking Charge (£)": "2.50"})
    assert pf.autopay_price_flag(sr, "£3.00 per hour") is None


def test_autopay_price_flag_uses_only_the_first_price_in_a_banded_detail():
    # Stripping every non-digit character from the whole string would run
    # all four band prices together into one meaningless number instead of
    # reading the first one, £6.00.
    sr = sheet_row(**{"Ferro Autopay": "✅", "Parking Charge (£)": "25.00"})
    detail = "0-1 hrs £6.00; 1-2 hrs £12.00; 2-3 hrs £18.00; 3-4 hrs £24.00; 4-24 hrs £25.00"
    assert pf.autopay_price_flag(sr, detail) == "Autopay price differs: sheet £25.00, source £6.00"


# ---- build_row_values: Notes/Review Flag appending, protected columns ---------
def captured(value="Conditional", place_id="PP-1"):
    """ALL LONDON's own Can Park?, by Place ID."""
    return {place_id: value}


def test_notes_appended_not_replaced():
    sr = sheet_row(Notes="Existing note.")
    extracted = {"Can Park? (Yes/No/Conditional)": "Conditional", "_notes": ["Page says free for 2 hrs"]}
    new = pf.build_row_values(sr, extracted, TODAY, captured())
    assert new[pf.NOTES] == "Existing note. | Page says free for 2 hrs"


def test_review_flag_appended_and_flag_status_opened():
    sr = sheet_row(**{"Review Flag": "Possible duplicate of row 5"})
    extracted = {"Can Park? (Yes/No/Conditional)": "Conditional",
                 "_flags": ["Autopay price differs: sheet £2.50, source £3.00"]}
    new = pf.build_row_values(sr, extracted, TODAY, captured())
    assert new[pf.REVIEW_FLAG] == "Possible duplicate of row 5; Autopay price differs: sheet £2.50, source £3.00"
    assert new[pf.FLAG_STATUS] == "Open"


def test_change_made_set_when_can_park_differs_from_captured():
    # ALL LONDON's own Can Park? was "Unknown"; the clean tab's current
    # value (which may be blank, cleared, or unresearched) plays no part.
    sr = sheet_row()
    new = pf.build_row_values(sr, {"Can Park? (Yes/No/Conditional)": "Yes"}, TODAY, captured("Unknown"))
    assert new[pf.fill.CHANGE_MADE] == "Yes"


def test_change_made_set_from_all_london_even_when_clean_tab_blank():
    # The clean tab's own Can Park? is blank (cleared); ALL LONDON still
    # says "No", so writing "Conditional" still counts as a change.
    sr = sheet_row(**{"Can Park? (Yes/No/Conditional)": ""})
    new = pf.build_row_values(sr, {"Can Park? (Yes/No/Conditional)": "Conditional"}, TODAY, captured("No"))
    assert new[pf.fill.CHANGE_MADE] == "Yes"


def test_build_row_values_never_touches_a_protected_column():
    with pytest.raises(AssertionError):
        pf.build_row_values(sheet_row(), {"Latitude": "1"}, TODAY, captured())


def test_build_row_values_sets_verified_by_and_date():
    new = pf.build_row_values(sheet_row(), {"Can Park? (Yes/No/Conditional)": "Conditional"}, TODAY,
                               captured())
    assert new[pf.fill.VERIFIED_BY] == "Claude (page check)"
    assert new[pf.fill.VERIFIED_DATE] == "2026-11-02"


# ---- consistency checks --------------------------------------------------------
def clean_row(**overrides):
    row = {
        "Can Park? (Yes/No/Conditional)": "Conditional", "Who Can Park": "Customers only",
        "Cost Type": "Free", "Price Status": "Published", "Tariff Type": "Free with time limit",
        "Tariff Detail": "Free for up to 60 mins", "Max Stay (mins)": "60",
        "Source Tier": "Official site - text", "Review Flag": "", "Flag Status": "",
        "Decision Reason": "Route A: store page states free parking for 60 minutes.",
    }
    row.update(overrides)
    return row


def test_clean_row_has_no_violations():
    assert pf.consistency_checks(clean_row()) == []


def test_free_cost_type_requires_free_tariff_type():
    row = clean_row(**{"Cost Type": "Free", "Tariff Type": "Not published"})
    assert any("Tariff Type" in v for v in pf.consistency_checks(row))


def test_can_park_yes_requires_a_strong_source():
    row = clean_row(**{"Can Park? (Yes/No/Conditional)": "Yes", "Source Tier": "Google Maps - About"})
    assert any("not a strong source" in v for v in pf.consistency_checks(row))


def test_review_flag_without_flag_status_is_flagged():
    row = clean_row(**{"Review Flag": "Something to check"})
    assert any("Flag Status is blank" in v for v in pf.consistency_checks(row))


def test_decision_reason_must_name_the_route():
    row = clean_row(**{"Decision Reason": "Free parking confirmed."})
    assert any("Decision Reason" in v for v in pf.consistency_checks(row))


def test_can_park_no_requires_not_applicable_everywhere():
    row = clean_row(**{"Can Park? (Yes/No/Conditional)": "No", "Who Can Park": "Unknown"})
    assert any("Who Can Park" in v for v in pf.consistency_checks(row))
