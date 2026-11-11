"""Fetchers A to E, read on saved fixtures. No test touches the network."""
import csv
from datetime import date
from pathlib import Path

import pytest

from ferro_parking import db, fetch_fill, fill, plan
from ferro_parking.sources import station as station_mod
from ferro_parking.sources import venue as venue_mod

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
PAGES = Path(__file__).parent / "fixtures" / "pages"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))
TODAY = date(2026, 11, 10)

STATION_PAGE = """Station parking
250 parking spaces
12 accessible parking spaces
The car park is managed by APCOA Parking."""

NO_PARKING_PAGE = """Station parking
No parking spaces
No accessible parking spaces"""

ACCESSIBLE_ONLY_PAGE = """Station parking
4 accessible parking spaces"""

SILENT_PAGE = "Live departures. Buy tickets. Plan your journey."


def sheet_row(**values):
    row = {header: "" for header in HEADERS}
    row.update(values)
    return row


def saved(key):
    folder = PAGES / key
    if not folder.is_dir():
        pytest.skip(f"no saved pages for {key}")
    return [path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.txt"))]


# ---------------------------------------------------------------- A, the slug

@pytest.mark.parametrize("name,slug", [
    ("Brockley Station", "brockley"),
    ("Brockley Station – via Coulgate Street", "brockley"),
    ("Hampton Court Station Car Park", "hampton-court"),
    ("Barking Station Car Parks", "barking"),
    ("Watford Junction Station (NCP)", "watford-junction"),
    ("East Croydon Station - Car Park", "east-croydon"),
    ("Harrow-on-the-Hill Station – via Station Approach", "harrow-on-the-hill"),
    ("Highams Park Station – via Hale End Road north east end", "highams-park"),
    ("Drayton Park Station Parking", "drayton-park"),
])
def test_the_station_slug_drops_the_sheets_own_wording(name, slug):
    assert station_mod.station_slug(name) == slug


def test_a_name_that_is_only_wording_resolves_to_nothing():
    assert station_mod.station_slug("Station Car Park") == ""
    assert station_mod.station_slug("") == ""


def test_an_unresolvable_name_gives_no_url():
    assert station_mod.StationFetcher().branch_url(
        sheet_row(**{"Location Name": "Car Park"})) == ""


def test_the_url_is_the_national_rail_station_page():
    url = station_mod.StationFetcher(lookup={"brockley": "https://www.nationalrail.co.uk/stations/brockley/"}).branch_url(
        sheet_row(**{"Location Name": "Brockley Station"}))
    assert url == "https://www.nationalrail.co.uk/stations/brockley/"


# ---------------------------------------------------------------- A, the rules

def test_a_stated_space_count_sets_can_park_yes_and_notes_the_count():
    values, notes, quote = station_mod.StationFetcher().values(STATION_PAGE)
    assert values[fill.CAN_PARK] == "Yes"
    assert quote == "250 parking spaces"
    assert any("250 parking spaces" in note for note in notes)
    assert values["Evidence Detail (what the source shows)"] == "250 parking spaces"


def test_no_parking_spaces_sets_can_park_no_with_that_quote():
    values, _, quote = station_mod.StationFetcher().values(NO_PARKING_PAGE)
    assert values[fill.CAN_PARK] == "No"
    assert quote == "No parking spaces"
    assert values["Evidence Detail (what the source shows)"] == "No parking spaces"


def test_can_park_no_marks_every_parking_detail_not_applicable():
    from ferro_parking import page_fill
    values, _, _ = station_mod.StationFetcher().values(NO_PARKING_PAGE)
    for column in page_fill.NOT_APPLICABLE_IF_NO_PARKING:
        assert values[column] == "Not applicable", column


def test_accessible_spaces_alone_write_nothing():
    values, notes, quote = station_mod.StationFetcher().values(ACCESSIBLE_ONLY_PAGE)
    assert values == {}
    assert notes == []
    assert quote == ""


def test_a_page_with_no_parking_statement_writes_nothing():
    assert station_mod.StationFetcher().values(SILENT_PAGE)[0] == {}


def test_the_operator_is_written_only_when_the_page_names_it():
    with_operator, _, _ = station_mod.StationFetcher().values(STATION_PAGE)
    assert with_operator["Operator"] == "APCOA Parking"
    without, _, _ = station_mod.StationFetcher().values("Station parking\n250 parking spaces")
    assert "Operator" not in without


def test_the_station_fetcher_never_writes_a_tariff_free_or_a_max_stay():
    page = STATION_PAGE + "\nParking costs £5.00 per day and the max stay is 24 hours."
    values, _, _ = station_mod.StationFetcher().values(page)
    for column in ("Cost Type", "Tariff Type", "Tariff Detail", "Max Stay (mins)",
                    "Price Status"):
        assert column not in values, column


def test_the_saved_station_pages_all_read_as_no_parking_spaces():
    fetcher = station_mod.StationFetcher()
    for text in saved("nationalrail.co.uk"):
        values, _, quote = fetcher.values(text)
        assert values.get(fill.CAN_PARK) == "No"
        assert quote == "No parking spaces"


# ---------------------------------------------------------------- B, C, D

def test_a_free_parking_line_sets_cost_type_free():
    values, _, _, quote = venue_mod.VenueFetcher("thegymgroup.com").values(
        "Opening hours vary. Free parking is available at this gym.")
    assert values["Cost Type"] == "Free"
    assert values["Tariff Type"] == "Free (time limit not published)"
    assert values["Tariff Detail"] == "Free"
    assert values[fill.CAN_PARK] == "Conditional"
    assert values["Who Can Park"] == "Customers only"
    assert "Free parking is available" in quote


def test_a_parking_type_free_facility_line_counts():
    text = ("By car Car parking available 40 total spaces available "
            "2 disabled spaces available Parking type: Free")
    values, notes, _, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert values["Cost Type"] == "Free"
    assert any("40 parking spaces" in note for note in notes)


def test_a_stated_charge_with_no_template_leaves_cost_type_unknown():
    text = ("There are 155 car parking spaces available for customers. "
            "If you plan to stay beyond the free four hour period, customers must pay "
            "for additional time using the parking app.")
    values, notes, flags, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert values["Cost Type"] == "Unknown"
    assert "Tariff Detail" not in values
    assert any("Charges stated but not in a template" in note for note in notes)
    assert flags


def test_a_free_period_with_an_hourly_rate_becomes_the_template():
    text = ("Parking is free for 60 mins. After that customers must pay £2.50 per hour.")
    values, _, _, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert values["Cost Type"] == "Free then paid"
    assert values["Tariff Type"] == "Free period, then hourly"
    assert values["Tariff Detail"] == "Free for 60 mins, then £2.50 per hour"


def test_a_free_period_is_never_read_as_a_max_stay():
    """Four hours free then pay lets a driver stay longer, so Max Stay stays
    empty. Writing 240 there would send them away early."""
    text = ("Customers are entitled to up to four hours free car parking. "
            "Beyond that you must pay for additional time.")
    values, _, _, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert "Max Stay (mins)" not in values


def test_free_on_named_days_is_not_free():
    """The live PureGym Romford page says parking is free on Sundays and to
    check the car park for prices. Writing Free would mislead a driver on six
    days out of seven."""
    text = ("1,730 parking spaces on site. All parking is free on Sundays. "
            "Check car park for latest prices.")
    values, notes, flags, quote = venue_mod.VenueFetcher("puregym.com").values(text)
    assert values["Cost Type"] == "Unknown"
    assert values["Price Status"] == "Not published"
    assert "Tariff Detail" not in values
    assert any("free only at stated times" in note.lower() for note in notes)
    assert flags
    # The row still records that the branch has a car park.
    assert values[fill.CAN_PARK] == "Conditional"


@pytest.mark.parametrize("sentence,free", [
    ("Free parking is available.", True),
    ("Parking type: Free", True),
    ("Parking is free on Saturdays.", False),
    ("Parking is free at weekends.", False),
    ("Parking is free on bank holidays.", False),
    ("Parking is free after 6pm.", False),
    ("Parking is free between 9am and 5pm.", False),
    ("Parking is free overnight.", False),
])
def test_a_qualified_free_claim_never_becomes_a_price(sentence, free):
    values = venue_mod.VenueFetcher("puregym.com").values(sentence)[0]
    assert (values.get("Cost Type") == "Free") == free, values.get("Cost Type")


def test_a_stated_maximum_stay_is_written():
    text = "Free parking is available. The maximum stay is 3 hours."
    values, notes, _, _ = venue_mod.VenueFetcher("puregym.com").values(text)
    assert values["Max Stay (mins)"] == "180"
    assert any("Max stay from the branch page" in note for note in notes)


def test_a_parking_charge_notice_is_not_read_as_a_tariff():
    text = ("Free parking is available for members. Vehicles parked in these bays may "
            "receive a Parking Charge Notice (PCN).")
    values, _, _, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert values["Cost Type"] == "Free"


def test_the_operator_and_the_pcn_amount_come_only_from_the_page():
    text = ("Free parking is available. The car park is managed by Parking Eye. "
            "A PCN of £100 applies.")
    values, _, _, _ = venue_mod.VenueFetcher("better.org.uk").values(text)
    assert values["Operator"] == "Parking Eye"
    assert values["PCN (Penalty Charge Notice) amount (£)"] == "100"
    plain, _, _, _ = venue_mod.VenueFetcher("better.org.uk").values("Free parking is available.")
    assert "Operator" not in plain
    assert "PCN (Penalty Charge Notice) amount (£)" not in plain


def test_a_caution_about_the_signs_goes_in_notes():
    text = ("Free Parking. Parking restrictions may apply. Please check in the car park "
            "before you enter the gym.")
    _, notes, _, _ = venue_mod.VenueFetcher("puregym.com").values(text)
    assert any("check in the car park" in note for note in notes)


def test_a_silent_venue_page_writes_nothing():
    values, notes, flags, quote = venue_mod.VenueFetcher("kfc.co.uk").values(
        "Order now. Our menu. Find a restaurant.")
    assert (values, notes, flags, quote) == ({}, [], [], "")


def test_a_page_that_only_mentions_parking_in_passing_writes_nothing():
    values, _, _, _ = venue_mod.VenueFetcher("puregym.com").values(
        "The gym is near the station car park and the bus stop.")
    assert values == {}


def test_every_value_carries_an_official_site_specific_source():
    values, _, _, _ = venue_mod.VenueFetcher("puregym.com").values("Free parking is available.")
    assert values["Source Tier"] == "Official site - text"
    assert values["Specificity"] == "Site-specific"
    assert "Route B" in values["Decision Reason"]


@pytest.mark.parametrize("key", ["better.org.uk", "thegymgroup.com", "puregym.com"])
def test_the_saved_pages_for_each_key_still_give_values(key):
    fetcher = venue_mod.VenueFetcher(key)
    results = [fetcher.values(text)[0] for text in saved(key)]
    assert any(values for values in results)
    for values in results:
        if values:
            assert values[fill.CAN_PARK] == "Conditional"
            assert values["Who Can Park"] == "Customers only"
            assert values["Cost Type"] in ("Free", "Paid", "Free then paid", "Unknown")


def test_the_saved_asda_store_pages_state_a_car_park_and_nothing_more():
    fetcher = venue_mod.StoreFetcher("Asda", "storelocator.asda.com")
    results = [fetcher.values(text)[0] for text in saved("storelocator.asda.com")]
    assert results and all(results)
    for values in results:
        assert values[fill.CAN_PARK] == "Conditional"
        assert values["Who Can Park"] == "Customers only"
        assert values["Brand"] == "Asda"
        assert values["Specificity"] == "Site-specific"
        # The facility list says the store has a car park. It states no price,
        # no maximum stay and no public access.
        assert values["Cost Type"] == "Unknown"
        assert "Max Stay (mins)" not in values
        assert "Tariff Detail" not in values


def test_the_saved_lidl_store_pages_list_only_accessible_bays():
    """Accessible bays alone establish no car park, as the station rule says."""
    fetcher = venue_mod.StoreFetcher("Lidl", "www.lidl.co.uk")
    texts = saved("www.lidl.co.uk")
    assert texts
    # Three of the four saved pages list accessible bays and no car park. The
    # fourth states no parking at all. Neither shape writes a value.
    assert any("Disabled Parking" in text for text in texts)
    assert not any("Car Park" in text for text in texts)
    assert not any(fetcher.values(text)[0] for text in texts)


@pytest.mark.parametrize("entry,read", [
    ("Car Park", True), ("car parking", True), ("Free Car Park", True),
    ("Disabled Parking", False), ("Temporary Disabled Parking Pass", False),
    ("Accessible Car Park", False), ("Car Park Closed For Repairs", False)])
def test_only_an_unqualified_facility_entry_counts_as_a_car_park(entry, read):
    assert bool(venue_mod.facility_car_park([entry])) == read


def test_a_store_page_url_comes_from_the_identity_match_not_the_name(conn):
    conn.execute(
        "INSERT INTO evidence (place_id, field, quote) VALUES (?, 'Brand', ?)",
        ("PP-000002", "name=Asda; shop=supermarket; "
                      "contact:website=https://storelocator.asda.com/london/sutton/x"))
    # Two urls on the same host leave the place out, like an ambiguous station.
    conn.execute(
        "INSERT INTO evidence (place_id, field, quote) VALUES (?, 'Brand', ?)",
        ("PP-000001", "name=Asda; website=https://storelocator.asda.com/a"))
    conn.execute(
        "INSERT INTO evidence (place_id, field, quote) VALUES (?, 'Brand', ?)",
        ("PP-000001", "name=Asda; website=https://storelocator.asda.com/b"))
    conn.commit()
    lookup = venue_mod.official_store_urls(conn, "storelocator.asda.com")
    assert lookup == {"PP-000002": "https://storelocator.asda.com/london/sutton/x"}
    fetcher = venue_mod.StoreFetcher("Asda", "storelocator.asda.com", lookup)
    assert fetcher.branch_url({"Place ID": "PP-000002"}).endswith("/london/sutton/x")
    assert fetcher.branch_url({"Place ID": "PP-000001"}) == ""
    assert fetcher.branch_url({"Place ID": "PP-000004", "Location Name": "Asda Acton"}) == ""


def test_the_saved_marks_and_spencer_pages_are_cache_only():
    assert "marksandspencer.com" in fetch_fill.CACHE_ONLY
    assert "marksandspencer.com" not in fetch_fill.REGISTRY


def test_the_registry_holds_only_the_approved_fetchers():
    assert set(fetch_fill.REGISTRY) == {"station", "better.org.uk", "thegymgroup.com",
                                        "puregym.com", "storelocator.asda.com",
                                        "www.lidl.co.uk"}


def test_a_measured_unreadable_host_is_named_and_never_registered():
    for host in fetch_fill.SKIPPED_HOSTS:
        assert host not in fetch_fill.REGISTRY
        assert fetch_fill.SKIPPED_HOSTS[host].strip()


# ---------------------------------------------------------------- the runner

@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    connection.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES ('route-1', ?, ?, 'test')",
        [("PP-000001", "default"), ("PP-000002", "station"),
         ("PP-000003", "station"), ("PP-000004", "grok")])
    connection.commit()
    return connection


