"""Ferro PP: capture extract. Turns a row's captured text into a structured
record of the same shape capture_fill.py expects in extracted.jsonl, by
pattern matching rather than a model read of each row.

This covers the patterns found by reading Westminster's captured text:
operator car parks with real banded tariffs, operator car parks with an
unclear tariff but real hours, explicit "no parking" denials under rule R9,
customer car parks that may be chain-wide policy, and the large remainder
left for Grok. A record this module cannot support with real site text is
always left_for_grok, never guessed.
"""
import json
import re
from pathlib import Path

from . import capture_fill
from . import rules as rules_mod

NOT_APPLICABLE = {
    "who_can_park": "Not applicable", "cost_type": "Not applicable",
    "tariff_type": "Not applicable", "tariff_detail": "Not applicable",
    "max_stay_mins": "Not applicable", "hours_osm_format": "Not applicable",
    "hours_basis": "Not applicable", "control_type": "Not applicable",
    "operator": "Not applicable", "pcn_gbp": "Not applicable",
}

WEEKEND_MARKERS = ("weekend", "saturday", "sat ", "evening", "night", "bank holiday", "motorcycle")

# "(Sat/Sun only)" restricts a band to the weekend and must be dropped from
# a weekday tariff; "(not Sun)" only excludes one day and must be kept, so
# this requires "only" next to the day/weekend word, not just the word.
WEEKEND_ONLY_RE = re.compile(
    r"(sat(urday)?|sun(day)?|weekend|bank hol\w*)\W{0,15}only|only\W{0,15}(sat(urday)?|sun(day)?|weekend|bank hol\w*)",
    re.I)

CUSTOMER_CAR_PARK_RE = re.compile(r"customer car park", re.I)
NEGATED_CUSTOMER_CAR_PARK_RE = re.compile(r"no\s+customer car park", re.I)
MAYBE_GENERIC_RE = re.compile(r"may be generic|VERIFY.{0,40}generic", re.I)

# A capture column carrying one of these alongside a matched R9 phrase is
# hedging ("NO OFFICIAL INFO ... verify on site"), not quoting the source's
# own denial, so it must not count as an explicit statement under rule R9.
R9_HEDGE_MARKERS = ("no official info", "verify")

# "N/A on site (no car park listed)" and "No car park listed. Captured via
# browser ...": the capture agent's own shorthand for an absent listing,
# whether parenthesized or written as its own sentence, not a quote of the
# source denying parking. Any "no ... listed" disqualifies the whole column
# under rule R9, the same as a hedge marker.
R9_SHORTHAND_LISTED_RE = re.compile(r"\bno\b[^.;()]{0,60}\blisted\b", re.I)

# Some station rows carry a boilerplate "Checked SWR station page
# southwesternrailway.com/.../<slug> <date>: car parking not available at
# this station. (operator <code>)" sentence that was run for every station
# regardless of who actually operates it. When Station operator is not
# South Western Railway, that sentence is not a statement about this
# station and must be stripped before R9 is evaluated; a real statement
# from the station's own operator, if present elsewhere in the text, is
# unaffected.
STATION_OPERATOR_RE = re.compile(r"Station operator:\s*([^.]+)\.")
SWR_BOILERPLATE_RE = re.compile(
    r"Checked SWR station page southwesternrailway\.com\S*\s*\d{1,2}/\d{1,2}/\d{4}:"
    r"\s*car parking not available at this station\.(?:\s*\([^)]*\))?",
    re.I)


def strip_mismatched_swr_citation(text):
    operator_match = STATION_OPERATOR_RE.search(text)
    if not operator_match:
        return text
    operator = operator_match.group(1).strip().lower()
    if "south western" in operator or "swr" in operator:
        return text
    return SWR_BOILERPLATE_RE.sub("", text)

MAX_STAY_RE = re.compile(r"(\d+)\s*(hour|hr|hrs|hours|min|mins|minute|minutes)\b", re.I)


