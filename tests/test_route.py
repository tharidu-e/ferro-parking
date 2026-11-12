"""Phase 2: every branch of the router's decision order, and the source key."""
import csv
from pathlib import Path

import pytest

from ferro_parking import db, route

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))


def sheet_row(**values):
    row = {header: "" for header in HEADERS}
    row.update(values)
    return row


def stage_of(row, missing=(), duplicates=None, fetchers=None):
    return route.classify(row, set(missing), duplicates or {}, fetchers)[0]


def classify(row, missing=(), duplicates=None, fetchers=None):
    return route.classify(row, set(missing), duplicates or {}, fetchers)


# ---------------------------------------------------------------- rule 1, skip_named

def test_a_tharidu_row_is_never_touched():
    row = sheet_row(**{"Place ID": "PP-1", "Verified By": "Tharidu",
                       "Verification Result": ""})
    stage, priority, key, reason = classify(row)
    assert stage == "skip_named"
    assert priority == ""
    assert "named person" in reason


def test_a_tharidu_row_wins_over_every_later_rule():
    row = sheet_row(**{"Place ID": "PP-1", "Verified By": "Tharidu (hand check)",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes", "Who Can Park": "Unknown"})
    assert stage_of(row, missing=["PP-1"], duplicates={"PP-1": "PP-2"}) == "skip_named"


def test_an_agent_label_is_not_a_named_person():
    for label in ("PP (validation)", "Policy script", "Grok (discovery)",
                  "Claude (capture check)", "Category policy script", "OSM script"):
        row = sheet_row(**{"Place ID": "PP-1", "Verified By": label,
                           "Verification Result": ""})
        assert stage_of(row) != "skip_named", label


# ---------------------------------------------------------------- rule 2, skip_missing

def test_a_place_id_absent_from_the_newest_import_is_skipped():
    row = sheet_row(**{"Place ID": "PP-9", "Verification Result": ""})
    stage, priority, _, reason = classify(row, missing=["PP-9"])
    assert (stage, priority) == ("skip_missing", "")
    assert "newest import" in reason


def test_skip_missing_wins_over_duplicate_and_blank_result():
    row = sheet_row(**{"Place ID": "PP-9", "Verification Result": ""})
    assert stage_of(row, missing=["PP-9"], duplicates={"PP-9": "PP-1"}) == "skip_missing"


# ---------------------------------------------------------------- rule 3, skip_duplicate

def test_a_duplicate_row_is_skipped():
    row = sheet_row(**{"Place ID": "PP-2", "Verification Result": ""})
    stage, priority, _, reason = classify(row, duplicates={"PP-2": "PP-1"})
    assert (stage, priority) == ("skip_duplicate", "")
    assert "PP-1" in reason


def test_a_blank_duplicate_of_does_not_skip():
    row = sheet_row(**{"Place ID": "PP-2", "Verification Result": ""})
    assert stage_of(row, duplicates={"PP-2": ""}) == "no_evidence"


def test_skip_duplicate_wins_over_needs_on_site_check():
    row = sheet_row(**{"Place ID": "PP-2", "Verification Result": "Needs on-site check"})
    assert stage_of(row, duplicates={"PP-2": "PP-1"}) == "skip_duplicate"


# ---------------------------------------------------------------- rule 4, skip_onsite

def test_needs_on_site_check_gets_its_own_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Needs on-site check"})
    stage, priority, _, reason = classify(row)
    assert (stage, priority) == ("skip_onsite", "")
    assert "Needs on-site check" in reason


def test_skip_onsite_wins_over_the_public_car_park_gap():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Needs on-site check",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes", "Who Can Park": "Unknown"})
    assert stage_of(row) == "skip_onsite"


# ---------------------------------------------------------------- rule 5, skip_done

def test_a_finished_row_is_skipped():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Who Can Park": "Customers only", "Cost Type": "Free"})
    stage, priority, _, reason = classify(row)
    assert (stage, priority) == ("skip_done", "")
    assert "Confirmed" in reason


