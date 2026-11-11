"""Tests for the read-only discovery count (discovery module)."""
from pathlib import Path

import pytest

from ferro_parking import discovery as d
from ferro_parking import osm_match
from ferro_parking import policy_fill

FIX = Path(__file__).parent / "fixtures"
CATEGORIES = d.load_categories()


def row(place_id, name, **kw):
    r = {"Place ID": place_id, "Location Name": name, "Brand": "",
         "Place Category": "", "Type (as captured)": "", "Latitude": "", "Longitude": ""}
    r.update(kw)
    return r


# ---- category classification: OSM side -------------------------------------
@pytest.mark.parametrize("tags,expected", [
    ({"shop": "supermarket"}, "supermarket"),
    ({"shop": "convenience"}, "convenience_store"),
    ({"amenity": "parking"}, "car_park"),
    ({"railway": "station"}, "station"),
    ({"public_transport": "station"}, "station"),
    ({"tourism": "hotel"}, "hotel"),
    ({"amenity": "cinema"}, "cinema"),
    ({"amenity": "bicycle_parking"}, None),   # not a tracked category
])
def test_classify_osm(tags, expected):
    assert d.classify_osm(tags, CATEGORIES) == expected


# ---- category classification: sheet side ------------------------------------
def test_sheet_place_category_wins_over_type_text():
    r = row("PP-1", "Lidl Kingston", **{"Place Category": "Supermarket - large format",
                                         "Type (as captured)": "Hotel"})
    assert d.classify_sheet_row(r, CATEGORIES) == "supermarket"


def test_small_format_brand_reroutes_to_convenience_store():
    r = row("PP-2", "Iceland Romford", **{"Type (as captured)": "Retail / Supermarket"})
    assert d.classify_sheet_row(r, CATEGORIES) == "convenience_store"


def test_generic_supermarket_text_without_small_format_brand():
    r = row("PP-3", "Morrisons Ealing", **{"Type (as captured)": "Retail / Supermarket"})
    assert d.classify_sheet_row(r, CATEGORIES) == "supermarket"


@pytest.mark.parametrize("name", [
    "Tesco Express", "Sainsbury's Local", "Tesco Metro", "Little Waitrose",
    "Simply Food", "Co-op Food", "The Co-operative Food", "Cooperative Food",
])
def test_small_format_brand_names_all_reroute_to_convenience_store(name):
    # "Co-op" and "Co-operative" normalise to different word pairs ("co
    # op" vs "co operative"; osm_match.norm() turns a hyphen into a
    # space), so both need their own entry in sheet_small_format_brands,
    # not just one covering the other.
    r = row("PP-4", name, **{"Type (as captured)": "Retail / Supermarket"})
    assert d.classify_sheet_row(r, CATEGORIES) == "convenience_store"


def test_brand_key_three_word_fallback_limits_mands_simply_food():
    # Known, pre-existing limitation, not fixed here: with no Brand
    # column and no Type (as captured) parenthetical, brand_key keeps
    # only the first two words of Location Name, so a three-word name
    # loses its last word before it ever reaches sheet_small_format_brands.
    # "M&S Simply Food" sees its config entry go unmatched; the shorter
    # "Simply Food" (tested above) and "M&S" with a Brand column value
    # both still work.
    r = row("PP-5", "M&S Simply Food", **{"Type (as captured)": "Retail / Supermarket"})
    assert d.classify_sheet_row(r, CATEGORIES) == "supermarket"


def test_station_car_park_is_a_car_park_not_a_station():
    r = row("PP-4", "Barkingside Station Car Park (TfL)",
            **{"Type (as captured)": "Station Car Park (TfL)"})
    assert d.classify_sheet_row(r, CATEGORIES) == "car_park"


def test_no_keyword_hit_falls_back_to_other():
    r = row("PP-5", "Pets at Home Croydon", **{"Type (as captured)": "Retail (Pets at Home)"})
    assert d.classify_sheet_row(r, CATEGORIES) == "other"


def test_public_car_park_is_not_a_pub():
    """'pub' must not match inside 'public' (substring, not whole word)."""
    r = row("PP-6", "Ealing Council public car park", **{"Type (as captured)": "Public Car Park (Council)"})
    assert d.classify_sheet_row(r, CATEGORIES) == "car_park"