class FakeFetcher:
    key = "fake"
    verified_by = "Code (page fetch)"

    def __init__(self, url="https://example.org/branch", values=None, notes=None, flags=None):
        self._url, self._values = url, values or {}
        self._notes, self._flags = notes or [], flags or []

    def branch_url(self, row):
        return self._url

    def values(self, text, row=None):
        return dict(self._values), list(self._notes), list(self._flags), "the quote"


def fake_fetch(pages):
    def inner(url, conn, *args, **kwargs):
        return (*pages.get(url, (404, "")), False)
    return inner


def test_the_station_fetcher_reads_only_station_rows(conn):
    rows, run_id = fetch_fill.rows_for(conn, "station")
    assert sorted(row[0]["Place ID"] for row in rows) == ["PP-000002"]
    assert run_id == "route-1"


def test_a_skipped_row_is_never_read(conn):
    conn.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES ('route-2', ?, ?, 'test')",
        [("PP-000001", "skip_done"), ("PP-000002", "skip_onsite")])
    conn.commit()
    rows, _ = fetch_fill.rows_for(conn, "station")
    assert rows == []


def test_a_key_fetcher_reads_rows_by_source_key(conn):
    rows, _ = fetch_fill.rows_for(conn, "horizon parking")
    assert [row[0]["Place ID"] for row in rows] == ["PP-000001"]


