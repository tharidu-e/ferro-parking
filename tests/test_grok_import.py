"""Offline importer mapping, safety and artifact regression tests."""
import copy
import json
from datetime import date

import pytest

from ferro_parking import grok_import as gi

CFG = gi.load_config()
TODAY = date(2026, 11, 6)


def source(**updates):
    values = {k: "Not published" for k in gi.RESULT_COLUMNS}
    values.update({"Place ID": "PP-1", "Location Name": "Example Sports Centre", "Can Park?": "Unknown",
                   "Who Can Park": "Unknown", "Location Status": "Unknown", "Rules Summary": "No information found.",
                   "Cost Type": "Unknown", "Evidence Type": "No info found", "Evidence Detail": "No sources found.",
                   "Source URLs": "", "Source Tier": "None found", "Specificity": "Area only", "Rules Stated": "No",
                   "Prices Stated": "No", "Evidence Age": "Older or undated", "Agreeing Sources": "0", "Conflict": "No",
                   "Evidence Level": "Presumed", "Notes": "", "Review Flag": "", "Decision Reason": "No evidence found.",
                   "Proposed Result": "No evidence", "Fields Found": "None", "Minutes Spent": "5", "Researched Date": "2026-11-06"})
    values.update(updates)
    return values


def target(**updates):
    values = {gi.ALIASES.get(k, k): "" for k in gi.RESULT_COLUMNS if k not in gi.IGNORED}
    values.update({"Place ID": "PP-1", "Location Name": "Example Sports Centre", "Verified By": "",
                   "Flag Status": "", "Postcode": "N1 1AA", "_sheet_row": 10})
    values.update(updates)
    return values


def strong(**updates):
    return source(**{"Can Park?": "Conditional", "Who Can Park": "Customers only", "Source Tier": "Official site - text",
                     "Specificity": "Site-specific", "Evidence Type": "Official site: partial info",
                     "Evidence Detail": "Example Sports Centre has customer parking.", "Source URLs": "https://example.test/site",
                     "Evidence Level": "Verified", "Fields Found": "Can Park?; Who Can Park",
                     "Proposed Result": "Confirmed, details not published", **updates})


def mapped(s):
    return gi.map_values(s, target(), CFG)


def build(results=None, rows=None):
    return gi.build_plan(list(target()), rows or [target()], gi.RESULT_COLUMNS,
                         results or [source()], CFG, TODAY)


def snapshot(results=None):
    headers = list(target())
    cells = [{"dataValidation": {"condition": {"type": "ONE_OF_LIST", "values": [
        {"userEnteredValue": v} for v in CFG["dropdowns"][h] if v not in {"Reported", "Third-party only"}]}}}
        if h in CFG["dropdowns"] else {} for h in headers]
    return {"tabs": {gi.RESULTS: [gi.RESULT_COLUMNS, results or [source()]], gi.sheets.TAB: [headers, [target()]]},
            "validations": {"sheets": [{"properties": {"title": gi.sheets.TAB},
                                        "data": [{"startRow": 1, "rowData": [{"values": cells}]}]}]}}


@pytest.mark.parametrize("column,old,new", [(c, k, v) for c, values in CFG["direct"].items() for k, v in values.items()])
def test_every_configured_direct_mapping(column, old, new):
    result, changes, _ = mapped(source(**{column: old}))
    assert result[gi.ALIASES.get(column, column)] == new
    assert any(c["Before"] == old and c["After"] == new for c in changes)


def test_other_only_maps_when_no_fields_found():
    assert mapped(source(**{"Source Tier": "Other"}))[0]["Source Tier"] == "None found"
    result, _, errors = mapped(source(**{"Source Tier": "Other", "Fields Found": "Operator"}))
    assert result["Source Tier"] == "Other"
    assert errors


