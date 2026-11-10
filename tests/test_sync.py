"""Tests for sync.py, built from real aligned row pairs between
"ALL LONDON" and "ALL LONDON (clean)" (sheet rows 2, 5, and 8)."""
from ferro_parking import sync


def orig_row(**overrides):
    base = {
        "sheet": "Salisbury Street Car Park (Ealing Council, ref A02)",
        "Address / Postcode": "Salisbury Street, Acton, London W3 8NW",
        "Type (Public/Private/Retail/Hotel/etc.)": "Public Car Park (Council, surface)",
        "Can Park? (Yes/No/Conditional)": "No",
        "Parking Rules / Restrictions": 'Council pay-by-phone car park. Council page marks '
            'it "temporarily closed due to development". When open: pay via PayByPhone '
            "location 37208; charges apply 8am-6pm Mon-Sun.",
        "Max Stay": "Not stated",
        "Charges / Fees": "When open: £1.30-£2.60 per hour depending on vehicle "
            "emissions (Ealing 'hourly rate 4' tariff). Annual season ticket £778.50, "
            "quarterly permit £311.40. Free on bank holidays (council-wide).",
        "Hours / Days Allowed": "Open 24 hours; charging hours 8am-6pm Mon-Sun (when open)",
        "Enforcement / Penalties": "Ealing Council (council PCN enforcement; amount not "
            "stated on page)",
        "Source URL": "https://www.ealing.gov.uk/info/201178/parking/640/"
            "car_parks_and_other_visitor_information/3",
        "Notes / Special Conditions": "CURRENTLY CLOSED (development). 62 regular bays, 4 "
            "disabled, 4 motorcycle, 1 car club bay.",
        "Date Captured": "2026-10-30",
        "Verified By": "PP",
        "Location Status (Open / Closed)": "Temporarily closed",
        "Latitude": "51.505716",
        "Longitude": "-0.267111",
        "Geo Source / Precision": "OSM – car park (Salisbury Street Car Park)",
        "Borough": "Ealing",
    }
    base.update(overrides)
    return base


# ---- real aligned pair: sheet row 2, "Salisbury Street Car Park" ---------
def test_salisbury_street_car_park_maps_direct_fields_exactly():
    mapped = sync.map_row(orig_row())
    assert mapped["Location Name"] == "Salisbury Street Car Park (Ealing Council, ref A02)"
    assert mapped["Type (as captured)"] == "Public Car Park (Council, surface)"
    assert mapped["Borough"] == "Ealing"
    assert mapped["Date Captured"] == "2026-10-30"
    assert mapped["Captured By"] == "PP"
    assert mapped["Latitude"] == "51.505716"
    assert mapped["Longitude"] == "-0.267111"
    assert mapped["Geo (as captured)"] == "OSM – car park (Salisbury Street Car Park)"
    assert mapped["Location Status"] == "Temporarily closed"


def test_salisbury_street_car_park_splits_address():
    mapped = sync.map_row(orig_row())
    assert mapped["Street Address"] == "Salisbury Street, Acton, London"
    assert mapped["Postcode"] == "W3 8NW"


# ---- real aligned pair: sheet row 5, "Lidl East Acton" --------------------
def test_lidl_east_acton_maps_direct_fields_and_status():
    row = orig_row(
        **{"sheet": "Lidl East Acton (Western Avenue)",
           "Address / Postcode": "Western Avenue, East Acton, London W3 7XX",
           "Type (Public/Private/Retail/Hotel/etc.)": "Retail – Supermarket",
           "Max Stay": "Not published",
           "Charges / Fees": "Not published",
           "Hours / Days Allowed": "Not published (store hours apply)",
           "Enforcement / Penalties": "Not published by Lidl",
           "Source URL": "https://www.lidl.co.uk/s/en-GB/store-finder/east-acton/"
               "western-avenue/",
           "Notes / Special Conditions": "Disabled parking; EV charging. NO OFFICIAL INFO "
               "on max stay/charges - flag.",
           "Location Status (Open / Closed)": "Open",
           "Latitude": "51.513538", "Longitude": "-0.249449",
           "Geo Source / Precision": "OSM – building/POI (Lidl Western Avenue)"})
    mapped = sync.map_row(row)
    assert mapped["Location Name"] == "Lidl East Acton (Western Avenue)"
    assert mapped["Charges (as published)"] == "Not published"
    assert mapped["Max Stay (as captured)"] == "Not published"
    assert mapped["Hours (as captured)"] == "Not published (store hours apply)"
    assert mapped["Street Address"] == "Western Avenue, East Acton, London"
    assert mapped["Postcode"] == "W3 7XX"
    assert mapped["Location Status"] == "Open"