def test_an_unregistered_key_is_refused(conn):
    with pytest.raises(SystemExit, match="No fetcher registered"):
        fetch_fill.run(conn, "nosuchkey.example")


def test_the_runner_counts_every_outcome(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "Free parking is available.")}))
    lines, report = fetch_fill.run(
        conn, "station", today=TODAY,
        fetcher=FakeFetcher(values={fill.CAN_PARK: "No", "Source Tier": "Official site - text",
                                     "Specificity": "Site-specific",
                                     "Decision Reason": "Route A: test"}))
    assert report["counts"]["rows attempted"] == 1
    assert report["counts"]["pages fetched"] == 1
    assert report["counts"]["rows with values"] == 1
    assert lines


def test_a_silent_page_is_counted_and_plans_nothing(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "nothing here")}))
    lines, report = fetch_fill.run(conn, "station", today=TODAY, fetcher=FakeFetcher())
    assert report["counts"]["silent pages"] == 1
    assert lines == []


def test_a_blocked_page_is_counted_and_plans_nothing(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (403, "Forbidden")}))
    lines, report = fetch_fill.run(conn, "station", today=TODAY, fetcher=FakeFetcher())
    assert report["counts"]["blocked pages"] == 1
    assert lines == []


def test_a_404_is_reported_as_an_unresolved_name(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch({}))
    _, report = fetch_fill.run(conn, "station", today=TODAY, fetcher=FakeFetcher())
    assert report["counts"]["unresolved names"] == 1
    assert "404" in report["unresolved"][0]["reason"]