@pytest.mark.parametrize("control", CFG["conditional"]["payment_controls"])
def test_payment_methods_move_to_notes(control):
    result, _, errors = mapped(source(**{"Parking Control Type": control, "Notes": "Original"}))
    assert result["Parking Control Type (Cameras / Barrier / Patrol)"] == "Not published"
    assert result["Notes"] == f"Original | Payment: {control.lower()}"
    assert not errors


@pytest.mark.parametrize("detail,expected,allowed", [("£5.00 per day", "£5.00 per 24 hours", True),
    ("£5.00 per 24 hours", "£5.00 per 24 hours", True), ("£40.00 flat rate", "£40.00 flat rate", False),
    ("£5.00 per night", "£5.00 per night", False)])
def test_flat_rate_mapping_is_conditional(detail, expected, allowed):
    result, _, errors = mapped(strong(**{"Tariff Type": "Flat rate", "Tariff Detail": detail}))
    assert result["Tariff Detail"] == expected
    assert (result["Tariff Type"] == "Flat rate per 24 hours") == allowed
    assert bool(errors) != allowed


def test_free_hourly_and_free_band_mappings():
    result, _, errors = mapped(strong(**{"Tariff Type": "Free period then paid",
        "Tariff Detail": "Free for up to 30 mins, then £1.00 per hour"}))
    assert result["Tariff Type"] == "Free period, then hourly"
    assert result["Tariff Detail"] == "Free for 30 mins, then £1.00 per hour"
    assert not errors
    result, _, errors = mapped(strong(**{"Tariff Type": "Banded",
        "Tariff Detail": "Free for up to 10 mins, then 0-1 hrs £1.00; 1-2 hrs £2.00"}))
    assert result["Tariff Detail"] == "0-1 hrs £1.00; 1-2 hrs £2.00"
    assert "Free for first 10 mins" in result["Notes"]
    assert not errors
    assert mapped(strong(**{"Tariff Type": "Free period then paid", "Tariff Detail": "Free then unknown"}))[2]


@pytest.mark.parametrize("detail", ["Free", "Free for up to 2 hrs", "Free for up to 30 mins",
    "Free for 30 mins, then £1.00 per hour", "£1.30 per hour", "£18.00 per 24 hours", "£15.00 per night",
    "0-2 hrs £5.00; 2-3 hrs £6.50", "0-30 mins £1.00; 30-60 mins £2.00; 1-2 hrs £3.00",
    "0-0.5 hrs £1.00; 0.5-1 hrs £2.00", "Not published", "Not applicable"])
def test_allowed_tariff_templates(detail):
    assert gi.valid_tariff(detail)


@pytest.mark.parametrize("detail", ["£1 per hour", "£1.234 per hour", "£6 per 24 hrs", "£40 flat rate",
    "Free (donors only)", "2+ hrs £5.00", "0-2 hrs £5.00; 3-4 hrs £6.00", "2-1 hrs £2.00", "",
    "Free for up to 4 hrs, then paid (price not published)"])
def test_unknown_tariffs_rejected_without_guessing(detail):
    assert not gi.valid_tariff(detail)


def test_unclear_specificity_needs_official_source_for_this_site():
    assert mapped(strong(**{"Specificity": "Unclear"}))[0]["Specificity"] == "Site-specific"
    assert mapped(strong(**{"Specificity": "Unclear", "Evidence Detail": "General chain policy"}))[0]["Specificity"] == "Area only"
    assert mapped(source(**{"Specificity": "Unclear"}))[0]["Specificity"] == "Area only"


def test_conflicting_and_forum_evidence():
    new, _, _ = mapped(strong(**{"Evidence Type": "Conflicting sources"}))
    assert new["Evidence Type"] == "Official site: partial info"
    assert new["Conflict"] == "Yes"
    new, _, _ = mapped(source(**{"Evidence Type": "Local forum / community"}))
    assert new["Evidence Type"] == "No info found"
    assert new["Review Flag"] == "Forum evidence only"
    assert new["Flag Status"] == "Open"
    new, _, _ = mapped(strong(**{"Evidence Type": "Local forum / community"}))
    assert new["Evidence Type"] == "Official site: partial info"
    assert not new["Review Flag"]


