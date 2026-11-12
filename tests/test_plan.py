"""Phase 3: plan files, the refusals, the change log, the undo and grok-import."""
import csv
import json
from pathlib import Path

import pytest

from ferro_parking import db, plan

FIXTURE = Path(__file__).parent / "fixtures" / "db_sheet_sample.csv"
HEADERS = next(csv.reader(FIXTURE.open(encoding="utf-8-sig")))

# PP-000004 is the nearly empty Pret row, so a plan line on it adds a value
# rather than replacing one. PP-000003 is the Tharidu row.
BLANK_ROW = "PP-000004"
NAMED_ROW = "PP-000003"
FILLED_ROW = "PP-000001"

STRONG = {"Source Tier": "Official site - text", "Specificity": "Site-specific"}


def line(place_id=BLANK_ROW, column="Who Can Park", new_value="Customers only", **extra):
    out = {"place_id": place_id, "column": column, "new_value": new_value,
           "quote": "the page says customers only", "source_url": "https://example.org/x",
           "stage": "default", "verified_by": "Policy script"}
    out.update(extra)
    return out


def full_row_lines(place_id=BLANK_ROW, **overrides):
    """A plan that satisfies validate_rows: the consistency checks want a
    Decision Reason naming the route, and a Review Flag needs a Flag Status."""
    values = {
        "Brand": "Pret",
        "Place Category": "Restaurant / pub / cafe",
        "Can Park? (Yes/No/Conditional)": "Conditional",
        "Who Can Park": "Customers only",
        "Cost Type": "Unknown",
        "Max Stay (mins)": "Not published",
        "Decision Reason": "Route D: category default, no site-specific evidence read",
        "Evidence Level": "Presumed",
    }
    values.update(overrides)
    return [line(place_id=place_id, column=column, new_value=value)
            for column, value in values.items()]


def seed_routing(connection, stage="default", run_id="route-test"):
    """Every plan line names a stage, and db-apply refuses a row the latest
    routing run put somewhere else. Most tests here are about something other
    than routing, so they start from a run that puts every row on one stage."""
    _, rows = db.current_rows(connection)
    connection.executemany(
        "INSERT OR REPLACE INTO routing (run_id, place_id, stage, reason)"
        " VALUES (?, ?, ?, 'test')",
        [(run_id, row["Place ID"], stage) for row in rows])
    connection.commit()


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    seed_routing(connection)
    return connection


def reasons(conn, lines):
    return [reject["reason"] for reject in plan.check_plan(conn, lines)[1]]


# ---------------------------------------------------------------- plan file format

def test_a_plan_file_round_trips(tmp_path):
    lines = [line(), line(column="Cost Type", new_value="Unknown")]
    path = tmp_path / "plan.jsonl"
    assert plan.write_plan(path, lines) == 2
    assert plan.read_plan(path) == lines


def test_each_plan_line_is_one_json_object(tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, [line(), line(column="Cost Type", new_value="Unknown")])
    objects = [json.loads(text) for text in path.read_text(encoding="utf-8").splitlines()]
    assert len(objects) == 2
    assert set(objects[0]) == set(plan.LINE_FIELDS)