def test_fuel_station_is_not_a_railway_station():
    """petrol_station must win over the more generic 'station' keyword that
    'Fuel station (Esso)' also contains."""
    r = row("PP-7", "Esso Hanger Lane", **{"Type (as captured)": "Fuel station (Esso)"})
    assert d.classify_sheet_row(r, CATEGORIES) == "petrol_station"
    r2 = row("PP-8", "Shell Brixton", **{"Type (as captured)": "Petrol Station (Shell)"})
    assert d.classify_sheet_row(r2, CATEGORIES) == "petrol_station"


def test_discovery_and_policy_fill_share_one_whole_word_helper():
    """The 'pub in Public Car Park' fix lives in osm_match.contains_word;
    discovery.py and policy_fill.py both call that one function, not a
    copy of their own."""
    assert d.contains_word is osm_match.contains_word
    assert policy_fill._contains_word is osm_match.contains_word
    assert osm_match.contains_word("public car park council", "pub") is False
    assert osm_match.contains_word("ealing council pub", "pub") is True


# ---- borough boundaries: City of London is not a borough, admin_level=6 ----
def test_city_of_london_counts_as_a_borough_boundary():
    assert d.is_borough_boundary({"boundary": "administrative", "admin_level": "8",
                                   "name": "Camden"}) is True
    assert d.is_borough_boundary({"boundary": "administrative", "admin_level": "6",
                                   "designation": "sui_generis", "name": "City of London"}) is True


def test_neighbouring_county_does_not_count_as_a_borough():
    """admin_level=6 alone (Surrey, Kent...) must not count: only the City
    of London's specific sui_generis designation does."""
    assert d.is_borough_boundary({"boundary": "administrative", "admin_level": "6",
                                   "name": "Surrey"}) is False


def test_borough_boundary_without_a_name_never_counts():
    assert d.is_borough_boundary({"boundary": "administrative", "admin_level": "6",
                                   "designation": "sui_generis", "name": ""}) is False


# ---- access split -------------------------------------------------------------
@pytest.mark.parametrize("access,group", [
    ("customers", "customers"), ("destination", "customers"),
    ("yes", "public"), ("public", "public"),
    ("private", "private"), ("no", "private"),
    ("residents", "residents"), ("permit", "residents"),
    ("", "unknown"), ("delivery", "unknown"),
])
def test_access_group(access, group):
    assert d.access_group({"access": access}) == group


# ---- match groups and radius overrides --------------------------------------
def test_grocery_group_merges_supermarket_and_convenience():
    groups = d.build_match_groups(CATEGORIES)
    grocery = next(g for g in groups if "supermarket" in g)
    assert set(grocery) == {"supermarket", "convenience_store"}
    singleton_groups = [g for g in groups if g != list(grocery)]
    assert ["car_park"] in singleton_groups
    assert ["hotel"] in singleton_groups


@pytest.mark.parametrize("group,radius", [
    (["supermarket", "convenience_store"], 150),   # supermarket's override wins
    (["diy_store"], 150), (["retail_park"], 150), (["hospital"], 150), (["station"], 150),
    (["car_park"], 100), (["hotel"], 100), (["convenience_store"], 100),
])
def test_group_radius_m(group, radius):
    assert d.group_radius_m(group) == radius


def test_radius_override_lets_150m_match_where_100m_fails():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    feat = {"tags": {"name": "M&S Simply Food"}, "geom": to_m(Point(-0.3300, 51.4400))}
    far_row = row("PP-10", "M&S Simply Food Clapham", Brand="M&S",
                  Latitude="51.44110", Longitude="-0.33001")   # ~122 m away
    points = [d.row_point_m(far_row)]
    assert d.match_category([feat], [far_row], points, radius_m=100) == ({}, set())
    feature_to_row, matched_rows = d.match_category([feat], [far_row], points, radius_m=150)
    assert feature_to_row == {0: 0}
    assert matched_rows == {0}


