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


def record(place_id, fields=None, leave_for_grok=False, reason="", notes_append=None, flags=None):
    """notes_append holds sentences capture_fill appends to the row's Notes
    (never replaces it) via page_fill's existing "_notes" hook. flags holds
    Review Flag text the same way, via page_fill's "_flags" hook, which
    also sets Flag Status to Open."""
    return {"place_id": place_id, "leave_for_grok": leave_for_grok, "reason": reason,
            "fields": fields or {}, "notes_append": notes_append or [], "flags": flags or []}


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

HOTEL_TYPE_RE = re.compile(r"hotel", re.I)
PRICE_RE = re.compile(r"(?:£|GBP\s?)(\d+(?:\.\d{1,2})?)")
# Written as codepoints: no file in this project carries an en or em dash.
EN_DASH, EM_DASH = chr(0x2013), chr(0x2014)
DASHES_RE = re.compile(f"[{EN_DASH}{EM_DASH}]")

# "free for hotel guests", "Free for Travelodge guests only", "Limited free
# hotel parking", and a bare "Free" in Charges whose Notes say "Free parking
# available" all state the same fact. A bare "Free" on its own does not: it
# needs the "guests" or "parking" word within the same clause, which is what
# the gap limit here requires.
HOTEL_FREE_RE = re.compile(r"\bfree\b[^.;]{0,30}?\b(guests?|parking)\b", re.I)

# "No free parking; any paid parking not stated" (the Best Western rows)
# carries the literal "free parking" and states the opposite of it. "2 EV
# charging points ... free to use (daily parking charge applies)" (Park
# Plaza Westminster Bridge) is the same trap from the other direction: the
# free thing nearby is the EV charging, not the parking, and the same
# sentence says a parking charge applies.
NO_FREE_RE = re.compile(r"\bno\s+free\b|\bnot\s+free\b|\bcharge applies\b|\bcharges apply\b", re.I)

# A confirmed charge, whatever the figure. "any paid parking not stated" is
# not one: it reports the absence of a tariff, not that parking costs money.
HOTEL_CHARGEABLE_RE = re.compile(
    r"\bchargeable\b|\bparking is charged\b|\bthere is a charge\b|\bprice varies\b", re.I)

NON_GUEST_RE = re.compile(r"non-?residents?|non-?guests?", re.I)
VALET_RE = re.compile(r"\bvalet\b", re.I)

# "night" sits inside "overnight stay" and both mean the same tariff, so the
# earliest hit wins and no separate ordering is needed between them.
STAY_UNITS = (("overnight stay", "night"), ("night", "night"), ("24 hours", "24 hours"),
              ("24 hrs", "24 hours"), ("day", "day"))
UNIT_BEFORE_PRICE_RE = re.compile(r"\b(daily|nightly)\b", re.I)

HOUR_WORD = r"h(?:ours?|rs?)?"
_MONEY = r"(?:£|GBP\s?)(\d+(?:\.\d{1,2})?)"
# "4-5h GBP 16.50": an explicit lower AND upper bound. Distinct from a bare
# "4h"/"up to 4h"/"for 4 hours" shape, which only ever states the upper
# bound, because only a stated lower bound can ever disagree with where the
# previous band actually left off, which is the one thing worth flagging.
EXPLICIT_RANGE_RE = re.compile(rf"(\d+)\s*[-{EN_DASH}{EM_DASH}]\s*(\d+)\s*{HOUR_WORD}\s*{_MONEY}", re.I)
UP_TO_HOURS_RE = re.compile(rf"up to\s*(\d+)\s*{HOUR_WORD}\s*{_MONEY}", re.I)
DAILY_BAND_RE = re.compile(rf"\bdaily\b\s*{_MONEY}", re.I)
FOR_N_HOURS_RE = re.compile(rf"{_MONEY}\s*for\s*(\d+)\s*{HOUR_WORD}", re.I)
PER_N_HOURS_RE = re.compile(rf"{_MONEY}\s*(?:per\s*\w+\s*)?per\s*(\d+)\s*{HOUR_WORD}", re.I)
PER_HOUR_UP_TO_RE = re.compile(rf"{_MONEY}\s*per\s*hour\s*up to\s*(\d+)\s*{HOUR_WORD}", re.I)
# "£5.00/hr", the slash-shorthand a non-resident clause states its own rate
# in, distinct from the "per"/"for" connector price_per_unit looks for.
SLASH_RATE_RE = re.compile(rf"{_MONEY}\s*/\s*(hr|hour|day|night)\b", re.I)
SLASH_UNIT_TO_TARIFF = {"hr": "Hourly rate", "hour": "Hourly rate",
                         "day": "Flat rate per 24 hours", "night": "Flat rate per night"}