def test_a_name_that_resolves_to_no_url_is_reported(conn, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("no url, so no request")

    monkeypatch.setattr(fetch_fill, "fetch", explode)
    _, report = fetch_fill.run(conn, "station", today=TODAY, fetcher=FakeFetcher(url=""))
    assert report["counts"]["unresolved names"] == 1


def test_a_row_without_brand_or_category_is_held(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "Free parking is available.")}))
    lines, report = fetch_fill.run(
        conn, "station", today=TODAY,
        fetcher=FakeFetcher(values={fill.CAN_PARK: "Conditional"}))
    assert report["counts"]["rows held for a person"] == 1
    assert lines == []
    assert "no Brand" in report["held"][0]["reason"]


def test_a_cache_only_key_plans_nothing(conn, monkeypatch):
    conn.execute("UPDATE raw SET json = json_set(json_set(json, '$.Operator', ''),"
                 " '$.\"Source URLs (primary first)\"',"
                 " 'https://www.marksandspencer.com/stores/bow-1234')"
                 " WHERE place_id = 'PP-000001'")
    conn.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES ('route-3', ?, 'default', 'test')", [("PP-000001",)])
    conn.commit()
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://www.tesco.com/store-locator/hackney": (200, "Car parking")}))
    lines, report = fetch_fill.run(conn, "marksandspencer.com", today=TODAY,
                                    fetcher=FakeFetcher(
                                        url="https://www.tesco.com/store-locator/hackney"))
    assert lines == []
    assert report["counts"]["pages fetched"] == 1


