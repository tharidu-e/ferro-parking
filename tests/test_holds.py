"""Every rule, the loader, the merge matrix and the read only guarantee.

Fixtures only. No real extract, no real database, no network.
"""
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from ferro_parking import db, holds

FIXTURES = Path(__file__).parent / "fixtures"
SHEET = FIXTURES / "holds_sheet.csv"
HELD_ALL = FIXTURES / "holds_held_all.csv"
POSSIBLE_DUPLICATES = FIXTURES / "holds_possible_duplicates.csv"
STRICT = FIXTURES / "holds_strict.csv"
NAMES = FIXTURES / "holds_names.csv"


@pytest.fixture
def database(tmp_path):
    """A small sheet, imported. Returns the file path, not a connection, so a
    test can hash it and open it read only the way the module does."""
    path = tmp_path / "ferro.sqlite"
    conn = db.connect(path)
    db.import_sheet_csv(conn, SHEET)
    conn.close()
    return path


@pytest.fixture
def cases(database):
    conn = holds.read_only_conn(database)
    return holds.load_cases(conn, HELD_ALL, POSSIBLE_DUPLICATES, STRICT, NAMES)


def by_ref(cases, ref):
    return next(case for case in cases if case.candidate_ref == ref)


def a_case(ref, name, **kwargs):
    return holds.HeldCase(case_id=f"test:{ref}", candidate_ref=ref,
                          candidate_name=name, source_file="test", **kwargs)


def verdict_of(case, polygons=None, others=()):
    holds.decide([case, *others], polygons or {})
    return case.verdict, case.decided_by


# ---------------------------------------------------------------- the loader

def test_loader_normalizes_all_four_headers(cases):
    """Four different headers, one shape of case out of all of them."""
    refs = {case.candidate_ref for case in cases}
    assert {"node/26846355", "node/266898069", "way/555001", "node/777001",
            "way/999001", "way/888001", "node/888002"} == refs
    chinatown = by_ref(cases, "node/26846355")
    assert chinatown.candidate_name == "QPark Chinatown"
    assert chinatown.case_id == "holds_held_all:node/26846355"
    # File 2 carries a candidate point. File 1 does not, and the merge keeps it.
    assert chinatown.latitude == pytest.approx(51.51229)
    # Files 3 and 4 name no existing place at all.
    assert by_ref(cases, "node/888002").near == []
    assert by_ref(cases, "node/888002").candidate_name == "Bluebird Retail Park Car Park"


def test_loader_merges_a_ref_that_appears_in_two_files(cases):
    """One candidate in two files is one car park read twice, and both near
    places are evidence, so they join rather than replace."""
    chinatown = by_ref(cases, "node/26846355")
    assert chinatown.source_file == "holds_held_all+holds_possible_duplicates"
    assert [near.place_id for near in chinatown.near] == ["PP-000125", "PP-000125"]
    # The strict and the names file share way/888001 too.
    assert by_ref(cases, "way/888001").source_file == "holds_strict+holds_names"
    assert len(cases) == 7


def test_reconciliation_marks_a_case_created(cases):
    """Place PP-000600 already carries way/999001, so that record exists."""
    created = by_ref(cases, "way/999001")
    assert created.state == "created"
    assert created.created_place_id == "PP-000600"
    pending = by_ref(cases, "node/26846355")
    assert pending.state == "pending"
    assert pending.created_place_id == ""


def test_reconciliation_fills_the_near_place_from_the_database(cases):
    """The source files give a Place ID and a name. Everything a rule reads,
    the geo precision, the verifier and the reference, comes from the store."""
    near = by_ref(cases, "way/555001").near[0]
    assert near.verified_by == "Tharidu"
    assert near.postcode == "SE1 9AA"
    assert by_ref(cases, "node/777001").near[0].geo_precision == "Postcode centroid"


