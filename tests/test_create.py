"""Created records: the create path, its refusals, undo, rebuild and export.

A created record is one the database made itself, from OpenStreetMap, with no
sheet row behind it. These tests hold the gates the execution checklist keeps:
creation never states a parking answer, a repeated run adds no duplicate, undo
deactivates and never frees a Place ID, and an imported row never changes.
"""
import csv
import json
from pathlib import Path

import pytest

from ferro_parking import create, db

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"


def record(source_ref="way/100", **overrides):
    row = {
        "Location Name": "Hill Street Car Park",
        "Place Category": "Council car park",
        "Borough": "Sutton",
        "Latitude": "51.361737",
        "Longitude": "-0.149787",
        "Geo Source": "OpenStreetMap",
        "Geo Precision": "Polygon centroid",
        "Captured By": "OSM discovery",
        "Date Captured": "2026-11-10",
        "Source URLs (primary first)": "https://www.openstreetmap.org/way/100",
        "OSM ID": "way/100",
        "Notes": "OSM tags: access=yes; capacity=40.",
    }
    row.update(overrides.pop("row", {}))
    out = {"source": "osm", "source_ref": source_ref, "row": row}
    out.update(overrides)
    return out


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    return connection


def run(conn, records, run_id="create-test", apply=True):
    return create.apply_plan(conn, records, run_id, apply=apply)


# ---------------------------------------------------------------- plan file