def test_a_finished_customer_venue_with_a_gap_is_still_skipped():
    """Priority 2 is only for public car parks. A shop with an Unknown cost
    and a filled result stays done."""
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed, details not published",
                       "Place Category": "Supermarket - large format",
                       "Can Park? (Yes/No/Conditional)": "Conditional", "Cost Type": "Unknown"})
    assert stage_of(row) == "skip_done"


def test_a_finished_public_car_park_with_no_gap_is_skipped():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes",
                       "Who Can Park": "Anyone (paid)", "Cost Type": "Paid"})
    assert stage_of(row) == "skip_done"


# ---------------------------------------------------------------- rule 6, priority 2

def test_a_public_car_park_missing_who_can_park_is_routed():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes",
                       "Who Can Park": "Unknown", "Cost Type": "Paid"})
    stage, priority, _, reason = classify(row)
    assert (stage, priority) == ("grok", "2")
    assert "public car park with no Who Can Park or Cost Type" in reason


def test_a_public_car_park_missing_cost_type_is_routed():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Private / operator car park",
                       "Can Park? (Yes/No/Conditional)": "Conditional",
                       "Who Can Park": "Anyone (paid)", "Cost Type": "Unknown"})
    assert classify(row)[:2] == ("grok", "2")


def test_a_car_park_named_only_in_the_type_column_counts():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Type (as captured)": "Public car park",
                       "Can Park? (Yes/No/Conditional)": "Yes", "Cost Type": "Unknown"})
    assert classify(row)[:2] == ("grok", "2")


def test_not_published_counts_as_a_gap_like_readiness_says():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes",
                       "Who Can Park": "Not published", "Cost Type": "Paid"})
    assert classify(row)[1] == "2"


def test_can_park_no_is_not_routed_by_priority_2():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "No", "Cost Type": "Unknown"})
    assert stage_of(row) == "skip_done"


# ---------------------------------------------------------------- rule 7, priority 1

def test_a_blank_verification_result_is_routed_at_priority_1():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Supermarket - large format",
                       "Location Name": "Tesco Hackney"})
    stage, priority, _, reason = classify(row)
    assert priority == "1"
    assert stage in ("default", "no_evidence")
    assert "Verification Result is blank" in reason


def test_a_blank_result_on_a_public_car_park_goes_to_grok():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Private / operator car park"})
    assert classify(row)[:2] == ("grok", "1")


def test_whitespace_only_verification_result_counts_as_blank():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "   "})
    assert classify(row)[1] == "1"


# ---------------------------------------------------------------- stage choice

def test_a_registered_fetcher_wins_over_grok():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Council car park",
                       "Operator": "Bromley Council"})
    stage, _, key, reason = classify(row, fetchers={"bromley council": object()})
    assert stage == "fetcher:bromley council"
    assert key == "bromley council"
    assert "fetcher for bromley council" in reason


def test_a_registered_fetcher_wins_over_default():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Location Name": "Tesco Hackney", "Brand": "Tesco"})
    assert stage_of(row, fetchers={"tesco": object()}) == "fetcher:tesco"


def test_fetchers_share_the_runner_registry():
    from ferro_parking.fetch_fill import REGISTRY
    assert route.FETCHERS is REGISTRY


def test_a_customer_venue_with_car_park_evidence_goes_to_default():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Gym / leisure centre", "Location Name": "PureGym Bow"})
    records = route.route_rows([row], set(), {}, osm_rows={
        "PP-1": {"Car Park Distance (m)": "15", "OSM Raw Tags": "amenity=parking;access=customers"}})
    assert records[0]["stage"] == "default"


def test_a_customer_venue_without_car_park_evidence_waits():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Gym / leisure centre", "Location Name": "PureGym Bow"})
    assert stage_of(row) == "no_evidence"


# ---------------------------------------------------------------- station stage

def test_a_station_category_row_goes_to_the_station_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Station", "Location Name": "Bromley South Station"})
    stage, priority, _, reason = classify(row)
    assert (stage, priority) == ("station", "1")
    assert "National Rail station research" in reason


def test_a_station_car_park_named_in_the_type_column_counts():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Type (as captured)": "Station car park"})
    assert stage_of(row) == "station"


