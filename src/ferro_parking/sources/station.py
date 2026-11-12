"""Fetcher A: National Rail station pages, read for parking spaces only.

The station page publishes a short parking block:

    Station parking
    No parking spaces
    4 accessible parking spaces

The rules this fetcher follows, and nothing more:

- A stated number of parking spaces sets Can Park? Yes, and the count goes in
  Notes with its quote.
- The exact statement "No parking spaces" sets Can Park? No, with that quote.
- A statement about accessible spaces alone writes nothing. A station with 4
  accessible bays and no parking total has not told us it has a car park.
- Operator is written only when the page names one.
- Tariff, Free and Max Stay are never written from this page. The page does
  not carry them, and rule R7 would refuse them anyway.

A row that writes nothing stays unanswered, and the next route run sends it to
the bot.
"""
import re

from .. import page_fill
from ..osm_match import norm

CONFLICT_FLAG = "Station page says no parking but the row shows a car park: confirm"

BASE = "https://www.nationalrail.co.uk/stations/{slug}/"

# Words that belong to the sheet's own wording rather than the station name.
TRAILING_WORDS = ("station", "stations", "rail", "railway", "national rail",
                  "car park", "car parks", "carpark", "parking", "multi storey",
                  "multi-storey", "ncp", "apcoa", "overground", "underground",
                  "dlr", "tube")

SPACES = re.compile(r"\b(\d[\d,]*)\s+parking spaces\b", re.I)
NO_SPACES = re.compile(r"\bno parking spaces\b", re.I)
ACCESSIBLE = re.compile(r"\b(?:no|\d[\d,]*)\s+accessible parking spaces\b", re.I)
OPERATOR = re.compile(
    r"\b(?:car park|parking)\s+(?:is\s+)?(?:managed|operated|run)\s+by\s+([A-Z][\w&.' -]{2,40})")


def station_slug(name):
    """The National Rail slug for a station name, or "" when nothing is left.

    The sheet's names carry extra wording ("Brockley Station Car Park"), so the
    trailing words above are stripped. Anything in brackets goes too. The
    result is never guessed past that: a page that answers 404 is reported as
    unresolved."""
    text = re.sub(r"\(.*?\)", " ", name or "")
    # The sheet writes the entrance after a dash: "Brockley Station - via
    # Coulgate Street". Only the station name goes in the slug. The en and em
    # dash are both in the live data.
    text = re.split(r"\s[-\u2013\u2014]\s|,", text)[0]
    text = norm(text).replace(" and ", " ")
    words = text.split()
    changed = True
    while changed and words:
        changed = False
        for phrase in sorted(TRAILING_WORDS, key=lambda value: -len(value.split())):
            parts = phrase.split()
            if len(words) >= len(parts) and words[-len(parts):] == parts:
                del words[-len(parts):]
                changed = True
                break
    return "-".join(words)


def accessible_only(text):
    """True when the page's only parking numbers are about accessible bays."""
    return bool(ACCESSIBLE.search(text)) and not SPACES.search(text) and not NO_SPACES.search(text)


def _sentence_around(text, match):
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return text[start:end if end != -1 else len(text)].strip()


def denial_conflict(row):
    row = row or {}
    return (bool(str(row.get("Charges (as published)", "")).strip())
            or str(row.get("Tariff Detail", "")).strip() not in ("", "Not published")
            or row.get("_mapped_car_park_50m", False))


class StationFetcher:
    """key is the routing stage name, because the station stage is chosen by
    category rather than by a source key."""

    key = "station"
    source_tier = "Operator / council site"

    def __init__(self, lookup=None):
        self.lookup = lookup

    def branch_url(self, row):
        from .station_list import load
        lookup = self.lookup if self.lookup is not None else load()
        key = station_slug(row.get("Location Name", ""))
        return (lookup or {}).get(key, "")

    def quotes(self, text, row=None):
        found = []
        match = SPACES.search(text)
        if match:
            found.append(_sentence_around(text, match))
        match = NO_SPACES.search(text)
        if match:
            found.append(_sentence_around(text, match))
        return found

    def values(self, text, row=None):
        """(new_values, notes, quote). new_values is empty when the page says
        nothing this fetcher may act on."""
        if accessible_only(text):
            return {}, [], ""

        spaces = SPACES.search(text)
        if spaces and int(spaces.group(1).replace(",", "")) > 0:
            quote = _sentence_around(text, spaces)
            values = {
                "Can Park? (Yes/No/Conditional)": "Yes",
                "Brand": "National Rail",
                "Evidence Detail (what the source shows)": quote,
                "Source Tier": self.source_tier,
                "Specificity": "Site-specific",
                "Evidence Type": "Official site: partial info",
                "Rules Stated": "Yes",
                "Prices Stated": "No",
                "Evidence Level": "Verified",
                "Decision Reason": "Route A: National Rail station page, visible text",
            }
            notes = [f"National Rail station data: {quote}"]
            operator = OPERATOR.search(text)
            if operator:
                values["Operator"] = operator.group(1).strip().rstrip(".")
            return values, notes, quote

        denial = NO_SPACES.search(text)
        if denial:
            quote = _sentence_around(text, denial)
            if denial_conflict(row):
                return {
                    "Review Flag": CONFLICT_FLAG,
                    "Flag Status": "Open",
                    "Decision Reason": "Route A: National Rail denial conflicts with existing car park evidence; confirm with Grok",
                    "Source Tier": self.source_tier,
                    "Specificity": "Site-specific",
                    "Evidence Level": "Verified",
                    "Evidence Detail (what the source shows)": quote,
                }, [], quote
            return {
                "Can Park? (Yes/No/Conditional)": "No",
                "Brand": "National Rail",
                "Evidence Detail (what the source shows)": quote,
                "Source Tier": self.source_tier,
                "Specificity": "Site-specific",
                "Evidence Type": "Official site: clear answer",
                "Rules Stated": "Yes",
                "Prices Stated": "No",
                "Evidence Level": "Verified",
                "Decision Reason": "Route A: National Rail station page, visible text",
                # Can Park? No makes every parking detail not applicable, which
                # page_fill's consistency checks require.
                **{column: "Not applicable" for column in page_fill.NOT_APPLICABLE_IF_NO_PARKING},
            }, [], quote

        return {}, [], ""
