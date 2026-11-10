"""Phase 4: the category default, only for rows the router sent to "default"."""
import csv
from datetime import date
from pathlib import Path

import pytest

from ferro_parking import category_default, db, fill, plan, rules as rules_mod

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))
TODAY = date(2026, 11, 10)
RULES = rules_mod.load_rules()


def sheet_row(**values):
    row = {header: "" for header in HEADERS}
    row.update(values)
    return row


def outcome_of(row, osm_row=None):
    return category_default.plan_lines_for(row, osm_row or {}, RULES, TODAY)[0]


def planned(row, osm_row=None):
    lines = category_default.plan_lines_for(row, osm_row or {}, RULES, TODAY)[1]
    return {entry["column"]: entry["new_value"] for entry in lines}


# ---------------------------------------------------------------- the rules, unchanged

def test_a_large_format_chain_becomes_a_cautious_conditional_row():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney",
                       "Place Category": "Supermarket - large format", "Brand": "Tesco"})
    assert outcome_of(row) == category_default.OUTCOME_CHAIN_POLICY
    values = planned(row)
    assert values[fill.CAN_PARK] == "Conditional"
    assert values[fill.WHO_CAN_PARK] == "Customers only"
    assert values["Cost Type"] == "Unknown"
    assert values["Max Stay (mins)"] == "Not published"
    assert values["Evidence Level"] == "Chain policy"
    assert values["Verification Result"] == "Confirmed, details not published"
    assert values[fill.VERIFIED_BY] == "Policy script"


def test_r7_holds_so_no_outcome_is_free_anyone_or_a_max_stay():
    for name, category in (("Tesco Superstore Hackney", "Supermarket - large format"),
                           ("Asda Leyton", "Supermarket - large format"),
                           ("Lidl Bow", "Supermarket - large format"),
                           ("Morrisons Southwark", "Supermarket - large format")):
        values = planned(sheet_row(**{"Place ID": "PP-1", "Location Name": name,
                                       "Place Category": category,
                                       "Brand": name.split()[0]}))
        assert values["Cost Type"] in ("Unknown", "Paid"), name
        assert values[fill.WHO_CAN_PARK] in ("Customers only", "Guests only",
                                              "Patients and visitors"), name
        assert values["Max Stay (mins)"] == "Not published", name


def test_a_hotel_chain_gets_guests_only():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Premier Inn London Bow",
                       "Place Category": "Hotel", "Brand": "Premier Inn",
                       "Type (as captured)": "Hotel"})
    if outcome_of(row) == category_default.OUTCOME_CHAIN_POLICY:
        assert planned(row)[fill.WHO_CAN_PARK] == "Guests only"


def test_an_unrecognised_brand_is_not_classified():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Costless Supermarket",
                       "Place Category": "Supermarket - large format"})
    assert outcome_of(row) == category_default.OUTCOME_UNCLASSIFIED
    assert planned(row) == {}


def test_a_gym_with_no_mapped_car_park_is_not_classified():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "PureGym Bow",
                       "Place Category": "Gym / leisure centre"})
    assert outcome_of(row) == category_default.OUTCOME_UNCLASSIFIED


def test_a_gym_with_a_mapped_car_park_nearby_becomes_chain_policy():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "PureGym Bow",
                       "Place Category": "Gym / leisure centre", "Brand": "PureGym"})
    assert outcome_of(row, {"Car Park Distance (m)": "20"}) == category_default.OUTCOME_CHAIN_POLICY


def test_a_car_park_row_is_never_given_a_category_default():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Waitrose Car Park",
                       "Place Category": "Private / operator car park"})
    assert outcome_of(row) == category_default.OUTCOME_UNCLASSIFIED


def test_map_absence_alone_never_presumes_no_parking():
    """policy_fill now answers "Map absence is not evidence of no parking" for
    a small venue and for a convenience format, so R10's presumed No never
    fires from this command."""
    for name, category in (("Pret A Manger Liverpool Street", "Restaurant / pub / cafe"),
                           ("Tesco Express Bow", "Supermarket - convenience")):
        row = sheet_row(**{"Place ID": "PP-1", "Location Name": name,
                           "Place Category": category})
        assert outcome_of(row) == category_default.OUTCOME_UNCLASSIFIED, name


# ---------------------------------------------------------------- context columns

def test_brand_and_place_category_travel_as_context():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney",
                       "Place Category": "Supermarket - large format", "Brand": "Tesco"})
    values = planned(row)
    assert values["Brand"] == "Tesco"
    assert values["Place Category"] == "Supermarket - large format"


def test_no_plan_line_is_blank():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney",
                       "Place Category": "Supermarket - large format", "Brand": "Tesco"})
    lines = category_default.plan_lines_for(row, {}, RULES, TODAY)[1]
    assert lines
    assert all(str(entry["new_value"]).strip() for entry in lines)


def test_every_line_names_the_default_stage():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney",
                       "Place Category": "Supermarket - large format", "Brand": "Tesco"})
    lines = category_default.plan_lines_for(row, {}, RULES, TODAY)[1]
    assert {entry["stage"] for entry in lines} == {"default"}
    assert {entry["verified_by"] for entry in lines} == {"Policy script"}


# ---------------------------------------------------------------- the input set

@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    return connection


def seed(connection, stages, run_id="route-1"):
    connection.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES (?, ?, ?, 'test')",
        [(run_id, place_id, stage) for place_id, stage in stages.items()])
    connection.commit()


def test_only_default_stage_rows_are_read(conn):
    seed(conn, {"PP-000001": "default", "PP-000002": "grok", "PP-000003": "skip_named",
                "PP-000004": "station"})
    rows, run_id = category_default.default_rows(conn)
    assert [row["Place ID"] for row in rows] == ["PP-000001"]
    assert run_id == "route-1"