def test_a_plain_station_type_without_car_park_wording_is_not_the_station_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Type (as captured)": "Railway station", "Location Name": "Some Halt"})
    assert stage_of(row) == "no_evidence"


def test_the_station_stage_is_checked_before_grok():
    """A Station row whose Type also says car park is a station, not a grok row."""
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Station", "Type (as captured)": "Car park"})
    assert stage_of(row) == "station"


def test_the_station_stage_is_checked_before_default():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Station"})
    assert stage_of(row) == "station"


def test_a_registered_fetcher_still_wins_over_the_station_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Station",
                       "Source URLs (primary first)": "https://www.nationalrail.co.uk/stations/brx"})
    stage, _, key, _ = classify(row, fetchers={"nationalrail.co.uk": object()})
    assert stage == "fetcher:nationalrail.co.uk"
    assert key == "nationalrail.co.uk"


def test_a_skipped_station_row_stays_skipped():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Station", "Who Can Park": "Anyone (paid)",
                       "Cost Type": "Paid"})
    assert stage_of(row) == "skip_done"


def test_a_public_car_park_that_is_not_a_station_still_goes_to_grok():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Council car park"})
    assert stage_of(row) == "grok"


def test_station_counts_and_keys_are_reported():
    rows = [
        sheet_row(**{"Place ID": "PP-1", "Verification Result": "", "Place Category": "Station",
                     "Source URLs (primary first)": "https://www.nationalrail.co.uk/a"}),
        sheet_row(**{"Place ID": "PP-2", "Verification Result": "", "Place Category": "Station",
                     "Source URLs (primary first)": "https://www.nationalrail.co.uk/b"}),
        sheet_row(**{"Place ID": "PP-3", "Verification Result": "",
                     "Place Category": "Council car park", "Operator": "Barnet Council"}),
    ]
    report = route.counts(route.route_rows(rows, set(), {}), rows)
    assert report["per_stage"] == {"station": 2, "grok": 1}
    assert report["station_stage"] == 2
    assert report["stations_routed"] == 2
    assert report["station_keys"].most_common() == [("nationalrail.co.uk", 2)]
    assert report["grok_keys"].most_common() == [("barnet council", 1)]


# ---------------------------------------------------------------- source key

def test_the_operator_is_the_first_choice():
    row = sheet_row(**{"Place ID": "PP-1", "Operator": "Euro Car Parks",
                       "Source URLs (primary first)": "https://www.tesco.com/x",
                       "Location Name": "Tesco Hackney"})
    assert route.source_key(row) == "euro car parks"


def test_a_placeholder_operator_is_not_a_key():
    for value in ("Not published", "Not applicable", "Unknown", "", "   "):
        row = sheet_row(**{"Place ID": "PP-1", "Operator": value,
                           "Source URLs (primary first)": "https://ncp.co.uk/car-park"})
        assert route.source_key(row) == "ncp.co.uk", value


def test_the_first_source_url_domain_is_the_second_choice():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Hackney",
                       "Source URLs (primary first)":
                           "https://www.bromley.gov.uk/parking; https://ncp.co.uk/x"})
    assert route.source_key(row) == "bromley.gov.uk"


def test_a_non_http_source_url_is_ignored():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Odeon Streatham",
                       "Source URLs (primary first)": "not a url; https://odeon.co.uk/x"})
    assert route.source_key(row) == "odeon.co.uk"


def test_the_brand_from_the_name_is_the_last_choice():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Sainsbury's Hornsey",
                       "Brand": "Sainsbury's"})
    assert route.source_key(row) == "sainsburys"


def test_a_row_with_no_key_at_all_is_grouped_as_unbranded():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": ""})
    assert classify(row)[2] == "unbranded"
    assert route.UNBRANDED == "unbranded"


def test_trailing_car_park_wording_is_stripped_from_the_fallback_key():
    cases = {
        "Sainsbury's Car Park": "sainsburys",
        "Tesco Car Park": "tesco",
        "NCP Car Park": "ncp",
        "Visitor Car Park": "visitor",
        "Beckton Gateway Car Park": "beckton gateway",
        "Finsbury Square Car Park": "finsbury square",
        "Ealing Broadway Station": "ealing broadway",
        "Odeon Parking": "odeon",
    }
    for name, expected in cases.items():
        row = sheet_row(**{"Place ID": "PP-1", "Location Name": name})
        assert route.source_key(row) == expected, name