@pytest.mark.parametrize("updates,fragment", [
    ({"Can Park?": "Yes", "Who Can Park": "Customers only"}, "Yes requires public"),
    ({"Can Park?": "Yes", "Who Can Park": "Anyone", "Proposed Result": "Needs on-site check"}, "Yes requires public"),
    ({"Source Tier": "Parkopedia"}, "Verified requires strong"),
    ({"Specificity": "Chain-wide"}, "Verified requires site-specific"),
    ({"Fields Found": "None"}, "None requires Presumed"),
    ({"Source Tier": "Parkopedia", "Cost Type": "Free"}, "strong site-specific"),
    ({"Source Tier": "Parkopedia", "Who Can Park": "Anyone (paid)"}, "strong site-specific"),
    ({"Source Tier": "Parkopedia", "Tariff Detail": "£1.00 per hour"}, "strong site-specific"),
    ({"Specificity": "Chain-wide", "Max Stay (mins)": "120"}, "max stay requires"),
    ({"Hours Basis": "Invented hours"}, "dropdown: Hours Basis"),
    ({"Tariff Detail": "Text" + chr(8212) + "text"}, "typography"),
    ({"Hours Basis": "Text" + chr(8211) + "text"}, "typography"),
    ({"Researched Date": "2026-11-07"}, "date:"),
    ({"Researched Date": "06/11/2026"}, "date:"),
    ({"Agreeing Sources": "4"}, "Agreeing Sources"),
    ({"Max Stay (mins)": "1.5"}, "whole minutes"),
    ({"PCN amount (£)": "£100"}, "PCN amount"),
    ({"Location Status": "Closed"}, "Closed requires"),
    ({"Can Park?": "No", "Evidence Detail": "No parking information listed."}, "explicit site-specific"),
    ({"Evidence Detail": ""}, "lacks detail or URL"),
    ({"Source URLs": "javascript:alert(1)"}, "lacks detail or URL"),
    ({"Proposed Result": "Confirmed"}, "complete strong"),
    ({"Tariff Type": "Hourly rate", "Tariff Detail": "£5.00 per 24 hours"}, "Tariff Type disagrees"),
])
def test_safety_rules_reject(updates, fragment):
    s = strong(**updates)
    new, _, _ = mapped(s)
    assert any(fragment in error for error in gi.validate(s, new, CFG, TODAY))


def test_reported_accepted_without_upgrading_source_strength():
    s = strong(**{"Evidence Level": "Reported", "Source Tier": "Google search / third-party"})
    new, _, _ = mapped(s)
    assert gi.validate(s, new, CFG, TODAY) == []


def test_strong_public_price_passes():
    s = strong(**{"Can Park?": "Yes", "Who Can Park": "Anyone (paid)", "Cost Type": "Paid",
                  "Tariff Type": "Hourly rate", "Tariff Detail": "£1.00 per hour", "Price Status": "Published"})
    assert gi.validate(s, mapped(s)[0], CFG, TODAY) == []


def test_blank_optional_numbers_do_not_reject_the_row():
    # The 12 November pilot left PCN amount and Max Stay blank on 13 rows of
    # 25. A blank cell is not a value: plan.py drops it before the write, so
    # checking it as a number refused the row's good fields.
    s = strong(**{"Can Park?": "Yes", "Who Can Park": "Anyone (paid)", "Cost Type": "Paid",
                  "Tariff Type": "Hourly rate", "Tariff Detail": "£1.00 per hour",
                  "Price Status": "Published", "PCN amount (£)": "", "Max Stay (mins)": ""})
    new, _, _ = mapped(s)
    assert new["PCN (Penalty Charge Notice) amount (£)"].strip() == ""
    assert gi.validate(s, new, CFG, TODAY) == []


