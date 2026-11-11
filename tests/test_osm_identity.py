"""Offline geometry, collector and db-apply contract tests."""
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, box

from ferro_parking import db, discovery, osm_identity as identity, plan

CATEGORIES = discovery.load_categories()


def anchor(geom, name="Tesco Extra", brand="Tesco", category="supermarket", oid=1):
    return {"geom": geom, "tags": {"name": name, "brand": brand, "shop": "supermarket"},
            "category": category, "type": "node", "id": oid}


@pytest.mark.parametrize("parking,geom,method", [
    (box(-5, -5, 5, 5), Point(0, 0), "inside the car park"),
    (box(-5, -5, 5, 5), box(-10, -10, 100, 100), "inside the site"),
    (Point(0, 0), Point(20, 0), "beside it"),
    (Point(0, 0), Point(60, 0), ""),
])
def test_methods(parking, geom, method):
    assert identity.Matcher([anchor(geom)]).match({"geom": parking})[0] == method


def test_strongest_wins():
    method, found = identity.Matcher([anchor(Point(0, 0)), anchor(Point(20, 0), brand="Lidl")]).match(
        {"geom": box(-5, -5, 5, 5)})
    assert method == "inside the car park"
    assert len(found) == 1


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "identity.sqlite")
    db.import_sheet_csv(connection, Path(__file__).parent / "fixtures/db_sheet_sample.csv")
    row = {"Place ID": "PP-100000", "Location Name": "Car park (unnamed)"}
    connection.execute("INSERT INTO created (place_id,run_id,source,source_ref,json,created_at) VALUES (?,?,?,?,?,?)",
                       (row["Place ID"], "fixture", "osm", "way/10", json.dumps(row), "2026-11-11"))
    connection.execute("INSERT INTO routing VALUES (?,?,?,?)", ("route-fixture", row["Place ID"], "no_evidence", "test"))
    connection.commit()
    yield connection
    connection.close()


def handler(anchors):
    result = identity.Collector(CATEGORIES)
    result.parking = {"way/10": {"geom": box(-5, -5, 5, 5)}}
    result.anchors = anchors
    return result


def test_plan_contract_and_import_exclusion(conn, tmp_path):
    lines, proposals, held, absent = identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)
    assert not held and not absent
    assert len(proposals) == 1
    assert {line["column"] for line in lines} == {"Brand", "Place Category", "Notes"}
    assert {line["place_id"] for line in lines} == {"PP-100000"}
    assert {line["stage"] for line in lines} == {"no_evidence"}
    parking_columns = {"Operator", "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type",
                       "Tariff Detail", "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)"}
    assert not parking_columns.intersection(line["column"] for line in lines)
    path = tmp_path / "plan.jsonl"
    plan.write_plan(path, lines)
    assert plan.read_plan(path) == lines
    assert not plan.check_plan(conn, lines)[1]


@pytest.mark.parametrize("brands,expected", [(["Tesco", "Lidl"], False), (["Tesco", "Tesco"], True)])
def test_competing_anchors(conn, brands, expected):
    lines, proposals, held, _ = identity.propose(conn, handler([
        anchor(Point(0, 0), brand=brand, oid=i) for i, brand in enumerate(brands)]), CATEGORIES)
    assert bool(proposals) == expected
    if not expected:
        assert not lines
        assert "Tesco" in held[0]["reason"] and "Lidl" in held[0]["reason"]


def test_filled_columns_and_notes_preserved(conn):
    row = {"Place ID": "PP-100000", "Brand": "Existing", "Notes": "Keep verbatim"}
    conn.execute("UPDATE created SET json=?", (json.dumps(row),))
    lines, *_ = identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)
    assert {line["column"] for line in lines} == {"Place Category"}


@pytest.mark.parametrize("field,value", [("Verification Result", "Confirmed"), ("Verified By", "Deshan"), ("Verified By", "Tharidu")])
def test_protected_rows(conn, field, value):
    conn.execute("UPDATE created SET json=?", (json.dumps({"Place ID": "PP-100000", field: value}),))
    assert not identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)[0]


def test_inactive_absent_unrouted_and_unmapped(conn):
    h = handler([anchor(Point(0, 0), category="cafe")])
    assert "no sheet category" in identity.propose(conn, h, CATEGORIES)[2][0]["reason"]
    h.parking = {}
    assert len(identity.propose(conn, h, CATEGORIES)[3]) == 1
    conn.execute("UPDATE created SET active=0")
    assert identity.propose(conn, h, CATEGORIES) == ([], [], [], [])


def test_no_routing_stage(conn):
    conn.execute("UPDATE routing SET run_id='old', place_id='other'")
    result = identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)
    assert not result[0] and "no stage" in result[2][0]["reason"]