def test_a_name_that_is_only_car_park_wording_becomes_unbranded():
    for name in ("Car Park", "Car park", "Parking", "Station"):
        row = sheet_row(**{"Place ID": "PP-1", "Location Name": name})
        assert route.source_key(row) == "unbranded", name


def test_the_noise_strip_does_not_touch_an_operator_or_a_domain():
    row = sheet_row(**{"Place ID": "PP-1", "Operator": "Euro Car Parks"})
    assert route.source_key(row) == "euro car parks"
    row = sheet_row(**{"Place ID": "PP-1",
                       "Source URLs (primary first)": "https://www.carparking.co.uk/x"})
    assert route.source_key(row) == "carparking.co.uk"


def test_strip_key_noise_leaves_an_ordinary_brand_alone():
    assert route.strip_key_noise("sainsburys") == "sainsburys"
    assert route.strip_key_noise("beckton gateway") == "beckton gateway"
    assert route.strip_key_noise("") == ""


def test_unbranded_never_matches_a_fetcher():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": ""})
    assert stage_of(row, fetchers={"unbranded": object()}) == "no_evidence"


def test_unbranded_rows_are_counted_apart_from_real_keys():
    rows = [
        sheet_row(**{"Place ID": "PP-1", "Verification Result": ""}),
        sheet_row(**{"Place ID": "PP-2", "Verification Result": "",
                     "Location Name": "Car Park", "Place Category": "Council car park"}),
        sheet_row(**{"Place ID": "PP-3", "Verification Result": "", "Location Name": "Tesco Bow"}),
    ]
    report = route.counts(route.route_rows(rows, set(), {}), rows)
    assert report["no_key"] == {"no_evidence": 1, "grok": 1}
    assert report["no_evidence_keys"].most_common() == [("tesco bow", 1)]
    assert report["grok_keys"] == {}


# ---------------------------------------------------------------- proposals

def test_a_blank_location_name_on_a_routed_row_becomes_a_proposal():
    rows = [
        sheet_row(**{"Place ID": "PP-1", "Verification Result": "", "Location Name": ""}),
        sheet_row(**{"Place ID": "PP-2", "Verification Result": "", "Location Name": "Tesco Bow"}),
    ]
    proposals = route.review_proposals(rows, route.route_rows(rows, set(), {}))
    assert [p["Place ID"] for p in proposals] == ["PP-1"]
    assert proposals[0]["column"] == "Location Name"
    assert proposals[0]["current value"] == ""


def test_a_skipped_row_with_a_blank_name_is_not_proposed():
    rows = [sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                         "Who Can Park": "Customers only", "Cost Type": "Free",
                         "Location Name": ""})]
    assert route.review_proposals(rows, route.route_rows(rows, set(), {})) == []


def test_route_writes_a_proposals_file(conn, tmp_path):
    out = tmp_path / "with_proposals"
    route.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(out)])
    with open(out / "proposals.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert list(csv.DictReader(open(out / "proposals.csv", encoding="utf-8")).fieldnames
                or []) == route.PROPOSAL_HEADERS
    assert rows == []


def test_first_source_domain_drops_the_www_prefix():
    assert route.first_source_domain("https://www.harrow.gov.uk/parking") == "harrow.gov.uk"
    assert route.first_source_domain("") == ""


# ---------------------------------------------------------------- one stage per row

def test_every_row_gets_exactly_one_stage():
    rows = [
        sheet_row(**{"Place ID": "PP-1", "Verified By": "Tharidu"}),
        sheet_row(**{"Place ID": "PP-2", "Verification Result": ""}),
        sheet_row(**{"Place ID": "PP-3", "Verification Result": "Needs on-site check"}),
        sheet_row(**{"Place ID": "PP-4", "Verification Result": "Confirmed"}),
        sheet_row(**{"Place ID": "PP-5", "Verification Result": ""}),
    ]
    records = route.route_rows(rows, {"PP-9"}, {"PP-5": "PP-2"})
    assert len(records) == len(rows)
    assert [record["Place ID"] for record in records] == ["PP-1", "PP-2", "PP-3", "PP-4", "PP-5"]
    assert [record["stage"] for record in records] == [
        "skip_named", "no_evidence", "skip_onsite", "skip_done", "skip_duplicate"]