SLASH_UNIT_WORD = {"hr": "hour", "hour": "hour", "day": "day", "night": "night"}


def _band_from_clause(clause):
    """(hours, price, lower_bound_or_None) for one clause naming a single
    duration band, or None if the clause names no duration at all. Only
    EXPLICIT_RANGE_RE's own lower bound is ever returned non-None: a bare
    "4h" / "up to 4h" / "for 4 hours" / "Daily" clause never claims where
    its own band starts, only where it ends."""
    m = EXPLICIT_RANGE_RE.search(clause)
    if m:
        return int(m.group(2)), float(m.group(3)), int(m.group(1))
    m = UP_TO_HOURS_RE.search(clause)
    if m:
        return int(m.group(1)), float(m.group(2)), None
    m = DAILY_BAND_RE.search(clause)
    if m:
        return 24, float(m.group(1)), None
    m = FOR_N_HOURS_RE.search(clause)
    if m:
        return int(m.group(2)), float(m.group(1)), None
    m = PER_N_HOURS_RE.search(clause)
    if m:
        return int(m.group(2)), float(m.group(1)), None
    return None


def hotel_bands(text):
    """(bands, leftover, gap_flags): bands is a [(lo, hi, price), ...] list
    ready for format_hotel_bands, ascending by hi. lo is the band's own
    stated lower bound if it had one, else wherever the previous band left
    off, so a real gap still shows in the displayed string, not just in
    gap_flags. leftover is the clauses that named no duration at all (a
    weekly rate, a motorcycle rate, a parenthetical qualifier) and so can
    never be a duration band. gap_flags names a real gap in the source's
    own numbers: an explicit "N-Mh" clause whose stated N does not match
    where the previous band actually ended. A bare "4h" or "for 4 hours"
    clause never triggers this, since it never claims a lower bound of its
    own."""
    raw, leftover = [], []
    # A "." splits clauses, but not a decimal point: "13.20" must survive.
    for clause in re.split(r";|(?<!\d)\.(?!\d)", text):
        clause = clause.strip()
        if not clause:
            continue
        expand = PER_HOUR_UP_TO_RE.search(clause)
        if expand:
            rate, cap = float(expand.group(1)), int(expand.group(2))
            raw.extend((h, round(rate * h, 2), None) for h in range(1, cap + 1))
            continue
        # A parenthetical qualifier ("(before pre-book discount)") can sit
        # right next to a band's own numbers in the same clause: pull it
        # out first, so the clause underneath it can still be read as a band.
        paren = re.search(r"\(([^)]+)\)", clause)
        qualifier = paren.group(1).strip() if paren else None
        clause_core = (clause[:paren.start()] + clause[paren.end():]).strip() if paren else clause
        band = _band_from_clause(clause_core)
        if band:
            raw.append(band)
            if qualifier:
                leftover.append(qualifier)
        else:
            leftover.append(clause)
    bands_sorted = sorted(set(raw), key=lambda t: t[0])
    # Two different clauses naming the same hour cap ("discount of £10 per
    # 24 hours" next to "prices start from £20 per 24 hours") are two
    # different products at the one duration, never two duration bands of
    # the same product: real bands always end at strictly increasing hours.
    hours_seen = [h for h, _, _ in bands_sorted]
    if len(set(hours_seen)) != len(hours_seen):
        return [], leftover, []
    bands, gap_flags, prev, seen_gaps = [], [], 0, set()
    for hours, price, lo in bands_sorted:
        if lo is not None and lo != prev and (prev, lo) not in seen_gaps:
            gap_flags.append(f"Source tariff has no {prev}-{lo} hr band")
            seen_gaps.add((prev, lo))
        # A band with its own stated lower bound keeps it in the display
        # even across a gap ("4-24 hrs", not "3-24 hrs" bridging the gap
        # the flag above already names); a bare upper-bound-only band still
        # reads as continuing from wherever the previous one left off.
        bands.append((lo if lo is not None else prev, hours, price))
        prev = hours
    return bands, leftover, gap_flags


