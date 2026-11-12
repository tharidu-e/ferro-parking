"""The OSM car park eligibility gates, naming, category and retained tags.

These tests read no extract. They hold the rules that decide whether an OSM
feature becomes a candidate identity, because that decision is the one that can
send a driver to a car park they may not use.
"""
import json

from shapely.geometry import Point, Polygon

from ferro_parking import osm_places as op


def tags(**extra):
    out = {"amenity": "parking"}
    out.update(extra)
    return out


# ---------------------------------------------------------------- what counts

def test_only_amenity_parking_counts():
    assert op.is_parking(tags())
    assert not op.is_parking({"amenity": "fuel"})
    assert not op.is_parking({"shop": "supermarket"})


def test_a_lifecycle_prefixed_car_park_is_not_a_car_park():
    for prefix in ("disused", "abandoned", "proposed", "construction"):
        assert not op.is_parking({f"{prefix}:amenity": "parking"})
        assert op.lifecycle_excluded({f"{prefix}:amenity": "parking"})


# ---------------------------------------------------------------- access

def test_the_excluded_access_values_are_the_ones_the_checklist_names():
    assert op.EXCLUDED_ACCESS >= {"private", "no", "residents", "permit",
                                  "employees", "delivery", "staff", "students"}


def test_only_four_access_values_mean_the_public_may_park():
    assert op.PUBLIC_ACCESS == {"yes", "public", "permissive", "customers"}


def test_destination_access_is_not_treated_as_public():
    assert "destination" not in op.PUBLIC_ACCESS


# ---------------------------------------------------------------- vehicle type

def test_a_lorry_or_coach_park_is_excluded():
    assert op.lorry_only(tags(parking="lorry"))
    assert op.lorry_only(tags(parking="coach"))
    assert op.lorry_only(tags(parking="hgv"))


def test_parking_a_car_may_not_enter_is_excluded():
    assert op.lorry_only(tags(motorcar="no"))
    assert op.lorry_only(tags(motor_vehicle="no"))
    assert op.lorry_only(tags(hgv="designated"))


def test_a_lorry_park_that_also_takes_cars_is_kept():
    assert not op.lorry_only(tags(hgv="designated", motorcar="yes"))
    assert not op.lorry_only(tags(capacity="40"))


# ---------------------------------------------------------------- qualifiers

def test_a_feature_with_no_access_tag_needs_a_qualifier():
    assert op.qualifier(tags(), 0.0) == ""
    assert op.qualifier(tags(), 10.0) == ""


def test_each_qualifier_admits_a_candidate():
    assert op.qualifier(tags(name="Hill Street Car Park"), 0.0) == "name"
    assert op.qualifier(tags(operator="Sutton Council"), 0.0) == "operator"
    assert op.qualifier(tags(fee="yes"), 0.0) == "fee"
    assert op.qualifier(tags(capacity="10"), 0.0) == "capacity"
    assert op.qualifier(tags(parking="multi-storey"), 0.0) == "type"
    assert op.qualifier(tags(), 500.0) == "area"


def test_a_small_capacity_or_a_small_polygon_does_not_qualify():
    assert op.qualifier(tags(capacity="9"), 0.0) == ""
    assert op.qualifier(tags(), 499.0) == ""


def test_an_unreadable_capacity_does_not_qualify():
    assert op.qualifier(tags(capacity="lots"), 0.0) == ""
    assert op.qualifier(tags(capacity=""), 0.0) == ""


# ---------------------------------------------------------------- naming

def test_the_name_falls_back_in_the_documented_order():
    assert op.place_name(tags(name="Hill Street Car Park")) == "Hill Street Car Park"
    assert op.place_name(tags(operator="Q-Park")) == "Q-Park car park"
    assert op.place_name(tags(**{"addr:street": "Hill Street"})) == "Car park, Hill Street"
    assert op.place_name(tags()) == "Car park (unnamed)"


def test_a_blank_name_tag_does_not_become_the_name():
    assert op.place_name(tags(name="   ", operator="Q-Park")) == "Q-Park car park"


# ---------------------------------------------------------------- category

def test_a_council_operator_gives_the_council_category():
    assert op.place_category(tags(operator="Sutton Council")) == op.COUNCIL_CATEGORY
    assert op.place_category(tags(operator="London Borough of Ealing")) == op.COUNCIL_CATEGORY
    assert op.place_category(
        tags(operator="City of London Corporation")) == op.COUNCIL_CATEGORY


def test_an_operator_type_of_government_gives_the_council_category():
    assert op.place_category(tags(**{"operator:type": "government"})) == op.COUNCIL_CATEGORY


