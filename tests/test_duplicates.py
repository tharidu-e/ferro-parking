"""Marking one place a duplicate of another, and every refusal."""
from pathlib import Path

import pytest

from ferro_parking import create, db, duplicates

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "ferro.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    return connection


def two_ids(conn):
    _, rows = db.current_rows(conn)
    ids = [str(row[db.PLACE_ID]).strip() for row in rows if str(row.get(db.PLACE_ID) or "").strip()]
    return ids[0], ids[1]


def test_a_duplicate_is_marked_and_logged_and_nothing_is_deleted(conn):
    keep, dup = two_ids(conn)
    before = len(db.current_rows(conn)[1])
    plan, refusals = duplicates.check(conn, dup, keep)
    assert refusals == []
    report = duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    assert report["applied"] == 1
    assert db.duplicate_of_map(conn)[dup] == keep
    assert len(db.current_rows(conn)[1]) == before, "no row is removed"
    logged = conn.execute(
        "SELECT column_name, old_value, new_value, stage FROM changes"
        " WHERE run_id = 'duplicate-test'").fetchall()
    assert [tuple(row) for row in logged] == [(duplicates.COLUMN, "", keep, "duplicate")]


def test_the_mark_survives_a_rebuild(conn):
    """rebuild recomputes the derived tables from the imported rows. A mark the
    database set itself must not be wiped by it."""
    keep, dup = two_ids(conn)
    plan, _ = duplicates.check(conn, dup, keep)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    db.rebuild(conn)
    assert db.duplicate_of_map(conn)[dup] == keep


def test_a_marked_row_is_skipped_by_routing(conn):
    """The mark has to change something. route reads duplicate_of."""
    from ferro_parking import route

    keep, dup = two_ids(conn)
    plan, _ = duplicates.check(conn, dup, keep)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    _, rows = db.current_rows(conn)
    row = next(r for r in rows if str(r[db.PLACE_ID]).strip() == dup)
    stage, _, _, reason = route.classify(row, set(), db.duplicate_of_map(conn))
    assert stage == "skip_duplicate"
    assert keep in reason


def test_clear_reverses_the_mark(conn):
    keep, dup = two_ids(conn)
    plan, _ = duplicates.check(conn, dup, keep)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    back, refusals = duplicates.check(conn, dup, None, clear=True)
    assert refusals == []
    duplicates.apply_plan(conn, back, "duplicate-clear", apply=True)
    assert dup not in db.duplicate_of_map(conn)


def test_a_dry_run_changes_nothing(conn):
    keep, dup = two_ids(conn)
    plan, _ = duplicates.check(conn, dup, keep)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=False)
    assert db.duplicate_of_map(conn) == {}


@pytest.mark.parametrize("make, expected", [
    (lambda keep, dup: ("PP-999999", keep), "unknown to the database"),
    (lambda keep, dup: (dup, "PP-999999"), "unknown to the database"),
    (lambda keep, dup: (dup, dup), "cannot be a duplicate of itself"),
    (lambda keep, dup: (dup, ""), "--keep is required"),
])
def test_refusals_block_the_command(conn, make, expected):
    keep, dup = two_ids(conn)
    duplicate, stands = make(keep, dup)
    plan, refusals = duplicates.check(conn, duplicate, stands)
    assert plan == []
    assert any(expected in line["reason"] for line in refusals)


def test_a_chain_is_refused(conn):
    """Marking a row a duplicate of a row that is itself a duplicate would
    leave a chain nobody reads."""
    _, rows = db.current_rows(conn)
    ids = [str(r[db.PLACE_ID]).strip() for r in rows if str(r.get(db.PLACE_ID) or "").strip()]
    first, second, third = ids[0], ids[1], ids[2]
    plan, _ = duplicates.check(conn, second, first)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    plan, refusals = duplicates.check(conn, third, second)
    assert plan == []
    assert any("would leave a chain" in line["reason"] for line in refusals)


def test_a_personally_verified_row_is_never_marked(tmp_path):
    """current_rows reads the imported rows, so the verifier has to be in the
    import, the way a hand check reaches the database in real life."""
    import csv

    with open(FIXTURE, newline="", encoding="utf-8-sig") as stream:
        rows = list(csv.DictReader(stream))
        headers = list(rows[0])
    rows[1]["Verified By"] = "Tharidu"
    path = tmp_path / "hand_checked.csv"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

    connection = db.connect(tmp_path / "ferro.sqlite")
    db.import_sheet_csv(connection, path)
    keep = str(rows[0][db.PLACE_ID]).strip()
    dup = str(rows[1][db.PLACE_ID]).strip()
    plan, refusals = duplicates.check(connection, dup, keep)
    assert plan == []
    assert any("a named person" in line["reason"] for line in refusals)


def test_an_active_created_record_is_refused(conn):
    """Its authoritative row lives in created, so db-create-undo retires it."""
    keep, _ = two_ids(conn)
    made = create.apply_plan(conn, [{
        "source": "osm", "source_ref": "way/7777",
        "row": {"Location Name": "Somewhere Wharf Car Park",
                "Place Category": "Council car park", "Borough": "Sutton",
                "Latitude": "51.200000", "Longitude": "-0.200000",
                "Geo Source": "OpenStreetMap", "Geo Precision": "Polygon centroid",
                "Captured By": "OSM discovery", "Date Captured": "2026-11-11",
                "Source URLs (primary first)": "https://www.openstreetmap.org/way/7777",
                "OSM ID": "way/7777", "Notes": "OSM tags: access=yes."}}],
        "create-test", apply=True)
    created_id = made["rows"][0]["Place ID"]
    plan, refusals = duplicates.check(conn, created_id, keep)
    assert plan == []
    assert any("db-create-undo" in line["reason"] for line in refusals)


def test_marking_the_same_pair_twice_changes_nothing(conn):
    keep, dup = two_ids(conn)
    plan, _ = duplicates.check(conn, dup, keep)
    duplicates.apply_plan(conn, plan, "duplicate-test", apply=True)
    again, refusals = duplicates.check(conn, dup, keep)
    assert again == []
    assert any("nothing to change" in line["reason"] for line in refusals)