def parse_max_stay_minutes(text):
    """A number of hours/minutes stated in Max Stay (as captured), e.g.
    "24 hours" or "90 mins". None when the column has no such number."""
    match = MAX_STAY_RE.search(text or "")
    if not match:
        return None
    n = int(match.group(1))
    return n * 60 if match.group(2).lower().startswith("h") else n


def record(place_id, fields=None, leave_for_grok=False, reason=""):
    return {"place_id": place_id, "leave_for_grok": leave_for_grok, "reason": reason,
            "fields": fields or {}}


def field(value, scope, quote):
    return {"value": value, "scope": scope, "quote": quote}


def no_parking_record(place_id, quote):
    fields = {"can_park": field("No", "site", quote)}
    for name, value in NOT_APPLICABLE.items():
        fields[name] = field(value, "site", quote)
    return record(place_id, fields)


def matches_r9(text):
    """True only if some sentence has an explicit no-parking phrase AND
    that same sentence is not conditioned on "during" ("No car park access
    during events", Lee Valley Hockey and Tennis Centre): a denial that
    only holds during a specific circumstance is not a general denial, and
    the venue may still have real, generally usable spaces."""
    low = (text or "").lower()
    for sentence in re.split(r"(?<=[.;])\s+", low):
        if "during" in sentence:
            continue
        if any(re.search(r"\b" + re.escape(p) + r"\b", sentence) for p in capture_fill.NO_PARKING_PHRASES):
            return True
    return False


def find_r9_quote(captured):
    for col in capture_fill.CAPTURE_COLS:
        text = strip_mismatched_swr_citation(captured.get(col, ""))
        if (matches_r9(text) and not any(h in text.lower() for h in R9_HEDGE_MARKERS)
                and not R9_SHORTHAND_LISTED_RE.search(text)):
            return text
    return None


def parse_bands(charges_text):
    """"1 hour £10.00", "Up to 1 hour £4.50", or the abbreviated "1h £5.15"
    all count, each giving one (hours, price) band. Only the weekday rate:
    cut the string at the first weekend/night/motorcycle marker, wherever
    it falls, since a semicolon does not always separate the two (some
    charges strings run weekday and weekend rates together in one sentence).

    A per-minute tariff ("£0.10 per 15 minutes", the Royal Parks pattern)
    has no "<N>h ... £<price>" shape, so it returns no bands here and stays
    left for Grok rather than being misread as hourly.

    Stops at the first hour that is not greater than the one before it: a
    car park with two unrelated schedules in the same sentence (a standard
    tariff next to an emission-based or early-bird one) restarts its band
    count from a small number, and that restart point is not a real next
    band of the first schedule.

    A band immediately tagged "(Sat/Sun only)" is skipped even when it sits
    before the weekend cutoff: that cutoff only catches a weekend rate that
    starts a new clause, not one tag per band in an otherwise weekday list.
    A band tagged "(not Sun)" is kept: that excludes one day, it does not
    restrict the band to the weekend the way "only" does."""
    cutoff = len(charges_text)
    low = charges_text.lower()
    for marker in WEEKEND_MARKERS:
        idx = low.find(marker)
        if idx != -1:
            cutoff = min(cutoff, idx)
    weekday_text = charges_text[:cutoff]
    # The trailing-context group is a lookahead so it does not consume
    # characters (consuming them would make finditer skip past the next
    # band's own match), and stops at the next ";" so it never reads into
    # the next band's own tag.
    matches = re.finditer(r"(\d+)\s*h(?:ours?)?\b.{0,3}£\s?(\d+(?:\.\d{2})?)(?=([^;]{0,40}))",
                           weekday_text, re.I)
    bands = []
    prev_hours = 0
    for m in matches:
        h, p, trailing = m.group(1), m.group(2), m.group(3).lower()
        if WEEKEND_ONLY_RE.search(trailing):
            continue
        hours = int(h)
        if hours <= prev_hours:
            break
        bands.append((hours, float(p)))
        prev_hours = hours
    return bands