# ---------------------------------------------------------------- counts

def test_counts_cover_stages_priorities_keys_and_stations():
    rows = [
        sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                     "Place Category": "Council car park", "Operator": "Bromley Council"}),
        sheet_row(**{"Place ID": "PP-2", "Verification Result": "",
                     "Place Category": "Council car park", "Operator": "Bromley Council"}),
        sheet_row(**{"Place ID": "PP-3", "Verification Result": "",
                     "Place Category": "Station", "Location Name": "Bromley South Station"}),
        sheet_row(**{"Place ID": "PP-4", "Verification Result": "Confirmed",
                     "Who Can Park": "Customers only", "Cost Type": "Free"}),
        sheet_row(**{"Place ID": "PP-5", "Verification Result": ""}),
    ]
    report = route.counts(route.route_rows(rows, set(), {}), rows)
    assert report["per_stage"] == {"grok": 2, "station": 1, "no_evidence": 1, "skip_done": 1}
    assert report["per_priority"] == {"1": 4, "skipped": 1}
    assert report["grok_keys"].most_common(1) == [("bromley council", 2)]
    assert report["station_keys"].most_common() == [("bromley south", 1)]
    assert report["no_key"] == {"no_evidence": 1}
    assert report["stations_routed"] == 1
    assert report["routed"] == 4


# ---------------------------------------------------------------- end to end

@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    return connection


def test_route_writes_the_table_and_the_csv(conn, tmp_path):
    out = tmp_path / "route_out"
    assert route.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(out)]) == 0
    with open(out / "routing.csv", newline="", encoding="utf-8") as stream:
        records = list(csv.DictReader(stream))
    assert [record["Place ID"] for record in records] == [
        "PP-000001", "PP-000002", "PP-000003", "PP-000004"]
    assert {record["Place ID"]: record["stage"] for record in records} == {
        "PP-000001": "skip_done",
        "PP-000002": "skip_onsite",
        "PP-000003": "skip_named",
        "PP-000004": "no_evidence",
    }
    assert list(records[0]) == route.HEADERS
    stored = {row["place_id"]: row["stage"] for row in
              conn.execute("SELECT place_id, stage FROM routing")}
    assert stored == {record["Place ID"]: record["stage"] for record in records}


def test_route_skips_a_place_id_the_newest_import_dropped(tmp_path):
    connection = db.connect(tmp_path / "drop.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    headers, rows = [], []
    with open(FIXTURE, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        headers = list(reader.fieldnames)
        rows = [row for row in reader if row["Place ID"] != "PP-000004"]
    variant = tmp_path / "variant.csv"
    with open(variant, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    db.import_sheet_csv(connection, variant)
    route.main(["--db", str(tmp_path / "drop.sqlite"), "--out", str(tmp_path / "out")])
    stored = {row["place_id"]: row["stage"] for row in
              connection.execute("SELECT place_id, stage FROM routing")}
    assert stored["PP-000004"] == "skip_missing"
    assert len(stored) == 4


def test_route_marks_a_database_duplicate(tmp_path):
    connection = db.connect(tmp_path / "dupe.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    connection.execute("UPDATE places SET duplicate_of = 'PP-000001' WHERE place_id = 'PP-000004'")
    connection.commit()
    route.main(["--db", str(tmp_path / "dupe.sqlite"), "--out", str(tmp_path / "out")])
    stored = {row["place_id"]: row["stage"] for row in
              connection.execute("SELECT place_id, stage FROM routing")}
    assert stored["PP-000004"] == "skip_duplicate"


def test_route_refuses_an_empty_database(tmp_path):
    with pytest.raises(SystemExit, match="db-import"):
        route.main(["--db", str(tmp_path / "empty.sqlite"), "--out", str(tmp_path / "out")])


def test_route_refuses_to_overwrite_an_output_folder(conn, tmp_path):
    out = tmp_path / "taken"
    out.mkdir()
    with pytest.raises(FileExistsError):
        route.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(out)])


def test_two_route_runs_keep_both_rows_per_place_id(conn, tmp_path):
    route.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(tmp_path / "one")])
    route.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(tmp_path / "two")])
    runs = {row["run_id"] for row in conn.execute("SELECT DISTINCT run_id FROM routing")}
    assert len(runs) in (1, 2)
    assert conn.execute("SELECT COUNT(*) AS n FROM routing").fetchone()["n"] == 4 * len(runs)


