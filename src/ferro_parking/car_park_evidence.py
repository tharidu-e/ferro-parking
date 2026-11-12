"""Positive evidence that a venue has a car park.

Phase 4 showed that the category default cannot fire on nothing: a chain policy
row claims a car park exists, and a brand name alone does not establish that.
This module answers one question for one row, from evidence already on disk.

A row has evidence when any of these holds:

1. A cached official page for this place states parking. The pages table holds
   the fetch, and the text on disk holds the words.
2. An OpenStreetMap amenity=parking feature lies within 50 m and either is
   tagged access=customers or matches the venue by name, brand or operator.
   That match was already made by the match command, so this reads its
   osm_results.csv rather than the PBF again.
3. Type (as captured) or the Location Name says car park.

No network, no PBF. A row the OSM match run never covered simply has no OSM
evidence, which the report says out loud.
"""
import re
from pathlib import Path

from .fill import PLACE_ID, SOURCE_URLS
from .osm_match import contains_word, norm

# 50 m, as the brief sets it. osm_match's own adjacency radius is its own
# concern and is not reused here.
NEARBY_M = 50.0

# A car park the match run linked to this place, rather than any feature that
# happens to be nearby. "Nearby Car Park (not this place's)" is excluded by
# reading only these two link kinds.
LINKED = ("Adjacent to place", "Name/operator matches brand")

PARKING_PHRASES = (
    "car park", "car parks", "customer parking", "customer car park",
    "parking is available", "parking available", "free parking", "paid parking",
    "on-site parking", "onsite parking", "parking on site", "spaces available",
    "pay and display", "blue badge", "disabled parking", "parking spaces",
)

# A page that only denies parking is evidence about parking, but not evidence
# that a car park exists, so these phrases never count.
DENIAL_PHRASES = (
    "no car park", "no customer parking", "no parking", "parking not available",
    "there is no parking", "we have no parking", "no on-site parking",
    # A station page reads "No accessible parking spaces", which says a car
    # park has none of those, not that a car park exists.
    "no accessible parking", "no parking spaces", "no dedicated parking",
    "0 accessible parking",
)

EVIDENCE_PAGE = "a cached page states parking"
EVIDENCE_OSM_CUSTOMERS = "an OpenStreetMap customers car park within 50 m"
EVIDENCE_OSM_MATCH = "an OpenStreetMap car park within 50 m matching the venue"
EVIDENCE_NAME = "the name or Type says car park"


def _sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def page_parking_quotes(text):
    """Sentences in a cached page that state parking. A sentence that only
    denies parking is left out."""
    quotes = []
    for sentence in _sentences(text):
        low = norm(sentence)
        if any(phrase in low for phrase in DENIAL_PHRASES):
            continue
        if any(phrase in low for phrase in PARKING_PHRASES):
            quotes.append(sentence)
    return quotes


def cached_page_evidence(conn, row):
    """(quote, url) from a cached page for one of this row's source URLs, or
    (None, None). Reads the pages table and the text file it points at."""
    urls = [part.strip() for part in re.split(r";|\s+", row.get(SOURCE_URLS, "") or "")
            if part.strip().startswith("http")]
    if not urls:
        return None, None
    placeholders = ", ".join("?" * len(urls))
    cursor = conn.execute(
        f"SELECT url, text_path, http_status FROM pages WHERE url IN ({placeholders})", urls)
    for page in cursor:
        if page["http_status"] and int(page["http_status"]) >= 400:
            continue
        path = Path(page["text_path"] or "")
        if not path.is_file():
            continue
        quotes = page_parking_quotes(path.read_text(encoding="utf-8", errors="replace"))
        if quotes:
            return quotes[0], page["url"]
    return None, None


def _distance(osm_row):
    try:
        return float(osm_row.get("Car Park Distance (m)", ""))
    except (TypeError, ValueError):
        return None


def _tags(raw):
    tags = {}
    for part in (raw or "").split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            tags[key.strip()] = value.strip()
    return tags


def osm_evidence(row, osm_row):
    """Which OSM test a nearby mapped car park passes, or None."""
    distance = _distance(osm_row)
    if distance is None or distance > NEARBY_M:
        return None
    tags = _tags(osm_row.get("OSM Car Park Raw Tags", "") or osm_row.get("OSM Raw Tags", ""))
    if tags.get("access") == "customers":
        return EVIDENCE_OSM_CUSTOMERS
    if osm_row.get("Car Park Link", "") in LINKED:
        return EVIDENCE_OSM_MATCH
    park_name = norm(osm_row.get("OSM Car Park Name", ""))
    for column in ("Location Name", "Brand", "Operator"):
        value = norm(row.get(column, ""))
        if value and park_name and (value in park_name or park_name in value):
            return EVIDENCE_OSM_MATCH
    return None


def name_evidence(row):
    text = norm(f"{row.get('Type (as captured)', '')} {row.get('Location Name', '')}")
    if any(contains_word(text, word) for word in ("car park", "car parks", "parking")):
        return EVIDENCE_NAME
    return None


def evidence_for(row, osm_row=None, conn=None):
    """(reason, quote, url). reason is None when the row has no evidence."""
    reason = name_evidence(row)
    if reason:
        return reason, "", ""
    if conn is not None:
        quote, url = cached_page_evidence(conn, row)
        if quote:
            return EVIDENCE_PAGE, quote, url
    reason = osm_evidence(row, osm_row or {})
    if reason:
        return reason, "", osm_row.get("OSM Car Park", "") if osm_row else ""
    return None, "", ""


def has_evidence(row, osm_row=None, conn=None):
    return evidence_for(row, osm_row, conn)[0] is not None
