"""Phase 1: the SQLite store must lose nothing and must rebuild the same way twice."""
import csv
import json
from pathlib import Path

import pytest

from ferro_parking import db

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"


def read_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def compare(path_a, path_b):
    """Mismatching (Place ID, column) cells between two sheet CSVs."""
    headers_a, rows_a = read_rows(path_a)
    headers_b, rows_b = read_rows(path_b)
    assert headers_a == headers_b, "column order or header text differs"
    by_id_b = {row["Place ID"]: row for row in rows_b}
    mismatches = []
    for row in rows_a:
        other = by_id_b.get(row["Place ID"])
        if other is None:
            mismatches.append((row["Place ID"], "*", "row missing"))
            continue
        for header in headers_a:
            if row[header] != other[header]:
                mismatches.append((row["Place ID"], header, f"{row[header]!r} vs {other[header]!r}"))
    for place_id in set(by_id_b) - {row["Place ID"] for row in rows_a}:
        mismatches.append((place_id, "*", "extra row"))
    return mismatches


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "test.sqlite")


# ---------------------------------------------------------------- round trip

def test_import_then_export_matches_on_every_cell(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    out = tmp_path / "exported.csv"
    assert db.export_csv(conn, out) == 4
    assert compare(FIXTURE, out) == []


def test_export_is_byte_identical_to_the_import(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    out = tmp_path / "exported.csv"
    db.export_csv(conn, out)
    # Raw bytes, line endings included. .gitattributes keeps the fixture's
    # CRLF, which is what the csv module writes and what the sheet export has.
    assert out.read_bytes() == FIXTURE.read_bytes()


def test_export_keeps_the_sheet_row_order(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    out = tmp_path / "exported.csv"
    db.export_csv(conn, out)
    _, rows = read_rows(out)
    assert [row["Place ID"] for row in rows] == ["PP-000001", "PP-000002", "PP-000003", "PP-000004"]


def test_awkward_values_survive_the_round_trip(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    out = tmp_path / "exported.csv"
    db.export_csv(conn, out)
    _, rows = read_rows(out)
    second = {row["Place ID"]: row for row in rows}["PP-000002"]
    assert '"The Mall"' in second["Location Name"]
    assert "\n" in second["Notes"]
    assert second["Charges (as published)"] == "0-2 hrs £2.50; 2-4 hrs £4.00"


def test_export_refuses_to_overwrite_an_existing_file(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    out = tmp_path / "exported.csv"
    db.export_csv(conn, out)
    with pytest.raises(FileExistsError):
        db.export_csv(conn, out)


def test_export_before_any_import_is_refused(conn, tmp_path):
    with pytest.raises(ValueError, match="nothing imported yet"):
        db.export_csv(conn, tmp_path / "exported.csv")


# ---------------------------------------------------------------- raw table

def test_raw_keeps_every_column_of_every_row(conn):
    db.import_sheet_csv(conn, FIXTURE)
    headers, rows = read_rows(FIXTURE)
    stored = db.raw_rows(conn, db.latest_import_id(conn))
    assert len(stored) == len(rows)
    for row in rows:
        _, kept = stored[row["Place ID"]]
        assert kept == row
        assert len(kept) == 60


def test_sheet_owned_columns_are_mirrored(conn):
    db.import_sheet_csv(conn, FIXTURE)
    row = conn.execute("SELECT * FROM sheet_owned WHERE place_id = 'PP-000001'").fetchone()
    assert row["free_stay_countdown_mins"] == "30"
    assert row["ferro_autopay"] == "✅"
    assert row["parking_charge_gbp"] == "2.50"
    assert row["total_incl_ferro_fee_gbp"] == "3.00"


# ---------------------------------------------------------------- repeat imports

def test_second_import_of_the_same_file_changes_nothing(conn, tmp_path):
    first_id, _ = db.import_sheet_csv(conn, FIXTURE)
    second_id, report = db.import_sheet_csv(conn, FIXTURE)
    assert second_id != first_id
    assert report["previous_import_id"] == first_id
    assert report["changed_cells"] == []
    assert report["new_place_ids"] == []
    assert report["missing_place_ids"] == []
    out = tmp_path / "exported.csv"
    db.export_csv(conn, out)
    assert compare(FIXTURE, out) == []


def test_both_imports_are_kept(conn):
    db.import_sheet_csv(conn, FIXTURE)
    db.import_sheet_csv(conn, FIXTURE)
    assert conn.execute("SELECT COUNT(*) AS n FROM imports").fetchone()["n"] == 2
    assert conn.execute("SELECT COUNT(*) AS n FROM raw").fetchone()["n"] == 8


def write_variant(tmp_path, edits=None, drop=(), extra=None):
    """The fixture with some cells edited, some rows dropped, one row added."""
    headers, rows = read_rows(FIXTURE)
    rows = [row for row in rows if row["Place ID"] not in drop]
    for row in rows:
        for column, value in (edits or {}).get(row["Place ID"], {}).items():
            row[column] = value
    if extra:
        new = {header: "" for header in headers}
        new.update(extra)
        rows.append(new)
    path = tmp_path / "variant.csv"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_report_names_changed_cells_new_and_missing_rows(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    variant = write_variant(
        tmp_path,
        edits={"PP-000001": {"Operator": "Euro Car Parks", "Max Stay (mins)": "90"}},
        drop=("PP-000004",),
        extra={"Place ID": "PP-000005", "Location Name": "New place"})
    _, report = db.import_sheet_csv(conn, variant)
    assert report["new_place_ids"] == ["PP-000005"]
    assert report["missing_place_ids"] == ["PP-000004"]
    assert sorted((cell["column"], cell["this import"]) for cell in report["changed_cells"]) == [
        ("Max Stay (mins)", "90"), ("Operator", "Euro Car Parks")]


def test_a_cell_the_database_never_changed_takes_the_sheet_value(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    variant = write_variant(tmp_path, edits={"PP-000003": {"Who Can Park": "Guests only"}})
    db.import_sheet_csv(conn, variant)
    _, rows = db.effective_rows(conn)
    assert {row["Place ID"]: row["Who Can Park"] for row in rows}["PP-000003"] == "Guests only"


def test_a_missing_place_id_keeps_its_derived_row(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    variant = write_variant(tmp_path, drop=("PP-000004",))
    db.import_sheet_csv(conn, variant)
    kept = conn.execute("SELECT name FROM places WHERE place_id = 'PP-000004'").fetchone()
    assert kept["name"] == "Pret A Manger, Liverpool Street"


# ---------------------------------------------------------------- applied changes

def apply_change(conn, place_id, column, old_value, new_value, run_id="run-1"):
    conn.execute(
        "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value, stage, applied_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run_id, place_id, column, old_value, new_value, "test", "2026-11-10T00:00:00+00:00"))
    conn.commit()


def test_an_applied_change_wins_over_the_sheet_value(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    apply_change(conn, "PP-000002", "Who Can Park", "Unknown", "Anyone (paid)")
    db.rebuild(conn)
    _, rows = db.effective_rows(conn)
    assert {row["Place ID"]: row["Who Can Park"] for row in rows}["PP-000002"] == "Anyone (paid)"
    assert conn.execute(
        "SELECT who_can_park FROM parking WHERE place_id = 'PP-000002'").fetchone()[0] == "Anyone (paid)"


def test_an_unapplied_change_is_ignored(conn):
    db.import_sheet_csv(conn, FIXTURE)
    conn.execute(
        "INSERT INTO changes (run_id, place_id, column_name, old_value, new_value, stage)"
        " VALUES ('run-1', 'PP-000002', 'Who Can Park', 'Unknown', 'Anyone (paid)', 'test')")
    conn.commit()
    _, rows = db.effective_rows(conn)
    assert {row["Place ID"]: row["Who Can Park"] for row in rows}["PP-000002"] == "Unknown"


def test_the_newest_applied_change_wins(conn):
    db.import_sheet_csv(conn, FIXTURE)
    apply_change(conn, "PP-000002", "Cost Type", "Unknown", "Paid")
    apply_change(conn, "PP-000002", "Cost Type", "Paid", "Free then paid", run_id="run-2")
    _, rows = db.effective_rows(conn)
    assert {row["Place ID"]: row["Cost Type"] for row in rows}["PP-000002"] == "Free then paid"


def test_a_hand_edit_on_a_database_owned_cell_is_reported_as_a_conflict(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    apply_change(conn, "PP-000002", "Cost Type", "Unknown", "Paid")
    variant = write_variant(tmp_path, edits={"PP-000002": {"Cost Type": "Free"}})
    _, report = db.import_sheet_csv(conn, variant)
    assert [(c["Place ID"], c["column"], c["sheet value"], c["database value"])
            for c in report["conflicts"]] == [("PP-000002", "Cost Type", "Free", "Paid")]


def test_the_sheet_catching_up_with_the_database_is_not_a_conflict(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    apply_change(conn, "PP-000002", "Cost Type", "Unknown", "Paid")
    variant = write_variant(tmp_path, edits={"PP-000002": {"Cost Type": "Paid"}})
    _, report = db.import_sheet_csv(conn, variant)
    assert report["conflicts"] == []


# ---------------------------------------------------------------- derived tables

def table_contents(conn, table):
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY place_id")]


def test_rebuild_is_idempotent(conn):
    db.import_sheet_csv(conn, FIXTURE)
    first = table_contents(conn, "places"), table_contents(conn, "parking")
    db.rebuild(conn)
    db.rebuild(conn)
    assert (table_contents(conn, "places"), table_contents(conn, "parking")) == first


def test_rebuild_adds_no_rows_when_run_twice(conn):
    db.import_sheet_csv(conn, FIXTURE)
    db.rebuild(conn)
    assert conn.execute("SELECT COUNT(*) AS n FROM places").fetchone()["n"] == 4
    assert conn.execute("SELECT COUNT(*) AS n FROM parking").fetchone()["n"] == 4


def test_derived_tables_carry_the_sheet_values(conn):
    db.import_sheet_csv(conn, FIXTURE)
    place = conn.execute("SELECT * FROM places WHERE place_id = 'PP-000001'").fetchone()
    assert place["name"] == "Tesco Superstore, Hackney"
    assert place["borough"] == "Hackney"
    assert place["osm_id"] == "way/123456"
    assert place["duplicate_of"] is None
    parking = conn.execute("SELECT * FROM parking WHERE place_id = 'PP-000003'").fetchone()
    assert parking["verified_by"] == "Tharidu"
    assert parking["max_stay_mins"] == "90"


def test_rebuild_after_an_import_needs_no_second_call(conn):
    db.import_sheet_csv(conn, FIXTURE)
    assert conn.execute("SELECT COUNT(*) AS n FROM parking").fetchone()["n"] == 4


# ---------------------------------------------------------------- place id allocation

def test_next_place_id_follows_the_highest_imported_id(conn):
    db.import_sheet_csv(conn, FIXTURE)
    assert db.next_place_id(conn) == "PP-000005"


def test_next_place_id_counts_ids_from_earlier_imports(conn, tmp_path):
    db.import_sheet_csv(conn, FIXTURE)
    variant = write_variant(tmp_path, drop=("PP-000004",))
    db.import_sheet_csv(conn, variant)
    assert db.next_place_id(conn) == "PP-000005"


def test_next_place_id_on_an_empty_database(conn):
    assert db.next_place_id(conn) == "PP-000001"


# ---------------------------------------------------------------- input validation

def test_a_duplicate_place_id_is_refused(conn, tmp_path):
    headers, rows = read_rows(FIXTURE)
    rows[1]["Place ID"] = rows[0]["Place ID"]
    path = tmp_path / "duplicate.csv"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="duplicate Place ID"):
        db.import_sheet_csv(conn, path)


def test_a_blank_place_id_is_refused(conn, tmp_path):
    headers, rows = read_rows(FIXTURE)
    rows[0]["Place ID"] = ""
    path = tmp_path / "blank.csv"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError, match="blank Place ID"):
        db.import_sheet_csv(conn, path)


def test_a_file_without_a_place_id_column_is_refused(conn, tmp_path):
    path = tmp_path / "noid.csv"
    path.write_text("Location Name,Postcode\nA shop,E1 1AA\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no 'Place ID' column"):
        db.import_sheet_csv(conn, path)


def test_a_short_row_reads_back_as_empty_strings_not_nulls(conn, tmp_path):
    headers, _ = read_rows(FIXTURE)
    path = tmp_path / "short.csv"
    # A row that stops at Place ID, leaving the last two columns absent
    # rather than empty, which is what DictReader turns into None.
    fields = [""] * (headers.index("Place ID") + 1)
    fields[headers.index("Location Name")] = "A shop"
    fields[headers.index("Place ID")] = "PP-000009"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        stream.write(",".join(headers) + "\n")
        stream.write(",".join(fields) + "\n")
    db.import_sheet_csv(conn, path)
    _, stored = db.raw_rows(conn, db.latest_import_id(conn))["PP-000009"]
    assert set(stored) == set(headers)
    assert all(value == "" for key, value in stored.items()
               if key not in ("Location Name", "Place ID"))


# ---------------------------------------------------------------- schema

def test_every_table_in_the_agreed_schema_exists(conn):
    names = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"imports", "raw", "places", "parking", "evidence", "pages", "changes",
            "routing", "sheet_owned", "published"} <= names


def test_connect_is_safe_to_call_twice_on_one_file(tmp_path):
    path = tmp_path / "twice.sqlite"
    first = db.connect(path)
    db.import_sheet_csv(first, FIXTURE)
    second = db.connect(path)
    assert second.execute("SELECT COUNT(*) AS n FROM raw").fetchone()["n"] == 4


def test_the_four_sheet_owned_columns_are_the_protected_ones():
    assert set(db.SHEET_OWNED_COLUMNS.values()) == {
        "Free Stay Countdown (mins)", "Ferro Autopay",
        "Parking Charge (£)", "Total incl. Ferro Fee (£)"}


def test_the_database_file_path_sits_under_the_ignored_data_folder():
    assert db.DB_PATH.parts[:2] == ("data", "db")


def test_the_header_order_of_the_import_is_stored(conn):
    db.import_sheet_csv(conn, FIXTURE)
    stored = json.loads(conn.execute(
        "SELECT header_json FROM imports").fetchone()["header_json"])
    headers, _ = read_rows(FIXTURE)
    assert stored == headers
