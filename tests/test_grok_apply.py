"""Approval preflight, dropdown preservation and full re-export regressions."""
import copy

import pytest

from ferro_parking import grok_apply as ga
from ferro_parking import grok_import as gi
from ferro_parking import sync
from test_grok_import import source, target, build, snapshot, CFG


def args():
    saved = snapshot()
    saved["tabs"][gi.sheets.TAB][0].remove("_sheet_row")
    result = build()
    return [saved, result["plan"], result["undo"], saved["tabs"][gi.sheets.TAB],
            *saved["tabs"][gi.RESULTS], CFG]


def test_preflight_matches_id_after_row_movement():
    a = args()
    a[3] = (a[3][0], [{**target(), "_sheet_row": 50}])
    plan, undo = ga.preflight(*a)
    assert plan[0]["sheet_row"] == undo[0]["sheet_row"] == 50


@pytest.mark.parametrize("column,value", [("Verification Result", "Confirmed"), ("Verified By", "Tharidu"),
    ("Notes", "Changed"), ("Latitude", "51.5")])
def test_preflight_aborts_changed_target_and_locks(column, value):
    a = args()
    a[3] = (a[3][0], [{**target(), column: value}])
    if column == "Latitude":
        a[0]["tabs"][gi.sheets.TAB][0].append("Latitude")
    with pytest.raises(ValueError):
        ga.preflight(*a)


def test_preflight_aborts_changed_source_or_bad_undo():
    a = args()
    a[5] = [source(**{"Notes": "New research"})]
    with pytest.raises(ValueError, match="research changed"):
        ga.preflight(*a)
    a = args()
    a[2][0]["old"]["Notes"] = "wrong"
    with pytest.raises(ValueError, match="undo"):
        ga.preflight(*a)


def metadata():
    rule = {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": x} for x in ["Verified", "Chain policy", "Presumed"]]},
            "strict": True, "showCustomUi": True, "inputMessage": "Keep this"}
    return {"sheets": [{"properties": {"title": gi.sheets.TAB, "sheetId": 123, "gridProperties": {"rowCount": 4}},
        "data": [{"startRow": 1, "startColumn": 0, "rowData": [{"values": [{"dataValidation": rule}]}]}]}]}


def test_validation_only_extends_approved_column_and_preserves_properties():
    approved = {"column": "Evidence Level", "before": ["Verified", "Chain policy", "Presumed"],
                "after": ["Verified", "Chain policy", "Presumed", "Reported"]}
    original = metadata()
    before = copy.deepcopy(original)
    requests, expected = ga.validation_requests(original, ["Place ID", "Evidence Level"], approved)
    assert len(requests) == 1
    request = requests[0]["setDataValidation"]
    assert request["range"] == {"sheetId": 123, "startRowIndex": 1, "endRowIndex": 4,
                                 "startColumnIndex": 1, "endColumnIndex": 2}
    assert request["rule"]["inputMessage"] == "Keep this"
    assert request["rule"]["strict"] is True
    assert request["rule"]["condition"]["values"][-1] == {"userEnteredValue": "Reported"}
    assert len(expected) == 3
    assert before == original
    original["sheets"][0]["data"][0]["rowData"][0]["values"][0]["dataValidation"]["condition"]["type"] = "CUSTOM_FORMULA"
    with pytest.raises(ValueError, match="Dropdown rule changed"):
        ga.validation_requests(original, ["Evidence Level"], approved)


def test_reexport_compares_planned_and_unplanned_cells_and_formulas():
    headers = ["Place ID", "Notes", "Confidence (1-5)", "Max Stay (mins)"]
    before = [{"Place ID": "PP-1", "Notes": "old", "Confidence (1-5)": "=SUM(A1)", "Max Stay (mins)": ""}]
    plan = [{"place_id": "PP-1", "new": {"Notes": "new", "Max Stay (mins)": "120"}}]
    after = [{**before[0], "Notes": "new", "Max Stay (mins)": 120}]
    assert not sync.compare_updates(headers, before, headers, after, plan)
    after[0]["Confidence (1-5)"] = "=SUM(A2)"
    assert sync.compare_updates(headers, before, headers, after, plan) == ["PP-1: Confidence (1-5) differs"]
    assert sync.compare_updates(headers, before, headers, [], plan)


def test_existing_writer_sends_verification_result_last():
    from ferro_parking import sheets
    calls = []
    class Service:
        def spreadsheets(self): return self
        def values(self): return self
        def batchUpdate(self, **kw): calls.append(kw); return self
        def execute(self): return {}
    sheets.write_cells(Service(), ["Notes", "Verification Result"], [(2, "Verification Result", "Confirmed"), (2, "Notes", "Note")])
    assert calls[0]["body"]["data"][0]["values"] == [["Note"]]
    assert calls[1]["body"]["data"][0]["values"] == [["Confirmed"]]


def test_apply_preflight_rejects_explicit_scope_flags_even_with_old_approved_values():
    a = args()
    a[5] = [source(**{"Notes": "Out of scope: HGV/coach"})]
    with pytest.raises(ValueError, match="marked out of scope"):
        ga.preflight(*a)


def test_approved_extensions_support_old_and_new_envelopes_but_never_remove_values():
    old = {"tab": gi.sheets.TAB, "column": "Evidence Level", "before": ["Presumed"], "after": ["Presumed", "Reported"]}
    third = {"tab": gi.sheets.TAB, "column": "Evidence Type", "before": ["No info found"], "after": ["No info found", "Third-party only"]}
    assert ga.approved_extensions(old) == [old]
    assert ga.approved_extensions({"changes": [third]}) == [third]
    for invalid in ({**third, "after": ["Third-party only"]}, {**third, "column": "Who Can Park"},
                    {**third, "tab": "Grok Queue"}):
        with pytest.raises(ValueError, match="Only explicitly planned"):
            ga.approved_extensions({"changes": [invalid]})


def test_repetitive_validation_metadata_is_requested_without_gzip():
    class Request:
        headers = {}
        def execute(self):
            assert self.headers["accept-encoding"] == "identity"
            return {"complete": True}
    class Service:
        def spreadsheets(self): return self
        def get(self, **kwargs):
            assert kwargs["ranges"] == ["'ALL LONDON (clean)'!B2:B"]
            return Request()
    assert ga.read_validation(Service(), ["Place ID", "Evidence Type"], "Evidence Type") == {"complete": True}


def test_legacy_shorter_dropdown_retains_its_options_and_only_gets_approved_addition():
    m = metadata()
    grid = m["sheets"][0]["data"][0]
    legacy = copy.deepcopy(grid["rowData"][0])
    legacy["values"][0]["dataValidation"]["condition"]["values"].pop(1)
    grid["rowData"].append(legacy)
    approved = {"column": "Evidence Level", "before": ["Verified", "Chain policy", "Presumed"],
                "after": ["Verified", "Chain policy", "Presumed", "Reported"]}
    requests, expected = ga.validation_requests(m, ["Evidence Level"], approved)
    assert [v["userEnteredValue"] for v in expected[2]["condition"]["values"]] == ["Verified", "Presumed", "Reported"]
    assert [v["userEnteredValue"] for v in expected[1]["condition"]["values"]] == approved["after"]
    assert len(requests) == 3
    legacy["values"][0]["dataValidation"]["condition"]["values"].append({"userEnteredValue": "Unexpected"})
    with pytest.raises(ValueError, match="Dropdown rule changed"):
        ga.validation_requests(m, ["Evidence Level"], approved)