def test_blank_lines_in_a_plan_file_are_skipped(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(json.dumps(line()) + "\n\n\n", encoding="utf-8")
    assert len(plan.read_plan(path)) == 1


def test_a_plan_line_that_is_not_json_is_refused(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not JSON"):
        plan.read_plan(path)


def test_a_plan_line_missing_a_required_field_is_refused(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text(json.dumps({"place_id": "PP-000001"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        plan.read_plan(path)


def test_a_plan_line_that_is_a_list_is_refused(tmp_path):
    path = tmp_path / "plan.jsonl"
    path.write_text('["PP-000001"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        plan.read_plan(path)


def test_write_plan_refuses_to_overwrite(tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, [line()])
    with pytest.raises(FileExistsError):
        plan.write_plan(path, [line()])


# ---------------------------------------------------------------- refusals

def test_an_unknown_place_id_is_refused(conn):
    assert "unknown Place ID 'PP-999999'" in reasons(conn, [line(place_id="PP-999999")])


def test_an_unknown_column_is_refused(conn):
    assert any("unknown column" in reason for reason in reasons(conn, [line(column="Nonsense")]))


def test_each_of_the_four_owner_columns_is_refused(conn):
    for column in ("Free Stay Countdown (mins)", "Ferro Autopay",
                   "Parking Charge (£)", "Total incl. Ferro Fee (£)"):
        got = reasons(conn, [line(column=column, new_value="1")])
        assert any("belongs to another owner" in reason for reason in got), column


def test_other_protected_columns_are_refused(conn):
    for column in ("Latitude", "Longitude", "Postcode", "Postcode Area", "Place ID",
                   "Confidence (1-5)", "Captured By", "Date Captured", "Geo Source",
                   "Geo Precision", "Charges (as published)", "Enforcement Details",
                   "Max Stay (as captured)", "Hours (as captured)", "Location Name"):
        got = reasons(conn, [line(column=column, new_value="x")])
        assert any("protected" in reason or "allowlist" in reason for reason in got), column


def test_a_column_outside_the_research_allowlist_is_refused(conn):
    """OSM ID is writable on the sheet but outside fill.RESEARCH_COLUMNS."""
    assert any("allowlist" in reason for reason in
               reasons(conn, [line(column="OSM ID", new_value="way/1")]))


def test_a_tharidu_row_is_refused(conn):
    assert any("a named person" in reason for reason in reasons(conn, [line(place_id=NAMED_ROW)]))


def test_an_agent_verified_row_is_not_refused_for_its_verifier(conn):
    for label in ("PP (validation)", "Grok (discovery)", "Policy script"):
        conn.execute("UPDATE raw SET json = json_set(json, '$.\"Verified By\"', ?)"
                     " WHERE place_id = ?", (label, BLANK_ROW))
        conn.commit()
        got = reasons(conn, full_row_lines())
        assert not any("named person" in reason for reason in got), label


def test_the_same_column_twice_for_one_place_id_is_refused(conn):
    got = reasons(conn, [line(), line(new_value="Anyone (paid)")])
    assert any("twice" in reason for reason in got)


# ---------------------------------------------------------------- replacing a value

def test_replacing_a_value_without_strong_evidence_is_refused(conn):
    got = reasons(conn, [line(place_id=FILLED_ROW, column="Who Can Park",
                              new_value="Anyone (paid)")])
    assert any("without strong site-specific evidence" in reason for reason in got)


def test_replacing_a_value_with_strong_site_specific_evidence_is_allowed(conn):
    lines = full_row_lines(
        place_id=FILLED_ROW,
        **{"Who Can Park": "Anyone (paid)", "Cost Type": "Paid",
           "Evidence Detail (what the source shows)": "the operator page lists public tariffs",
           **STRONG})
    got = [reject["reason"] for reject in plan.check_plan(conn, lines)[1]]
    assert not any("without strong site-specific evidence" in reason for reason in got), got


def test_a_weak_tier_with_site_specific_scope_is_still_refused(conn):
    lines = [line(place_id=FILLED_ROW, column="Who Can Park", new_value="Anyone (paid)"),
             line(place_id=FILLED_ROW, column="Source Tier",
                  new_value="Google search / third-party"),
             line(place_id=FILLED_ROW, column="Specificity", new_value="Site-specific")]
    assert any("without strong site-specific evidence" in reason
               for reason in reasons(conn, lines))


def test_a_strong_tier_with_chain_wide_scope_is_refused(conn):
    lines = [line(place_id=FILLED_ROW, column="Who Can Park", new_value="Anyone (paid)"),
             line(place_id=FILLED_ROW, column="Source Tier", new_value="Official site - text"),
             line(place_id=FILLED_ROW, column="Specificity", new_value="Chain-wide")]
    assert any("without strong site-specific evidence" in reason
               for reason in reasons(conn, lines))


def test_the_rows_own_old_evidence_cannot_vouch_for_a_new_value(conn):
    """PP-000001 already carries a strong site-specific Source Tier, but that
    evidence belongs to the value being replaced, so the plan must bring its
    own."""
    got = reasons(conn, [line(place_id=FILLED_ROW, column="Operator",
                              new_value="Euro Car Parks")])
    assert any("without strong site-specific evidence" in reason for reason in got)


def test_filling_a_blank_value_needs_no_strong_evidence(conn):
    got = reasons(conn, full_row_lines())
    assert not any("without strong site-specific evidence" in reason for reason in got), got


# ---------------------------------------------------------------- validate_rows

def test_the_existing_validate_rules_run_on_the_plan(conn):
    """Free with no strong site-specific evidence is rule R7's refusal, and it
    comes from validation.validate_rows, not from this module."""
    lines = full_row_lines(**{"Cost Type": "Free", "Tariff Type": "Free with time limit",
                              "Max Stay (mins)": "60"})
    assert any("evidence" in reject["reason"] for reject in plan.check_plan(conn, lines)[1])


def test_an_en_dash_is_refused(conn):
    lines = full_row_lines(**{"Rules Summary": "Free for 2 hours – then paid"})
    assert any("dashes" in reject["reason"] for reject in plan.check_plan(conn, lines)[1])


def test_a_value_outside_the_dropdown_is_refused(conn):
    lines = full_row_lines(**{"Who Can Park": "Everybody"})
    assert any("dropdown" in reject["reason"] for reject in plan.check_plan(conn, lines)[1])


def test_a_blank_new_value_is_refused(conn):
    lines = full_row_lines(**{"Who Can Park": ""})
    assert any("blank" in reject["reason"] for reject in plan.check_plan(conn, lines)[1])


def test_a_clean_plan_has_no_rejections(conn):
    assert plan.check_plan(conn, full_row_lines())[1] == []


# ---------------------------------------------------------------- apply

def test_a_dry_run_writes_nothing(conn):
    report = plan.apply_plan(conn, full_row_lines(), "run-1", apply=False)
    assert report["applied"] == 0
    assert len(report["dry_run_rows"]) == 8
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


def test_apply_records_every_change_under_one_run_id(conn):
    report = plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    assert report["applied"] == 8
    rows = [dict(row) for row in conn.execute(
        "SELECT run_id, place_id, column_name, old_value, new_value, stage, applied_at"
        " FROM changes ORDER BY id")]
    assert {row["run_id"] for row in rows} == {"run-1"}
    assert {row["place_id"] for row in rows} == {BLANK_ROW}
    assert all(row["applied_at"] for row in rows)
    assert all(row["old_value"] == "" for row in rows)


def test_verification_result_is_recorded_last(conn):
    lines = full_row_lines(**{"Verification Result": "Confirmed, details not published"})
    plan.apply_plan(conn, lines, "run-1", apply=True)
    columns = [row["column_name"] for row in conn.execute(
        "SELECT column_name FROM changes WHERE run_id = 'run-1' ORDER BY id")]
    assert columns[-1] == "Verification Result"


def test_the_dry_run_rows_also_put_verification_result_last(conn):
    lines = full_row_lines(**{"Verification Result": "Confirmed, details not published"})
    report = plan.apply_plan(conn, lines, "run-1", apply=False)
    assert report["dry_run_rows"][-1]["column"] == "Verification Result"


def test_an_applied_plan_changes_what_the_database_reads(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    _, rows = db.current_rows(conn)
    row = {r["Place ID"]: r for r in rows}[BLANK_ROW]
    assert row["Who Can Park"] == "Customers only"
    assert row["Evidence Level"] == "Presumed"
    assert conn.execute(
        "SELECT who_can_park FROM parking WHERE place_id = ?", (BLANK_ROW,)).fetchone()[0] == "Customers only"


def test_a_quote_and_a_source_url_become_evidence_rows(conn):
    report = plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    assert report["evidence"] == 8
    row = conn.execute(
        "SELECT * FROM evidence WHERE place_id = ? LIMIT 1", (BLANK_ROW,)).fetchone()
    assert row["run_id"] == "run-1"
    assert row["quote"] == "the page says customers only"
    assert row["source_url"] == "https://example.org/x"


def test_a_line_with_no_quote_records_no_evidence(conn):
    lines = [dict(entry, quote="", source_url="") for entry in full_row_lines()]
    report = plan.apply_plan(conn, lines, "run-1", apply=True)
    assert report["applied"] == 8
    assert report["evidence"] == 0


def test_one_refusal_blocks_the_whole_plan(conn):
    lines = full_row_lines() + [line(place_id="PP-999999")]
    report = plan.apply_plan(conn, lines, "run-1", apply=True)
    assert report["rejected"]
    assert report["applied"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


def test_applying_the_same_plan_twice_records_nothing_the_second_time(conn):
    """A line that restates the value already there is context for the
    validator, not a change, so db-apply is safe to run twice."""
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    report = plan.apply_plan(conn, full_row_lines(), "run-2", apply=True)
    assert report["rejected"] == []
    assert report["applied"] == 0
    assert report["unchanged"] == 8
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 8


def test_a_line_that_restates_the_current_value_is_not_a_replacement(conn):
    """The validator only sees the plan's own columns, so a plan that sets Can
    Park? must restate Brand and Place Category even when the row has them.
    Restating them must not trip the replacement rule."""
    lines = [line(place_id=FILLED_ROW, column="Brand", new_value="Tesco"),
             line(place_id=FILLED_ROW, column="Place Category",
                  new_value="Supermarket - large format")]
    got = [reject["reason"] for reject in plan.check_plan(conn, lines)[1]]
    assert not any("without strong site-specific evidence" in reason for reason in got), got


def test_an_unchanged_line_is_left_out_of_the_dry_run_rows(conn):
    lines = [line(place_id=FILLED_ROW, column="Brand", new_value="Tesco"),
             line(place_id=FILLED_ROW, column="Place Category",
                  new_value="Supermarket - large format")]
    report = plan.apply_plan(conn, lines, "run-1", apply=True)
    assert report["dry_run_rows"] == []
    assert report["unchanged"] == 2
    assert report["applied"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


# ---------------------------------------------------------------- undo

def test_undo_restores_the_old_values(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    report = plan.undo_run(conn, "run-1", apply=True)
    assert report["restored"] == 8
    _, rows = db.current_rows(conn)
    row = {r["Place ID"]: r for r in rows}[BLANK_ROW]
    assert row["Who Can Park"] == ""
    assert row["Evidence Level"] == ""


def test_an_undo_dry_run_changes_nothing(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    report = plan.undo_run(conn, "run-1", apply=False)
    assert report["restored"] == 0
    assert len(report["dry_run_rows"]) == 8
    _, rows = db.current_rows(conn)
    assert {r["Place ID"]: r for r in rows}[BLANK_ROW]["Who Can Park"] == "Customers only"


def test_undo_deletes_nothing(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    plan.undo_run(conn, "run-1", apply=True)
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 16
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM changes WHERE run_id = 'run-1'").fetchone()["n"] == 8


def test_undoing_twice_does_nothing_the_second_time(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    plan.undo_run(conn, "run-1", apply=True)
    report = plan.undo_run(conn, "run-1", apply=True)
    assert report["already_undone"] is True
    assert report["restored"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 16


def test_undoing_an_unknown_run_reports_nothing_to_do(conn):
    report = plan.undo_run(conn, "no-such-run", apply=True)
    assert report["changes"] == 0
    assert report["restored"] == 0


def test_an_undo_is_refused_once_a_person_checks_the_row(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    set_cell(conn, BLANK_ROW, "Verified By", "Deshan (pilot, manual check)")
    report = plan.undo_run(conn, "run-1", apply=True)
    assert report["restored"] == 0
    assert all("manual check" in reject["reason"] for reject in report["rejected"])
    _, rows = db.current_rows(conn)
    assert {r["Place ID"]: r for r in rows}[BLANK_ROW]["Who Can Park"] == "Customers only"


def test_an_undo_is_refused_when_a_value_drifted_since_the_run(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    conn.execute("INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
                 " stage, applied_at) VALUES ('run-2', ?, 'Who Can Park', 'Customers only',"
                 " 'Anyone', 'default', '2026-11-11T00:00:00+00:00')", (BLANK_ROW,))
    conn.commit()
    report = plan.undo_run(conn, "run-1", apply=True)
    assert report["restored"] == 0
    assert any("a later change would be lost" in reject["reason"]
               for reject in report["rejected"])


def test_an_undo_of_a_run_that_finished_the_row_is_still_allowed(conn):
    plan.apply_plan(conn, full_row_lines(), "run-1", apply=True)
    conn.execute("INSERT INTO changes (run_id, place_id, column_name, old_value, new_value,"
                 " stage, applied_at) VALUES ('run-1', ?, 'Verification Result', '',"
                 " 'Confirmed', 'default', '2026-11-11T00:00:00+00:00')", (BLANK_ROW,))
    conn.commit()
    db.rebuild(conn)
    report = plan.undo_run(conn, "run-1", apply=True)
    assert report["rejected"] == []
    assert report["restored"] == 9
    _, rows = db.current_rows(conn)
    assert {r["Place ID"]: r for r in rows}[BLANK_ROW]["Verification Result"] == ""


def test_an_unapplied_change_is_not_undone(conn):
    conn.execute("INSERT INTO changes (run_id, place_id, column_name, old_value, new_value)"
                 " VALUES ('run-1', ?, 'Who Can Park', '', 'Customers only')", (BLANK_ROW,))
    conn.commit()
    assert plan.undo_run(conn, "run-1", apply=True)["changes"] == 0


# ---------------------------------------------------------------- commands

def test_db_apply_dry_run_exits_zero_and_writes_reports(conn, tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, full_row_lines())
    out = tmp_path / "apply_out"
    code = plan.apply_main(["--plan", str(path), "--db", str(tmp_path / "test.sqlite"),
                            "--out", str(out)])
    assert code == 0
    with open(out / "dry_run.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 8
    assert list(rows[0]) == plan.PLAN_HEADERS
    with open(out / "rejected.csv", newline="", encoding="utf-8") as stream:
        assert list(csv.DictReader(stream)) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


def test_db_apply_exits_one_and_lists_every_refusal(conn, tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, [line(place_id=NAMED_ROW), line(column="Ferro Autopay", new_value="x")])
    out = tmp_path / "apply_out"
    code = plan.apply_main(["--plan", str(path), "--db", str(tmp_path / "test.sqlite"),
                            "--out", str(out), "--apply"])
    assert code == 1
    with open(out / "rejected.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert list(rows[0]) == plan.REJECT_HEADERS
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


def test_db_apply_with_apply_writes_the_changes(conn, tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, full_row_lines())
    code = plan.apply_main(["--plan", str(path), "--db", str(tmp_path / "test.sqlite"),
                            "--out", str(tmp_path / "out"), "--run-id", "run-7", "--apply"])
    assert code == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM changes WHERE run_id = 'run-7'").fetchone()["n"] == 8


def test_db_undo_command_round_trip(conn, tmp_path):
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, full_row_lines())
    plan.apply_main(["--plan", str(path), "--db", str(tmp_path / "test.sqlite"),
                     "--out", str(tmp_path / "a"), "--run-id", "run-7", "--apply"])
    assert plan.undo_main(["--run", "run-7", "--db", str(tmp_path / "test.sqlite"),
                           "--out", str(tmp_path / "b")]) == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 8
    assert plan.undo_main(["--run", "run-7", "--db", str(tmp_path / "test.sqlite"),
                           "--out", str(tmp_path / "c"), "--apply"]) == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 16


def test_db_undo_of_an_unknown_run_exits_one(conn, tmp_path):
    assert plan.undo_main(["--run", "nope", "--db", str(tmp_path / "test.sqlite"),
                           "--out", str(tmp_path / "b")]) == 1


# ---------------------------------------------------------------- grok import

def grok_results_csv(tmp_path, **overrides):
    """One results row for the nearly empty Pret row, in the bot's own columns."""
    from ferro_parking.grok_import import RESULT_COLUMNS
    row = {column: "" for column in RESULT_COLUMNS}
    row.update({
        "Place ID": BLANK_ROW,
        "Location Name": "Pret A Manger, Liverpool Street",
        "Can Park?": "No",
        "Who Can Park": "Not applicable",
        "Location Status": "Open",
        "Rules Summary": "No parking at this branch. Check on arrival.",
        "Cost Type": "Not applicable",
        "Price Status": "Not applicable",
        "Tariff Type": "Not applicable",
        "Tariff Detail": "Not applicable",
        "Max Stay (mins)": "Not applicable",
        "Hours (OpenStreetMap opening_hours format)": "Not applicable",
        "Hours Basis": "Not applicable",
        "Parking Control Type": "Not applicable",
        "Operator": "Not applicable",
        "PCN amount (£)": "Not applicable",
        "Evidence Type": "Official site: clear answer",
        "Evidence Detail": 'The branch page states "there is no car park at this shop"',
        "Source URLs": "https://www.pret.co.uk/en-GB/find-a-pret/liverpool-street",
        "Source Tier": "Official site - text",
        "Specificity": "Site-specific",
        "Rules Stated": "Yes",
        "Prices Stated": "No",
        "Evidence Age": "Under 12 months",
        "Agreeing Sources": "1",
        "Conflict": "No",
        "Evidence Level": "Verified",
        "Decision Reason": "Route B: official branch page read",
        "Proposed Result": "Confirmed, details not published",
        "Fields Found": "1",
        "Minutes Spent": "2",
        "Researched Date": "2026-11-10",
    })
    row.update(overrides)
    path = tmp_path / "grok_results.csv"
    with open(path, "w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerow(row)
    return path


def test_grok_import_turns_results_into_plan_lines(conn, tmp_path):
    results = grok_results_csv(tmp_path)
    lines, result = plan.grok_results_to_plan(conn, results)
    assert result["report"]["source_rows"] == 1
    assert lines, result["report"]
    assert {entry["place_id"] for entry in lines} == {BLANK_ROW}
    assert {entry["stage"] for entry in lines} == {"grok"}
    assert all(set(entry) == set(plan.LINE_FIELDS) for entry in lines)


def test_grok_import_puts_verification_result_last(conn, tmp_path):
    lines, _ = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    assert lines[-1]["column"] == "Verification Result"


def test_grok_import_carries_the_quote_and_the_source_url(conn, tmp_path):
    lines, _ = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    assert "no car park at this shop" in lines[0]["quote"]
    assert lines[0]["source_url"].startswith("https://www.pret.co.uk/")


def test_grok_import_reuses_the_existing_importers_refusals(conn, tmp_path):
    """An unknown Place ID is rejected by grok_import.build_plan, not here."""
    results = grok_results_csv(tmp_path, **{"Place ID": "PP-999999"})
    lines, result = plan.grok_results_to_plan(conn, results)
    assert lines == []
    assert result["report"]["rejected"] == 1


def test_grok_import_skips_a_tharidu_row(conn, tmp_path):
    results = grok_results_csv(tmp_path, **{"Place ID": NAMED_ROW})
    lines, result = plan.grok_results_to_plan(conn, results)
    assert lines == []
    assert result["report"]["skipped"] == 1


def test_a_grok_import_plan_passes_db_apply(conn, tmp_path):
    lines, _ = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    seed_routing(conn, stage="grok", run_id="route-grok")
    report = plan.apply_plan(conn, lines, "run-grok", apply=False)
    assert report["rejected"] == []
    assert report["places"] == 1


def test_grok_import_drops_the_columns_db_apply_could_never_write(conn, tmp_path):
    """build_plan writes the bot's whole answer, Location Status included. That
    column is protected, so it is dropped and listed rather than left in the
    plan to block it."""
    lines, result = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    dropped = {row["column"]: row["reason"] for row in result["dropped_columns"]}
    assert "Location Status" in dropped
    assert "protected" in dropped["Location Status"]
    assert "Location Status" not in {entry["column"] for entry in lines}


def test_grok_import_drops_a_column_the_bot_left_blank(conn, tmp_path):
    lines, result = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    dropped = {row["column"]: row["reason"] for row in result["dropped_columns"]}
    assert "Notes" in dropped
    assert "no value" in dropped["Notes"]
    assert all(str(entry["new_value"]).strip() for entry in lines)


def test_grok_import_command_writes_the_dropped_columns_file(conn, tmp_path):
    out = tmp_path / "grok_out"
    plan.grok_import_main(["--results-csv", str(grok_results_csv(tmp_path)),
                            "--db", str(tmp_path / "test.sqlite"), "--out", str(out)])
    with open(out / "dropped_columns.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert rows
    assert list(rows[0]) == plan.REJECT_HEADERS


def test_grok_import_command_writes_a_plan_and_its_reports(conn, tmp_path):
    results = grok_results_csv(tmp_path)
    out = tmp_path / "grok_out"
    assert plan.grok_import_main(["--results-csv", str(results),
                                   "--db", str(tmp_path / "test.sqlite"),
                                   "--out", str(out)]) == 0
    assert plan.read_plan(out / "plan.jsonl")
    for name in ("skipped.csv", "rejects.csv"):
        assert (out / name).exists()


# ---------------------------------------------------------------- the four owner columns

def test_the_owner_columns_match_the_sheet_owned_mirror():
    assert plan.OWNER_COLUMNS == set(db.SHEET_OWNED_COLUMNS.values())


def test_no_applied_change_ever_names_an_owner_column(conn):
    for column in plan.OWNER_COLUMNS:
        report = plan.apply_plan(conn, [line(column=column, new_value="1")], "run-1", apply=True)
        assert report["applied"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM changes").fetchone()["n"] == 0


# ---------------------------------------------------------------- the routing gate

def test_a_line_whose_stage_is_not_the_routed_stage_is_refused(conn):
    got = reasons(conn, [line(stage="grok")])
    assert any("put this row on stage 'default', not the plan's 'grok'" in reason
               for reason in got)


def test_a_line_on_a_skipped_row_is_refused(conn):
    seed_routing(conn, stage="skip_done", run_id="route-later")
    got = reasons(conn, full_row_lines())
    assert any("stage 'skip_done'" in reason for reason in got)


def test_only_the_latest_routing_run_counts(conn):
    seed_routing(conn, stage="station", run_id="route-later")
    assert any("stage 'station'" in reason for reason in reasons(conn, [line()]))


def test_a_row_the_latest_routing_run_never_saw_is_refused(tmp_path):
    connection = db.connect(tmp_path / "part.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    connection.execute(
        "INSERT INTO routing (run_id, place_id, stage, reason)"
        " VALUES ('route-1', 'PP-000001', 'default', 'test')")
    connection.commit()
    got = [reject["reason"] for reject in plan.check_plan(connection, [line()])[1]]
    assert any("stage None" in reason for reason in got)


def test_a_plan_is_refused_when_no_routing_run_exists(tmp_path):
    connection = db.connect(tmp_path / "noroute.sqlite")
    db.import_sheet_csv(connection, FIXTURE)
    got = [reject["reason"] for reject in plan.check_plan(connection, [line()])[1]]
    assert got == ["no routing run in the database: run route first"]


# ---------------------------------------------------------------- placeholders

def set_cell(conn, place_id, column, value):
    conn.execute("UPDATE raw SET json = json_set(json, '$.\"' || ? || '\"', ?)"
                 " WHERE place_id = ?", (column, value, place_id))
    conn.commit()


def replacement_reasons(conn, place_id, column, new_value):
    """Every refusal that says the value already there stays. A finished row
    refuses first and with its own wording, so both phrases count."""
    return [reason for reason in
            reasons(conn, [line(place_id=place_id, column=column, new_value=new_value)])
            if "without strong site-specific evidence" in reason
            or "the row is finished, so its" in reason]


def test_an_empty_value_is_a_placeholder(conn):
    set_cell(conn, FILLED_ROW, "Operator", "")
    assert replacement_reasons(conn, FILLED_ROW, "Operator", "NCP") == []


def test_unknown_is_a_placeholder_in_every_column(conn):
    for column, value in (("Operator", "NCP"), ("Hours Basis", "Store hours"),
                           ("Price Status", "Published")):
        set_cell(conn, FILLED_ROW, column, "Unknown")
        assert replacement_reasons(conn, FILLED_ROW, column, value) == [], column


def test_not_yet_checked_is_a_placeholder_in_every_column(conn):
    set_cell(conn, FILLED_ROW, "Evidence Level", "Not yet checked")
    assert replacement_reasons(conn, FILLED_ROW, "Evidence Level", "Chain policy") == []


def test_not_published_is_a_placeholder_while_the_row_is_unfinished(conn):
    set_cell(conn, FILLED_ROW, "Verification Result", "")
    set_cell(conn, FILLED_ROW, "Operator", "Not published")
    assert replacement_reasons(conn, FILLED_ROW, "Operator", "NCP") == []


def test_not_published_is_an_answer_once_the_row_is_finished(conn):
    set_cell(conn, FILLED_ROW, "Verification Result", "Confirmed")
    set_cell(conn, FILLED_ROW, "Operator", "Not published")
    assert replacement_reasons(conn, FILLED_ROW, "Operator", "NCP")


def test_a_real_value_is_never_a_placeholder(conn):
    set_cell(conn, FILLED_ROW, "Operator", "Horizon Parking")
    assert replacement_reasons(conn, FILLED_ROW, "Operator", "NCP")


def test_is_placeholder_reads_the_rows_verification_result():
    unfinished = {"Verification Result": ""}
    finished = {"Verification Result": "Confirmed"}
    assert plan.is_placeholder("", finished) is True
    assert plan.is_placeholder("Unknown", finished) is True
    assert plan.is_placeholder("Not yet checked", finished) is True
    assert plan.is_placeholder("Not published", unfinished) is True
    assert plan.is_placeholder("Not published", finished) is False
    assert plan.is_placeholder("Customers only", unfinished) is False


def test_r7_still_refuses_free_over_a_placeholder(conn):
    """A placeholder makes the replacement rule stand aside. It does not make
    rule R7 stand aside: Free still needs strong site-specific evidence."""
    set_cell(conn, BLANK_ROW, "Cost Type", "Unknown")
    lines = full_row_lines(**{"Cost Type": "Free", "Tariff Type": "Free with time limit",
                              "Max Stay (mins)": "60"})
    got = reasons(conn, lines)
    assert any("Free, public access and a max stay require quoted strong" in reason
               for reason in got), got


def test_r7_still_refuses_anyone_over_a_placeholder(conn):
    set_cell(conn, BLANK_ROW, "Who Can Park", "Unknown")
    got = reasons(conn, full_row_lines(**{"Who Can Park": "Anyone"}))
    assert any("Free, public access and a max stay require quoted strong" in reason
               for reason in got), got


# ---------------------------------------------------------------- one named-person list

def test_db_apply_and_grok_import_share_one_named_person_list():
    from ferro_parking import fill, grok_import
    import inspect
    assert fill.is_named_person("Tharidu")
    assert fill.is_named_person("Tharidu (hand check)")
    assert not fill.is_named_person("Grok (discovery)")
    assert not fill.is_named_person("")
    # grok_import no longer keeps its own reviewer exception.
    source = inspect.getsource(grok_import.build_plan)
    assert "fill.is_named_person" in source
    assert "reviewers" not in source


@pytest.mark.parametrize("verified_by,held", [
    ("Deshan (pilot, manual check)", True), ("Unrecognised bot", True),
    ("Tharidu", True), ("Grok (discovery)", False), ("Policy script", False)])
def test_an_undeclared_verifier_is_held_as_a_person(conn, verified_by, held):
    set_cell(conn, BLANK_ROW, "Verified By", verified_by)
    got = [reason for reason in reasons(conn, [line()]) if "Verified By is" in reason]
    assert bool(got) == held, got


def test_a_finished_row_keeps_its_result_and_its_answers(conn):
    set_cell(conn, BLANK_ROW, "Verification Result", "Confirmed")
    set_cell(conn, BLANK_ROW, "Who Can Park", "Customers only")
    got = reasons(conn, [line(column="Verification Result", new_value="No evidence"),
                          line(column="Who Can Park", new_value="Anyone")])
    assert any("its Verification Result stays" in reason for reason in got), got
    assert any("'Who Can Park' stays" in reason for reason in got), got


def test_a_finished_row_still_takes_a_blank_cell_routing_asked_for(conn):
    set_cell(conn, BLANK_ROW, "Verification Result", "Confirmed")
    got = [reason for reason in reasons(conn, [line(column="Who Can Park")])
           if "the row is finished" in reason]
    assert got == []


def test_a_row_that_needs_an_on_site_check_is_not_finished(conn):
    set_cell(conn, BLANK_ROW, "Verification Result", "Needs on-site check")
    set_cell(conn, BLANK_ROW, "Who Can Park", "Customers only")
    got = [reason for reason in reasons(conn, [line(new_value="Anyone")])
           if "the row is finished" in reason]
    assert got == []


def test_grok_import_accepts_an_agent_verified_row(conn, tmp_path):
    """An agent label is not a person, so the bot's answer is imported."""
    conn.execute("UPDATE raw SET json = json_set(json, '$.\"Verified By\"', 'Grok (discovery)')"
                 " WHERE place_id = ?", (BLANK_ROW,))
    conn.commit()
    lines, result = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    assert result["report"]["skipped"] == 0
    assert lines


# ---------------------------------------------------------------- closed proposals

def test_a_closed_place_the_bot_reports_becomes_a_proposal(conn, tmp_path):
    results = grok_results_csv(tmp_path, **{"Location Status": "Closed"})
    _, result = plan.grok_results_to_plan(conn, results)
    assert [(p["Place ID"], p["proposed value"]) for p in result["proposals"]] == [
        (BLANK_ROW, "Closed")]
    proposal = result["proposals"][0]
    assert "no car park at this shop" in proposal["quote"]
    assert proposal["source url"].startswith("https://www.pret.co.uk/")
    assert proposal["column"] == "Location Status"


def test_a_temporarily_closed_place_also_becomes_a_proposal(conn, tmp_path):
    results = grok_results_csv(tmp_path, **{"Location Status": "Temporarily closed"})
    _, result = plan.grok_results_to_plan(conn, results)
    assert [p["proposed value"] for p in result["proposals"]] == ["Temporarily closed"]


def test_an_open_place_is_not_proposed(conn, tmp_path):
    _, result = plan.grok_results_to_plan(conn, grok_results_csv(tmp_path))
    assert result["proposals"] == []
    assert any(row["column"] == "Location Status" for row in result["dropped_columns"])


def test_a_closed_proposal_is_never_a_plan_line(conn, tmp_path):
    results = grok_results_csv(tmp_path, **{"Location Status": "Closed"})
    lines, _ = plan.grok_results_to_plan(conn, results)
    assert "Location Status" not in {entry["column"] for entry in lines}


def test_grok_import_command_writes_the_proposals_file(conn, tmp_path):
    results = grok_results_csv(tmp_path, **{"Location Status": "Closed"})
    out = tmp_path / "grok_out"
    plan.grok_import_main(["--results-csv", str(results),
                            "--db", str(tmp_path / "test.sqlite"), "--out", str(out)])
    with open(out / "proposals.csv", newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 1
    assert list(rows[0]) == plan.PROPOSAL_HEADERS

@pytest.mark.parametrize('reason', ['', 'Existing reason without a route', 'Old reason \u2013 unchanged'])
def test_category_only_does_not_require_or_change_decision_reason(conn, reason):
    from ferro_parking import category_plan
    conn.execute("UPDATE raw SET json = json_set(json, '$.\"Decision Reason\"', ?) WHERE place_id = ?", (reason, BLANK_ROW))
    conn.commit()
    lines, review, _ = category_plan.build(conn, [{'Place ID': BLANK_ROW, 'proposed_place_category': 'Restaurant / pub / cafe'}])
    assert {entry['column'] for entry in lines} == {'Place Category'}
    assert not review
    report = plan.apply_plan(conn, lines, 'category-only', apply=True)
    assert report['rejected'] == []
    assert report['applied'] == 1
    assert db.current_rows(conn)[1][-1]['Decision Reason'] == reason


def test_category_exception_does_not_allow_a_changed_reason_or_bad_category(conn):
    assert reasons(conn, [line(column='Place Category', new_value='not a category')])
    assert reasons(conn, [line(column='Brand', new_value='Pret'), line(column='Decision Reason', new_value='No route')])
    assert reasons(conn, [line(column='Brand', new_value='Pret'), line(column='Decision Reason', new_value='Route F: bad \u2013 dash')])


def test_category_context_can_restate_a_reason_but_not_change_it(conn):
    conn.execute("UPDATE raw SET json = json_set(json, '$.\"Decision Reason\"', ?) WHERE place_id = ?", ('Old \u2013 reason', BLANK_ROW))
    conn.commit()
    assert reasons(conn, [line(column='Brand', new_value='Pret'), line(column='Decision Reason', new_value='Old \u2013 reason')]) == []


def test_category_exception_never_exempts_a_parking_change(conn):
    failures = reasons(conn, [line(column='Brand', new_value='Pret'), line(column='Can Park? (Yes/No/Conditional)', new_value='No')])
    assert any('Decision Reason' in reason for reason in failures)
