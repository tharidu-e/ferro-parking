import hashlib
from copy import deepcopy

import pytest

from ferro_parking import evaluation as ev


def case(answer="Free", status="supported"):
    text = "This site has free customer parking."
    source = {"url": "https://example.org/site", "retrieved_at": "2026-11-10T22:00:00Z", "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    support = {"status": status, "value": "Free", "quote": text,
               "exact_site": True, "supports_claim": True, "source_sha256": source["sha256"]}
    return {"case_id": "tesco", "source": source, "reference": {"Cost Type": "Free"},
            "answers": {"Cost Type": answer}, "assessments": {"Cost Type": support},
            "claim_support": {"Cost Type": support}}


def test_snapshot_preserves_labels_notes_and_hash_without_aliasing():
    rows = [{"Verification Result": "Corrected", "Notes": "paid on Maps", "Verified By": "Tharidu"}]
    saved = ev.snapshot(rows, title="Acton", retrieved_at="2026-11-10")
    rows[0]["Notes"] = "changed"
    assert saved["rows"][0]["Notes"] == "paid on Maps"
    assert len(saved["sha256"]) == 64


def test_mapping_never_pairs_by_order_and_holds_duplicate_targets():
    originals = [{"sheet": "A"}, {"sheet": "B"}, {"sheet": "Unmatched"}]
    result = ev.reconcile(originals, [{"Location Name": "B"}, {"Location Name": "A"}])
    assert [r["target_index"] for r in result] == [1, 0, None]
    assert ev.reconcile([originals[0], originals[0]], [{"Location Name": "A"}])[0]["status"] == "unresolved"


def test_conflicting_ids_postcodes_and_ambiguous_names_are_held():
    assert ev.reconcile([{"Place ID": "1", "Location Name": "A"}],
                        [{"Place ID": "2", "Location Name": "A"}])[0]["status"] == "unresolved"
    assert ev.reconcile([{"Location Name": "A", "Postcode": "W3 1AA"}],
                        [{"Location Name": "A", "Postcode": "W3 2AA"}])[0]["status"] == "unresolved"
    assert ev.reconcile([{"Location Name": "A"}], [{"Location Name": "A"}] * 2)[0]["status"] == "unresolved"


def test_extractor_never_receives_reference_or_notes():
    item = ev.extractor_input({"Location Name": "A", "Notes": "expected free", "Cost Type": "Free"}, {})
    assert "Notes" not in item["identity"] and "Cost Type" not in item["identity"]


def test_all_unknown_has_zero_supported_coverage():
    report = ev.evaluate([case("Unknown")])
    result = report["fields"]["Cost Type"]
    assert result["accuracy_denominator"] == 1
    assert result["abstention"] == 1
    assert result["supported_answer_coverage"] == 0
    assert result["accuracy"] == 0
    assert not report["evaluation_checks_passed"]


def test_conflicting_reference_excluded_but_unsupported_free_blocks_apply():
    report = ev.evaluate([case(status="conflicting")])
    result = report["fields"]["Cost Type"]
    assert result.get("accuracy_denominator", 0) == 0
    assert result["conflicting"] == 1
    assert result["unsupported_positive"] == 1
    assert not report["evaluation_checks_passed"]


def test_exact_quote_site_claim_and_version_required_for_support():
    for key, value in [("quote", "absent"), ("exact_site", False), ("supports_claim", False),
                       ("source_sha256", "other"), ("value", "Paid")]:
        item = case()
        item["assessments"]["Cost Type"][key] = value
        assert ev.evaluate([item])["fields"]["Cost Type"]["unresolved"] == 1


def test_drift_is_not_wrong_and_modified_frozen_source_refused():
    item = case("Paid")
    item["answer_source_sha256"] = "new version"
    report = ev.evaluate([item])
    assert report["fields"]["Cost Type"]["source_drift"] == 1
    assert not report["critical_blockers"]
    item["source"]["text"] += "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        ev.evaluate([item])


def test_supported_correct_and_critical_wrong():
    assert ev.evaluate([case()])["fields"]["Cost Type"]["correct"] == 1
    report = ev.evaluate([case("Paid")])
    assert report["fields"]["Cost Type"]["wrong"] == 1
    assert not report["evaluation_checks_passed"]


def test_command_is_append_only(tmp_path):
    import json
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"cases": [case()]}))
    out = tmp_path / "output"
    assert ev.main(["--input", str(bundle), "--out", str(out)]) == 0
    assert (out / "reference_snapshot.json").exists()
    with pytest.raises((FileExistsError, ValueError)):
        ev.main(["--input", str(bundle), "--out", str(out)])


def test_replay_uses_frozen_sources_without_human_answers_or_old_attestations():
    item = case()
    item["identity"] = {"Location Name": "A", "Notes": "Free expected"}
    seen = []

    def extractor(request):
        seen.append(request)
        return {"Cost Type": "Paid"}

    result = ev.replay([item], extractor)
    assert "Notes" not in seen[0]["identity"]
    assert set(seen[0]) == {"identity", "source"}
    assert result[0]["answers"]["Cost Type"] == "Paid"
    assert result[0]["claim_support"] == {}
    assert item["answers"]["Cost Type"] == "Free"