def test_an_existing_notes_dash_leaves_the_notes_line_out(conn, monkeypatch):
    """PP-000002's Notes already holds a newline and plain text. A dash in the
    sheet's own Notes must not drag the plan into a validator failure."""
    conn.execute("UPDATE raw SET json = json_set(json, '$.Notes', 'Old note – see sign')"
                 " WHERE place_id = 'PP-000002'")
    conn.commit()
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "x")}))
    lines, _ = fetch_fill.run(
        conn, "station", today=TODAY,
        fetcher=FakeFetcher(values={fill.CAN_PARK: "No"}, notes=["a new note"]))
    assert "Notes" not in {line["column"] for line in lines}


def test_the_plan_a_fetcher_writes_passes_db_apply(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "Free parking is available.")}))
    from ferro_parking import page_fill
    values = {fill.CAN_PARK: "No", "Source Tier": "Operator / council site",
              "Specificity": "Site-specific", "Evidence Level": "Verified",
              "Evidence Type": "Official site: clear answer",
              "Evidence Detail (what the source shows)": "No parking spaces",
              "Rules Stated": "Yes", "Prices Stated": "No",
              "Decision Reason": "Route A: National Rail station page, visible text"}
    values.update({column: "Not applicable"
                   for column in page_fill.NOT_APPLICABLE_IF_NO_PARKING})
    lines, _ = fetch_fill.run(conn, "station", today=TODAY,
                               fetcher=FakeFetcher(values=values))
    assert lines
    report = plan.apply_plan(conn, lines, "run-fetch", apply=False)
    assert report["rejected"] == [], report["rejected"]


