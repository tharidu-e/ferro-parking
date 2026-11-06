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
    snapshot.write_text(json.dumps({gs.QUEUE: [HEADERS, [row()]], gs.RESULTS: [["Place ID"], []],
                                    gs.sheets.TAB: [["Place ID", "OSM ID"], []]}))
    tags = tmp_path / "tags.json"
    tags.write_text("{}")
    def forbidden():
        raise AssertionError("Unexpected network access")
    monkeypatch.setattr(gs.sheets, "get_service", forbidden)
    assert gs.main(["--snapshot", str(snapshot), "--out", str(tmp_path / "run"),
                    "--osm-object-tags", str(tags), "--osm-packets"]) == 0
    assert "No sheet changes" in capsys.readouterr().out


@pytest.mark.parametrize("phrase", gs.PUBLIC_NAMES + ("multi-storey", "q park", "CAR PARK"))
def test_public_name_kept_in_category_rule(phrase):
    candidate = row(**{"Location Name": f"Example {phrase}", "Place Category": gs.PRIVATE_CATEGORY})
    assert gs.skip_reason(candidate, tightened=False)
    assert not gs.skip_reason(candidate)
    assert gs.second_reading([candidate], [], [])["mismatches"] == 0


@pytest.mark.parametrize("tags", [{"fee": "yes"}, {"operator": "Example Ltd"},
                                   {"access": "yes"}, {"access": "public"},
                                   {"access": "permissive"}, {"access": " YES "}])
def test_public_osm_sign_kept(tags):
    candidate = row(**{"Place Category": gs.PRIVATE_CATEGORY, "_osm_tags": [tags]})
    assert not gs.skip_reason(candidate)
    assert gs.second_reading([candidate], [], [])["mismatches"] == 0


@pytest.mark.parametrize("tags", [{}, {"fee": "no"}, {"operator": " "}, {"access": "private"}])
def test_no_public_sign_still_category_skip(tags):
    assert gs.skip_reason(row(**{"Place Category": gs.PRIVATE_CATEGORY, "_osm_tags": [tags]}))


@pytest.mark.parametrize("keyword", ["staff", "private", "residents", "goods in", "HGV"])
def test_restrictive_keyword_unchanged_despite_public_signs(keyword):
    candidate = row(**{"Location Name": f"Business {keyword} Car Park", "Place Category": gs.PRIVATE_CATEGORY,
                       "_osm_tags": [{"fee": "yes", "operator": "NCP", "access": "public"}]})
    assert gs.skip_reason(candidate)
    plan = [{"place_id": "PP-1"}]
    assert gs.second_reading([candidate], [], plan)["mismatches"] == 0


def test_backtest_ignores_completed_exclusion_and_reports_every_found_row():
    candidate = row(**{"Place Category": gs.PRIVATE_CATEGORY, "Location Name": "Town Car Park"})
    results = [{"Place ID": "PP-1", "Source Tier": "Operator / council site", "Fields Found": "Tariff",
                "Evidence Level": "Verified"}, {"Place ID": "missing"}]
    original = gs.backtest([candidate], results, tightened=False)
    assert original["would_skip"] == original["with_fields"] == original["verified"] == 1
    assert original["found_rows"][0]["Source Tier"] == "Operator / council site"
    assert original["unavailable_ids"] == ["missing"]
    assert gs.backtest([candidate], results)["would_skip"] == 0


@pytest.mark.parametrize("value", ["None", " None ", "", "none"])
def test_backtest_no_field_values(value):
    results = [{"Place ID": "PP-1", "Fields Found": value, "Evidence Level": "Presumed"}]
    report = gs.backtest([row(**{"Location Name": "staff"})], results)
    assert report["would_skip"] == 1
    assert report["with_fields"] == report["verified"] == 0