def test_station_rows_are_out_of_scope(conn):
    seed(conn, {"PP-000001": "station", "PP-000002": "station",
                "PP-000003": "station", "PP-000004": "station"})
    assert category_default.default_rows(conn)[0] == []


def test_grok_and_fetcher_rows_are_out_of_scope(conn):
    seed(conn, {"PP-000001": "grok", "PP-000002": "fetcher:ncp",
                "PP-000003": "skip_done", "PP-000004": "skip_onsite"})
    assert category_default.default_rows(conn)[0] == []


def test_only_the_latest_routing_run_counts(conn):
    seed(conn, {"PP-000001": "default", "PP-000004": "default"}, run_id="route-1")
    seed(conn, {"PP-000001": "skip_done", "PP-000004": "default"}, run_id="route-2")
    rows, run_id = category_default.default_rows(conn)
    assert [row["Place ID"] for row in rows] == ["PP-000004"]
    assert run_id == "route-2"


def test_no_routing_run_stops_the_command(conn):
    with pytest.raises(SystemExit, match="Run route first"):
        category_default.default_rows(conn)


# ---------------------------------------------------------------- the report

def test_build_counts_outcomes_and_categories(conn):
    seed(conn, {"PP-000001": "default", "PP-000002": "default",
                "PP-000003": "default", "PP-000004": "default"})
    lines, report = category_default.build(conn, rules=RULES, today=TODAY)
    assert report["rows"] == 4
    assert sum(report["outcomes"].values()) == 4
    assert report["routing_run"] == "route-1"
    assert set(report["by_category"]) == {"Supermarket - large format",
                                          "Private / operator car park", "(blank)"}


def test_examples_are_capped_at_five_per_outcome(conn):
    seed(conn, {f"PP-00000{n}": "default" for n in range(1, 5)})
    _, report = category_default.build(conn, rules=RULES, today=TODAY)
    assert all(len(examples) <= 5 for examples in report["examples"].values())


def test_an_unclassified_example_records_the_reason(conn):
    seed(conn, {"PP-000004": "default"})
    _, report = category_default.build(conn, rules=RULES, today=TODAY)
    rows = category_default.example_rows(report)
    assert rows
    assert rows[0]["column"] == "(no change)"
    assert rows[0]["new value"]


def test_the_summary_names_each_group(conn):
    seed(conn, {"PP-000001": "default", "PP-000004": "default"})
    _, report = category_default.build(conn, rules=RULES, today=TODAY)
    groups = {row["group"] for row in category_default.summary_rows(report)}
    assert "outcome" in groups
    assert any(group.startswith("category: ") for group in groups)


# ---------------------------------------------------------------- the command

def test_default_fill_writes_a_plan_and_two_reports(conn, tmp_path):
    seed(conn, {"PP-000001": "default", "PP-000002": "default",
                "PP-000003": "default", "PP-000004": "default"})
    out = tmp_path / "out"
    assert category_default.main(["--db", str(tmp_path / "test.sqlite"),
                                  "--out", str(out), "--osm-results", str(no_osm(tmp_path))]) == 0
    for name in ("plan.jsonl", "summary.csv", "examples.csv"):
        assert (out / name).exists()


def no_osm(tmp_path):
    """An osm_results.csv with headers and no rows, so the command never reads
    the real run folders during a test."""
    path = tmp_path / "osm_results.csv"
    path.write_text("Place ID,Car Park Distance (m)\n", encoding="utf-8")
    return path


def test_default_fill_writes_nothing_to_the_database(conn, tmp_path):
    seed(conn, {"PP-000001": "default", "PP-000004": "default"})
    category_default.main(["--db", str(tmp_path / "test.sqlite"), "--out", str(tmp_path / "o"),
                            "--osm-results", str(no_osm(tmp_path))])
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM evidence").fetchone()["n"] == 0


def test_the_plan_it_writes_is_readable_by_db_apply(conn, tmp_path):
    """A plan for a recognised chain must pass db-apply's own checks."""
    conn.execute("UPDATE raw SET json = json_set(json_set(json_set(json_set(json,"
                 " '$.\"Location Name\"', 'Tesco Superstore Hackney'),"
                 " '$.\"Brand\"', 'Tesco'),"
                 " '$.\"Place Category\"', 'Supermarket - large format'),"
                 " '$.\"Verification Result\"', '') WHERE place_id = 'PP-000004'")
    conn.commit()
    seed(conn, {"PP-000004": "default"})
    lines, _ = category_default.build(conn, rules=RULES, today=TODAY)
    assert lines
    report = plan.apply_plan(conn, lines, "run-default", apply=False)
    assert report["rejected"] == [], report["rejected"]


def test_load_osm_rows_with_no_file_reports_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rows, source = category_default.load_osm_rows()
    assert rows == {}
    assert source is None


def test_a_row_with_no_brand_or_category_waits_for_a_person():
    """validate_rows asks for both on a Conditional row, and this command does
    not invent either one."""
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney"})
    outcome, lines, reason = category_default.plan_lines_for(row, {}, RULES, TODAY)
    assert outcome == category_default.OUTCOME_UNCLASSIFIED
    assert lines == []
    assert "no Brand and no Place Category" in reason


def test_a_row_with_a_brand_but_no_category_also_waits():
    row = sheet_row(**{"Place ID": "PP-1", "Location Name": "Tesco Superstore Hackney",
                       "Brand": "Tesco"})
    outcome, _, reason = category_default.plan_lines_for(row, {}, RULES, TODAY)
    assert outcome == category_default.OUTCOME_UNCLASSIFIED
    assert "no Place Category" in reason