# ---- car park widened pool and unnamed-car-park phase 2 ----------------------
def test_is_car_park_row_widens_the_match_pool_beyond_classify_sheet_row():
    """A row with no Type or Place Category text falls to 'other' under
    classify_sheet_row, but its Location Name says it is a car park, so
    osm_match.is_car_park_row (not classify_sheet_row) decides who is in
    the car_park matching pool."""
    r = row("PP-11", "Mystery NCP Car Park")
    assert d.classify_sheet_row(r, CATEGORIES) == "other"
    assert osm_match.is_car_park_row(r) is True


def test_match_unnamed_car_parks_distance_method():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    r = row("PP-12", "Mystery NCP Car Park", Latitude="51.75000", Longitude="-0.40000")
    points = [d.row_point_m(r)]
    unnamed = [{"tags": {}, "geom": to_m(Point(-0.40004, 51.75004))}]   # a few metres away
    row_to_match, matched_rows = d.match_unnamed_car_parks([r], points, unnamed)
    assert matched_rows == {0}
    _feat, method = row_to_match[0]
    assert method == "distance"


def test_match_unnamed_car_parks_polygon_method():
    from shapely.geometry import Polygon
    from ferro_parking.osm_match import to_m
    r = row("PP-13", "Riverside Car Park Entrance", Latitude="51.76000", Longitude="-0.41000")
    points = [d.row_point_m(r)]
    square = Polygon([(-0.4110, 51.7590), (-0.4090, 51.7590), (-0.4090, 51.7610), (-0.4110, 51.7610)])
    unnamed = [{"tags": {}, "geom": to_m(square)}]
    row_to_match, matched_rows = d.match_unnamed_car_parks([r], points, unnamed)
    assert matched_rows == {0}
    _feat, method = row_to_match[0]
    assert method == "polygon"


def test_match_unnamed_car_parks_beyond_edge_threshold_no_match():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    r = row("PP-14", "Somewhere Car Park", Latitude="51.75000", Longitude="-0.40000")
    points = [d.row_point_m(r)]
    # 100 m away: within the 150 m search radius but past the 50 m edge threshold
    unnamed = [{"tags": {}, "geom": to_m(Point(-0.40000, 51.7509))}]
    row_to_match, matched_rows = d.match_unnamed_car_parks([r], points, unnamed)
    assert row_to_match == {}
    assert matched_rows == set()


# ---- borough diagnostics and tranche 1 ---------------------------------------
def test_nearest_borough_for_a_point_outside_every_boundary():
    from shapely.geometry import Polygon
    from ferro_parking.osm_match import to_m
    boroughs = [{"name": "Test Borough", "geom": to_m(Polygon([(0, 0), (0, 1), (1, 1), (1, 0)]))}]
    far_point = to_m(Polygon([(5, 5), (5, 6), (6, 6), (6, 5)]).centroid)
    assert d.nearest_borough(boroughs, far_point) == "Test Borough"
    assert d.nearest_borough([], far_point) == ""


@pytest.mark.parametrize("category,access,expected", [
    ("supermarket", "", True), ("hospital", "", True), ("petrol_station", "", True),
    ("station", "", True), ("retail_park", "", True),
    ("car_park", "customers", True), ("car_park", "yes", True), ("car_park", "", True),
    ("car_park", "private", False), ("car_park", "residents", False),
    ("gym", "", False), ("other", "", False),
])
def test_is_tranche1(category, access, expected):
    assert d.is_tranche1({"Category": category, "Access": access}) is expected


# ---- matching: one sheet row per OSM feature, and vice versa ----------------
def test_one_to_one_match_on_duplicate_sheet_rows():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    feat = {"tags": {"name": "Iceland Romford"}, "geom": to_m(Point(-0.2000, 51.6000))}
    rows = [row("PP-2", "Iceland Romford", Latitude="51.60002", Longitude="-0.20002"),
            row("PP-3", "Iceland Romford", Latitude="51.60003", Longitude="-0.20003")]
    points = [d.row_point_m(r) for r in rows]
    feature_to_row, matched_rows = d.match_category([feat], rows, points, radius_m=100)
    assert feature_to_row == {0: 0}      # the closer duplicate wins
    assert matched_rows == {0}           # exactly one row matched, not both