def format_hotel_bands(bands):
    return "; ".join(f"{lo}-{hi} hrs £{price:.2f}" for lo, hi, price in bands)


def plain_dashes(text):
    """No en dash or em dash reaches a cell. Prose keeps a plain hyphen."""
    return DASHES_RE.sub("-", text or "")


def restate_leftover(text):
    """A band clause's leftover qualifier, restated for Notes. A dangling
    "before pre-book discount" (pulled out of its own parenthetical) reads
    as a sentence fragment on its own, so it gets a subject put back."""
    out = restate(text)
    if re.match(r"before\b", out, re.I):
        out = f"Prices {out}"
    return out


def restate(text):
    """A captured rate or band string rewritten for a cell: GBP to £, every
    price to two decimals, "2h" to "2 hours", "/day" to " per day", "&" to
    "and", and a dash range to "4 to 5 hours". Only rate strings go through
    this, where a dash always joins the two ends of a range. Prose keeps its
    dash as a hyphen via plain_dashes instead."""
    out = re.sub(r"^\s*valet\b[:,]?\s*", "", text.strip(), flags=re.I)
    out = re.sub(r"/\s*hr\b", " per hour", out, flags=re.I)
    out = re.sub(r"/\s*day\b", " per day", out, flags=re.I)
    out = re.sub(r"/\s*night\b", " per night", out, flags=re.I)
    out = PRICE_RE.sub(lambda m: f"£{float(m.group(1)):.2f}", out)
    out = re.sub(r"(\d)\s*h\b", r"\1 hours", out)
    out = re.sub(r"\bhrs?\b", "hours", out, flags=re.I)
    out = DASHES_RE.sub(" to ", out)
    return re.sub(r"\s{2,}", " ", out.replace("&", "and")).strip()


def price_per_unit(text):
    """(price, unit) for one single stated rate, or None.

    A £ or GBP price counts when a stay unit follows it within 40 characters
    and a "per" or "for" joins the two: "£15 per night", "£65 per vehicle
    per night", "£18.00 per overnight stay per car", "£20 for 24 hours". The
    connector requirement is what stops a bare price in prose being read as
    a rate. A unit named just before the price counts too ("Daily fee of
    £45"), which is the only shape where no connector exists to find.

    Callers must try the banded branch first: the last band of a banded
    tariff often reads "Daily GBP 33.00", which this would otherwise return
    as one flat daily rate for the whole car park."""
    matches = list(PRICE_RE.finditer(text or ""))
    for i, match in enumerate(matches):
        # Never read past the next price: "GBP 6 per hour; GBP 16 per
        # night" must not let the 6 borrow the 16's "night" unit just
        # because it falls inside an unbounded 40-character window.
        window_end = matches[i + 1].start() if i + 1 < len(matches) else match.end() + 40
        window = text[match.end():min(window_end, match.end() + 40)].lower()
        unit_at = None
        for phrase, unit in STAY_UNITS:
            idx = window.find(phrase)
            if idx != -1 and (unit_at is None or idx < unit_at[0]):
                unit_at = (idx, unit)
        if unit_at and re.search(r"\b(per|for)\b", window[:unit_at[0]]):
            return float(match.group(1)), unit_at[1]
        before = UNIT_BEFORE_PRICE_RE.search(text[max(0, match.start() - 25):match.start()])
        if before:
            return float(match.group(1)), "day" if before.group(1).lower() == "daily" else "night"
    return None