def cache_page(conn, url="https://example.org/branch",
               fetched_at="2026-11-11T09:00:00+00:00", text_hash="abc123"):
    conn.execute("INSERT OR REPLACE INTO pages (url, fetched_at, http_status, text_hash,"
                 " text_path) VALUES (?, ?, 200, ?, '')", (url, fetched_at, text_hash))
    conn.commit()


def test_page_metadata_goes_only_to_the_fields_the_page_states(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "No parking spaces")}))
    cache_page(conn)
    lines, _ = fetch_fill.run(conn, "station", today=TODAY, fetcher=FakeFetcher(values={
        fill.CAN_PARK: "No", "Source Tier": "Operator / council site",
        "Specificity": "Site-specific"}))
    by_column = {entry["column"]: entry for entry in lines}
    stated = by_column[fill.CAN_PARK]
    assert stated["quote"] == "the quote"
    assert stated["source_url"] == "https://example.org/branch"
    assert stated["retrieved_at"] == "2026-11-11T09:00:00+00:00"
    assert stated["page_hash"] == "abc123"
    for column in ("Source Tier", "Specificity", fill.VERIFIED_BY, fill.SOURCE_URLS):
        book = by_column[column]
        assert (book["quote"], book["source_url"]) == ("", ""), column
        assert (book["retrieved_at"], book["page_hash"]) == ("", ""), column


def test_an_uncached_url_reports_no_page_metadata(conn):
    assert fetch_fill.page_metadata(conn, "https://example.org/missing") == ("", "")


def test_evidence_rows_keep_the_page_version_and_skip_bookkeeping(conn, monkeypatch):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "No parking spaces")}))
    cache_page(conn)
    from ferro_parking import page_fill
    values = {fill.CAN_PARK: "No", "Source Tier": "Operator / council site",
              "Specificity": "Site-specific", "Evidence Level": "Verified",
              "Evidence Type": "Official site: clear answer",
              "Evidence Detail (what the source shows)": "No parking spaces",
              "Rules Stated": "Yes", "Prices Stated": "No",
              "Decision Reason": "Route A: National Rail station page, visible text"}
    values.update({column: "Not applicable"
                   for column in page_fill.NOT_APPLICABLE_IF_NO_PARKING})
    lines, _ = fetch_fill.run(conn, "station", today=TODAY,
                               fetcher=FakeFetcher(values=values))
    plan.apply_plan(conn, lines, "run-meta", apply=True)
    rows = {row["field"]: row for row in conn.execute(
        "SELECT field, retrieved_at, page_hash FROM evidence WHERE run_id = 'run-meta'")}
    assert rows[fill.CAN_PARK]["retrieved_at"] == "2026-11-11T09:00:00+00:00"
    assert rows[fill.CAN_PARK]["page_hash"] == "abc123"
    assert "Source Tier" not in rows
    assert "Decision Reason" not in rows


def test_the_runner_writes_no_change_to_the_database(conn, monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_fill, "fetch", fake_fetch(
        {"https://example.org/branch": (200, "Free parking is available.")}))
    fetch_fill.run(conn, "station", today=TODAY,
                    fetcher=FakeFetcher(values={fill.CAN_PARK: "No"}))
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0

@pytest.mark.parametrize('text', [
    'There is no free parking at this gym.',
    'Free parking for customers. A charge applies after two hours.',
    'Free parking is available. Additional parking costs apply.',
])
def test_free_never_ignores_a_denial_or_later_charge(text):
    values, _, _, _ = venue_mod.VenueFetcher('puregym.com').values(text)
    assert values.get('Cost Type') != 'Free'


def test_zero_station_spaces_is_not_yes():
    assert station_mod.StationFetcher().values('0 parking spaces')[0].get(fill.CAN_PARK) != 'Yes'