def test_bad_optional_numbers_still_reject_the_row():
    s = strong(**{"PCN amount (£)": "£100 reduced to 60", "Max Stay (mins)": "two hours"})
    errors = gi.validate(s, mapped(s)[0], CFG, TODAY)
    assert "numeric: invalid PCN amount" in errors
    assert "numeric: Max Stay must be whole minutes or an allowed marker" in errors


def test_no_parking_passes_only_with_explicit_denial_and_not_applicable_fields():
    s = strong(**{"Can Park?": "No", "Evidence Detail": 'Example Sports Centre says "no car park".'})
    for column in gi.page_fill.NOT_APPLICABLE_IF_NO_PARKING:
        original = next((k for k, v in gi.ALIASES.items() if v == column), column)
        s[original] = "Not applicable"
    assert gi.validate(s, mapped(s)[0], CFG, TODAY) == []


def test_finished_and_person_rows_skipped_and_rerun_is_idempotent():
    # One named-person list, shared with db-apply (fill.is_named_person).
    # A label the automation list in grok_value_map.toml does not declare is
    # held as a person, so the pilot label and an unrecognised bot are both
    # skipped. The live data carried "Deshan (pilot, manual check)" on four
    # rows that the earlier prefix test let through.
    for updates in ({"Verification Result": "Confirmed"}, {"Verified By": "Tharidu"},
                    {"Verified By": "Tharidu (hand check)"},
                    {"Verified By": "Deshan (pilot, manual check)"},
                    {"Verified By": "Unrecognised bot"}):
        result = build(rows=[target(**updates)])
        assert len(result["skipped"]) == 1
        assert result["plan"] == []
    for updates in ({"Verified By": "Grok (discovery)"}, {"Verified By": "PP"}):
        result = build(rows=[target(**updates)])
        assert result["skipped"] == []
    first = build()
    applied = target(**first["plan"][0]["new"])
    assert not build(rows=[applied])["plan"]


@pytest.mark.parametrize("s,rows", [([source(), source()], [target()]),
    ([source()], [target(), target()]), ([source(**{"Place ID": "unknown"})], [target()]),
    ([source(**{"Place ID": ""})], [target()]), ([source(**{"Place ID": " PP-1"})], [target()])])
def test_bad_identity_never_reaches_plan(s, rows):
    result = build(s, rows)
    assert result["rejects"]
    assert not result["plan"]


def test_preserves_notes_flags_and_urls_and_never_imports_ignored_or_protected_columns():
    s = source(**{"Notes": "New note", "Review Flag": "New flag", "Source URLs": "https://new.test"})
    t = target(**{"Notes": "Old note", "Review Flag": "Old flag", "Source URLs (primary first)": "https://old.test"})
    before = copy.deepcopy(s)
    new, _, _ = gi.map_values(s, t, CFG)
    assert new["Notes"] == "Old note | New note"
    assert new["Review Flag"] == "Old flag | New flag"
    assert new["Source URLs (primary first)"] == "https://new.test ; https://old.test"
    assert not (set(new) & gi.IGNORED)
    gi.fill.assert_not_protected({k: v for k, v in new.items() if k != "Location Status"})
    assert before == s


def test_plan_uses_place_id_not_source_row_number_and_existing_second_reading(monkeypatch):
    s = source(**{"_sheet_row": 999})
    result = build([s])
    assert result["plan"][0]["sheet_row"] == 10
    assert result["second_reading"] == {"checked": 1, "failures": []}
    def fail(plan, kind):
        return {}, [{"Place ID": "PP-1", "Location Name": "Example", "Violations": "independent failure"}]
    monkeypatch.setattr(gi, "second_reading", fail)
    result = build([s])
    assert not result["plan"]
    assert "second reading" in result["rejects"][0]["Reasons"][0]


def test_dropdown_extension_only_adds_reported_and_requires_live_validation():
    s = snapshot()
    plan = gi.dropdown_plan(s, CFG)
    assert plan["before"] == ["Verified", "Chain policy", "Presumed"]
    assert plan["after"] == ["Verified", "Chain policy", "Presumed", "Reported"]
    assert not plan["apply"]
    assert plan["required"]
    del s["validations"]
    with pytest.raises(ValueError, match="lacks live"):
        gi.dropdown_plan(s, CFG)