# ---------------------------------------------------------------- car parks by name

def test_a_name_that_says_car_park_sends_the_row_to_grok():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Location Name": "Kings Mall Car Park",
                       "Type (as captured)": "Retail / Shopping Centre"})
    assert stage_of(row) == "grok"


def test_the_plural_and_the_bare_word_both_count():
    for name in ("Westfield London - Car Parks A, B & C", "Odeon Streatham Parking",
                 "Exchange Ilford Car Park"):
        row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                           "Location Name": name,
                           "Type (as captured)": "Retail / Shopping Centre"})
        assert stage_of(row) == "grok", name


def test_a_name_that_merely_contains_park_is_not_a_car_park():
    for name in ("Finsbury Park Leisure Centre", "Battersea Park Cafe"):
        row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                           "Location Name": name, "Type (as captured)": "Leisure Centre"})
        assert stage_of(row) != "grok", name


def test_a_registered_fetcher_still_wins_over_the_name_test():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Location Name": "Kings Mall Car Park", "Operator": "NCP"})
    assert stage_of(row, fetchers={"ncp": object()}) == "fetcher:ncp"


def test_a_station_named_car_park_stays_on_the_station_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Station", "Location Name": "Ealing Broadway Car Park"})
    assert stage_of(row) == "station"


def test_the_name_test_never_makes_a_finished_row_routed_again():
    """Ruling 1 is for stage choice only. The priority 2 rule still reads the
    category and the Type, never the name, so a finished row stays finished."""
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Location Name": "Kings Mall Car Park",
                       "Can Park? (Yes/No/Conditional)": "Yes", "Who Can Park": "Unknown"})
    assert stage_of(row) == "skip_done"


def test_a_category_car_park_with_a_gap_is_still_priority_2():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "Confirmed",
                       "Place Category": "Council car park",
                       "Can Park? (Yes/No/Conditional)": "Yes", "Who Can Park": "Unknown"})
    assert classify(row)[:2] == ("grok", "2")


def test_car_park_by_name_only_names_just_the_movers():
    by_name = sheet_row(**{"Place ID": "PP-1", "Location Name": "Kings Mall Car Park",
                           "Type (as captured)": "Retail / Shopping Centre"})
    by_category = sheet_row(**{"Place ID": "PP-2", "Place Category": "Council car park",
                               "Location Name": "Bromley Car Park"})
    by_type = sheet_row(**{"Place ID": "PP-3", "Type (as captured)": "Car park",
                           "Location Name": "Some Car Park"})
    neither = sheet_row(**{"Place ID": "PP-4", "Location Name": "Tesco Bow"})
    assert route.car_park_by_name_only(by_name) is True
    assert route.car_park_by_name_only(by_category) is False
    assert route.car_park_by_name_only(by_type) is False
    assert route.car_park_by_name_only(neither) is False


def test_the_report_lists_the_name_only_movers():
    rows = [sheet_row(**{"Place ID": f"PP-{n}", "Verification Result": "",
                         "Location Name": f"Centre {n} Car Park",
                         "Type (as captured)": "Retail / Shopping Centre"})
            for n in range(1, 4)]
    report = route.counts(route.route_rows(rows, set(), {}), rows)
    assert len(report["name_only_car_parks"]) == 3
    assert report["name_only_car_parks"][0]["stage"] == "grok"


# ---------------------------------------------------------------- the no_evidence stage

VENUE = {"Place ID": "PP-1", "Verification Result": "", "Location Name": "Tesco Bow",
         "Brand": "Tesco", "Place Category": "Supermarket - large format"}


