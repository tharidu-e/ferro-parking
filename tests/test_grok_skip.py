"""Offline tests for the read-only Grok skip filter and its approval artifacts."""
import json

import pytest

from ferro_parking import grok_skip as gs


def row(**values):
    return {"Place ID": "PP-1", "Location Name": "Example", "Place Category": "",
            "Priority": "2", "Official URL": "", "OSM Website": "", "Ferro Autopay": "",
            "_sheet_row": 2, **values}


HEADERS = [k for k in row() if k != "_sheet_row"]


@pytest.mark.parametrize("word", gs.WORDS)
def test_whole_word_case_insensitive(word):
    assert gs.skip_reason(row(**{"Location Name": f"Example {word.upper()} parking"}))


@pytest.mark.parametrize("name", ["Stafford", "Privateer", "Coaching", "Lorrying",
                                  "Backyard", "Workshops", "goods inside", "HGVs"])
def test_substrings_do_not_match(name):
    assert not gs.skip_reason(row(**{"Location Name": name}))


def test_private_category_and_whitespace_urls():
    assert gs.skip_reason(row(**{"Place Category": gs.PRIVATE_CATEGORY, "Official URL": "  "}))
    assert not gs.skip_reason(row(**{"Place Category": "Council car park"}))


@pytest.mark.parametrize("url_column", ["Official URL", "OSM Website"])
def test_either_website_prevents_ordinary_skip(url_column):
    assert not gs.skip_reason(row(**{"Location Name": "Private yard", url_column: "https://example.test"}))


def test_autopay_prevents_ordinary_skip():
    assert not gs.skip_reason(row(**{"Location Name": "Private yard", "Ferro Autopay": " ✅ "}))


@pytest.mark.parametrize("name", ["HGV park", "LORRY park", "Coach park"])
def test_scope_overrides_urls_and_autopay(name):
    assert gs.skip_reason(row(**{"Location Name": name, "Official URL": "https://example.test",
                                 "Ferro Autopay": "✅"})) == "Out of scope: HGV/coach"


def test_results_excluded_even_scope_override_and_input_order_preserved():
    rows = [row(**{"Place ID": "PP-2", "Location Name": "Private"}),
            row(**{"Location Name": "Coach park", "_sheet_row": 3}),
            row(**{"Place ID": "PP-3", "Location Name": "Staff", "_sheet_row": 4})]
    original = json.dumps(rows)
    plan, undo, skips, reading = gs.build_plan(HEADERS, rows, ["Place ID"], [{"Place ID": "PP-1"}])
    assert [e["place_id"] for e in plan] == ["PP-2", "PP-3"]
    assert all(e["new"] == {"Skip": "Yes"} for e in plan)
    assert all(e["old"] == {"Skip": ""} for e in undo)
    assert [r["Place ID"] for r in skips] == ["PP-2", "PP-3"]
    assert reading["mismatches"] == 0
    assert original == json.dumps(rows)


@pytest.mark.parametrize("headers,rows,result_headers,results", [
    (HEADERS + ["Skip"], [row()], ["Place ID"], []),
    (HEADERS + ["Priority"], [row()], ["Place ID"], []),
    (HEADERS + [""], [row()], ["Place ID"], []),
    ([h for h in HEADERS if h != "Official URL"], [row()], ["Place ID"], []),
    (HEADERS, [row(), row()], ["Place ID"], []),
    (HEADERS, [row(**{"Place ID": ""})], ["Place ID"], []),
    (HEADERS, [row(**{"Place ID": " PP-1"})], ["Place ID"], []),
    (HEADERS, [row()], [], []),
    (HEADERS, [row()], ["Place ID"], [{"Place ID": "", "Location Name": "Coach park"}]),
])
def test_ambiguous_input_aborts(headers, rows, result_headers, results):
    with pytest.raises(ValueError):
        gs.build_plan(headers, rows, result_headers, results)


def test_independent_reading_detects_wrong_selection():
    with pytest.raises(ValueError, match="Independent"):
        gs.second_reading([row(**{"Location Name": "Private"})], [], [])


def test_artifacts_are_exclusive_and_have_only_skip_changes(tmp_path):
    out = tmp_path / "run"
    report = gs.prepare((HEADERS, [row(**{"Location Name": "Private"})]), (["Place ID"], []), out)
    assert report["skip_count"] == 1
    assert report["per_priority"] == {"2": 1}
    assert sorted(p.name for p in out.iterdir()) == ["dry_run.csv", "plan.json", "report.json",
                                                   "skip_list.csv", "snapshot.json", "undo.json"]
    plan = json.loads((out / "plan.json").read_text())
    assert plan["tab"] == "Grok Queue"
    assert plan["add_column"] == {"header": "Skip", "after_header": HEADERS[-1], "initial_value": ""}
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        gs.prepare((HEADERS, [row()]), (["Place ID"], []), out)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}


def test_empty_plan_and_duplicate_result_ids_are_safe(tmp_path):
    report = gs.prepare((HEADERS, [row()]), (["Place ID"], [{"Place ID": "X"}] * 2), tmp_path / "run")
    assert report["skip_count"] == 0


def test_snapshot_cli_never_connects_to_google(tmp_path, monkeypatch, capsys):
    snapshot = tmp_path / "input.json"
    snapshot.write_text(json.dumps({gs.QUEUE: [HEADERS, [row()]], gs.RESULTS: [["Place ID"], []]}))
    def forbidden():
        raise AssertionError("Unexpected network access")
    monkeypatch.setattr(gs.sheets, "get_service", forbidden)
    assert gs.main(["--snapshot", str(snapshot), "--out", str(tmp_path / "run")]) == 0
    assert "No sheet changes" in capsys.readouterr().out