def test_a_create_plan_round_trips(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    assert create.read_plan(path) == [record()]


def test_a_plan_line_without_a_row_is_an_error(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(json.dumps({"source": "osm", "source_ref": "way/1"}) + "\n",
                    encoding="utf-8")
    with pytest.raises(ValueError, match="missing 'row'"):
        create.read_plan(path)


# ---------------------------------------------------------------- the create gate

def test_creation_may_not_state_who_can_park(conn):
    report = run(conn, [record(row={"Who Can Park": "Anyone"})], apply=False)
    assert report["created"] == 0
    assert any("not a creation column" in line["reason"] for line in report["rejected"])


@pytest.mark.parametrize("column,value", [
    ("Can Park? (Yes/No/Conditional)", "Yes"),
    ("Cost Type", "Free"),
    ("Max Stay (mins)", "120"),
    ("Tariff Detail", "£2 per hour"),
    ("Verification Result", "Confirmed"),
    ("Verified By", "OSM discovery"),
    ("Evidence Level", "Verified"),
    ("Confidence (1-5)", "5"),
    ("Ferro Autopay", "Yes"),
    ("Parking Charge (£)", "2.50"),
    ("Free Stay Countdown (mins)", "60"),
    ("Total incl. Ferro Fee (£)", "3.00"),
])
def test_every_parking_answer_and_owner_field_is_refused_at_creation(conn, column, value):
    report = run(conn, [record(row={column: value})], apply=False)
    assert report["rejected"], f"{column} was allowed at creation"
    assert report["created"] == 0


def test_an_unknown_column_is_refused(conn):
    report = run(conn, [record(row={"Parking Vibes": "good"})], apply=False)
    assert any("unknown column" in line["reason"] for line in report["rejected"])


def test_a_record_needs_a_name_and_a_point(conn):
    report = run(conn, [record(row={"Location Name": ""})], apply=False)
    assert any("needs a Location Name" in line["reason"] for line in report["rejected"])
    report = run(conn, [record(row={"Latitude": ""})], apply=False)
    assert any("needs a Latitude" in line["reason"] for line in report["rejected"])
    report = run(conn, [record(row={"Longitude": "west a bit"})], apply=False)
    assert any("not a number" in line["reason"] for line in report["rejected"])


def test_a_plan_may_not_choose_its_own_place_id(conn):
    report = run(conn, [record(row={"Place ID": "PP-000001"})], apply=False)
    assert any("allocates the Place ID" in line["reason"] for line in report["rejected"])


def test_one_refusal_blocks_the_whole_plan(conn):
    before = len(db.current_rows(conn)[1])
    report = run(conn, [record(source_ref="way/1"),
                        record(source_ref="way/2", row={"Cost Type": "Free"})])
    assert report["created"] == 0
    assert len(db.current_rows(conn)[1]) == before


def test_the_same_source_ref_twice_in_one_plan_is_refused(conn):
    report = run(conn, [record(source_ref="way/7"), record(source_ref="way/7")], apply=False)
    assert any("appears twice" in line["reason"] for line in report["rejected"])


# ---------------------------------------------------------------- creating

def test_a_dry_run_creates_nothing(conn):
    before = len(db.current_rows(conn)[1])
    report = run(conn, [record()], apply=False)
    assert report["accepted"] == 1
    assert report["created"] == 0
    assert len(db.current_rows(conn)[1]) == before
    assert conn.execute("SELECT COUNT(*) AS n FROM created").fetchone()["n"] == 0


def test_a_created_record_is_readable_and_keeps_its_parking_answers_blank(conn):
    run(conn, [record()])
    headers, rows = db.current_rows(conn)
    created = [row for row in rows if row["Location Name"] == "Hill Street Car Park"]
    assert len(created) == 1
    row = created[0]
    assert row["Place ID"].startswith("PP-")
    assert row["Borough"] == "Sutton"
    assert row["OSM ID"] == "way/100"
    for column in ("Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type",
                   "Tariff Detail", "Max Stay (mins)", "Verification Result",
                   "Verified By", "Ferro Autopay", "Parking Charge (£)"):
        assert row[column] == "", f"{column} is not blank on a created record"


def test_a_created_record_reaches_the_derived_tables(conn):
    run(conn, [record()])
    place = conn.execute(
        "SELECT * FROM places WHERE name = 'Hill Street Car Park'").fetchone()
    assert place is not None
    assert place["borough"] == "Sutton"
    parking = conn.execute(
        "SELECT * FROM parking WHERE place_id = ?", (place["place_id"],)).fetchone()
    assert parking is not None
    assert parking["can_park"] == ""


def test_created_records_append_after_the_imported_rows(conn):
    _, before = db.effective_rows(conn)
    run(conn, [record()])
    _, after = db.effective_rows(conn)
    assert len(after) == len(before) + 1
    assert [row["Place ID"] for row in after[:len(before)]] == \
           [row["Place ID"] for row in before]


def test_an_imported_row_is_unchanged_by_a_create(conn):
    _, before = db.effective_rows(conn)
    first_before = dict(before[0])
    run(conn, [record()])
    _, after = db.effective_rows(conn)
    assert dict(after[0]) == first_before


def test_export_keeps_the_imported_rows_and_appends_the_created_one(conn, tmp_path):
    first = tmp_path / "before.csv"
    db.export_csv(conn, first)
    before = list(csv.DictReader(first.open(encoding="utf-8")))
    run(conn, [record()])
    second = tmp_path / "after.csv"
    db.export_csv(conn, second)
    after = list(csv.DictReader(second.open(encoding="utf-8")))
    assert after[:len(before)] == before
    assert len(after) == len(before) + 1
    assert after[-1]["Location Name"] == "Hill Street Car Park"


def test_place_ids_continue_from_the_highest_imported_id(conn):
    expected = db.next_place_id(conn)
    run(conn, [record()])
    created = conn.execute("SELECT place_id FROM created").fetchone()["place_id"]
    assert created == expected


def test_two_records_in_one_plan_get_different_ids(conn):
    run(conn, [record(source_ref="way/1"), record(source_ref="way/2")])
    ids = [row["place_id"] for row in conn.execute(
        "SELECT place_id FROM created ORDER BY rowid")]
    assert len(set(ids)) == 2


# ---------------------------------------------------------------- repeat safety

def test_running_the_same_plan_twice_creates_nothing_the_second_time(conn):
    plan = [record(source_ref="way/1"), record(source_ref="way/2")]
    first = run(conn, plan, run_id="create-1")
    assert first["created"] == 2
    second = run(conn, plan, run_id="create-2")
    assert second["created"] == 0
    assert second["rejected"] == []
    assert len(second["skipped"]) == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM created").fetchone()["n"] == 2


def test_a_source_ref_already_created_does_not_block_a_new_one(conn):
    run(conn, [record(source_ref="way/1")], run_id="create-1")
    report = run(conn, [record(source_ref="way/1"), record(source_ref="way/2")],
                 run_id="create-2")
    assert report["created"] == 1
    assert len(report["skipped"]) == 1


def test_an_id_is_never_reused_after_an_undo(conn):
    run(conn, [record(source_ref="way/1")], run_id="create-1")
    first = conn.execute("SELECT place_id FROM created").fetchone()["place_id"]
    create.undo_run(conn, "create-1", apply=True)
    run(conn, [record(source_ref="way/2")], run_id="create-2")
    ids = [row["place_id"] for row in conn.execute(
        "SELECT place_id FROM created ORDER BY rowid")]
    assert ids[1] != first
    assert len(set(ids)) == 2


# ---------------------------------------------------------------- undo

def test_undo_deactivates_and_deletes_nothing(conn):
    run(conn, [record()], run_id="create-1")
    before = len(db.current_rows(conn)[1])
    report = create.undo_run(conn, "create-1", apply=True)
    assert report["deactivated"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM created").fetchone()["n"] == 1
    assert conn.execute("SELECT active FROM created").fetchone()["active"] == 0
    assert len(db.current_rows(conn)[1]) == before - 1


def test_an_undo_dry_run_changes_nothing(conn):
    run(conn, [record()], run_id="create-1")
    report = create.undo_run(conn, "create-1", apply=False)
    assert report["deactivated"] == 0
    assert conn.execute("SELECT active FROM created").fetchone()["active"] == 1


def test_undo_of_an_unknown_run_is_refused(conn):
    report = create.undo_run(conn, "create-nope", apply=True)
    assert any("no create run" in line["reason"] for line in report["refused"])


def test_undo_is_refused_when_a_later_run_changed_the_record(conn):
    run(conn, [record()], run_id="create-1")
    place_id = conn.execute("SELECT place_id FROM created").fetchone()["place_id"]
    conn.execute(
        "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
        " stage, applied_at) VALUES ('research-1', ?, 'Cost Type', '', 'Paid',"
        " 'grok', '2026-11-11T00:00:00+00:00')", (place_id,))
    conn.commit()
    report = create.undo_run(conn, "create-1", apply=True)
    assert report["deactivated"] == 0
    assert any("newer evidence" in line["reason"] for line in report["refused"])
    assert conn.execute("SELECT active FROM created").fetchone()["active"] == 1


def test_undo_twice_is_safe(conn):
    run(conn, [record()], run_id="create-1")
    create.undo_run(conn, "create-1", apply=True)
    report = create.undo_run(conn, "create-1", apply=True)
    assert report["deactivated"] == 0
    assert report["already_inactive"] == 1


# ---------------------------------------------------------------- research later

def test_a_created_record_keeps_a_research_change(conn):
    run(conn, [record()])
    place_id = conn.execute("SELECT place_id FROM created").fetchone()["place_id"]
    conn.execute(
        "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
        " stage, applied_at) VALUES ('research-1', ?, 'Cost Type', '', 'Paid',"
        " 'grok', '2026-11-11T00:00:00+00:00')", (place_id,))
    conn.commit()
    db.rebuild(conn)
    _, rows = db.current_rows(conn)
    row = next(r for r in rows if r["Place ID"] == place_id)
    assert row["Cost Type"] == "Paid"


def test_a_later_sheet_import_does_not_drop_created_records(conn):
    run(conn, [record()])
    db.import_sheet_csv(conn, FIXTURE)
    _, rows = db.current_rows(conn)
    assert any(row["Location Name"] == "Hill Street Car Park" for row in rows)
    _, rows = db.effective_rows(conn)
    assert any(row["Location Name"] == "Hill Street Car Park" for row in rows)


# ---------------------------------------------------------------- output files

def test_db_create_writes_its_report_as_files(tmp_path, conn, monkeypatch):
    """Regression: the run-path helper reserves directories, not files. Calling
    it on plan.csv created a directory and the write then failed."""
    plan = tmp_path / "plan.jsonl"
    plan.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite")
    assert create.main(["--plan", str(plan), "--db", str(tmp_path / "test.sqlite"),
                        "--out", str(out)]) == 0
    assert (out / "plan.csv").is_file()
    assert (out / "report.json").is_file()
    rows = list(csv.DictReader((out / "plan.csv").open(encoding="utf-8")))
    assert rows[0]["Location Name"] == "Hill Street Car Park"


def test_db_create_writes_a_rejected_file_and_exits_nonzero(tmp_path, conn, monkeypatch):
    plan = tmp_path / "plan.jsonl"
    plan.write_text(json.dumps(record(row={"Cost Type": "Free"})) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    assert create.main(["--plan", str(plan), "--db", str(tmp_path / "test.sqlite"),
                        "--out", str(out), "--apply"]) == 1
    assert (out / "rejected.csv").is_file()