def test_a_venue_with_no_car_park_evidence_gets_the_no_evidence_stage():
    stage, priority, _, reason = classify(sheet_row(**VENUE))
    assert stage == "no_evidence"
    assert priority == "1"
    assert "no evidence that this venue has a car park" in reason


def test_an_osm_customers_car_park_within_50_m_is_evidence():
    rows = [sheet_row(**VENUE)]
    records = route.route_rows(rows, set(), {}, osm_rows={
        "PP-1": {"Car Park Distance (m)": "20", "OSM Raw Tags": "amenity=parking;access=customers"}})
    assert records[0]["stage"] == "default"
    assert "customers car park within 50 m" in records[0]["reason"]


def test_an_osm_car_park_matching_the_venue_is_evidence():
    rows = [sheet_row(**VENUE)]
    records = route.route_rows(rows, set(), {}, osm_rows={
        "PP-1": {"Car Park Distance (m)": "35", "Car Park Link": "Name/operator matches brand"}})
    assert records[0]["stage"] == "default"


def test_a_car_park_further_than_50_m_is_not_evidence():
    rows = [sheet_row(**VENUE)]
    records = route.route_rows(rows, set(), {}, osm_rows={
        "PP-1": {"Car Park Distance (m)": "80", "Car Park Link": "Name/operator matches brand"}})
    assert records[0]["stage"] == "no_evidence"


def test_a_nearby_car_park_that_is_not_this_places_is_not_evidence():
    rows = [sheet_row(**VENUE)]
    records = route.route_rows(rows, set(), {}, osm_rows={
        "PP-1": {"Car Park Distance (m)": "30", "Car Park Link": "Nearby, not this place's",
                 "OSM Car Park Name": "Somewhere else"}})
    assert records[0]["stage"] == "no_evidence"


def test_no_evidence_rows_are_not_queued_for_grok():
    rows = [sheet_row(**VENUE)]
    records = route.route_rows(rows, set(), {})
    assert records[0]["stage"] != "grok"


def test_a_public_car_park_never_reaches_the_evidence_gate():
    row = sheet_row(**{"Place ID": "PP-1", "Verification Result": "",
                       "Place Category": "Council car park"})
    assert stage_of(row) == "grok"


def test_no_evidence_keys_are_counted(conn, tmp_path):
    rows = [sheet_row(**dict(VENUE, **{"Place ID": "PP-1"})),
            sheet_row(**dict(VENUE, **{"Place ID": "PP-2"}))]
    report = route.counts(route.route_rows(rows, set(), {}), rows)
    assert report["per_stage"] == {"no_evidence": 2}
    assert report["no_evidence_keys"].most_common() == [("tesco", 2)]


@pytest.fixture(autouse=True)
def no_real_station_list(monkeypatch):
    from ferro_parking.sources import station_list
    monkeypatch.setattr(station_list, 'load', lambda *args: None)


def test_unresolved_official_station_name_routes_to_grok(monkeypatch):
    from ferro_parking.sources import station_list
    monkeypatch.setattr(station_list, 'load', lambda *args: {'brockley': 'https://www.nationalrail.co.uk/stations/brockley/'})
    row = sheet_row(**{'Place ID': 'PP-1', 'Place Category': 'Station', 'Location Name': 'Invented Station'})
    result = classify(row)
    assert result[0] == 'grok'
    assert 'not National Rail' in result[3]


def test_station_denial_with_mapped_car_park_routes_to_grok(monkeypatch):
    from ferro_parking.sources import station_list, fetch
    monkeypatch.setattr(station_list, 'load', lambda *args: {'brockley': 'https://www.nationalrail.co.uk/stations/brockley/'})
    monkeypatch.setattr(fetch, 'cached', lambda *args: (200, 'No parking spaces'))
    row = sheet_row(**{'Place ID': 'PP-1', 'Place Category': 'Station', 'Location Name': 'Brockley Station'})
    result = route.classify(row, set(), {}, conn=object(), osm_rows={'PP-1': {'Car Park Distance (m)': '50'}})
    assert result[0] == 'grok'
    assert 'confirm' in result[3]