def valet_note(charges):
    """A valet detail belongs in Notes, never in Tariff Detail. A charges
    string that opens with "Valet" prices the valet service itself, so that
    is the only way to park there."""
    if re.match(r"\s*valet\b", charges, re.I):
        return "Valet only."
    parenthetical = re.search(r"\(([^)]*\bvalet\b[^)]*)\)", charges, re.I)
    if parenthetical:
        rest = ", ".join(p.strip() for p in parenthetical.group(1).split(",")
                          if "valet" not in p.lower())
        return f"Valet parking ({rest})." if rest else "Valet parking."
    return "Valet parking."


def _lower_first(text):
    return text[:1].lower() + text[1:] if text else text


def non_guest_record(place_id, charges):
    """A hotel row open to non-residents (anyone, paid) as well as guests,
    on two separate rate structures. The non-resident clause's own first
    rate is the real, usable tariff (Who Can Park is open to anyone, so
    this is the rate an actual non-guest driver pays); everything else in
    the charges string, the resident rate and any other non-resident band,
    is restated in Notes rather than lost."""
    clauses = [c.strip() for c in charges.split(";")]
    target_i = next((i for i, c in enumerate(clauses) if NON_GUEST_RE.search(c)), 0)
    target = clauses[target_i]
    sub_clauses = [s.strip() for s in target.split(",")]
    rate = SLASH_RATE_RE.search(sub_clauses[0]) or SLASH_RATE_RE.search(target)
    if not rate:
        return hotel_record(place_id, charges, "Paid", "Not published", "Not published",
                             can_park="Yes", who_can_park="Anyone (paid)",
                             notes_append=[sentence(restate(charges))])
    price, unit = float(rate.group(1)), rate.group(2).lower()
    tariff_type = SLASH_UNIT_TO_TARIFF[unit]
    detail = f"£{price:.2f} per {SLASH_UNIT_WORD[unit]}"
    leftover = sub_clauses[1:] + [c for i, c in enumerate(clauses) if i != target_i]
    notes = [_lower_first(restate(c)) if i > 0 else restate(c) for i, c in enumerate(leftover)]
    return hotel_record(place_id, charges, "Paid", tariff_type, detail,
                         can_park="Yes", who_can_park="Anyone (paid)",
                         notes_append=[sentence("; ".join(notes))] if notes else [])


def hotel_record(place_id, quote, cost_type, tariff_type, tariff_detail,
                  can_park="Conditional", who_can_park=HOTEL_WHO_CAN_PARK, notes_append=None,
                  flags=None):
    """A hotel car park is for the hotel's own guests under rule R1 and is
    Conditional on being one, unless the row's own text opens it to anyone.
    Nothing in a hotel row's captured text has ever given hours, a max stay,
    an operator or a PCN amount, so those stay Not published."""
    evidence = plain_dashes(quote)[:200]
    fields = {
        "can_park": field(can_park, "site", evidence),
        "who_can_park": field(who_can_park, "site", evidence),
        "cost_type": field(cost_type, "site", evidence),
        "tariff_type": field(tariff_type, "site", evidence),
        "tariff_detail": field(tariff_detail, "site", evidence),
    }
    for name in ("max_stay_mins", "hours_osm_format", "hours_basis", "control_type",
                 "operator", "pcn_gbp"):
        fields[name] = field("Not published", "site", evidence)
    return record(place_id, fields, notes_append=notes_append, flags=flags)


def sentence(text):
    return f"{plain_dashes(text).strip().rstrip('.')}."