def tariff_detail_from_bands(bands):
    parts = []
    prev = 0
    for hours, price in bands:
        parts.append(f"{prev}-{hours} hrs £{price:.2f}")
        prev = hours
    return "; ".join(parts)


def is_real_tariff(charges_text):
    low = charges_text.lower()
    if any(w in low for w in ("unclear", "not shown", "not stated", "no official info")):
        return False
    return len(parse_bands(charges_text)) >= 2


OPERATOR_RE = re.compile(r"(NCP|Q-Park|Euro Car Parks|CitiPark|APCOA[\w ()]*)")
ECP_RE = re.compile(r"\bECP\b")


# "see NCP row 496" and "Distinct from row 689 (Sainsbury's Kings Mall
# customer car park)" both describe a DIFFERENT database row for a
# different physical car park, not this row. Whatever they say about that
# other row (an operator name, "customer car park") is not a statement
# about this one, so the whole sentence is stripped from every captured
# column before any pattern match runs.
CROSS_REFERENCE_SENTENCE_RE = re.compile(
    r"\b(?:see|distinct from|same car park as|same location as)\b[^.]*?\brow\b\s*\d+[^.]*\.?", re.I)


def strip_cross_references(text):
    return CROSS_REFERENCE_SENTENCE_RE.sub("", text or "")


def operator_name_from(type_text, notes):
    """Type (as captured) often names the operator plainly ("Euro Car
    Parks"); Notes sometimes only gives the abbreviation ("ECP"). Check
    Type (as captured) first, since it is the less ambiguous of the two."""
    match = OPERATOR_RE.search(type_text) or OPERATOR_RE.search(notes)
    if match:
        return match.group(1).strip()
    if ECP_RE.search(notes):
        return "Euro Car Parks"
    return "Not published"


def who_can_park_for_commercial(captured_text):
    return "Anyone (paid)"  # a named commercial car park operator: open to any paying driver


def extract_hours_osm(hours_text):
    """"24/7", "24 hours", or "24HR"/"24Hr" (no space) all count. A bare
    "00:00" timestamp does not: it is often a daily close time on a day
    that is not open round the clock, not proof of 24/7."""
    low = hours_text.lower()
    if "24 hour" in low or "24/7" in low or re.search(r"24\s*hr", low):
        return "24/7"
    return None


def customer_car_park_record(place_id, notes):
    scope = "chain" if MAYBE_GENERIC_RE.search(notes) else "site"
    fields = {
        "can_park": field("Conditional", scope, notes[:200]),
        "who_can_park": field("Customers only", scope, notes[:200]),
        "cost_type": field("Unknown", scope, notes[:200]),
        "tariff_type": field("Not published", scope, notes[:200]),
        "tariff_detail": field("Not published", scope, notes[:200]),
        "max_stay_mins": field("Not published", scope, notes[:200]),
        "hours_osm_format": field("Not published", scope, notes[:200]),
        "hours_basis": field("Not published", scope, notes[:200]),
        "control_type": field("Not published", scope, notes[:200]),
        "operator": field("Not published", scope, notes[:200]),
        "pcn_gbp": field("Not published", scope, notes[:200]),
    }
    return record(place_id, fields)


HOTEL_WHO_CAN_PARK = rules_mod.load_rules().r1_category_defaults["hotel"]

# "Chargeable ... amount UNCLEAR (official page says "additional fee", no
# tariff)" is a fixed capture phrase meaning the page confirms a charge and
# withholds the price, so it is checked before the generic "unclear" skip
# below, which exists for pages that genuinely contradict themselves.
HOTEL_CHARGEABLE_AMOUNT_UNCLEAR_RE = re.compile(r"chargeable\b.{0,40}\bamount unclear", re.I)
HOTEL_FREE_FOR_GUESTS_RE = re.compile(r"free for hotel guests", re.I)
HOTEL_PRICE_PER_UNIT_RE = re.compile(
    r"(?:£|GBP\s?)(\d+(?:\.\d{1,2})?)\s*per\s*(night|day|24 hours)", re.I)