def test_osm_join_uses_place_id_and_exact_object_id_not_name():
    candidates = [row(), row(**{"Place ID": "PP-2"})]
    main = [{"Place ID": "PP-1", "OSM ID": "way/123"}]
    tags = {"way/123": {"operator": "NCP"}, "way/456": {"access": "yes"}}
    packets = [{"Place ID": "PP-2", "OSM Raw Tags": "fee=yes; access=private"}]
    enriched = gs.attach_osm(candidates, main, tags, packets)
    assert enriched[0]["_osm_tags"] == [{"operator": "NCP"}]
    assert enriched[1]["_osm_tags"] == [{"fee": "yes", "access": "private"}]
    assert "_osm_tags" not in candidates[0]


def test_independent_reading_catches_missing_public_exemption():
    candidate = row(**{"Place Category": gs.PRIVATE_CATEGORY, "Location Name": "Town Car Park"})
    with pytest.raises(ValueError, match="Independent"):
        gs.second_reading([candidate], [], [{"place_id": "PP-1"}])


def test_backtest_main_sheet_fallback_does_not_invent_missing_urls():
    results = [{"Place ID": "store"}, {"Place ID": "park"}]
    fallback = [{"Place ID": "store", "Location Name": "Tesco", "Place Category": "Supermarket - large format"},
                {"Place ID": "park", "Location Name": "Example", "Place Category": gs.PRIVATE_CATEGORY}]
    report = gs.backtest([], results, fallback_rows=fallback)
    assert report["main_sheet_noncandidates"] == ["store"]
    assert report["unavailable_ids"] == ["park"]
    assert report["evaluated"] == 1


def test_review_cli_saves_backtests_and_separates_original_reason_groups(tmp_path, capsys):
    from ferro_parking import grok_skip_review as gr
    rows = [row(**{"Location Name": "Town Car Park", "Place Category": gs.PRIVATE_CATEGORY}),
            row(**{"Place ID": "PP-2", "Location Name": "Coach", "_sheet_row": 3}),
            row(**{"Place ID": "PP-3", "Location Name": "Example", "Place Category": gs.PRIVATE_CATEGORY,
                   "_sheet_row": 4})]
    results = [{"Place ID": "PP-3", "Location Name": "Example", "Fields Found": "Operator",
                "Source Tier": "Official site - text", "Evidence Level": "Verified"}]
    tabs = {gs.QUEUE: [HEADERS, rows], gs.RESULTS: [["Place ID"], results],
            gs.sheets.TAB: [["Place ID", "OSM ID"], []]}
    original = tmp_path / "original"
    original.mkdir()
    (original / "snapshot.json").write_text(json.dumps(tabs))
    (original / "plan.json").write_text(json.dumps({"rows": [{"place_id": "PP-1"}, {"place_id": "PP-2"}]}))
    snapshot = tmp_path / "live.json"
    snapshot.write_text(json.dumps(tabs))
    tags = tmp_path / "tags.json"
    tags.write_text("{}")
    out = tmp_path / "review"
    assert gr.main(["--snapshot", str(snapshot), "--original-run", str(original),
                    "--osm-object-tags", str(tags), "--osm-packets", "--out", str(out)]) == 0
    saved = json.loads((out / "review.json").read_text())
    assert saved["original_186_breakdown"]["restrictive_keyword"]["count"] == 1
    assert saved["original_186_breakdown"]["category_only"]["count"] == 1
    assert saved["original_backtest"]["with_fields"] == 1
    assert saved["tightened_backtest"]["with_fields"] == 1
    assert len(saved["retained_by_public_signs"]) == 1
    assert (out / "original_backtest.csv").exists()
    assert (out / "tightened_backtest.csv").exists()
    assert json.loads((out / "report.json").read_text())["skip_count"] == 1


def test_review_refuses_original_ids_missing_from_snapshot():
    from ferro_parking import grok_skip_review as gr
    tabs = {gs.QUEUE: [HEADERS, []], gs.RESULTS: [["Place ID"], []], gs.sheets.TAB: [[], []]}
    with pytest.raises(ValueError, match="Original plan IDs"):
        gr.review(tabs, tabs, {}, [], {"rows": [{"place_id": "missing"}]})