def test_xml_collector(tmp_path):
    path = tmp_path / "extract.osm"
    path.write_text((Path(__file__).parent / 'fixtures/osm_identity.osm').read_text())
    h = identity.collect(path, CATEGORIES)
    assert [a["tags"]["name"] for a in h.anchors] == ["Tesco"]
    assert set(h.parking) == {"node/3", "way/10"}


def test_command_read_only_and_outputs(conn, tmp_path, monkeypatch, capsys):
    database = conn.execute("PRAGMA database_list").fetchone()[2]
    before = Path(database).read_bytes()
    monkeypatch.setattr(identity, "collect", lambda *args: handler([anchor(Point(0, 0))]))
    out = tmp_path / "out"
    assert identity.main(["--pbf", "fixture.osm", "--db", database, "--out", str(out)]) == 0
    assert Path(database).read_bytes() == before
    assert {p.name for p in out.iterdir()} == {"plan.jsonl", "proposals.csv", "held.csv", "absent.csv", "counts.csv"}
    assert "Tesco: 1" in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        identity.main(["--pbf", "fixture.osm", "--db", database, "--out", str(out)])


def test_identity_validation_does_not_exempt_parking_answers(conn):
    lines, *_ = identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)
    lines.append({**lines[0], "column": "Cost Type", "new_value": "Free"})
    refused = plan.check_plan(conn, lines)[1]
    assert any("Decision Reason" in r["reason"] for r in refused)
    assert any("strong site-specific evidence" in r["reason"] for r in refused)


@pytest.mark.parametrize("value", ["Unknown", "Not yet checked", "Not published", ""])
def test_placeholders_and_append_only_notes(conn, value):
    row = {"Place ID": "PP-100000", "Brand": value, "Notes": value}
    conn.execute("UPDATE created SET json=?", (json.dumps(row),))
    lines, *_ = identity.propose(conn, handler([anchor(Point(0, 0), brand=" ")]), CATEGORIES)
    assert next(line["new_value"] for line in lines if line["column"] == "Brand") == "Tesco Extra"
    notes = next(line["new_value"] for line in lines if line["column"] == "Notes")
    if value:
        assert notes.startswith(value + " | ")
    assert not plan.check_plan(conn, lines)[1]


def test_limit_and_zero_matches(conn):
    row = {"Place ID": "PP-100001"}
    conn.execute("INSERT INTO created (place_id,run_id,source,source_ref,json,created_at) VALUES (?,?,?,?,?,?)",
                 (row["Place ID"], "fixture", "osm", "way/11", json.dumps(row), "2026-11-11"))
    assert len(identity.propose(conn, handler([]), CATEGORIES, limit=1)[2]) == 1
    assert len(identity.propose(conn, handler([]), CATEGORIES)[3]) == 1


def test_dashes_normalised_in_all_proposed_text(conn):
    lines, proposals, *_ = identity.propose(conn, handler([anchor(Point(0, 0), name="A\u2013B", brand="A\u2014B")]), CATEGORIES)
    assert proposals[0]["brand"] == "A-B"
    assert not any(chr(c) in json.dumps(lines, ensure_ascii=False) for c in (0x2013, 0x2014))


def test_exact_distance_and_empty_index():
    assert identity.Matcher([]).match({"geom": Point(0, 0)}) == ("", [])
    assert identity.Matcher([anchor(Point(40, 0))]).match({"geom": Point(0, 0)})[0] == "beside it"


def test_open_way_geometry_is_collected(tmp_path):
    path = tmp_path / "open.osm"
    path.write_text('''<osm version="0.6">
    <node id="1" lat="51.5" lon="-0.1"/><node id="2" lat="51.5001" lon="-0.1"/>
    <way id="20"><nd ref="1"/><nd ref="2"/><tag k="amenity" v="parking"/></way>
    <way id="21"><nd ref="1"/><nd ref="2"/><tag k="railway" v="station"/><tag k="name" v="Example"/></way>
    </osm>''')
    result = identity.collect(path, CATEGORIES)
    assert result.parking["way/20"]["geom"].geom_type == "LineString"
    assert result.anchors[0]["tags"]["name"] == "Example"


def test_automation_uses_existing_configuration(conn):
    row = {"Place ID": "PP-100000", "Verified By": "Code (page fetch)"}
    conn.execute("UPDATE created SET json=?", (json.dumps(row),))
    assert identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES)[0]


def test_created_record_later_imported_is_out_of_scope(conn):
    conn.execute("INSERT INTO raw (import_id,place_id,row_index,json,imported_at) VALUES (?,?,?,?,?)",
                 (db.latest_import_id(conn), "PP-100000", 99,
                  json.dumps({"Place ID": "PP-100000"}), "2026-11-11"))
    assert identity.propose(conn, handler([anchor(Point(0, 0))]), CATEGORIES) == ([], [], [], [])
