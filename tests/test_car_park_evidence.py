"""Ruling 3: positive evidence that a venue has a car park."""
import csv
from pathlib import Path

from ferro_parking import car_park_evidence as cpe, db

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))


def sheet_row(**values):
    row = {header: "" for header in HEADERS}
    row.update(values)
    return row


# ---------------------------------------------------------------- the name test

def test_a_type_that_says_car_park_is_evidence():
    row = sheet_row(**{"Type (as captured)": "Car park", "Location Name": "Somewhere"})
    assert cpe.evidence_for(row)[0] == cpe.EVIDENCE_NAME


def test_a_name_that_says_car_park_is_evidence():
    row = sheet_row(**{"Location Name": "Kings Mall Car Park"})
    assert cpe.evidence_for(row)[0] == cpe.EVIDENCE_NAME


def test_a_plain_venue_name_is_not_evidence():
    assert cpe.evidence_for(sheet_row(**{"Location Name": "Tesco Bow"}))[0] is None


# ---------------------------------------------------------------- the OSM test

def test_a_customers_car_park_within_50_m_is_evidence():
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    osm = {"Car Park Distance (m)": "20", "OSM Raw Tags": "amenity=parking;access=customers"}
    assert cpe.evidence_for(row, osm)[0] == cpe.EVIDENCE_OSM_CUSTOMERS


def test_a_linked_car_park_within_50_m_is_evidence():
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    for link in ("Adjacent to place", "Name/operator matches brand"):
        osm = {"Car Park Distance (m)": "49", "Car Park Link": link}
        assert cpe.evidence_for(row, osm)[0] == cpe.EVIDENCE_OSM_MATCH, link


def test_a_car_park_named_after_the_venue_is_evidence():
    row = sheet_row(**{"Location Name": "Tesco Bow", "Brand": "Tesco"})
    osm = {"Car Park Distance (m)": "30", "OSM Car Park Name": "Tesco Customer Car Park"}
    assert cpe.evidence_for(row, osm)[0] == cpe.EVIDENCE_OSM_MATCH


def test_a_car_park_matching_the_operator_is_evidence():
    row = sheet_row(**{"Location Name": "Some Gym", "Operator": "Euro Car Parks"})
    osm = {"Car Park Distance (m)": "10", "OSM Car Park Name": "Euro Car Parks"}
    assert cpe.evidence_for(row, osm)[0] == cpe.EVIDENCE_OSM_MATCH


def test_exactly_50_m_counts_and_51_m_does_not():
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    inside = {"Car Park Distance (m)": "50", "Car Park Link": "Adjacent to place"}
    outside = {"Car Park Distance (m)": "50.1", "Car Park Link": "Adjacent to place"}
    assert cpe.evidence_for(row, inside)[0] == cpe.EVIDENCE_OSM_MATCH
    assert cpe.evidence_for(row, outside)[0] is None


def test_an_unrelated_nearby_car_park_is_not_evidence():
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    osm = {"Car Park Distance (m)": "25", "Car Park Link": "Nearby, not this place's",
           "OSM Car Park Name": "Civic Centre"}
    assert cpe.evidence_for(row, osm)[0] is None


def test_a_blank_or_missing_distance_is_not_evidence():
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    assert cpe.evidence_for(row, {})[0] is None
    assert cpe.evidence_for(row, {"Car Park Distance (m)": ""})[0] is None
    assert cpe.evidence_for(row, {"Car Park Distance (m)": "not a number"})[0] is None


# ---------------------------------------------------------------- the cached page test

def cached_page(tmp_path, conn, text, url="https://example.org/branch", status=200):
    path = tmp_path / "page.txt"
    path.write_text(text, encoding="utf-8")
    conn.execute("INSERT OR REPLACE INTO pages (url, fetched_at, http_status, text_hash, text_path)"
                 " VALUES (?, '2026-11-10', ?, 'hash', ?)", (url, status, str(path)))
    conn.commit()
    return url


def test_a_cached_page_that_states_parking_is_evidence(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    url = cached_page(tmp_path, conn,
                      "Opening hours are 8am to 8pm. There is a customer car park at this store.")
    row = sheet_row(**{"Location Name": "Tesco Bow", "Source URLs (primary first)": url})
    reason, quote, got_url = cpe.evidence_for(row, {}, conn)
    assert reason == cpe.EVIDENCE_PAGE
    assert "customer car park at this store" in quote
    assert got_url == url


def test_a_cached_page_that_denies_parking_is_not_evidence(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    url = cached_page(tmp_path, conn, "There is no car park at this shop.")
    row = sheet_row(**{"Location Name": "Pret Bow", "Source URLs (primary first)": url})
    assert cpe.evidence_for(row, {}, conn)[0] is None


def test_a_cached_page_that_says_nothing_about_parking_is_not_evidence(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    url = cached_page(tmp_path, conn, "Opening hours are 8am to 8pm. Our coffee is fresh.")
    row = sheet_row(**{"Location Name": "Pret Bow", "Source URLs (primary first)": url})
    assert cpe.evidence_for(row, {}, conn)[0] is None


def test_a_failed_fetch_is_not_evidence(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    url = cached_page(tmp_path, conn, "There is a customer car park.", status=403)
    row = sheet_row(**{"Location Name": "Tesco Bow", "Source URLs (primary first)": url})
    assert cpe.evidence_for(row, {}, conn)[0] is None


def test_a_page_row_whose_file_is_gone_is_not_evidence(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO pages (url, fetched_at, http_status, text_hash, text_path)"
                 " VALUES ('https://example.org/x', '2026-11-10', 200, 'h', '/no/such/file')")
    conn.commit()
    row = sheet_row(**{"Location Name": "Tesco Bow",
                       "Source URLs (primary first)": "https://example.org/x"})
    assert cpe.evidence_for(row, {}, conn)[0] is None


def test_a_row_with_no_source_url_reads_no_page(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    cached_page(tmp_path, conn, "There is a customer car park.")
    row = sheet_row(**{"Location Name": "Tesco Bow"})
    assert cpe.evidence_for(row, {}, conn)[0] is None


def test_page_quotes_keep_the_exact_sentence():
    text = ("Welcome to the store. Free parking is available for two hours. "
            "Please shop responsibly.")
    assert cpe.page_parking_quotes(text) == ["Free parking is available for two hours."]


def test_page_quotes_leave_out_a_denial_sentence():
    text = "There is no parking at this branch. The nearest car park is council run."
    quotes = cpe.page_parking_quotes(text)
    assert quotes == ["The nearest car park is council run."]


# ---------------------------------------------------------------- the order

def test_the_name_test_answers_before_any_page_is_read(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    row = sheet_row(**{"Location Name": "Kings Mall Car Park"})
    assert cpe.evidence_for(row, {}, conn)[0] == cpe.EVIDENCE_NAME


def test_has_evidence_is_the_same_test():
    row = sheet_row(**{"Location Name": "Kings Mall Car Park"})
    assert cpe.has_evidence(row) is True
    assert cpe.has_evidence(sheet_row(**{"Location Name": "Tesco Bow"})) is False


def test_the_radius_is_fifty_metres():
    assert cpe.NEARBY_M == 50.0