def test_state_counts_report_each_file_separately(cases):
    counts = holds.state_counts(cases)
    assert counts["holds_held_all"] == {"pending": 4, "created": 0}
    assert counts["holds_possible_duplicates"] == {"pending": 1, "created": 1}


# ---------------------------------------------------------------- rule 1

def test_already_same_ref_fires_on_a_created_case(cases):
    created = by_ref(cases, "way/999001")
    assert verdict_of(created) == ("duplicate", "already_same_ref")
    assert "PP-000600" in created.evidence


def test_already_same_ref_fires_when_a_near_place_carries_the_ref():
    case = a_case("way/999001", "Riverside Wharf Car Park",
                  near=[holds.NearPlace(place_id="PP-000600",
                                        name="Riverside Wharf Car Park",
                                        osm_id="way/999001")])
    assert verdict_of(case) == ("duplicate", "already_same_ref")


def test_already_same_ref_does_not_fire_on_a_different_ref():
    """A near place naming another OSM feature is a near miss, not a match."""
    case = a_case("way/999001", "Riverside Wharf Car Park",
                  near=[holds.NearPlace(place_id="PP-000600", name="Riverside Wharf",
                                        osm_id="way/999002")])
    assert verdict_of(case) == ("unresolved", holds.NO_RULE)


def test_a_created_case_with_an_older_place_nearby_is_not_settled_by_rule_one():
    """The 47 cases discovery flagged as possible duplicates, which step 2
    created anyway. The open question is whether the created record duplicates
    the older place. Settling the case on its own creation throws that away."""
    case = a_case("node/1319513718", "Eastcote Station Car Park",
                  state="created", created_place_id="PP-A",
                  latitude=51.577043, longitude=-0.396241,
                  near=[holds.NearPlace(place_id="PP-B", name="Eastcote",
                                        latitude=51.5771, longitude=-0.3963,
                                        geo_precision="Rooftop", metres=8.0)])
    assert verdict_of(case) == ("unresolved", holds.NO_RULE)


def test_a_created_case_whose_only_near_place_is_its_own_record_is_a_duplicate():
    """Nothing is left to ask: the near place is the record this candidate made."""
    case = a_case("node/26866990", "Soho Cark Park", state="created",
                  created_place_id="PP-C",
                  near=[holds.NearPlace(place_id="PP-C", name="Soho Car Park",
                                        metres=0.0)])
    assert verdict_of(case) == ("duplicate", "already_same_ref")
    assert "nothing to create" in case.evidence


def test_a_created_case_with_an_older_place_nearby_still_stops_on_a_hand_check():
    """Falling through rule 1 must not fall past the hand check protection."""
    case = a_case("node/1319513718", "Eastcote Station Car Park",
                  state="created", created_place_id="PP-A",
                  near=[holds.NearPlace(place_id="PP-B", name="Eastcote",
                                        verified_by="Tharidu", metres=8.0)])
    assert verdict_of(case) == ("unresolved", "protected_row")


def test_a_reviewer_sees_that_a_case_is_a_live_record():
    """A reviewer judging one of the 47 must know it already has a Place ID."""
    case = a_case("node/1319513718", "Eastcote Station Car Park",
                  state="created", created_place_id="PP-A")
    payload = holds.review_payload(case)
    assert payload["state"] == "created"
    assert payload["created_place_id"] == "PP-A"


# ---------------------------------------------------------------- rule 2

def test_a_protected_row_is_unresolved_even_when_a_duplicate_rule_would_fire():
    """Rule 2 runs before every geometry rule. A hand check outranks a polygon:
    without this ordering, rule 4 would mark this case a duplicate."""
    polygon = box(-0.0906, 51.5036, -0.0894, 51.5044)
    case = a_case("way/555001", "Tharidu Checked Car Park",
                  latitude=51.504, longitude=-0.09,
                  near=[holds.NearPlace(place_id="PP-000400",
                                        name="Tharidu Checked Car Park",
                                        latitude=51.504, longitude=-0.09,
                                        geo_precision="Building",
                                        verified_by="Tharidu")])
    holds.attach_distances([case], {"way/555001": polygon})
    assert case.near[0].pin_inside_candidate is True
    assert holds.brands_overlap(case.candidate_name, case.near[0].name)
    assert verdict_of(case, {"way/555001": polygon}) == ("unresolved", "protected_row")
    assert "Tharidu" in case.evidence