def hotel_record(place_id, charges, cost_type, tariff_type, tariff_detail):
    # Who Can Park is always the hotel R1 default (Guests only), a
    # restricted group, so Can Park? is Conditional, the same as
    # customer_car_park_record's "Customers only" case, never Yes (Yes is
    # for unconditional access, Who Can Park Anyone / Anyone (paid)).
    quote = charges[:200]
    fields = {
        "can_park": field("Conditional", "site", quote),
        "who_can_park": field(HOTEL_WHO_CAN_PARK, "site", quote),
        "cost_type": field(cost_type, "site", quote),
        "tariff_type": field(tariff_type, "site", quote),
        "tariff_detail": field(tariff_detail, "site", quote),
    }
    for name in ("max_stay_mins", "hours_osm_format", "hours_basis", "control_type",
                 "operator", "pcn_gbp"):
        fields[name] = field("Not published", "site", quote)
    return record(place_id, fields)


def hotel_charges_record(place_id, type_text, charges):
    """A hotel row whose Charges (as published) states this hotel's own
    parking terms: free for its guests, chargeable at a stated nightly or
    daily price, or chargeable with the price withheld. None for any other
    row, including a hotel whose page is unclear or contradicts itself."""
    if type_text.strip().lower() != "hotel":
        return None
    if HOTEL_CHARGEABLE_AMOUNT_UNCLEAR_RE.search(charges):
        return hotel_record(place_id, charges, "Paid", "Not published", "Not published")
    if "unclear" in charges.lower():
        return None
    price = HOTEL_PRICE_PER_UNIT_RE.search(charges)
    if price:
        unit = price.group(2).lower()
        tariff_type = "Flat rate per night" if unit == "night" else "Flat rate per 24 hours"
        return hotel_record(place_id, charges, "Paid", tariff_type,
                             f"£{float(price.group(1)):.2f} per {unit}")
    if HOTEL_FREE_FOR_GUESTS_RE.search(charges):
        return hotel_record(place_id, charges, "Free", "Free (time limit not published)", "Free")
    return None