def test_artifacts_are_immutable_and_cli_cannot_write_or_connect_with_snapshot(tmp_path, monkeypatch):
    s = snapshot()
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(s))
    def forbidden():
        raise AssertionError("Unexpected network")
    monkeypatch.setattr(gi.sheets, "get_service", forbidden)
    out = tmp_path / "run"
    assert gi.main(["--snapshot", str(path), "--out", str(out)]) == 0
    assert json.loads((out / "report.json").read_text())["accepted"] == 1
    assert json.loads((out / "report.json").read_text())["rerun_simulation"]["accepted"] == 0
    assert json.loads((out / "undo.json").read_text())[0]["old"]["Verification Result"] == ""
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(FileExistsError):
        gi.prepare(s, out)
    assert before == {p.name: p.read_bytes() for p in out.iterdir()}
    with pytest.raises(SystemExit):
        gi.main(["--apply"])


def test_rejects_are_audited_but_never_reach_plan(tmp_path):
    s = snapshot([source(**{"Hours Basis": "Invented hours", "Source Tier": "Other"})])
    result = gi.prepare(s, tmp_path / "run")
    assert result["plan"] == []
    assert len(result["rejects"]) == 1
    assert result["mapping_audit"]
    assert all(c["Disposition"] == "rejected" for c in result["mapping_audit"])


def test_every_mapping_event_is_counted_including_payment_note_side_effects():
    result = build([source(**{"Parking Control Type": "Mixed"})])
    counts = result["report"]["mapping_counts"]
    assert counts["Parking Control Type: Mixed"] == 1
    assert counts["Notes: payment Mixed"] == 1
    assert sum(counts.values()) == len(result["mapping_audit"])
    assert counts["Conflict: conflicting evidence"] == 0


def test_free_only_and_free_band_consistency_rules():
    s = strong(**{"Cost Type": "Free", "Tariff Type": "Free period, then hourly",
                  "Tariff Detail": "Free for 30 mins, then £1.00 per hour"})
    assert any("free-only" in e for e in gi.validate(s, mapped(s)[0], CFG, TODAY))
    s = strong(**{"Cost Type": "Free then paid", "Tariff Type": "Banded by stay length",
                  "Tariff Detail": "0-1 hrs £1.00; 1-2 hrs £2.00"})
    assert any("explicit free period" in e for e in gi.validate(s, mapped(s)[0], CFG, TODAY))
    s["Notes"] = "Free for first 10 mins"
    assert gi.validate(s, mapped(s)[0], CFG, TODAY) == []


def test_no_fields_found_cannot_preserve_unproven_free_or_public_claim():
    s = strong(**{"Fields Found": "None", "Evidence Level": "Presumed", "Who Can Park": "Anyone"})
    assert any("None cannot establish" in e for e in gi.validate(s, mapped(s)[0], CFG, TODAY))


def test_generic_car_park_name_cannot_establish_site_specificity():
    s = strong(**{"Location Name": "Car Park", "Specificity": "Unclear", "Evidence Detail": "A car park exists somewhere."})
    assert mapped(s)[0]["Specificity"] == "Area only"


def test_existing_evidence_level_column_builder_accepts_reported():
    from ferro_parking.evidence_level import VALUES
    assert "Reported" in VALUES
    assert VALUES == CFG["dropdowns"]["Evidence Level"]


def test_all_live_dropdowns_must_match_exact_supported_values():
    s = snapshot()
    index = s["tabs"][gi.sheets.TAB][0].index("Who Can Park")
    s["validations"]["sheets"][0]["data"][0]["rowData"][0]["values"][index]["dataValidation"]["condition"]["values"] = []
    with pytest.raises(ValueError, match="Config differs"):
        gi.dropdown_plan(s, CFG)