def test_anything_else_gets_the_cautious_default():
    assert op.place_category(tags(operator="Q-Park")) == op.DEFAULT_CATEGORY
    assert op.place_category(tags()) == op.DEFAULT_CATEGORY
    assert op.DEFAULT_CATEGORY == "Private / operator car park"


def test_a_councillors_car_park_is_not_a_council_car_park_by_name_alone():
    assert op.place_category(tags(name="Council Offices Car Park")) == op.DEFAULT_CATEGORY


# ---------------------------------------------------------------- retained tags

def test_notes_retain_the_tags_and_claim_no_parking_answer():
    text = op.notes(tags(access="yes", capacity="40", fee="yes"), 1200.0, "")
    assert "access=yes" in text
    assert "capacity=40" in text
    assert "area=1200 m2" in text
    assert "not checked" in text.lower()
    for word in ("free", "anyone", "max stay"):
        assert word not in text.lower()


def test_notes_name_the_qualifier_when_one_was_used():
    assert "qualified by area" in op.notes(tags(), 900.0, "area")


def test_notes_survive_a_feature_with_no_tags():
    assert op.notes({"amenity": "parking"}, 0.0, "") == \
        "OSM amenity=parking, no further tags."


# ---------------------------------------------------------------- geometry

def test_a_node_keeps_its_own_point():
    point, precision = op.point_for(None, Point(-0.1, 51.5))
    assert (point.x, point.y) == (-0.1, 51.5)
    assert precision == "Node"


def test_a_simple_polygon_uses_its_centroid():
    square = Polygon([(0, 0), (0, 1), (1, 1), (1, 0)])
    point, precision = op.point_for(None, square)
    assert square.contains(point)
    assert precision == "Polygon centroid"


def test_a_polygon_whose_centroid_falls_outside_uses_an_interior_point():
    horseshoe = Polygon([(0, 0), (3, 0), (3, 3), (2, 3), (2, 1), (1, 1), (1, 3), (0, 3)])
    assert not horseshoe.contains(horseshoe.centroid)
    point, precision = op.point_for(None, horseshoe)
    assert horseshoe.contains(point)
    assert precision == "Polygon interior point"


# ---------------------------------------------------------------- street side

def test_street_side_and_kerb_parking_are_excluded():
    assert op.EXCLUDED_PARKING >= {"street_side", "lane", "on_street", "kerb", "shoulder"}


# ---------------------------------------------------------------- output files

def test_write_outputs_writes_three_files(tmp_path):
    """Regression: the run-path helper reserves directories, not files, so
    calling it on candidates.jsonl created a directory and the write failed."""
    candidate = {
        "source": "osm", "source_ref": "way/1",
        "row": {"Location Name": "Hill Street Car Park", "Borough": "Sutton",
                "Place Category": op.DEFAULT_CATEGORY, "Postcode": "",
                "Street Address": "", "Latitude": "51.36", "Longitude": "-0.14",
                "Notes": "OSM amenity=parking, no further tags."},
        "_review": {"access": "yes", "parking": "", "capacity": "",
                    "operator": "", "area_m2": "", "qualifier": "access tag"},
    }
    plan_path, csv_path = op.write_outputs([candidate], {"proposed": 1}, tmp_path / "out")
    assert plan_path.is_file()
    assert csv_path.is_file()
    assert (tmp_path / "out" / "counts.json").is_file()
    line = json.loads(plan_path.read_text(encoding="utf-8").strip())
    assert "_review" not in line
    assert line["source_ref"] == "way/1"


# ---------------------------------------------------------------- borough names

def test_a_borough_takes_the_sheets_own_spelling():
    """OSM calls it "London Borough of Barnet". The sheet's Borough column says
    "Barnet", and a mismatch splits every per-borough count in two."""
    assert op.borough_name("London Borough of Barnet") == "Barnet"
    assert op.borough_name("Royal Borough of Kingston upon Thames") == "Kingston upon Thames"
    assert op.borough_name("City of Westminster") == "Westminster"
    assert op.borough_name("London Borough of Barking and Dagenham") == "Barking and Dagenham"


def test_the_city_of_london_keeps_its_name():
    assert op.borough_name("City of London") == "City of London"


def test_an_unknown_or_blank_borough_passes_through():
    assert op.borough_name("") == ""
    assert op.borough_name(None) == ""
    assert op.borough_name("Elsewhere") == "Elsewhere"


def test_a_public_operator_type_is_not_a_council():
    """operator:type=public means a public company in OSM, not a council."""
    assert op.place_category(tags(**{"operator:type": "public"})) == op.DEFAULT_CATEGORY
    assert op.place_category(tags(**{"operator:type": "government"})) == op.COUNCIL_CATEGORY
