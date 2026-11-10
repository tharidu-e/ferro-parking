"""Regression tests: every bug fixed on 2 Nov 2026 has a test here."""
import csv
from pathlib import Path

import pytest

from ferro_parking import osm_match as m

FIX = Path(__file__).parent / "fixtures"


def row(name, typ="", **kw):
    r = {"Location Name": name, "Type (as captured)": typ}
    r.update(kw)
    return r


# ---- max stay parsing -------------------------------------------------------
@pytest.mark.parametrize("raw,mins", [
    ("120", "120"),            # bare number = minutes (Waitrose Nine Elms)
    ("90 minutes", "90"),
    ("2 hours", "120"),
    ("1 hour", "60"),
    ("no", "No limit"),
    ("", ""),
])
def test_parse_maxstay(raw, mins):
    assert m.parse_maxstay(raw) == mins


# ---- brand matching ---------------------------------------------------------
def test_place_word_is_not_a_brand_match():
    r = row("Sainsbury's Cheam Local", "Retail / Supermarket")
    hit, _ = m.name_score(r, {"name": "Cheam", "operator": "Sutton Council"}, m.brand_key(r))
    assert hit is False


@pytest.mark.parametrize("name,typ,tags", [
    ("Sainsbury's Nine Elms – customer car park", "Retail / Supermarket", {"name": "Sainsbury's"}),
    ("Tesco Hackney Morning Lane Superstore – customer car park", "Retail / Supermarket", {"name": "Tesco Customer Car Park"}),
    ("Co-op Surbiton - Ellerton Road", "Supermarket (Co-op)", {"brand": "Co-op", "name": "Co-op Food"}),
])
def test_real_brand_matches(name, typ, tags):
    r = row(name, typ)
    hit, _ = m.name_score(r, tags, m.brand_key(r))
    assert hit is True


# ---- car park ownership -----------------------------------------------------
def test_other_brands_car_park_rejected():
    m.CHAIN_KEYS = {"tesco", "iceland"}
    r = row("Iceland Hackney (337 Mare Street) – customer car park", "Supermarket (Iceland)")
    assert "another brand" in m.other_owner(r, {"name": "Tesco Customer Car Park", "access": "customers"}, m.brand_key(r))


def test_public_car_park_nearby_rejected():
    m.CHAIN_KEYS = set()
    r = row("PureGym London Canary Wharf", "Gym")
    why = m.other_owner(r, {"name": "West India Quay Car Park", "access": "yes", "operator": "Vinci"}, m.brand_key(r))
    assert "public car park" in why


def test_operator_run_customer_car_park_kept():
    m.CHAIN_KEYS = {"sainsburys"}
    r = row("Sainsbury's Hornsey – customer car park", "Retail / Supermarket")
    assert m.other_owner(r, {"access": "customers", "operator": "Euro Car Parks"}, m.brand_key(r)) == ""


# ---- row types --------------------------------------------------------------
@pytest.mark.parametrize("typ,name,expected", [
    ("Retail / Supermarket", "Sainsbury's Pimlico – customer car park", False),
    ("Supermarket (Iceland)", "Iceland Lower Marsh – customer car park", False),
    ("Leisure Centre", "Lee Valley Ice Centre – car park", True),
    ("Public Car Park (Council)", "Ealing Council customer parking", True),
    ("Private Car Park (operator – NCP)", "NCP London Bridge", True),
])
def test_car_park_row(typ, name, expected):
    assert m.is_car_park_row(row(name, typ)) is expected


def test_chain_keys_from_repeated_names():
    rows = [row(n) for n in ["PureGym London Acton", "The Gym London Bow", "Nuffield Health Fulham"]] * 5
    assert {"puregym", "the gym", "nuffield"} <= m.build_chain_keys(rows)


# ---- suggestions follow rules R1, R4 ---------------------------------------
def test_osm_max_stay_goes_to_notes_r4():
    s = m.suggest({"access": "customers", "fee": "no", "maxstay": "120"}, None)
    assert s["Max Stay (mins)"] == "Not published"
    assert "120" in s["OSM Notes"]
    assert s["Tariff Type"] == "Not published"
    assert s["Source Tier"] == "OpenStreetMap"
    assert s["Can Park? (Yes/No/Conditional)"] == "Conditional"   # OSM never gives Yes


# ---- suggestions follow rule R7 (Free needs site-specific evidence) --------
def test_fee_no_on_customers_only_car_park_gives_unknown_r7():
    s = m.suggest({"access": "customers", "fee": "no"}, None)
    assert s["Cost Type"] == "Unknown"


def test_fee_no_on_destination_car_park_gives_unknown_r7():
    s = m.suggest({"access": "destination", "fee": "no"}, None)
    assert s["Cost Type"] == "Unknown"


def test_fee_no_on_public_car_park_gives_unknown_r7():
    s = m.suggest({"access": "yes", "fee": "no"}, None)
    assert s["Cost Type"] == "Unknown"
    assert "R7" in s["OSM Notes"]


def test_fee_no_on_untagged_car_park_gives_unknown_r7():
    s = m.suggest({"fee": "no"}, None)
    assert s["Cost Type"] == "Unknown"
    assert "R7" in s["OSM Notes"]


# ---- end to end on the sample fixture ----------------------------------------
def test_end_to_end_routes(tmp_path):
    out = tmp_path / "out.csv"
    m.main([str(FIX / "sample.osm"), str(FIX / "sample_rows.csv"), "--out", str(out)])
    got = {r["Location Name"] or "(blank)": (r["Route"][:1], r) for r in csv.DictReader(open(out))}
    assert got["Co-op Surbiton - Ellerton Road"][0] == "C"
    assert got["Co-op London - Strand"][0] == "B"
    assert got["Queen Street Car Park"][0] == "A"          # Autopay car park -> operator page
    assert got["Tesco Nowhere"][0] == "E"                  # disused:shop -> possible closure
    assert got["Battersea Park Station"][0] == "A"         # station, not the park
    assert got["(blank)"][0] == "S"
    coop = got["Co-op Surbiton - Ellerton Road"][1]
    assert coop["Suggested Who Can Park"] == "Customers only"
    assert coop["Suggested Operator"] == "Not published"   # R3: Co-op runs its own lot
    assert coop["Suggested Max Stay (mins)"] == "Not published"  # R4