def test_a_protected_row_does_not_fire_for_another_verifier():
    polygon = box(-0.0906, 51.5036, -0.0894, 51.5044)
    case = a_case("way/555001", "Bermondsey Wharf Car Park",
                  latitude=51.504, longitude=-0.09,
                  near=[holds.NearPlace(place_id="PP-000401",
                                        name="Bermondsey Wharf Car Park",
                                        latitude=51.504, longitude=-0.09,
                                        geo_precision="Building",
                                        verified_by="Deshan")])
    holds.attach_distances([case], {"way/555001": polygon})
    assert verdict_of(case, {"way/555001": polygon}) == (
        "duplicate", "pin_inside_candidate_same_brand")


def test_a_recorded_fact_still_outranks_a_protected_row(cases):
    """Rule 1 is first by design: that a place already carries this exact
    reference is a fact on file, not a judgment a hand check could contradict."""
    case = a_case("way/555001", "Bermondsey Wharf Car Park",
                  near=[holds.NearPlace(place_id="PP-000400",
                                        name="Tharidu Checked Car Park",
                                        osm_id="way/555001", verified_by="Tharidu")])
    assert verdict_of(case) == ("duplicate", "already_same_ref")


# ---------------------------------------------------------------- rule 3

def test_a_postcode_centroid_near_place_never_produces_a_duplicate(cases):
    """The pin is the middle of a postcode, so its distance is not evidence."""
    case = by_ref(cases, "node/777001")
    assert verdict_of(case) == ("unresolved", "pin_is_postcode_centroid")
    assert "postcode centroid" in case.evidence


def test_a_postcode_centroid_is_dropped_but_a_usable_near_place_survives():
    """One unusable near place does not make the case unresolved on its own."""
    case = a_case("way/555003", "Angel Islington Car Park",
                  near=[holds.NearPlace(place_id="PP-000500", name="Centroid Only",
                                        geo_precision="Postcode centroid"),
                        holds.NearPlace(place_id="PP-000501", name="Angel Car Park",
                                        geo_precision="Building", metres=9.0)])
    assert holds.distance_near(case) == [case.near[1]]
    assert verdict_of(case) == ("unresolved", holds.NO_RULE)


def test_a_postcode_centroid_cannot_satisfy_the_pin_inside_rule():
    """Rule 4 reads the surviving near places only, so a centroid pin that
    happens to land inside the polygon still proves nothing."""
    polygon = box(-0.1006, 51.5396, -0.0994, 51.5404)
    case = a_case("way/555004", "Centroid Only Car Park",
                  latitude=51.54, longitude=-0.1,
                  near=[holds.NearPlace(place_id="PP-000500",
                                        name="Centroid Only Car Park",
                                        latitude=51.54, longitude=-0.1,
                                        geo_precision="Postcode centroid")])
    holds.attach_distances([case], {"way/555004": polygon})
    assert case.near[0].pin_inside_candidate is True
    assert verdict_of(case, {"way/555004": polygon}) == (
        "unresolved", "pin_is_postcode_centroid")


# ---------------------------------------------------------------- rule 4

def test_chinatown_resolves_to_duplicate_once_a_polygon_contains_the_pin():
    """The real case: QPark Chinatown against place PP-000125 Q-Park Chinatown,
    12 m apart. The brand token chinatown survives, car and park do not."""
    polygon = box(-0.1320, 51.5119, -0.1308, 51.5127)
    case = a_case("way/26846355", "QPark Chinatown",
                  latitude=51.51229, longitude=-0.13138,
                  near=[holds.NearPlace(place_id="PP-000125", name="Q-Park Chinatown",
                                        latitude=51.5123, longitude=-0.1314,
                                        geo_precision="Rooftop")])
    holds.attach_distances([case], {"way/26846355": polygon})
    assert case.near[0].pin_inside_candidate is True
    assert case.near[0].metres < 30
    assert verdict_of(case, {"way/26846355": polygon}) == (
        "duplicate", "pin_inside_candidate_same_brand")
    assert "chinatown" in case.evidence


