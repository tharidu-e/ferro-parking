"""Tests for tranche 1 prep (discovery tranche selection)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from ferro_parking import tranche1 as t1
from ferro_parking.osm_match import to_m

FIX = Path(__file__).parent / "fixtures"


def feat(kind, osm_id, tags, geom, category="supermarket", ts=None):
    geom_m = to_m(geom)
    return {"type": kind, "id": osm_id, "tags": tags, "category": category,
            "geom": geom_m, "ll": geom.representative_point(), "ts": ts}


# ---- hospital junk ------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [
    ("A&E Department", True), ("Oncology Ward", True), ("Maternity Wing", True),
    ("Renal Unit", True), ("Travel Clinic", True), ("Centre for Cancer Care", True),
    ("Royal Free Hospital", False),
])
def test_hospital_junk_by_name(name, expected):
    f = feat("node", 1, {"name": name}, Point(-0.1, 51.5), category="hospital")
    junk, reason = t1.hospital_is_junk(f, [f])
    assert junk is expected
    if expected:
        assert reason


def test_hospital_inside_another_hospital_polygon_is_junk_even_with_a_clean_name():
    main_site = feat("way", 10, {"name": "Royal Free Hospital"},
                      Polygon([(-0.11, 51.49), (-0.09, 51.49), (-0.09, 51.51), (-0.11, 51.51)]),
                      category="hospital")
    inner = feat("node", 11, {"name": "Phoenix Centre"}, Point(-0.10, 51.50), category="hospital")
    junk, reason = t1.hospital_is_junk(inner, [main_site, inner])
    assert junk is True
    assert "Royal Free Hospital" in reason


def test_hospital_outside_any_polygon_with_a_clean_name_is_kept():
    main_site = feat("way", 10, {"name": "Royal Free Hospital"},
                      Polygon([(-0.11, 51.49), (-0.09, 51.49), (-0.09, 51.51), (-0.11, 51.51)]),
                      category="hospital")
    elsewhere = feat("node", 12, {"name": "St George's Hospital"}, Point(-1.0, 51.5), category="hospital")
    junk, reason = t1.hospital_is_junk(elsewhere, [main_site, elsewhere])
    assert junk is False
    assert reason == ""


# ---- station junk and dedupe --------------------------------------------------
@pytest.mark.parametrize("tags,expected", [
    ({"railway": "station"}, False), ({"railway": "halt"}, False),
    ({"station": "subway"}, False), ({"public_transport": "station", "station": "train"}, False),
    ({"public_transport": "station"}, True),             # a bus or boat stop, no rail signal
    ({"amenity": "ferry_terminal", "public_transport": "station"}, True),
])
def test_station_is_junk(tags, expected):
    f = feat("node", 1, tags, Point(-0.1, 51.5), category="station")
    junk, _reason = t1.station_is_junk(f)
    assert junk is expected


def test_duplicate_stations_keep_the_railway_tagged_one():
    rail = feat("node", 1, {"name": "Clapham Junction", "railway": "station"},
                Point(-0.17, 51.46), category="station")
    bus = feat("node", 2, {"name": "Clapham Junction", "public_transport": "station",
                           "station": "train"},
               Point(-0.1701, 51.4601), category="station")   # a few metres away
    excluded = t1.dedupe_stations([rail, bus])
    assert excluded == {id(bus): f"duplicate station, kept node/{rail['id']}"}


def test_stations_over_400m_apart_are_not_duplicates():
    a = feat("node", 1, {"name": "Same Name", "railway": "station"}, Point(-0.17, 51.46), category="station")
    b = feat("node", 2, {"name": "Same Name", "railway": "station"}, Point(-0.20, 51.50), category="station")
    assert t1.dedupe_stations([a, b]) == {}


def test_different_named_stations_are_not_duplicates():
    a = feat("node", 1, {"name": "Angel", "railway": "station"}, Point(-0.1058, 51.5322), category="station")
    b = feat("node", 2, {"name": "Old Street", "railway": "station"}, Point(-0.0877, 51.5265), category="station")
    assert t1.dedupe_stations([a, b]) == {}


# ---- supermarket junk ---------------------------------------------------------
@pytest.mark.parametrize("tags,expected", [
    ({"name": "Lucky Phone Repairs", "shop": "supermarket"}, True),
    ({"name": "Cloud 9 Vape", "shop": "supermarket"}, True),
    ({"name": "City Mobile", "shop": "supermarket"}, True),
    ({"name": "Toni & Guy Barber", "shop": "supermarket"}, True),
    ({"name": "Blow Dry Salon", "shop": "supermarket"}, True),
    ({"name": "Tesco Express", "shop": "supermarket;mobile_phone"}, True),
    ({"name": "Tesco Express", "shop": "supermarket"}, False),
    ({"name": "Londis", "shop": "convenience;supermarket"}, False),
])
def test_supermarket_is_junk(tags, expected):
    f = feat("node", 1, tags, Point(-0.1, 51.5), category="supermarket")
    junk, _reason = t1.supermarket_is_junk(f)
    assert junk is expected


# ---- car park on a hotel site --------------------------------------------------
def test_car_park_within_50m_of_a_hotel_node_is_flagged():
    hotel = feat("node", 1, {"name": "Premier Inn"}, Point(-0.1, 51.5), category="hotel")
    park = feat("node", 2, {}, Point(-0.10040, 51.50000), category="car_park")   # ~28 m away
    assert t1.car_park_is_hotel_site(park, [hotel]) is True


def test_car_park_far_from_any_hotel_is_not_flagged():
    hotel = feat("node", 1, {"name": "Premier Inn"}, Point(-0.1, 51.5), category="hotel")
    park = feat("node", 2, {}, Point(-0.2, 51.6), category="car_park")
    assert t1.car_park_is_hotel_site(park, [hotel]) is False


def test_car_park_inside_a_hotel_polygon_is_flagged():
    hotel = feat("way", 1, {"name": "Premier Inn"},
                 Polygon([(-0.101, 51.499), (-0.099, 51.499), (-0.099, 51.501), (-0.101, 51.501)]),
                 category="hotel")
    park = feat("node", 2, {}, Point(-0.100, 51.500), category="car_park")
    assert t1.car_park_is_hotel_site(park, [hotel]) is True


# ---- confidence ----------------------------------------------------------------
NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


def test_confidence_high_for_brand():
    f = feat("node", 1, {"brand": "Tesco"}, Point(-0.1, 51.5), category="supermarket")
    assert t1.confidence(f, now=NOW) == "High"


def test_confidence_high_for_station():
    f = feat("node", 1, {}, Point(-0.1, 51.5), category="station")
    assert t1.confidence(f, now=NOW) == "High"


def test_confidence_high_for_hospital_with_emergency():
    f = feat("node", 1, {"emergency": "yes"}, Point(-0.1, 51.5), category="hospital")
    assert t1.confidence(f, now=NOW) == "High"


def test_confidence_not_high_for_hospital_without_emergency_or_healthcare_tag():
    f = feat("node", 1, {}, Point(-0.1, 51.5), category="hospital")
    assert t1.confidence(f, now=NOW) != "High"


def test_confidence_medium_for_website():
    f = feat("node", 1, {"website": "https://example.com"}, Point(-0.1, 51.5), category="supermarket")
    assert t1.confidence(f, now=NOW) == "Medium"


def test_confidence_medium_for_recent_check_date():
    f = feat("node", 1, {"check_date": "2025-06-01"}, Point(-0.1, 51.5), category="supermarket")
    assert t1.confidence(f, now=NOW) == "Medium"


def test_confidence_medium_for_recent_edit_timestamp():
    f = feat("node", 1, {}, Point(-0.1, 51.5), category="supermarket", ts=NOW - timedelta(days=100))
    assert t1.confidence(f, now=NOW) == "Medium"


def test_confidence_low_for_an_old_untouched_node():
    f = feat("node", 1, {}, Point(-0.1, 51.5), category="supermarket", ts=NOW - timedelta(days=365 * 5))
    assert t1.confidence(f, now=NOW) == "Low"


def test_confidence_low_for_an_old_check_date():
    f = feat("node", 1, {"check_date": "2015-01-01"}, Point(-0.1, 51.5), category="supermarket")
    assert t1.confidence(f, now=NOW) == "Low"


# ---- the car-park access defensive filter (unreachable via the real pipeline,
# since discovery.collect's is_tranche1 already excludes these; tested directly
# to prove the guard is actually there) -------------------------------------------
def test_filter_tranche1_drops_private_or_resident_car_parks_defensively():
    private_park = feat("node", 1, {"access": "private"}, Point(-0.1, 51.5), category="car_park")
    resident_park = feat("node", 2, {"access": "residents"}, Point(-0.2, 51.6), category="car_park")
    public_park = feat("node", 3, {"access": "public"}, Point(-0.3, 51.7), category="car_park")
    kept, excluded = t1.filter_tranche1([private_park, resident_park, public_park], {})
    assert kept == [public_park]
    assert {r["OSM Id"] for r in excluded} == {1, 2}


# ---- end to end ------------------------------------------------------------------
def test_end_to_end_run(tmp_path):
    result = t1.run(str(FIX / "tranche1_sample.osm"), str(FIX / "discovery_sample_rows.csv"), tmp_path)

    reasons = {r["Reason"] for r in result["excluded_rows"]}
    excluded_names = {r["Name"] for r in result["excluded_rows"]}
    assert "Oncology Unit" in excluded_names     # name keyword
    assert "Vape Corner" in excluded_names       # supermarket junk keyword
    assert "River Bus Pier" in excluded_names    # station junk: no rail signal
    assert any("duplicate station" in r for r in reasons)

    ready_names = {r["Name"]: r for r in result["ready_rows"]}
    assert "Tesco Express Battersea" in ready_names
    assert ready_names["Tesco Express Battersea"]["Confidence"] == "High"   # brand tag
    assert "Vauxhall" in ready_names                                         # railway=station kept
    assert ready_names["Vauxhall"]["Confidence"] == "High"

    car_park_notes = {r["Name"]: r["Notes"] for r in result["ready_rows"] if r["Category"] == "car_park"}
    assert car_park_notes.get("Premier Inn Car Park") == "Hotel car park (not public)"

    for path in ("tranche1_excluded.csv", "tranche1_ready.csv"):
        assert (tmp_path / path).exists()