def test_second_reading_and_all_six_original_consistency_rules_are_enforced():
    cases = [
        {"Can Park?": "No", "Who Can Park": "Customers only"},
        {"Cost Type": "Free", "Tariff Type": "Hourly rate"},
        {"Cost Type": "Mixed (free then paid)", "Tariff Type": "Hourly rate"},
        {"Price Status": "Published", "Tariff Detail": "Not published"},
        {"Tariff Type": "Free with time limit", "Max Stay (mins)": "Not published"},
        {"Source Tier": "None found", "Can Park?": "Conditional"},
    ]
    for updates in cases:
        result = build([strong(**updates)])
        assert result["rejects"]
        assert not result["plan"]


@pytest.mark.parametrize("column", CFG["normalization"]["free_text_columns"])
@pytest.mark.parametrize("dash", [chr(8211), chr(8212)])
def test_normalizes_only_authorized_free_text_columns(column, dash):
    s = source(**{column: f"Before{dash}after"})
    new, audit, _ = mapped(s)
    assert dash not in new[gi.ALIASES.get(column, column)]
    assert "Before-after" in new[gi.ALIASES.get(column, column)]
    assert any(r["Rule"] == f"Typography: {column}" for r in audit)


def test_normalizes_merged_existing_notes_and_flags_without_changing_dropdown():
    s = source(**{"Hours Basis": "Car" + chr(8211) + "park hours"})
    t = target(**{"Notes": "Old" + chr(8212) + "note", "Review Flag": "Old" + chr(8211) + "flag"})
    new, audit, _ = gi.map_values(s, t, CFG)
    assert new["Notes"] == "Old-note"
    assert new["Review Flag"] == "Old-flag"
    assert new["Hours Basis"] == s["Hours Basis"]
    assert any("dropdown: Hours Basis" in e for e in gi.validate(s, new, CFG, TODAY))


def test_signed_hours_maps_exactly_and_is_audited():
    s = strong(**{"Hours Basis": "Signed hours"})
    new, audit, _ = mapped(s)
    assert new["Hours Basis"] == "Car park hours"
    assert any(c["Rule"] == "Hours Basis: Signed hours" for c in audit)


@pytest.mark.parametrize("column", ["Notes", "Review Flag"])
@pytest.mark.parametrize("text", ["HGV/coach only, out of scope for car drivers", "Out of scope: HGV/coach",
    "OUT-OF-SCOPE: coaches", "HGVs - out of scope"])
def test_explicit_scope_flags_never_import(column, text):
    result = build([strong(**{column: text})])
    assert result["plan"] == []
    assert len(result["out_of_scope"]) == 1
    assert result["report"]["out_of_scope"] == 1
    assert result["report"]["rejected"] == 1


def test_target_scope_flag_blocks_import_but_hgv_prohibition_alone_does_not():
    assert not build([strong()], [target(**{"Notes": "Out of scope: HGV/coach"})])["plan"]
    assert build([strong(**{"Notes": "No HGVs allowed; car parking is available"})])["plan"]


@pytest.mark.parametrize("tier", CFG["conditional"]["third_party_sources"])
@pytest.mark.parametrize("evidence", ["No info found", "Official site: partial info"])
def test_use_third_party_only_for_weak_sources_with_findings(tier, evidence):
    s = strong(**{"Source Tier": tier, "Evidence Type": evidence, "Evidence Level": "Reported"})
    new, _, _ = mapped(s)
    assert new["Evidence Type"] == "Third-party only"
    assert not gi.validate(s, new, CFG, TODAY)


def test_third_party_label_never_promotes_source_or_bypasses_price_guard():
    s = strong(**{"Source Tier": "Parkopedia", "Evidence Level": "Reported", "Cost Type": "Paid",
                  "Tariff Type": "Hourly rate", "Tariff Detail": "£1.00 per hour"})
    new, _, _ = mapped(s)
    assert new["Source Tier"] == "Parkopedia"
    assert new["Evidence Type"] == "Third-party only"
    assert any("strong site-specific" in e for e in gi.validate(s, new, CFG, TODAY))
    s["Fields Found"] = "None"
    assert mapped(s)[0]["Evidence Type"] == "Official site: partial info"
    s = strong()
    assert mapped(s)[0]["Evidence Type"] == "Official site: partial info"