def test_hayes_station_stays_unresolved_because_a_node_has_no_polygon(cases):
    """The real near miss: the names do share a brand, but a point candidate
    cannot contain anything, so rule 4 has no answer and must not guess."""
    case = by_ref(cases, "node/266898069")
    case.geometry = "node"
    holds.attach_distances([case], {})
    assert case.near[0].pin_inside_candidate is None
    assert holds.brands_overlap(case.candidate_name, case.near[0].name)
    assert verdict_of(case) == ("unresolved", holds.NO_RULE)


def test_pin_inside_without_a_shared_brand_does_not_fire():
    """Inside the same polygon is the same site. It is not the same business."""
    polygon = box(-0.1006, 51.5196, -0.0994, 51.5204)
    case = a_case("way/555005", "Smithfield Car Park",
                  latitude=51.52, longitude=-0.1,
                  near=[holds.NearPlace(place_id="PP-000700", name="Clerkenwell Car Park",
                                        latitude=51.52, longitude=-0.1,
                                        geo_precision="Building")])
    holds.attach_distances([case], {"way/555005": polygon})
    assert case.near[0].pin_inside_candidate is True
    assert verdict_of(case, {"way/555005": polygon}) == ("unresolved", holds.NO_RULE)


# ---------------------------------------------------------------- rule 5

def test_same_feature_twice_makes_the_point_the_duplicate():
    """One car park reached the hold list as an area and as a point. The area
    is the better record, so the point is the duplicate."""
    polygon = box(-0.1906, 51.3596, -0.1894, 51.3604)
    area = a_case("way/888001", "Bluebird Retail Park Car Park",
                  latitude=51.36, longitude=-0.19, geometry="way")
    point = a_case("node/888002", "Bluebird Retail Park Car Park",
                   latitude=51.36001, longitude=-0.19001, geometry="node")
    polygons = {"way/888001": polygon}
    holds.decide([area, point], polygons)
    assert (point.verdict, point.decided_by) == ("duplicate", "same_feature_twice")
    assert "way/888001" in point.evidence
    # The area itself is contained by nothing, so it stays for a reviewer.
    assert (area.verdict, area.decided_by) == ("unresolved", holds.NO_RULE)


def test_same_feature_twice_needs_a_shared_brand():
    polygon = box(-0.1906, 51.3596, -0.1894, 51.3604)
    area = a_case("way/888001", "Hackbridge Car Park",
                  latitude=51.36, longitude=-0.19, geometry="way")
    point = a_case("node/888002", "Rosehill Car Park",
                   latitude=51.36001, longitude=-0.19001, geometry="node")
    holds.decide([area, point], {"way/888001": polygon})
    assert (point.verdict, point.decided_by) == ("unresolved", holds.NO_RULE)


def test_same_feature_twice_needs_containment():
    """A candidate outside the polygon is a different car park nearby."""
    polygon = box(-0.1906, 51.3596, -0.1894, 51.3604)
    area = a_case("way/888001", "Bluebird Retail Park Car Park",
                  latitude=51.36, longitude=-0.19, geometry="way")
    point = a_case("node/888002", "Bluebird Retail Park Car Park",
                   latitude=51.3700, longitude=-0.1800, geometry="node")
    holds.decide([area, point], {"way/888001": polygon})
    assert (point.verdict, point.decided_by) == ("unresolved", holds.NO_RULE)


# ---------------------------------------------------------------- brand tokens