def test_a_registered_fetcher_replays_on_the_frozen_page_alone():
    item = case()
    item["identity"] = {"Location Name": "Example Station", "Notes": "Free expected"}
    item["source"]["text"] = "Station parking\n120 parking spaces"
    item["source"]["sha256"] = hashlib.sha256(item["source"]["text"].encode()).hexdigest()
    result = ev.replay([item], ev.fetcher_extractor("station"))
    assert result[0]["answers"]["Can Park? (Yes/No/Conditional)"] == "Yes"
    # Tariff, free and max stay are never read from a station page.
    assert result[0]["answers"]["Cost Type"] == ""
    assert result[0]["answers"]["Max Stay (mins)"] == ""


def test_an_unknown_or_cache_only_replay_key_is_refused(monkeypatch):
    from ferro_parking import fetch_fill
    monkeypatch.setattr(fetch_fill, "CACHE_ONLY", {"cacheonly.example"})
    for key in ("nosuchsource.example", "cacheonly.example"):
        with pytest.raises(SystemExit):
            ev.fetcher_extractor(key)


def test_the_replay_command_scores_its_own_answers_per_field(tmp_path, capsys):
    import json
    item = case(answer="Free")
    item["identity"] = {"Location Name": "Example Station"}
    # The reviewer's quote stays in the page, so the reference is still
    # supported and the field has a denominator of one.
    item["source"]["text"] = ("This site has free customer parking.\n"
                               "Station parking\nNo parking spaces")
    item["source"]["sha256"] = hashlib.sha256(item["source"]["text"].encode()).hexdigest()
    item["assessments"]["Cost Type"]["quote"] = "This site has free customer parking."
    item["assessments"]["Cost Type"]["source_sha256"] = item["source"]["sha256"]
    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps({"cases": [item]}))
    out = tmp_path / "replayed"
    assert ev.main(["--input", str(bundle), "--out", str(out), "--replay", "station"]) == 0
    report = json.loads((out / "evaluation.json").read_text())
    assert report["replayed_with"] == "station"
    # The bundle's own "Free" answer is replaced by what the page states, and
    # the earlier attestation cannot certify the new answer.
    assert report["fields"]["Cost Type"]["accuracy"] == 0.0
    assert report["fields"]["Cost Type"]["accuracy_denominator"] == 1
    printed = capsys.readouterr().out
    assert "Cost Type: 0% of 1 supported" in printed
    assert "no reference answer and no reviewer note" in printed


def test_empty_or_unassessed_evaluation_cannot_authorise_apply():
    assert not ev.evaluate([])["evaluation_checks_passed"]
    item = case()
    item["answers"] = {}
    item["assessments"] = {}
    assert not ev.evaluate([item])["evaluation_checks_passed"]


def test_changed_name_and_shared_address_do_not_prove_same_facility():
    original = {"sheet": "Shop A", "Address / Postcode": "1 High Street, Acton W3 1AA"}
    target = {"Location Name": "Shop B", "Street Address": "1 High Street, Acton", "Postcode": "W31AA"}
    assert ev.reconcile([original], [target])[0]["status"] == "unresolved"


def test_unknown_reference_cannot_be_certified_by_matching_attestation():
    item = case("Unknown")
    item["reference"]["Cost Type"] = "Unknown"
    item["assessments"]["Cost Type"]["value"] = "Unknown"
    report = ev.evaluate([item])
    assert report["fields"]["Cost Type"].get("accuracy_denominator", 0) == 0
    assert not report["evaluation_checks_passed"]


def test_matching_answer_without_own_evidence_is_not_correct():
    item = case()
    item["claim_support"] = {}
    report = ev.evaluate([item])
    assert report["fields"]["Cost Type"].get("correct", 0) == 0
    assert report["fields"]["Cost Type"]["supported_answer_coverage"] == 0
    assert not report["evaluation_checks_passed"]


@pytest.mark.parametrize("missing", ["url", "retrieved_at"])
def test_missing_provenance_cannot_certify_claim(missing):
    item = case()
    del item["source"][missing]
    assert not ev.evaluate([item])["evaluation_checks_passed"]


@pytest.mark.parametrize("answer", [None, " unknown ", "Not stated", "UNCLEAR"])
def test_empty_and_unknown_variants_are_abstentions(answer):
    report = ev.evaluate([case(answer)])
    assert report["fields"]["Cost Type"]["abstention"] == 1
    assert not report["evaluation_checks_passed"]


def test_current_name_header_and_legacy_alias_match_equally():
    targets = [{"Location Name": "Tesco Acton"}]
    for header in ("Location Name", "sheet"):
        assert ev.reconcile([{header: "Tesco Acton"}], targets)[0]["status"] == "mapped"


@pytest.mark.parametrize("metadata", [{"http_status": 403}, {"http_status": 429}, {"blocked": True}])
def test_failed_or_blocked_page_cannot_certify(metadata):
    item = case()
    item["source"].update(metadata)
    assert not ev.evaluate([item])["evaluation_checks_passed"]