def test_no_match_beyond_radius():
    from shapely.geometry import Point
    from ferro_parking.osm_match import to_m
    feat = {"tags": {"name": "Lidl"}, "geom": to_m(Point(-0.3000, 51.4000))}
    far_row = row("PP-9", "Lidl Elsewhere", Brand="Lidl", Latitude="51.9000", Longitude="-0.9000")
    points = [d.row_point_m(far_row)]
    feature_to_row, matched_rows = d.match_category([feat], [far_row], points, radius_m=100)
    assert feature_to_row == {}
    assert matched_rows == set()


# ---- end to end on the fixture file ------------------------------------------
def test_end_to_end_summary(tmp_path):
    result = d.run(str(FIX / "discovery_sample.osm"), str(FIX / "discovery_sample_rows.csv"),
                    tmp_path / "results", categories=CATEGORIES)
    by_cat = {r["Category"]: r for r in result["summary_rows"]}

    # Lidl, Aldi, M&S Simply Food (named); M&S matches the sheet's
    # convenience_store-classified row (cross-category grocery match).
    assert by_cat["supermarket"]["OSM Count"] == 3
    # Sheet-side: only the Lidl Kingston row is natively "supermarket" and
    # matched (the M&S Simply Food feature matches a convenience_store row
    # instead, so it counts there, not here).
    assert by_cat["supermarket"]["Matched"] == 1
    # Feature-side: of the 3 named supermarket features, only Aldi found no
    # sheet counterpart at all (Lidl and M&S both did, M&S via cross-category).
    assert by_cat["supermarket"]["OSM Missing From Sheet"] == 1   # Aldi
    assert by_cat["supermarket"]["Sheet Rows With No OSM Match"] == 1  # Asda Nowhere

    # Iceland Romford node; two duplicate Iceland rows plus the cross-matched
    # M&S Simply Food row all land here on the sheet side.
    assert by_cat["convenience_store"]["OSM Count"] == 1
    assert by_cat["convenience_store"]["Sheet Count"] == 3
    assert by_cat["convenience_store"]["Matched"] == 2        # Iceland + M&S (cross-category)
    assert by_cat["convenience_store"]["Sheet Rows With No OSM Match"] == 1  # the duplicate row

    # Tesco Hackney / Vinci / Resident Bay (named, all still missing); the two
    # widened-pool sheet rows (Mystery NCP, Riverside) both land via phase 2.
    assert by_cat["car_park"]["OSM Count"] == 3
    assert by_cat["car_park"]["OSM Missing From Sheet"] == 3
    assert by_cat["car_park"]["Sheet Count"] == 2
    assert by_cat["car_park"]["Matched"] == 2
    assert by_cat["car_park"]["Sheet Rows With No OSM Match"] == 0

    assert result["car_park_match_methods"] == {"name": 0, "distance": 1, "polygon": 1}

    # the unnamed supermarket node, plus the two unnamed car parks used by
    # phase 2, are tracked but never counted as missing
    assert len(result["unnamed_rows"]) == 3
    missing_names = {r["Name"] for r in result["missing_rows"]}
    assert "" not in missing_names

    assert result["car_park_access_split"] == {"customers": 1, "public": 1, "residents": 1}

    aldi = next(r for r in result["missing_rows"] if r["Name"] == "Aldi Kingston")
    assert aldi["Borough"] == "Royal Borough of Kingston upon Thames"
    assert aldi["Postcode"] == "KT1 2BB"

    # the three missing car park features sit outside the one borough boundary
    # the fixture defines; nearest_borough still names it as the closest one
    assert result["no_borough_count"] == 3
    assert result["no_borough_causes"][0] == ("Royal Borough of Kingston upon Thames", 3)

    tranche1_names = {r["Name"] for r in result["tranche1_rows"]}
    assert tranche1_names == {"Aldi Kingston", "Tesco Hackney Car Park", "Vinci Car Park"}

    for path in ("discovery_summary.csv", "missing_places.csv",
                 "unnamed_features.csv", "sheet_unmatched.csv"):
        assert (tmp_path / "results" / path).exists()


def test_other_category_never_counted_as_missing(tmp_path):
    result = d.run(str(FIX / "discovery_sample.osm"), str(FIX / "discovery_sample_rows.csv"),
                    tmp_path / "results", categories=CATEGORIES)
    assert "other" not in [r["Category"] for r in result["summary_rows"]]