def classify(sr, osm_row):
    place_id = sr["Place ID"]
    captured = {c: strip_cross_references(sr.get(c, "")) for c in capture_fill.CAPTURE_COLS}
    type_text = captured.get("Type (as captured)", "")
    notes = captured.get("Notes", "")

    r9_quote = find_r9_quote(captured)
    if r9_quote:
        return no_parking_record(place_id, r9_quote.strip())

    if CUSTOMER_CAR_PARK_RE.search(notes) and not NEGATED_CUSTOMER_CAR_PARK_RE.search(notes):
        return customer_car_park_record(place_id, notes)

    is_operator_car_park = any(k in type_text for k in
                                ("NCP", "Q-Park", "Euro Car Parks", "CitiPark", "Station Car Park"))
    charges = captured.get("Charges (as published)", "")
    hours_raw = captured.get("Hours (as captured)", "")
    enforcement = captured.get("Enforcement Details", "")

    if is_operator_car_park and is_real_tariff(charges):
        bands = parse_bands(charges)
        operator = operator_name_from(type_text, notes)
        control = "ANPR (Automatic Number Plate Recognition) camera" if "anpr" in enforcement.lower() else "Not published"
        hours_osm = extract_hours_osm(hours_raw) or "Not published"
        max_stay_captured = captured.get("Max Stay (as captured)", "")
        max_stay_minutes = parse_max_stay_minutes(max_stay_captured)
        max_stay = (field(str(max_stay_minutes), "site", max_stay_captured[:150])
                    if max_stay_minutes is not None else field("No limit", "site", charges[:200]))
        fields = {
            "can_park": field("Yes", "site", charges[:200]),
            "who_can_park": field(who_can_park_for_commercial(charges + " " + notes), "site", charges[:200]),
            "cost_type": field("Paid", "site", charges[:200]),
            "tariff_type": field("Banded by stay length", "site", charges[:200]),
            "tariff_detail": field(tariff_detail_from_bands(bands), "site", charges[:200]),
            "max_stay_mins": max_stay,
            "hours_osm_format": field(hours_osm, "site", hours_raw[:120]),
            "hours_basis": field("Car park hours" if hours_osm != "Not published" else "Not published",
                                  "site", hours_raw[:120]),
            "control_type": field(control, "site", enforcement[:150]),
            "operator": field(operator, "site", notes[:150]),
            "pcn_gbp": field("Not published", "site", enforcement[:150]),
        }
        return record(place_id, fields)

    tariff_unclear = any(p in charges.lower() for p in
                          ("unclear", "prebook", "tariff not shown", "not stated", "not shown"))
    # "('Pay on the day' heading shown with no rows)" names a UI label the
    # page displays, not a confirmation that the car park is actually paid;
    # that shape always sits next to "unclear" in the same charges text.
    confirmed_paid = ("public pay car park" in notes.lower()
                       or ("pay on the day" in charges.lower() and "unclear" not in charges.lower()))
    hours_known = hours_raw and "no official info" not in hours_raw.lower()
    if is_operator_car_park and tariff_unclear and (hours_known or confirmed_paid):
        operator = operator_name_from(type_text, notes)
        hours_osm = (extract_hours_osm(hours_raw) or "Not published") if hours_known else "Not published"
        can_park = "Yes" if confirmed_paid else "Conditional"
        who_can_park = "Anyone (paid)" if confirmed_paid else "Unknown"
        quote = notes[:200] if confirmed_paid else charges[:200]
        fields = {
            "can_park": field(can_park, "site", quote),
            "who_can_park": field(who_can_park, "site", quote),
            "cost_type": field("Paid" if confirmed_paid else "Unknown", "site", charges[:200]),
            "tariff_type": field("Not published", "site", charges[:200]),
            "tariff_detail": field("Not published", "site", charges[:200]),
            "max_stay_mins": field("Not published", "site", charges[:200]),
            "hours_osm_format": field(hours_osm, "site", hours_raw[:120]),
            "hours_basis": field("Car park hours" if hours_osm != "Not published" else "Not published",
                                  "site", hours_raw[:120]),
            "control_type": field("Not published", "site", enforcement[:150]),
            "operator": field(operator, "site", notes[:150]),
            "pcn_gbp": field("Not published", "site", enforcement[:150]),
        }
        return record(place_id, fields)

    hotel = hotel_charges_record(place_id, type_text, charges)
    if hotel:
        return hotel

    return record(place_id, leave_for_grok=True,
                   reason="Captured text has no site-specific parking fact beyond NO OFFICIAL INFO / N/A")


def build_records(candidates):
    """`candidates` is a list of (sheet_row, osm_row) pairs, as returned by
    capture_fill.candidate_rows. Returns one classify() record per pair."""
    return [classify(sr, osm_row) for sr, osm_row in candidates]


def write_extracted(candidates, out_path):
    records = build_records(candidates)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return records


def main(argv=None):
    import argparse
    import csv

    from . import fill, sheets

    ap = argparse.ArgumentParser()
    ap.add_argument("--borough", required=True)
    ap.add_argument("--osm-results", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    service = sheets.get_service()
    headers, sheet_rows = sheets.read_tab(service)
    osm_path = args.osm_results or fill.latest_osm_results()
    with open(osm_path, newline="", encoding="utf-8") as f:
        osm_rows = list(csv.DictReader(f))

    candidates = capture_fill.candidate_rows(sheet_rows, osm_rows, args.borough)
    print(f"{len(candidates)} candidates")

    from datetime import date
    out = Path(args.out) if args.out else \
        Path("data/runs") / date.today().isoformat() / "capture" / args.borough / "extracted.jsonl"
    records = write_extracted(candidates, out)
    print(f"Wrote {len(records)} records to {out}")

    n_grok = sum(1 for r in records if r["leave_for_grok"])
    print(f"Classified as leave_for_grok: {n_grok}")
    print(f"Classified as fillable: {len(records) - n_grok}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