# ---- real aligned pair: sheet row 8, "Travelodge London Park Royal" ------
def test_travelodge_park_royal_maps_direct_fields():
    row = orig_row(
        **{"sheet": "Travelodge London Park Royal",
           "Address / Postcode": "614 Western Avenue, London W3 0TE",
           "Type (Public/Private/Retail/Hotel/etc.)": "Hotel",
           "Max Stay": "3 nights (max payable)",
           "Charges / Fees": "Guests £9.50 per 24 hours",
           "Hours / Days Allowed": "24/7",
           "Enforcement / Penalties": "Horizon Parking; ANPR cameras. PCN amount not stated",
           "Source URL": "https://www.travelodge.co.uk/hotels/50/London-Park-Royal-hotel",
           "Notes / Special Conditions": "Blue Badge holders exempt from charges.",
           "Location Status (Open / Closed)": "Open",
           "Latitude": "51.527085", "Longitude": "-0.278669",
           "Geo Source / Precision": "postcodes.io – postcode centroid (W3 0TE)"})
    mapped = sync.map_row(row)
    assert mapped["Location Name"] == "Travelodge London Park Royal"
    assert mapped["Street Address"] == "614 Western Avenue, London"
    assert mapped["Postcode"] == "W3 0TE"
    assert mapped["Max Stay (as captured)"] == "3 nights (max payable)"
    assert mapped["Hours (as captured)"] == "24/7"


# ---- split_address edge cases seen in the real sheet ----------------------
def test_split_address_handles_bare_outward_code_with_no_inward_part():
    # Sheet row 11: no full postcode captured, only the outward code.
    street, postcode = sync.split_address("South Acton, London W3")
    assert street == "South Acton, London"
    assert postcode == "W3"


def test_split_address_finds_a_full_postcode_mid_string():
    # Sheet row 13: postcode sits before a trailing parenthetical note.
    street, postcode = sync.split_address(
        "Entrance via Popes Lane, London W3 8LQ (satnav postcode)")
    assert postcode == "W3 8LQ"


def test_split_address_with_no_postcode_at_all():
    street, postcode = sync.split_address("Somewhere with no postcode")
    assert street == "Somewhere with no postcode"
    assert postcode == ""


# ---- Location Status -------------------------------------------------------
def test_map_location_status_known_values():
    assert sync.map_location_status("Open") == "Open"
    assert sync.map_location_status("Closed") == "Closed"
    assert sync.map_location_status("Temporarily closed") == "Temporarily closed"
    assert sync.map_location_status("Active") == "Open"


def test_map_location_status_unknown_free_text_is_unknown_not_guessed():
    # The real sheet shows this exact shape of free text landing on
    # different clean values depending on human judgment; this function
    # must not guess, it must say Unknown.
    assert sync.map_location_status("DUPLICATE of row 147 - see that row") == "Unknown"
    assert sync.map_location_status("UNCLEAR - store page shows closed all week") == "Unknown"


# ---- research-only fields are never silently mapped ------------------------
def test_map_row_never_sets_a_research_only_field():
    mapped = sync.map_row(orig_row())
    for field in sync.RESEARCH_ONLY_FIELDS:
        assert field not in mapped


# ---- duplicate detection ----------------------------------------------------
def clean_row(**kw):
    base = {"Location Name": "Nando's Wood Green", "Postcode": "N22 6LA",
            "Brand": "Nando's", "Latitude": "51.598", "Longitude": "-0.109"}
    base.update(kw)
    return base


def test_find_duplicates_matches_on_normalized_name_and_postcode():
    new_row = {"sheet": "Nando's Wood Green (High Road)", "Address / Postcode": "N22 6LA",
               "Type (Public/Private/Retail/Hotel/etc.)": "Restaurant (Nando's)",
               "Latitude": "51.598", "Longitude": "-0.109"}
    dups = sync.find_duplicates([new_row], [clean_row()])
    assert any(reason == "same name and postcode" for _, _, reason in dups)


def test_find_duplicates_matches_on_brand_within_radius():
    # Same brand, no postcode in the new row's address, but 20 m away.
    new_row = {"sheet": "Nando's Wood Green branch 2", "Address / Postcode": "no postcode here",
               "Type (Public/Private/Retail/Hotel/etc.)": "Restaurant (Nando's)",
               "Latitude": "51.59815", "Longitude": "-0.10905"}
    dups = sync.find_duplicates([new_row], [clean_row()])
    assert any("same brand within" in reason for _, _, reason in dups)