def hotel_charges_record(place_id, charges, notes):
    """One hotel row's Charges (as published) and Notes as a record, or None
    to leave the row for Grok. None is the answer whenever the text states
    both free and chargeable, says "unclear", or names no parking fact at
    all: a guess about a price or about who may park costs a driver money."""
    text = f"{charges} {notes}"
    is_free = bool(HOTEL_FREE_RE.search(text)) and not NO_FREE_RE.search(text)
    is_chargeable = bool(HOTEL_CHARGEABLE_RE.search(text))

    # Premier Inn London Docklands: the page states free parking and a
    # charge for the same car park. Neither half can be trusted over the other.
    if is_free and is_chargeable:
        return None
    # "Chargeable - amount UNCLEAR (... no tariff)" confirms the charge and
    # only withholds the figure, unlike a row whose own page contradicts
    # itself, so this is checked before the blanket "unclear" skip below.
    if is_chargeable and "unclear" in charges.lower():
        return hotel_record(place_id, charges, "Paid", "Not published", "Not published",
                             notes_append=[sentence(charges)])
    if "unclear" in charges.lower():
        return None

    if is_free:
        # "Limited" is a capacity note and a permit is an access condition.
        # Neither withholds Free, and neither fits one of the eleven fields.
        condition = [sentence(charges)] if "(" in charges else []
        return hotel_record(place_id, charges, "Free", "Free (time limit not published)",
                             "Free", notes_append=condition)

    # Novotel London West: two populations on two rate structures. The
    # non-resident (anyone, paid) rate is the real, usable tariff; the
    # resident (hotel guest) rate and any off-peak variant are restated in
    # Notes rather than lost, since neither population's full structure
    # fits one of the eleven fields.
    if NON_GUEST_RE.search(text):
        return non_guest_record(place_id, charges)

    valet = [valet_note(charges)] if VALET_RE.search(charges) else None
    # A second "Weekend:" schedule is parsed as its own independent set of
    # bands (its own hours start at 0 again), kept out of Tariff Detail
    # (which only ever carries one schedule) and restated in Notes instead.
    weekday_text, weekend_text = re.split(r"(?i)\bweekend\s*:", charges, maxsplit=1) \
        if re.search(r"(?i)\bweekend\s*:", charges) else (charges, "")
    bands, leftover, gap_flags = hotel_bands(weekday_text)
    if len(bands) >= 2:
        detail = format_hotel_bands(bands)
        notes = (valet or []) + [restate_leftover(c) for c in leftover]
        if weekend_text:
            weekend_bands, weekend_leftover, weekend_gap_flags = hotel_bands(weekend_text)
            if len(weekend_bands) >= 2:
                notes.append("Weekend: " + format_hotel_bands(weekend_bands))
            notes += [restate_leftover(c) for c in weekend_leftover]
            gap_flags = list(dict.fromkeys(gap_flags + weekend_gap_flags))
        return hotel_record(place_id, charges, "Paid", "Banded by stay length", detail,
                             notes_append=notes, flags=gap_flags)

    rate = price_per_unit(charges)
    if rate:
        price, unit = rate
        tariff_type = "Flat rate per night" if unit == "night" else "Flat rate per 24 hours"
        # A second clause next to the rate carries a condition the flat-rate
        # template drops ("payable at lobby car park stations"), so it is
        # restated in Notes rather than lost.
        conditions = [sentence(charges)] if ";" in charges else []
        return hotel_record(place_id, charges, "Paid", tariff_type,
                             f"£{price:.2f} per {'24 hours' if unit == 'day' else unit}", notes_append=(valet or []) + conditions)

    # The May Fair: Charges says nothing, and Notes is the only column that
    # shows a car park exists at all. Valet existing is not evidence it
    # costs money, so Cost Type stays Unknown rather than becoming Paid.
    if VALET_RE.search(notes) and not PRICE_RE.search(charges):
        return hotel_record(place_id, notes, "Unknown", "Not published", "Not published")

    if is_chargeable:
        return hotel_record(place_id, charges, "Paid", "Not published", "Not published",
                             notes_append=[sentence(charges)])
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
                    if max_stay_minutes is not None else field("No limit" if re.fullmatch(r"(?:There is )?(?:no (?:maximum stay|time limit|limit)|unlimited (?:stay|parking))\.?", max_stay_captured.strip(), re.I) else "Not published", "site", max_stay_captured[:200]))
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

    if HOTEL_TYPE_RE.search(type_text):
        hotel = hotel_charges_record(place_id, charges, notes)
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
    with out_path.open("x") as stream:
        stream.write("\n".join(json.dumps(r) for r in records) + "\n")
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

    from .run_paths import new_run_dir
    out = Path(args.out) if args.out else new_run_dir(Path("capture") / args.borough) / "extracted.jsonl"
    records = write_extracted(candidates, out)
    print(f"Wrote {len(records)} records to {out}")

    n_grok = sum(1 for r in records if r["leave_for_grok"])
    print(f"Classified as leave_for_grok: {n_grok}")
    print(f"Classified as fillable: {len(records) - n_grok}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