def test_two_names_sharing_only_a_generic_word_do_not_overlap():
    assert not holds.brands_overlap("Station Car Park", "Multi Storey Car Park")
    assert not holds.brands_overlap("Sutton Car Park", "Sutton Station Car Park")
    assert holds.brand_tokens("Car Park") == set()


def test_a_name_with_no_brand_token_never_overlaps():
    """False in both directions, never True by emptiness."""
    assert not holds.brands_overlap("Car Park", "Q-Park Chinatown")
    assert not holds.brands_overlap("Q-Park Chinatown", "Car Park")


def test_a_real_brand_survives_tokenising():
    assert holds.brands_overlap("QPark Chinatown", "Q-Park Chinatown")
    assert holds.brands_overlap("Hayes Station Car Park", "Hayes Station - Hayes (APCOA)")


# ---------------------------------------------------------------- the merge

def write_review(path, rows):
    lines = ["case_id,verdict,confidence,evidence"]
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def merged(tmp_path, rows_a, rows_b, case=None):
    case = case or a_case("node/1", "Somewhere Wharf", verdict="unresolved",
                          decided_by=holds.NO_RULE, evidence="no rule matched")
    reviews_a = holds.read_reviews(write_review(tmp_path / "a.csv", rows_a))
    reviews_b = holds.read_reviews(write_review(tmp_path / "b.csv", rows_b))
    rows, counts = holds.merge([case], reviews_a, reviews_b)
    return rows[0], counts


def test_merge_agree_high_duplicate(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "high", "same site"]],
                    [["test:node/1", "duplicate", "high", "same site"]])
    assert row["verdict"] == "duplicate"
    assert row["decided_by"] == holds.BY_REVIEWERS
    assert "high confidence" in row["evidence"]


def test_merge_agree_high_distinct(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "distinct", "high", "two car parks"]],
                    [["test:node/1", "distinct", "high", "two car parks"]])
    assert row["verdict"] == "distinct"


def test_merge_agree_low_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "low", "probably"]],
                    [["test:node/1", "duplicate", "low", "probably"]])
    assert row["verdict"] == "unresolved"
    assert "not confident" in row["evidence"]


def test_merge_one_low_reviewer_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "high", "same site"]],
                    [["test:node/1", "duplicate", "low", "probably"]])
    assert row["verdict"] == "unresolved"
    assert "reviewer b" in row["evidence"]


def test_merge_disagreement_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "high", "same site"]],
                    [["test:node/1", "distinct", "high", "two car parks"]])
    assert row["verdict"] == "unresolved"
    assert "disagree" in row["evidence"]


def test_merge_with_one_reviewer_missing_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "high", "same site"]], [])
    assert row["verdict"] == "unresolved"
    assert "reviewer b did not judge" in row["evidence"]


def test_merge_with_both_reviewers_missing_is_unresolved(tmp_path):
    row, _ = merged(tmp_path, [], [])
    assert row["verdict"] == "unresolved"
    assert "reviewer a and b did not judge" in row["evidence"]


def test_merge_with_an_unknown_verdict_string_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "probably duplicate", "high", "hmm"]],
                    [["test:node/1", "duplicate", "high", "same site"]])
    assert row["verdict"] == "unresolved"
    assert "is not one of" in row["evidence"]


def test_merge_with_an_unknown_confidence_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "duplicate", "fairly sure", "hmm"]],
                    [["test:node/1", "duplicate", "high", "same site"]])
    assert row["verdict"] == "unresolved"
    assert "high or low" in row["evidence"]


def test_merge_with_both_unresolved_is_unresolved(tmp_path):
    row, _ = merged(tmp_path,
                    [["test:node/1", "unresolved", "high", "cannot tell"]],
                    [["test:node/1", "unresolved", "high", "cannot tell"]])
    assert row["verdict"] == "unresolved"
    assert "does not settle" in row["evidence"]