@pytest.mark.parametrize('column,value', [('Charges (as published)', '£5'), ('Tariff Detail', 'Free'), ('_mapped_car_park_50m', True)])
def test_station_denial_with_conflicting_evidence_only_flags(column, value):
    row = sheet_row(**{column: value})
    values, _, _ = station_mod.StationFetcher().values(NO_PARKING_PAGE, row)
    assert fill.CAN_PARK not in values
    assert values['Review Flag'] == station_mod.CONFLICT_FLAG


def test_station_values_state_the_brand():
    assert station_mod.StationFetcher().values(NO_PARKING_PAGE, sheet_row())[0]['Brand'] == 'National Rail'


def test_official_list_lookup_has_no_guessed_row_urls():
    import json
    from ferro_parking.sources import station_list
    text = json.dumps({'data': {'StationList': {'stations': [{'name': 'London Paddington', 'crs': 'PAD'}, {'name': 'Brockley', 'crs': 'BCY'}]}}})
    lookup = station_list.parse(text)
    reader = station_mod.StationFetcher(lookup)
    assert reader.branch_url({'Location Name': 'Brockley Station Car Park'}).endswith('/brockley/')
    assert reader.branch_url({'Location Name': 'Invented Station'}) == ''
    assert reader.branch_url({'Location Name': 'Paddington Station'}) == ''


def test_ambiguous_names_in_the_list_are_unresolved():
    import json
    from ferro_parking.sources import station_list
    text = json.dumps({'data': {'StationList': {'stations': [{'name': 'Example & Town'}, {'name': 'Example and Town'}]}}})
    assert station_list.parse(text) == {}


def test_station_list_is_fetched_once_then_cached(tmp_path, monkeypatch):
    import json
    from ferro_parking.sources import station_list, fetch
    calls = []
    text = json.dumps({'data': {'StationList': {'stations': [{'name': 'Brockley'}]}}})
    def download(*args, **kwargs):
        calls.append(1)
        return 200, text, False
    monkeypatch.setattr(fetch, 'fetch', download)
    path = tmp_path / 'list.json'
    assert station_list.load(object(), path) == station_list.load(object(), path)
    assert len(calls) == 1


def test_membership_price_and_generic_caution_do_not_establish_parking():
    text = 'Membership costs £25 per month. Please check in the car park before you enter the gym.'
    assert venue_mod.VenueFetcher('puregym.com').values(text)[0] == {}


def test_a_free_period_is_preserved_in_the_tariff_without_inventing_a_max_stay():
    values, _, _, _ = venue_mod.VenueFetcher('puregym.com').values('Free parking for 2 hours.')
    assert values['Tariff Detail'] == 'Free for up to 120 mins'
    assert values['Tariff Type'] == 'Free with time limit'
    assert 'Max Stay (mins)' not in values


def test_venue_denial_never_becomes_conditional():
    assert venue_mod.VenueFetcher('puregym.com').values('No parking available. Membership costs £20.')[0] == {}


def test_fetch_plan_records_the_page_url_in_the_row():
    lines, held = fetch_fill.plan_lines('PP-1', 'station', {'Brand': 'National Rail', 'Decision Reason': 'Route A: page'}, [], [], sheet_row(), 'No parking spaces', 'https://www.nationalrail.co.uk/stations/brockley/', 'Code (page fetch)', TODAY)
    assert not held
    assert next(l['new_value'] for l in lines if l['column'] == fill.SOURCE_URLS).endswith('/brockley/')


def test_venue_never_treats_an_unrelated_domain_as_its_official_page():
    assert venue_mod.VenueFetcher('puregym.com').branch_url({'Source URLs (primary first)': 'https://booking.example/puregym'}) == ''


def test_a_charge_elsewhere_on_the_page_prevents_free():
    values, notes, flags, _ = venue_mod.VenueFetcher('puregym.com').values('Free parking is available. Opening times vary. Additional parking costs £2.00.')
    assert values['Cost Type'] == 'Unknown'
    assert notes and flags


def test_station_denial_allows_only_blank_or_unpublished_tariffs():
    for tariff in ['', 'Not published']:
        values, _, _ = station_mod.StationFetcher().values(NO_PARKING_PAGE, {'Tariff Detail': tariff})
        assert values[fill.CAN_PARK] == 'No'
        assert values['Brand'] == 'National Rail'