def test_only_original_reject_ids_selected_and_missing_ids_abort(tmp_path):
    s = snapshot([source(), source(**{"Place ID": "PP-2"})])
    s["tabs"][gi.sheets.TAB][1].append(target(**{"Place ID": "PP-2", "_sheet_row": 11}))
    result = gi.prepare(s, tmp_path / "only", only_ids={"PP-2"})
    assert result["report"]["source_rows"] == 1
    assert [r["place_id"] for r in result["plan"]] == ["PP-2"]
    validation = json.loads((tmp_path / "only" / "validation_plan.json").read_text())
    assert {r["column"] for r in validation["changes"]} == {"Evidence Type", "Evidence Level"}
    evidence = next(r for r in validation["changes"] if r["column"] == "Evidence Type")
    assert evidence["after"] == evidence["before"] + ["Third-party only"]
    with pytest.raises(ValueError, match="missing from live results"):
        gi.prepare(s, tmp_path / "missing", only_ids={"missing"})


def test_scope_files_distinguish_new_exclusions_from_previously_imported_rows(tmp_path):
    s = snapshot([strong(**{"Notes": "Out of scope: HGV/coach"}),
                  strong(**{"Place ID": "PP-2", "Notes": "Out of scope: HGV/coach"})])
    s["tabs"][gi.sheets.TAB][1].append(target(**{"Place ID": "PP-2", "_sheet_row": 11,
        "Verified By": "Grok (detail pass)", "Verification Result": "No evidence"}))
    result = gi.prepare(s, tmp_path / "run", only_ids={"PP-1"})
    assert result["report"]["out_of_scope"] == 1
    audit = json.loads((tmp_path / "run" / "scope_audit.json").read_text())
    assert audit["excluded_from_this_plan"][0]["Place ID"] == "PP-1"
    assert audit["previously_imported"][0]["Place ID"] == "PP-2"


def test_unimported_selection_excludes_only_finished_grok_imports(tmp_path):
    s = snapshot([source(**{"Place ID": f"PP-{i}"}) for i in range(1, 5)])
    s["tabs"][gi.sheets.TAB][1] = [
        target(**{"Place ID": "PP-1", "Verified By": "Grok (detail pass)", "Verification Result": "No evidence"}),
        target(**{"Place ID": "PP-2", "Verified By": "Grok (detail pass)", "_sheet_row": 11}),
        target(**{"Place ID": "PP-3", "Verified By": "Tharidu", "Verification Result": "Confirmed", "_sheet_row": 12}),
        target(**{"Place ID": "PP-4", "_sheet_row": 13}),
    ]
    result = gi.prepare(s, tmp_path / "run", unimported_only=True)
    assert result["report"]["total_result_rows"] == 4
    assert result["report"]["already_imported_excluded"] == 1
    assert result["report"]["source_rows"] == 3
    assert result["report"]["skipped"] == 1
    assert {r["place_id"] for r in result["plan"]} == {"PP-2", "PP-4"}
    with pytest.raises(ValueError, match="not both"):
        gi.prepare(s, tmp_path / "invalid", only_ids={"PP-1"}, unimported_only=True)


def test_unimported_selection_never_hides_ambiguous_duplicate_target_ids(tmp_path):
    s = snapshot()
    s["tabs"][gi.sheets.TAB][1] = [
        target(**{"Verified By": "Grok (detail pass)", "Verification Result": "Confirmed"}), target()]
    result = gi.prepare(s, tmp_path / "run", unimported_only=True)
    assert result["report"]["already_imported_excluded"] == 0
    assert result["report"]["rejected"] == 1