def test_a_rule_verdict_survives_the_merge_unchanged(tmp_path):
    """Two reviewers calling a recorded fact wrong does not change the fact."""
    case = a_case("way/999001", "Riverside Wharf Car Park", verdict="duplicate",
                  decided_by="already_same_ref",
                  evidence="place PP-000600 already carries it")
    row, counts = merged(tmp_path,
                         [["test:way/999001", "distinct", "high", "looks separate"]],
                         [["test:way/999001", "distinct", "high", "looks separate"]],
                         case=case)
    assert row["verdict"] == "duplicate"
    assert row["decided_by"] == "already_same_ref"
    assert row["evidence"] == "place PP-000600 already carries it"
    assert counts["carried through from the rules"] == 1
    assert counts["merged from the reviewers"] == 0
    # The merge still records what each reviewer said.
    assert row["reviewer_a"] == "distinct / high"


def test_merge_counts_reviewer_rows_for_cases_it_was_not_given(tmp_path):
    row, counts = merged(tmp_path,
                         [["test:node/1", "duplicate", "high", "same site"],
                          ["test:node/999", "duplicate", "high", "stray row"]],
                         [["test:node/1", "duplicate", "high", "same site"]])
    assert counts["reviewer rows not used"] == 1


# ---------------------------------------------------------------- the outputs