def test_find_duplicates_does_not_flag_a_genuinely_new_place():
    new_row = {"sheet": "A Totally Different Place", "Address / Postcode": "SW1A 1AA",
               "Type (Public/Private/Retail/Hotel/etc.)": "Hotel",
               "Latitude": "51.501", "Longitude": "-0.141"}
    dups = sync.find_duplicates([new_row], [clean_row()])
    assert dups == []


def test_haversine_m_known_distance():
    # Roughly 111 km per degree of latitude at the equator.
    distance = sync.haversine_m(0.0, 0.0, 1.0, 0.0)
    assert 110_000 < distance < 112_000


# ---- captured_can_park_by_place_id: ALL LONDON's own Can Park? by row --
def test_captured_can_park_by_place_id_joins_by_id():
    clean_rows = [{"Place ID": "PP-1"}, {"Place ID": "PP-2"}]
    orig_rows = [{"Place ID": "PP-2", "Can Park? (Yes/No/Conditional)": "Conditional"},
                 {"Place ID": "PP-1", "Can Park? (Yes/No/Conditional)": "No"}]
    out = sync.captured_can_park_by_place_id(clean_rows, orig_rows)
    assert out == {"PP-1": "No", "PP-2": "Conditional"}


def test_captured_can_park_by_place_id_uses_all_london_even_when_clean_is_blank():
    # A cleared or not-yet-researched clean row has no Can Park? of its
    # own; the lookup is keyed by Place ID and reads ALL LONDON only.
    clean_rows = [{"Place ID": "PP-1", "Can Park? (Yes/No/Conditional)": ""}]
    orig_rows = [{"Place ID": "PP-1", "Can Park? (Yes/No/Conditional)": "No"}]
    out = sync.captured_can_park_by_place_id(clean_rows, orig_rows)
    assert out["PP-1"] == "No"


def test_captured_can_park_by_place_id_skips_a_row_with_no_place_id():
    clean_rows = [{"Place ID": ""}]
    orig_rows = [{"Place ID": "PP-1", "Can Park? (Yes/No/Conditional)": "No"}]
    import pytest
    with pytest.raises(ValueError, match="alignment"):
        sync.captured_can_park_by_place_id(clean_rows, orig_rows)


# ---- applying the plan: formula shifting and row building ------------------
def test_shift_formula_row_postcode_area_pattern():
    template = '=IF(G4774="","",IFERROR(REGEXEXTRACT(G4774,"^[A-Z]{1,2}[0-9][A-Z0-9]?"),""))'
    shifted = sync.shift_formula_row(template, 4774, 4775)
    assert shifted == '=IF(G4775="","",IFERROR(REGEXEXTRACT(G4775,"^[A-Z]{1,2}[0-9][A-Z0-9]?"),""))'


def test_shift_formula_row_confidence_pattern_moves_every_reference():
    template = "=IF(AE4774=\"\",\"\",LET(base,SWITCH(AE4774,\"x\",1),spec,SWITCH(AF4774,\"y\",2),0))"
    shifted = sync.shift_formula_row(template, 4774, 5000)
    assert "4774" not in shifted
    assert shifted.count("5000") == 3


def test_shift_formula_row_does_not_touch_an_unrelated_row_number():
    # A literal numeric constant that happens to equal the row number must
    # not be mistaken for a cell reference: it has no column letter.
    template = '=IF(G4774="","",4774)'
    shifted = sync.shift_formula_row(template, 4774, 4775)
    assert shifted == '=IF(G4775="","",4774)'


def test_row_values_leaves_brandons_columns_and_filled_formulas_blank():
    headers = ["Location Name", "Postcode Area", "Confidence (1-5)",
               "Free Stay Countdown (mins)", "Ferro Autopay", "Parking Charge (£)",
               "Total incl. Ferro Fee (£)", "Place ID"]
    plan_row = {"Location Name": "Test Place", "Postcode Area": "W3", "Confidence (1-5)": "3",
                "Free Stay Countdown (mins)": "120", "Ferro Autopay": "✅",
                "Parking Charge (£)": "1.5", "Total incl. Ferro Fee (£)": "3.1",
                "Place ID": "PP-005000"}
    values = sync.row_values(plan_row, headers)
    assert values == ["Test Place", "", "", "", "", "", "", "PP-005000"]
