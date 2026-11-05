"""Tests for capture_extract.py: the pattern-match classifier capture_fill
uses to build extracted.jsonl automatically. Each test uses captured text
taken from the real Westminster rows (quoted in the comments), not made-up
text, so a change to the classifier that breaks a known real case fails here
first.
"""
from ferro_parking import capture_extract as ce
from ferro_parking import capture_fill as cf


def sheet_row(place_id, type_captured="", charges="", hours="", enforcement="", notes=""):
    return {
        "Place ID": place_id,
        "Type (as captured)": type_captured,
        "Max Stay (as captured)": "",
        "Hours (as captured)": hours,
        "Geo (as captured)": "",
        "Charges (as published)": charges,
        "Enforcement Details": enforcement,
        "Notes": notes,
    }


OSM_ROW = {}


# ---- PP-000798: APCOA "1h £5.15" style, from Network Rail's Paddington page --
def test_apcoa_1h_style_bands():
    row = sheet_row(
        "PP-000798", type_captured="Station Car Park",
        charges=("APCOA Paddington Station car park (code 2085, Bishops Bridge Road W2 6AA). "
                 "Mon–Fri: up to 1h £5.15, 3h £11.50, 6h £22.00, 12h £29.80, "
                 "24h £35.20; night (6pm–6am) £11.50. Weekends/BH: full day £16.90; "),
        hours="Not stated on NRE",
        enforcement="APCOA Parking (UK) Ltd (per Network Rail)",
        notes=("Station operator: Network Rail. Network Rail lists 'Paddington Station Car Park "
               "off of Platform 1', APCOA, 152 spaces, 24h, chargeable for all vehicle"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Yes"
    assert rec["fields"]["operator"]["value"] == "APCOA"
    assert rec["fields"]["tariff_detail"]["value"] == (
        "0-1 hrs £5.15; 1-3 hrs £11.50; 3-6 hrs £22.00; 6-12 hrs £29.80; 12-24 hrs £35.20")
    assert rec["fields"]["max_stay_mins"]["value"] == "No limit"


# ---- PP-000799: one sentence runs the weekday and weekend rate together ----
def test_weekday_weekend_split_in_one_sentence_keeps_only_weekday_bands():
    row = sheet_row(
        "PP-000799", type_captured="Station Car Park",
        charges=("APCOA tariff: Monday - Friday | Up to 1 hour: £5.15 | Up to 3 hours: "
                 "£11.50 | Up to 6 hours: £22.00 | Up to 12 hours: £29.80 | "
                 "Up to 24 hours: £35.20 | Night rate (6pm-6am): £11.50 | Weekends and Bank"),
        hours="Mon–Fri: 24 hours; Sat: 24 hours; Sun: 24 hours",
        enforcement="APCOA Parking (UK) Limited (car park operator); PCN amount not stated on NRE",
        notes=("Car park operator: APCOA Parking (UK) Limited. Station operator: Network Rail. "
               "CCTV: yes. Accessible parking: Parking is chargeable for all vehicles H"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    # Five weekday bands only: the weekend rate after "Weekends and Bank" is cut off,
    # not folded in as a sixth band or used to overwrite a weekday price.
    assert rec["fields"]["tariff_detail"]["value"] == (
        "0-1 hrs £5.15; 1-3 hrs £11.50; 3-6 hrs £22.00; 6-12 hrs £29.80; 12-24 hrs £35.20")
    assert rec["fields"]["hours_osm_format"]["value"] == "24/7"


# ---- PP-000124: Q-Park "prebook only", no published tariff ----------------
def test_q_park_prebook_only_leaves_tariff_not_published():
    row = sheet_row(
        "PP-000124", type_captured="Q-Park",
        charges=("UNCLEAR – no tariff published online; prebook price quoted on booking; "
                 "card payment (Maestro/Mastercard/Visa)"),
        hours="24/7 (Mon–Sun)",
        enforcement="Q-Park (operator); penalty/PCN not stated on page",
        notes=("Operator: Q-Park. 311 spaces; height limit 2.03 m; services listed: AED, CCTV "
               "in operation, Lift, Help point, Information, Shoe polisher; UNCLEAR: no "),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["cost_type"]["value"] == "Unknown"
    assert rec["fields"]["tariff_type"]["value"] == "Not published"
    assert rec["fields"]["tariff_detail"]["value"] == "Not published"
    assert rec["fields"]["operator"]["value"] == "Q-Park"
    assert rec["fields"]["hours_osm_format"]["value"] == "24/7"


# ---- PP-001363: Waitrose, "may be generic" so the record is chain scope ---
def test_waitrose_may_be_generic_is_chain_scope():
    row = sheet_row(
        "PP-001363", type_captured="Supermarket",
        notes=("Facilities: Disabled car parking, Customer car park. VERIFY: Waitrose lists car "
               "park at ~75% of stores incl. central sites – may be generic."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["scope"] == "chain"
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["who_can_park"]["value"] == "Customers only"


# ---- Royal Parks per-15-minute tariff: must stay left for Grok ------------
def test_royal_parks_per_15_minute_tariff_stays_left_for_grok():
    # "70p/15min" and "£2.80/h" never produce the "<N>h ... £<price>" shape
    # parse_bands looks for, so this can never be misread as an hourly band
    # even if a future change widened the operator-car-park keyword list.
    charges = ("Mon–Sat: 70p/15min, £2.80/h, £11.20 for 4h. "
               "Sun & BH: 50p/15min, £2/h, £20 for 10h.")
    assert len(ce.parse_bands(charges)) < 2

    row = sheet_row(
        "PP-002141", type_captured="Park / Attraction",
        charges=charges,
        hours="Charges 8:30am–6:30pm daily; vehicle gates open 5am",
        enforcement=("Excess Charge Notice issued by NSL on behalf of The Royal Parks; amount "
                      "not published (UNCLEAR); appeals via royalparks.org.uk/parking-fines-appeals"),
        notes="Blue Badge free (4h limit); motorcycles free (4h).",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is True


# ---- regressions found by the second-reading check on the Westminster plan --
def test_operator_regex_stops_before_station_operator_appended():
    # Was: "APCOA Parking (UK) Limited. Station operator" (a greedy match
    # across the full stop and into the next sentence).
    row = sheet_row(
        "PP-000799", type_captured="Station Car Park",
        charges="Monday - Friday | Up to 1 hour: £5.15 | Up to 2 hours: £9.00",
        hours="Mon–Fri: 24 hours",
        notes=("Car park operator: APCOA Parking (UK) Limited. Station operator: Network Rail."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["operator"]["value"] == "APCOA Parking (UK) Limited"


def test_two_separate_tariff_schedules_are_not_concatenated():
    # A standard schedule followed by an unrelated emission-based schedule in
    # the same sentence must not be read as one continuous band sequence.
    charges = ("Turn Up & Park: 1h £6.50; 2h £12.00; 12h £28.00; 24h £34.00. "
               "Emission Based Green Tariff: 1h £5.50; 2h £11.00; 12h £25.00.")
    bands = ce.parse_bands(charges)
    assert bands == [(1, 6.50), (2, 12.00), (12, 28.00), (24, 34.00)]


def test_24hr_no_space_spelling_counts_as_24_7():
    assert ce.extract_hours_osm("Mon-Sun 24HR") == "24/7"
    assert ce.extract_hours_osm("Mon-Sun 24Hr") == "24/7"


def test_bare_midnight_timestamp_is_not_24_7():
    # Mon closes at 22:00, only Sun runs the full day: one 00:00 is a close
    # time on a non-24-hour day, not evidence the car park never shuts.
    assert ce.extract_hours_osm("Mon 00:00-22:00, Tue-Fri 06:00-22:00, Sun 00:00-00:00") is None


def test_max_stay_uses_the_captured_column_when_it_states_a_limit():
    row = sheet_row(
        "PP-003815", type_captured="CitiPark",
        charges="1h £6.50; 2h £12.00",
        hours="Mon-Sun 24 hours",
        notes="CitiPark operator",
    )
    row["Max Stay (as captured)"] = "24 hours"
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["max_stay_mins"]["value"] == "1440"


def test_max_stay_stays_no_limit_when_the_captured_column_has_no_number():
    row = sheet_row(
        "PP-000798", type_captured="Station Car Park",
        charges="1h £5.15; 3h £11.50",
        hours="Not stated on NRE", notes="APCOA",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["max_stay_mins"]["value"] == "No limit"


def test_negated_customer_car_park_is_not_read_as_a_customer_car_park():
    row = sheet_row(
        "PP-004215", type_captured="Supermarket",
        notes="NO OFFICIAL INFO; no customer car park listed on the store page.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("who_can_park", {}).get("value") != "Customers only"


def test_not_sun_tag_keeps_the_band_unlike_sat_sun_only():
    # The Fox on the Hill - Camberwell (Southwark): "(not Sun)" excludes one
    # day, it does not restrict the band to the weekend the way "(Sat/Sun
    # only)" does, so this band must still be kept.
    charges = "3 hours £15.00; 4 hours £20.00 (not Sun); 5 hours £25.00"
    assert ce.parse_bands(charges) == [(3, 15.00), (4, 20.00), (5, 25.00)]


def test_r9_rejects_a_during_events_only_restriction():
    # Lee Valley Hockey and Tennis Centre (Waltham Forest): the denial only
    # holds during events, and the venue has 167 real spaces otherwise.
    row = sheet_row(
        "PP-001902", type_captured="Sports Centre",
        notes="No car park access during events (public transport only). 167 spaces, 15 disabled.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("can_park", {}).get("value") != "No"


def test_customer_car_park_ignores_a_distinct_from_other_row_cross_reference():
    # Kings Mall Car Park (Hammersmith and Fulham): Notes only says this row
    # is distinct from a different row that happens to be a customer car
    # park (Sainsbury's Kings Mall, row 689); that is not a statement that
    # THIS car park is a customer car park.
    row = sheet_row(
        "PP-001030", type_captured="Retail / Shopping Centre",
        notes="Distinct from row 689 (Sainsbury's Kings Mall customer car park).",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("who_can_park", {}).get("value") != "Customers only"


def test_operator_ignores_a_same_car_park_as_other_row_cross_reference():
    # Richmond (London) Station via Drummond Place: "Same car park as NCP
    # row 492" names a different database row for the same physical car
    # park, not a statement that NCP operates this station's car park
    # (whose own text says the operator is not stated on NRE).
    row = sheet_row(
        "PP-000845", type_captured="Station Car Park (National Rail)",
        charges="UNCLEAR – no tariff published on NRE",
        hours="Not stated on NRE",
        notes=("Station operator: South Western Railway. UNCLEAR – car park operator not "
               "stated on NRE. Same car park as NCP row 492 (Drummond Place, 5 disabled bays)."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["operator"]["value"] == "Not published"


def test_operator_ignores_a_see_other_row_cross_reference():
    # Rainham (Essex) Station (Havering): Notes cross-references "see NCP
    # row 496", a pointer to a different database row, not a statement that
    # NCP operates this c2c-run station's car park.
    row = sheet_row(
        "PP-000849", type_captured="Station Car Park (National Rail)",
        charges="UNCLEAR – no tariff published on NRE",
        hours="Not stated on NRE",
        notes=("Station operator: c2c. UNCLEAR – car park operator not stated on NRE. "
               "Entrance to Rainham Station car park – see NCP row 496."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["operator"]["value"] == "Not published"


def test_r9_rejects_a_boilerplate_swr_check_for_a_non_swr_station():
    # Goodmayes (Redbridge): Station operator is Elizabeth line, but the
    # only R9-qualifying text cites checking South Western Railway's own
    # site, a station SWR does not serve. That boilerplate check must not
    # count as a statement about this station.
    row = sheet_row(
        "PP-000411", type_captured="Station",
        notes=("Station operator: Elizabeth line. Accessible spaces: 4. Checked SWR station page "
               "southwesternrailway.com/travelling-with-us/at-the-station/goodmayes 30/10/2026: "
               "car parking not available at this station. (operator XR)"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("can_park", {}).get("value") != "No"


def test_r9_still_accepts_a_genuinely_swr_operated_station():
    row = sheet_row(
        "PP-000835", type_captured="Station",
        notes=("Station operator: South Western Railway. Checked SWR station page "
               "southwesternrailway.com/travelling-with-us/at-the-station/putney 30/10/2026: "
               "car parking not available at this station."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["can_park"]["value"] == "No"


def test_pay_on_the_day_ui_heading_is_not_read_as_confirmed_paid():
    # London Finsbury Forecourt (NCP), Islington: "('Pay on the day' heading
    # shown with no rows)" names a page heading, not a confirmation that the
    # car park charges; it always sits next to UNCLEAR in the real data.
    row = sheet_row(
        "PP-000486", type_captured="NCP",
        charges=("UNCLEAR – no tariff rows shown on official page | Season Tickets "
                 "from as little as £12.87 per day. ('Pay on the day' heading shown with no rows)"),
        hours="Mon–Sun 24 hours",
        notes="Operator: NCP; Total spaces: 12.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["cost_type"]["value"] == "Unknown"


def test_operator_read_from_type_captured_when_notes_only_has_the_abbreviation():
    # Type (as captured) names "Euro Car Parks" plainly; Notes only has the
    # abbreviation "ECP", which the old notes-only regex never matched.
    row = sheet_row(
        "PP-003922", type_captured="Euro Car Parks",
        charges="1h £4.00; 2h £7.00",
        hours="Mon-Sun 24 hours",
        notes="ECP car park; CCTV in operation.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["operator"]["value"] == "Euro Car Parks"


def test_sat_sun_only_bands_are_not_read_as_an_all_days_rate():
    # The Atrium - Uxbridge (Hillingdon): the 2h/4h bands are "(all days)",
    # the 6h/8h/12h bands are "(Sat/Sun only)". A weekday tariff must stop
    # at the "(all days)" bands and not pick up the weekend-only prices.
    charges = ("2 hours £2.20; 4 hours £4.00 (all days); 6 hours £5.00 (Sat/Sun only); "
               "8 hours £7.50 (Sat/Sun only); 12 hours £10.00 (Sat/Sun only)")
    assert ce.parse_bands(charges) == [(2, 2.20), (4, 4.00)]


def test_r9_does_not_match_the_no_x_listed_shorthand_even_without_a_hedge_word():
    # "N/A on site (no car park listed)" (Asda Heston Express Petrol,
    # Hounslow): the literal phrase "no car park" matches the R9 phrase
    # list, but this parenthetical shape is the capture agent's own
    # shorthand for an absent listing, not a quote of the source denying
    # parking, and carries no "NO OFFICIAL INFO" or "verify" hedge word.
    row = sheet_row("PP-004369", type_captured="Supermarket",
                     notes="N/A on site (no car park listed)")
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("can_park", {}).get("value") != "No"


def test_r9_does_not_match_inside_a_hedged_no_official_info_note():
    # "page lists no car park" sits inside a hedge ("NO OFFICIAL INFO ...
    # verify on site"), so it is capture-side hedging, not the source's own
    # explicit denial, and must not produce Can Park? No.
    row = sheet_row(
        "PP-002953", type_captured="Supermarket",
        notes="NO OFFICIAL INFO on car park; page lists no car park; verify on site.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"].get("can_park", {}).get("value") != "No"


# ---- PP-001076: Premier Inn, "Free for hotel guests (official page)" ------
def test_hotel_free_for_guests_is_free_at_site_scope():
    row = sheet_row(
        "PP-001076", type_captured="Hotel",
        charges="Free for hotel guests (official page)",
        notes=("Hotel guest parking per official Premier Inn hotel page; hours not stated. "
               "Works noted – parking may be limited. Parking detail: Yes – hotel guests (free)."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    # Conditional, not Yes: Who Can Park is Guests only, a restricted group.
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["who_can_park"]["value"] == "Guests only"
    assert rec["fields"]["cost_type"]["value"] == "Free"
    assert rec["fields"]["cost_type"]["scope"] == "site"
    assert rec["fields"]["tariff_type"]["value"] == "Free (time limit not published)"
    assert rec["fields"]["tariff_detail"]["value"] == "Free"
    assert cf.validate_record(rec) == []


def test_hotel_free_for_guests_complimentary_wording_also_matches():
    row = sheet_row(
        "PP-001076", type_captured="Hotel",
        charges="Free for hotel guests – self parking listed as Complimentary (official page)",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["cost_type"]["value"] == "Free"
    assert cf.validate_record(rec) == []


# ---- Accor ALL hotel: "Chargeable – amount UNCLEAR", price withheld ------
def test_hotel_chargeable_with_amount_unclear_is_paid_price_not_published():
    row = sheet_row(
        "PP-003000", type_captured="Hotel",
        charges='Chargeable – amount UNCLEAR (official page says "additional fee", no tariff)',
        notes=("Hotel guest parking per official hotel page. Source: Accor ALL official hotel "
               "page. Within Congestion Charge zone (check TfL). Parking detail: Yes – hotel "
               "guests (chargeable)."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["who_can_park"]["value"] == "Guests only"
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_type"]["value"] == "Not published"
    assert rec["fields"]["tariff_detail"]["value"] == "Not published"
    assert cf.validate_record(rec) == []


# ---- PP-001073 / PP-001984 / PP-001044: a stated price per night or day ---
def test_hotel_stated_price_per_night_becomes_a_flat_nightly_rate():
    row = sheet_row(
        "PP-001073", type_captured="Hotel",
        charges="Chargeable parking is available at £15 per night.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per night"
    assert rec["fields"]["tariff_detail"]["value"] == "£15.00 per night"
    assert cf.validate_record(rec) == []


def test_hotel_stated_price_per_day_becomes_a_flat_24_hour_rate():
    row = sheet_row("PP-001984", type_captured="Hotel", charges="Self parking £50.00 per day")
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per 24 hours"
    assert rec["fields"]["tariff_detail"]["value"] == "£50.00 per day"
    assert cf.validate_record(rec) == []


def test_hotel_stated_price_is_found_mid_sentence():
    row = sheet_row(
        "PP-001044", type_captured="Hotel",
        charges="Parking will operate on a first come, first served basis at £15 per night.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["fields"]["tariff_detail"]["value"] == "£15.00 per night"
    assert cf.validate_record(rec) == []


# ---- PP-001053: Premier Inn London Docklands Excel contradicts itself -----
def test_hotel_self_contradicting_page_stays_left_for_grok():
    # The page says both "Free parking is available for Premier Inn Guests"
    # and "car parking is chargeable at this hotel": the "unclear" guard must
    # keep this out of all three hotel patterns, including the chargeable one.
    row = sheet_row(
        "PP-001053", type_captured="Hotel",
        charges=('UNCLEAR – page states "Free parking is available for Premier Inn Guests" '
                 'but also "Please note car parking is chargeable at this hotel."'),
        notes=("CONFLICT: Premier Inn page says 'Free parking is available for Premier Inn "
               "Guests' and also 'Please note car parking is chargeable at this hotel' "
               "(amenity: Chargeable onsite parking), re-checked 31 Oct 2026 – verify on site "
               "| Hotel guest parking per official Premier Inn hotel page; hours not stated."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is True


def test_hotel_patterns_do_not_fire_on_a_non_hotel_row():
    row = sheet_row("PP-001073", type_captured="Restaurant",
                     charges="Chargeable parking is available at £15 per night.")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is True


# ================= hotel pattern gap, round 2: the 24 real stuck rows ======

# ---- PP-001538: "chargeable at £X for 24 hours" (connector before unit) ---
def test_hotel_chargeable_at_price_for_24_hours():
    row = sheet_row(
        "PP-001538", type_captured="Hotel",
        charges="Car parking is available for our guests and is chargeable at £20 for 24 hours.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Conditional"
    assert rec["fields"]["who_can_park"]["value"] == "Guests only"
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per 24 hours"
    assert rec["fields"]["tariff_detail"]["value"] == "£20.00 per 24 hours"
    assert cf.validate_record(rec) == []


# ---- PP-001539: "£X per car, per night" (qualifier between price and unit) -
def test_hotel_price_per_car_per_night():
    row = sheet_row("PP-001539", type_captured="Hotel", charges="£20 per car, per night")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per night"
    assert rec["fields"]["tariff_detail"]["value"] == "£20.00 per night"
    assert cf.validate_record(rec) == []


# ---- PP-001548: "Daily fee of £X" (unit named before the price) -----------
def test_hotel_daily_fee_of_price():
    row = sheet_row("PP-001548", type_captured="Hotel", charges="Daily fee of £45.")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per 24 hours"
    assert rec["fields"]["tariff_detail"]["value"] == "£45.00 per day"
    assert cf.validate_record(rec) == []


# ---- PP-001551: two duration bands in one charges string -------------------
def test_hotel_two_duration_bands_become_banded_by_stay_length():
    row = sheet_row("PP-001551", type_captured="Hotel",
                     charges="£25 for 24 hrs; £6.00 per hour up to 4 hours")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Banded by stay length"
    detail = rec["fields"]["tariff_detail"]["value"]
    assert "£25.00" in detail and "£6.00" in detail and ";" in detail
    assert "–" not in detail and "—" not in detail
    assert cf.validate_record(rec) == []


# ---- PP-001553: "£X per vehicle per night (valet, underground)" -----------
def test_hotel_valet_price_goes_to_tariff_detail_valet_detail_to_notes():
    row = sheet_row("PP-001553", type_captured="Hotel",
                     charges="£65 per vehicle per night (valet, underground)")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per night"
    assert rec["fields"]["tariff_detail"]["value"] == "£65.00 per night"
    assert any("valet" in n.lower() for n in rec["notes_append"])
    assert cf.validate_record(rec) == []


# ---- PP-001693: non-residents may also park, a real R1 exception ----------
def test_hotel_non_residents_welcome_opens_who_can_park_to_anyone():
    row = sheet_row(
        "PP-001693", type_captured="Hotel",
        charges=("Residents £40.00/day; non-residents £5.00/hr (Mon–Fri 8am–4pm), "
                 "£4.00/hr off-peak & weekends"),
        notes=("Hotel guest parking per official hotel page. Source: Accor ALL official hotel "
               "page. Card payment only. Outside Congestion Charge zone (per hotel). 240 spaces "
               "+ 6 coach bays. Parking detail: Yes – hotel guests and non-residents (chargeable)."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["can_park"]["value"] == "Yes"
    assert rec["fields"]["who_can_park"]["value"] == "Anyone (paid)"
    # The non-resident clause's own first rate is the real, usable tariff.
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_type"]["value"] == "Hourly rate"
    assert rec["fields"]["tariff_detail"]["value"] == "£5.00 per hour"
    assert "£40.00" in rec["notes_append"][0] and "£4.00" in rec["notes_append"][0]
    assert "–" not in rec["notes_append"][0] and "—" not in rec["notes_append"][0]
    assert cf.validate_record(rec) == []
    assert "–" not in rec["notes_append"][0] and "—" not in rec["notes_append"][0]
    assert cf.validate_record(rec) == []


# ---- PP-002541: "per overnight stay per car" plus a trailing condition ----
def test_hotel_per_overnight_stay_per_car():
    row = sheet_row(
        "PP-002541", type_captured="Hotel",
        charges=("£18.00 per overnight stay per car (additional cars/days); "
                 "payable at lobby car park stations"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per night"
    assert rec["fields"]["tariff_detail"]["value"] == "£18.00 per night"
    assert any("payable at lobby" in n.lower() for n in rec["notes_append"])
    assert cf.validate_record(rec) == []


# ---- PP-002542: valet short-stay band plus a 24-hour band -----------------
def test_hotel_valet_banded_tariff():
    row = sheet_row("PP-002542", type_captured="Hotel",
                     charges="Valet £50 for 4 hours; £75 per vehicle per 24 hours")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Banded by stay length"
    detail = rec["fields"]["tariff_detail"]["value"]
    assert "£50.00" in detail and "£75.00" in detail
    assert any("valet" in n.lower() for n in rec["notes_append"])
    assert cf.validate_record(rec) == []


# ---- PP-002543: a single valet 24-hour rate --------------------------------
def test_hotel_valet_single_24_hour_rate():
    row = sheet_row("PP-002543", type_captured="Hotel", charges="Valet £75 for 24 hours")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Flat rate per 24 hours"
    assert rec["fields"]["tariff_detail"]["value"] == "£75.00 per 24 hours"
    assert any("valet" in n.lower() for n in rec["notes_append"])
    assert cf.validate_record(rec) == []


# ---- PP-002846: valet confirmed, price genuinely not stated ---------------
def test_hotel_valet_confirmed_but_price_not_stated_is_cost_unknown():
    row = sheet_row(
        "PP-002846", type_captured="Hotel", charges="NOT STATED on official page",
        notes="Official Radisson page FAQ: valet parking available 8am–8pm; price not stated.",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Unknown"
    assert rec["fields"]["tariff_type"]["value"] == "Not published"
    assert cf.validate_record(rec) == []


# ---- PP-002851: a long multi-band GBP tariff -------------------------------
def test_hotel_long_banded_gbp_tariff():
    row = sheet_row(
        "PP-002851", type_captured="Hotel",
        charges=("Up to 4h GBP 13.20; 4–5h GBP 16.50; 5–6h GBP 19.80; 6–7h GBP 23.10; "
                 "7–8h GBP 27.00; 8–23h GBP 27.50; Daily GBP 33.00; Weekly GBP 165.00"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Banded by stay length"
    # Strict "0-N hrs £X" template: the weekly rate has no hour cap of its
    # own, so it cannot be a band and goes to Notes instead.
    assert rec["fields"]["tariff_detail"]["value"] == (
        "0-4 hrs £13.20; 4-5 hrs £16.50; 5-6 hrs £19.80; 6-7 hrs £23.10; "
        "7-8 hrs £27.00; 8-23 hrs £27.50; 23-24 hrs £33.00")
    assert rec["notes_append"] == ["Weekly £165.00"]
    assert cf.validate_record(rec) == []


# ---- PP-002855: weekday/weekend/motorcycle banded tariff ------------------
def test_hotel_weekday_weekend_motorcycle_banded_tariff():
    row = sheet_row(
        "PP-002855", type_captured="Hotel",
        charges=("Mon–Fri: up to 2h GBP 17.50; 2–3h GBP 27.50; 4–24h GBP 47.50. Weekend: up to 2h "
                 "GBP 10.00; 2–3h GBP 15.00; 4–24h GBP 30.00 (before pre-book discount). "
                 "Motorcycles GBP 8.00/day"),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["tariff_type"]["value"] == "Banded by stay length"
    # Tariff Detail carries only the weekday schedule; the weekend schedule,
    # the motorcycle rate and the pre-book disclaimer all go to Notes.
    assert rec["fields"]["tariff_detail"]["value"] == (
        "0-2 hrs £17.50; 2-3 hrs £27.50; 4-24 hrs £47.50")
    notes = "; ".join(rec["notes_append"])
    assert "Weekend: 0-2 hrs £10.00; 2-3 hrs £15.00; 4-24 hrs £30.00" in notes
    assert "£8.00" in notes and "pre-book discount" in notes
    assert "–" not in notes and "—" not in notes
    # Both the weekday and the weekend schedule skip straight from a 2-3
    # hour band to a 4-24 hour band: the source names no 3-4 hour band.
    assert rec["flags"] == ["Source tariff has no 3-4 hr band"]
    assert cf.validate_record(rec) == []


# ---- PP-002861: chargeable, price genuinely not published, no "unclear" ---
def test_hotel_chargeable_on_match_days_price_not_published():
    row = sheet_row(
        "PP-002861", type_captured="Hotel",
        charges="Chargeable on match days; price varies – not published (contact hotel)",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_type"]["value"] == "Not published"
    assert cf.validate_record(rec) == []


# ---- PP-002871 / PP-004842 / PP-004874: broadened free detection -----------
def test_hotel_bare_free_confirmed_by_notes():
    row = sheet_row(
        "PP-002871", type_captured="Hotel", charges="Free",
        notes="Official Best Western page: \"Free parking available. Street parking is not available.\"",
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Free"
    assert cf.validate_record(rec) == []


def test_hotel_free_for_brand_guests_only_not_just_hotel_guests():
    row = sheet_row("PP-004842", type_captured="Hotel", charges="Free for Travelodge guests only")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Free"
    assert cf.validate_record(rec) == []


def test_hotel_limited_free_hotel_parking_stays_free():
    row = sheet_row("PP-004874", type_captured="Hotel",
                     charges="Limited free hotel parking (permit from reception)")
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Free"
    assert any("permit" in n.lower() for n in rec["notes_append"])
    assert cf.validate_record(rec) == []


# ---- the remaining 7 negatives: must still read as leave_for_grok ---------
def test_hotel_unclear_no_tariff_stated_stays_left_for_grok():
    row = sheet_row("PP-001554", type_captured="Hotel",
                     charges="UNCLEAR – no tariff stated on official page")
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_unclear_no_valet_tariff_stated_stays_left_for_grok():
    row = sheet_row("PP-001644", type_captured="Hotel",
                     charges="UNCLEAR – no valet tariff stated (page wording may imply complimentary)")
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_unclear_canary_riverside_stays_left_for_grok():
    row = sheet_row("PP-001645", type_captured="Hotel",
                     charges="UNCLEAR – no tariff stated on official page")
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_no_free_parking_any_paid_not_stated_stays_left_for_grok():
    # "No free parking" carries the literal "free parking" substring; the
    # negation guard must keep it out of the broadened free match, and
    # "any paid parking not stated" must not be read as a confirmed charge.
    row = sheet_row(
        "PP-002865", type_captured="Hotel",
        charges="No free parking; any paid parking not stated",
        notes="Official Best Western page: \"No free parking available. Street parking is not available.\"",
    )
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_no_free_parking_ilford_stays_left_for_grok():
    row = sheet_row(
        "PP-002867", type_captured="Hotel",
        charges="No free parking; any paid parking not stated",
        notes="Official Best Western page: \"No free parking available. Street parking is not available.\"",
    )
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_no_free_parking_corona_stays_left_for_grok():
    row = sheet_row(
        "PP-002870", type_captured="Hotel",
        charges="No free parking; any paid parking not stated",
        notes="Official Best Western page: \"No free parking available. Street parking is not available.\"",
    )
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


def test_hotel_charged_offsite_zero_pounds_conflict_stays_left_for_grok():
    row = sheet_row(
        "PP-002866", type_captured="Hotel",
        charges='UNCLEAR – page says "Charged offsite parking cost of £0.00 (per 24 hours)"',
        notes=("Official Best Western page: \"No free parking available. Charged offsite parking "
               "cost of £0.00 (per 24 hours). Street parking is not available.\" CONFLICT: "
               "\"charged\" but £0.00."),
    )
    assert ce.classify(row, OSM_ROW)["leave_for_grok"] is True


# ---- regression: "free" near "parking" that is about something else -------
def test_hotel_ev_charging_free_does_not_make_parking_free():
    # "2 EV charging points ... free to use (daily parking charge applies)":
    # the free thing is the EV charging, and the same sentence says a
    # parking charge applies. Real row: Park Plaza Westminster Bridge,
    # Charges "£70 per day", wrongly read as Free before this guard existed.
    row = sheet_row(
        "PP-002844", type_captured="Hotel", charges="£70 per day",
        notes=("Official Radisson page FAQ. Hotel is within the London Congestion Charge Area "
               "(owner pays). 2 EV charging points on site, free to use (daily parking charge "
               "applies)."),
    )
    rec = ce.classify(row, OSM_ROW)
    assert rec["leave_for_grok"] is False
    assert rec["fields"]["cost_type"]["value"] == "Paid"
    assert rec["fields"]["tariff_detail"]["value"] == "£70.00 per day"
    assert cf.validate_record(rec) == []