def test_a_review_batch_holds_no_verdict_and_no_hint(cases, tmp_path):
    holds.decide(cases, {})
    paths = holds.write_review_batches(cases, tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload, "there should be cases for a reviewer"
    for entry in payload:
        assert set(entry) == {"case_id", "candidate_ref", "candidate_name",
                              "geometry", "area_m2", "latitude", "longitude",
                              "tags", "near", "state", "created_place_id"}
        for near in entry["near"]:
            assert set(near) == {"place_id", "name", "postcode", "geo_precision",
                                 "osm_id", "metres", "pin_inside_candidate"}


def test_review_batches_hold_at_most_twenty_five_cases(tmp_path):
    cases = [a_case(f"node/{index}", "Somewhere Wharf") for index in range(60)]
    holds.decide(cases, {})
    paths = holds.write_review_batches(cases, tmp_path)
    assert [len(json.loads(path.read_text(encoding="utf-8"))) for path in paths] \
        == [25, 25, 10]
    assert [path.name for path in paths] == ["batch_01.json", "batch_02.json",
                                            "batch_03.json"]


def test_a_protected_case_lands_in_protected_rows_and_not_in_a_batch(cases, tmp_path):
    holds.decide(cases, {})
    out_dir, _ = holds.write_outputs(cases, tmp_path / "holds")
    protected = (out_dir / "protected_rows.csv").read_text(encoding="utf-8")
    assert "PP-000400" in protected
    assert "Tharidu" in protected
    batched = " ".join(path.read_text(encoding="utf-8")
                       for path in (out_dir / "review").glob("*.json"))
    assert "way/555001" not in batched


def test_outputs_are_all_written(cases, tmp_path):
    holds.decide(cases, {})
    out_dir, batches = holds.write_outputs(cases, tmp_path / "holds")
    for name in ("rule_verdicts.csv", "counts.csv", "protected_rows.csv",
                 "sample60.csv"):
        assert (out_dir / name).exists(), name
    assert batches


def test_the_sample_is_seeded_and_only_holds_decided_cases(cases, tmp_path):
    holds.decide(cases, {})
    first = holds.write_sample(cases, tmp_path / "one.csv").read_text(encoding="utf-8")
    second = holds.write_sample(cases, tmp_path / "two.csv").read_text(encoding="utf-8")
    assert first == second
    assert "openstreetmap.org" in first
    assert holds.NO_RULE not in first


# ---------------------------------------------------------------- the bundle

def test_the_bundle_round_trips_including_the_polygons(cases, tmp_path):
    polygon = box(-0.1906, 51.3596, -0.1894, 51.3604)
    polygons = {"way/888001": polygon}
    holds.attach_distances(cases, polygons)
    holds.decide(cases, polygons)
    holds.write_bundle(cases, tmp_path / "bundle.jsonl", polygons)
    reloaded, reloaded_polygons = holds.read_bundle(tmp_path / "bundle.jsonl")
    assert [case.case_id for case in reloaded] == [case.case_id for case in cases]
    assert isinstance(reloaded[0].near[0], holds.NearPlace) \
        if reloaded[0].near else True
    assert reloaded_polygons["way/888001"].equals(polygon)


def test_a_reloaded_bundle_still_lets_rule_five_fire(tmp_path):
    """Rule 5 needs a shape, and a case record carries a point and an area, so
    a reload that lost the shapes would quietly decide fewer cases."""
    polygon = box(-0.1906, 51.3596, -0.1894, 51.3604)
    area = a_case("way/888001", "Bluebird Retail Park Car Park",
                  latitude=51.36, longitude=-0.19, geometry="way")
    point = a_case("node/888002", "Bluebird Retail Park Car Park",
                   latitude=51.36001, longitude=-0.19001, geometry="node")
    holds.write_bundle([area, point], tmp_path / "bundle.jsonl",
                       {"way/888001": polygon})
    reloaded, polygons = holds.read_bundle(tmp_path / "bundle.jsonl")
    holds.decide(reloaded, polygons)
    assert reloaded[1].decided_by == "same_feature_twice"


def test_the_extract_supplies_tags_geometry_area_and_a_point():
    """One small extract: an area and a point for the same car park. Rule 5
    fires on the extract's own geometry, with nothing hand built."""
    area = a_case("way/888001", "Bluebird Retail Park Car Park")
    point = a_case("node/888002", "Bluebird Retail Park Car Park")
    absent = a_case("way/404404", "Nowhere Wharf Car Park")
    polygons = holds.attach_extract([area, point, absent],
                                    FIXTURES / "holds_extract.osm")
    assert area.geometry == "way"
    assert area.area_m2 > 500
    assert area.tags["fee"] == "yes"
    assert point.geometry == "node"
    assert point.area_m2 == 0.0
    assert set(polygons) == {"way/888001"}
    assert absent.geometry == "absent" and absent.tags == {}
    holds.decide([area, point, absent], polygons)
    assert point.decided_by == "same_feature_twice"


def test_a_ref_missing_from_the_extract_is_absent_not_a_guess():
    case = a_case("node/1", "Somewhere Wharf", geometry="way", area_m2=50.0)
    case.geometry, case.tags = "absent", {}
    assert verdict_of(case) == ("unresolved", holds.NO_RULE)
    assert "no usable distance" in case.evidence


# ---------------------------------------------------------------- read only

def test_the_module_writes_nothing_to_the_database(database, tmp_path):
    """A whole bundle run, on a copy, leaving the file byte for byte the same."""
    copy = tmp_path / "copy.sqlite"
    shutil.copy(database, copy)
    before = hashlib.sha256(copy.read_bytes()).hexdigest()
    conn = holds.read_only_conn(copy)
    cases = holds.load_cases(conn, HELD_ALL, POSSIBLE_DUPLICATES, STRICT, NAMES)
    holds.decide(cases, {})
    holds.write_outputs(cases, tmp_path / "holds")
    conn.close()
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before


def test_the_read_only_connection_refuses_a_write(database):
    conn = holds.read_only_conn(database)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO routing (run_id, place_id, stage)"
                     " VALUES ('r', 'PP-000125', 'x')")


def test_the_commands_are_registered():
    from ferro_parking import __main__ as entry
    assert "holds-bundle" in entry.__doc__
    assert "holds-merge" in entry.__doc__


def test_no_dash_characters_in_the_new_files():
    """CLAUDE.md forbids an em dash and an en dash in any file."""
    em_dash, en_dash = chr(0x2014), chr(0x2013)
    for path in (Path(holds.__file__), Path(__file__)):
        text = path.read_text(encoding="utf-8")
        assert em_dash not in text, path
        assert en_dash not in text, path
