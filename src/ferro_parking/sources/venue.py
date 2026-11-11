"""Fetchers B, C and D: leisure and gym branch pages read for parking.

One reader serves better.org.uk, thegymgroup.com and puregym.com, because all
three publish the same kinds of sentence on a branch page:

    Car parking available 40 total spaces available Parking type: Free
    There is limited, free parking available outside the club.
    There are 155 car parking spaces available for customers.
    users ... are entitled to up to four hours free car parking.
    The car park is managed by Parking Eye.

The rules, per the brief:

- Can Park? Conditional and Who Can Park Customers only, for a venue car park.
- Cost Type Free only when the page says parking is free.
- When the page states charges, Paid, or Free then paid with the tariff in
  template form. A tariff that cannot be written in the template is never
  invented: Cost Type reads Unknown, the wording goes in Notes, and the row
  gets a Review Flag.
- Max Stay only when the page states a maximum stay with a number. A free
  period is not a maximum stay: "four hours free, then pay" lets a driver stay
  longer, so writing 240 there would send them away early.
- Free only when the free claim has no day or time qualifier. "All parking is
  free on Sundays" is not Free: the wording goes in Notes with a Review Flag.
- Operator and the PCN amount only when stated.
- A caution such as "check the signs in the car park" goes in Notes.
- Source Tier official, Specificity Site-specific, and every value carries the
  exact quote it came from.

A page that states no parking gives no values at all.
"""
import re

CAN_PARK = "Can Park? (Yes/No/Conditional)"

FREE = re.compile(
    r"parking type:\s*free"
    r"|\bfree,?\s+(?:on-?site\s+)?(?:car\s+)?parking\b"
    r"|\bparking\s+is\s+free\b"
    r"|\bpark(?:ing)?[^.\n]{0,40}\bfor\s+free\b"
    r"|\blimited,?\s+free\s+parking\b", re.I)

# "Parking Charge Notice" is a penalty, not a tariff, so it is cut out before
# the charge test runs.
PCN_WORDING = re.compile(r"parking charge notice(?:s)?(\s*\(pcn\))?", re.I)
CHARGE = re.compile(
    r"\bcharge to park\b|\bmust pay\b|\bpay and display\b|\bpay on exit\b"
    r"|\bpaid parking\b|\bparking charges\b|£\s?\d"
    r"|\b(?:charge|charges|charging|costs?|payment|fees?|payable)\b", re.I)

MAX_STAY = re.compile(
    r"\bmax(?:imum)?\s+stay\b[^.\n]{0,40}?(\d[\d,]*)\s*(hours?|hrs?|minutes?|mins?)", re.I)
HOURLY = re.compile(r"£\s?(\d+(?:\.\d{1,2})?)\s*(?:per|an|/)\s*hour", re.I)
# "up to four hours free car parking" and "free for 60 mins" both appear.
FREE_PERIOD = re.compile(
    r"\b(?:up to\s+)?(\d[\d,]*|one|two|three|four|five|six)\s*(hours?|hrs?|minutes?|mins?)"
    r"[^.\n]{0,30}?\bfree\b"
    r"|\bfree\b[^.\n]{0,20}?\b(\d[\d,]*|one|two|three|four|five|six)\s*"
    r"(hours?|hrs?|minutes?|mins?)", re.I)
# Two shapes in the live pages: "155 car parking spaces" in prose, and
# "40 total spaces available" in a facility list under a car heading.
SPACES = re.compile(r"\b(\d[\d,]*)\s*(?:total\s+)?(?:car\s+)?parking spaces\b"
                    r"|\b(\d[\d,]*)\s+total spaces available\b", re.I)
PCN_AMOUNT = re.compile(r"(?:pcn|penalty charge)[^.\n]{0,40}?£\s?(\d+)", re.I)
# The capture stops at a full stop, so "managed by Parking Eye. A PCN..."
# gives "Parking Eye" and not the next sentence.
OPERATOR = re.compile(
    r"\bcar park(?:\s+is)?\s+(?:managed|operated|run)\s+by\s+([A-Z][\w&' -]{2,40})")
CAUTION = re.compile(r"\bcheck\b[^.\n]{0,60}\b(?:signs?|car park)\b", re.I)

# A page can state that the branch has parking without saying what it costs:
# "Restricted parking is available for members". That is worth Conditional,
# Customers only and Cost Type Unknown. The generic caution every page carries
# ("Please check in the car park before you enter") asserts nothing about this
# branch, so it is deliberately not matched here.
AVAILABILITY = re.compile(
    r"\b(?:restricted|limited|free|customer|member|dedicated|on-?site)?\s*"
    r"parking is available\b"
    r"|\bparking available\b"
    r"|\bcar parking available\b"
    r"|\bon-?site (?:car park|parking)\b"
    r"|\bour (?:own )?car park\b"
    r"|\bdedicated (?:on-?site )?car park\b", re.I)

# A supermarket store page states its car park as one entry in a facility list,
# with no sentence around it: "Baby Changing | Car Park | Cash Machine". The
# entry stands alone, so it is matched only as a whole line. "Disabled
# Parking" and "Temporary Disabled Parking Pass" are entries of the same kind,
# and accessible bays alone never establish a car park, which is the rule the
# station reader already follows.
FACILITY_CAR_PARK = re.compile(r"^(?:free\s+|customer\s+)?car park(?:ing)?$", re.I)
ACCESSIBLE_ONLY = re.compile(r"\b(?:disabled|accessible|blue badge)\b", re.I)

# A free claim tied to named days, a date or a time window is not free. The
# live case was "All parking is free on Sundays. Check car park for latest
# prices." on a PureGym branch page: writing Free there tells a driver the
# wrong thing on six days out of seven.
FREE_QUALIFIER = re.compile(
    r"\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b"
    r"|\bweekends?\b|\bweekdays?\b|\bbank holidays?\b"
    r"|\b(?:after|before|from|until|till)\s+\d"
    r"|\bbetween\s+\d"
    r"|\bovernight\b|\bout of hours\b", re.I)

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

PARKING_MENTION = re.compile(r"\bcar park\b|\bparking\b", re.I)


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?;])\s+|\n+", text) if part.strip()]


def parking_sentences(text):
    return [sentence for sentence in sentences(text) if PARKING_MENTION.search(sentence)]


def facility_car_park(found):
    """The facility entry that states a car park at this store, or "".

    An entry about accessible bays is never that entry."""
    for sentence in found:
        if FACILITY_CAR_PARK.match(sentence.strip()) and not ACCESSIBLE_ONLY.search(sentence):
            return sentence.strip()
    return ""


def _minutes(value, unit):
    number = WORD_NUMBERS.get(value.lower(), None)
    if number is None:
        number = int(value.replace(",", ""))
    return number * 60 if unit.lower().startswith(("hour", "hr")) else number


def _without_pcn(text):
    return PCN_WORDING.sub(" penalty ", text)


# Require a parking subject or an explicit continuation, rather than treating
# proximity to a parking sentence as proof that a price buys parking.
PARKING_CHARGE = re.compile(
    r"\b(?:car park|parking)(?:\s+(?:is|charges?|costs?|fees?|payment|rate|tariff|of|are|apply|additional))*"
    r"\s*(?:£|paid\b|payable\b|charges?\b|costs?\b|fees?\b)"
    r"|\b(?:charge to park|paid parking|pay and display|pay on exit)\b", re.I)
CONTINUATION = re.compile(
    r"^(?:after that|beyond that|if you plan to stay beyond|a charge applies after|the max(?:imum)? stay)\b", re.I)
DENIAL = re.compile(
    r"\b(?:no|not)\s+(?:(?:free|customer|member|car)\s+)*parking\b"
    r"|\bparking (?:is )?not available\b", re.I)


def _charge_candidates(text, found):
    """Explicit parking clauses and narrowly linked following statements.

    A bare price or 'must pay' elsewhere on a branch page proves nothing.
    Clauses about a different service are deliberately left for a person.
    """
    every = sentences(text)
    out = []
    for index, sentence in enumerate(every):
        if PARKING_CHARGE.search(sentence):
            out.append(sentence)
        elif (index and every[index - 1] in found
              and CONTINUATION.search(sentence)
              and not re.search(r"\b(?:training|membership|classes?|sessions?|gym access)\b", sentence, re.I)):
            out.append(sentence)
    return out


def _parking_hourly(sentence):
    """Only format a rate whose own clause assigns it to parking.

    A mixed sentence can state parking charges and an unrelated hourly price.
    Unrecognised wording stays Unknown rather than borrowing that price.
    """
    match = HOURLY.search(sentence)
    if not match:
        return None
    prefix = sentence[:match.start()].strip()
    parking_subject = re.fullmatch(
        r"(?:additional )?(?:car park|parking)"
        r"(?:\s+(?:charges?|costs?|fees?|rates?|tariff|is|are|of|at|apply|then|pay))*\s*:?",
        prefix, re.I)
    continuation = re.fullmatch(
        r"(?:after that|beyond that)[, ]+(?:(?:customers|members|you)\s+)?"
        r"(?:must\s+)?pay", prefix, re.I)
    # Text after the rate may describe its purpose, so accept only the end of
    # the statement. More complex tariffs need a person to read them.
    if (parking_subject or continuation) and sentence[match.end():].strip() in ("", ".", ";"):
        return match
    return None


QUOTE_LIMIT = 220


def clip(sentence, pattern):
    """A readable window around the match. Some pages run a whole facility
    list together with no full stop, and the quote has to stay a contiguous
    piece of the page, so this trims rather than rewrites."""
    if len(sentence) <= QUOTE_LIMIT:
        return sentence
    match = pattern.search(sentence)
    middle = match.start() if match else 0
    start = max(0, middle - QUOTE_LIMIT // 3)
    return sentence[start:start + QUOTE_LIMIT].strip()


def find(pattern, sentences_list):
    for sentence in sentences_list:
        match = pattern.search(sentence)
        if match:
            return match, clip(sentence, pattern)
    return None, ""


class VenueFetcher:
    """key is the routing source key, such as "puregym.com"."""

    source_tier = "Official site - text"

    # The page this fetcher reads is the brand's own branch page, so the brand
    # is a fact about the row rather than a guess. validate_rows asks for Brand
    # on any Yes or Conditional row, and most of these rows leave it blank, so
    # without this the whole fetcher writes nothing.
    BRANDS = {
        "better.org.uk": "Better",
        "thegymgroup.com": "The Gym Group",
        "puregym.com": "PureGym",
    }

    def __init__(self, key, verified_by="Code (page fetch)", brand=None):
        self.key = key
        self.verified_by = verified_by
        self.brand = brand or self.BRANDS.get(key, "")

    def branch_url(self, row):
        from .fetch import SourceUrlFetcher
        from urllib.parse import urlsplit
        url = SourceUrlFetcher(self.key).branch_url(row)
        host = urlsplit(url).hostname or ""
        return url if host == self.key or host.endswith("." + self.key) else ""

    def quotes(self, text, row=None):
        found = parking_sentences(text)
        quotes = [sentence for sentence in found
                  if FREE.search(sentence) or CHARGE.search(_without_pcn(sentence))
                  or SPACES.search(sentence) or MAX_STAY.search(sentence)]
        # Keep this the same test values() uses, so a probe reports what the
        # fetcher will actually read.
        facility = facility_car_park(found)
        if facility and facility not in quotes:
            quotes.append(facility)
        return quotes

    def values(self, text, row=None):
        """(new_values, notes, flags, quote). Empty values mean a silent page."""
        found = parking_sentences(text)
        if not found:
            return {}, [], [], ""

        # Conflicting availability claims cannot safely establish permission.
        if any(DENIAL.search(sentence) for sentence in found):
            return {}, [], [], ""
        free_match, free_sentence = find(FREE, found)
        # A free claim limited to named days or a time window is not Free. The
        # wording is kept for a person instead of being turned into a price.
        qualified_free = ""
        if free_match and FREE_QUALIFIER.search(free_sentence):
            qualified_free, free_match, free_sentence = free_sentence, None, ""
        charge_match, charge_sentence = None, ""
        # Free is allowed only when no associated parking charge is stated.
        # Ignore penalties and explicit statements that no charge applies.
        for sentence in _charge_candidates(text, found):
            charge_text = _without_pcn(sentence)
            charge_text = re.sub(r"(?:pcn|penalty charge)[^.]*", "", charge_text, flags=re.I)
            charge_text = re.sub(r"\b(?:no|without)\s+(?:additional\s+)?(?:charge|charges|cost|fee|fees)\b|\bfree of charge\b", "", charge_text, flags=re.I)
            match = CHARGE.search(charge_text)
            if match:
                charge_match, charge_sentence = match, sentence
                break
        spaces_match, spaces_sentence = find(SPACES, found)
        available_match, available_sentence = find(AVAILABILITY, found)
        if not available_match:
            available_sentence = facility_car_park(found)
            available_match = bool(available_sentence)
        # An explicit maximum can follow the parking statement, but a free
        # period alone never establishes a maximum stay.
        stay_candidates = found + _charge_candidates(text, found)
        stay_match, stay_sentence = find(MAX_STAY, stay_candidates)

        parking_charge = charge_match is not None
        if not (free_match or parking_charge or spaces_match or stay_match
                or available_match or qualified_free):
            return {}, [], [], ""

        quote = (free_sentence or spaces_sentence or charge_sentence
                 or available_sentence or stay_sentence or qualified_free)
        values = {
            CAN_PARK: "Conditional",
            "Who Can Park": "Customers only",
            "Evidence Detail (what the source shows)": quote,
            "Source Tier": self.source_tier,
            "Specificity": "Site-specific",
            "Evidence Type": "Official site: partial info",
            "Rules Stated": "Yes",
            "Evidence Level": "Verified",
            "Decision Reason": f"Route B: official branch page on {self.key}",
        }
        if self.brand:
            values["Brand"] = self.brand
        notes, flags = [], []

        if free_match and not charge_match:
            values["Cost Type"] = "Free"
            values["Tariff Type"] = "Free (time limit not published)"
            values["Tariff Detail"] = "Free"
            period = FREE_PERIOD.search(free_sentence)
            if period:
                value = period.group(1) or period.group(3)
                unit = period.group(2) or period.group(4)
                values["Tariff Type"] = "Free with time limit"
                values["Tariff Detail"] = f"Free for up to {_minutes(value, unit)} mins"
            values["Price Status"] = "Published"
            values["Prices Stated"] = "Yes"
        elif charge_match:
            hourly = _parking_hourly(charge_sentence)
            period = FREE_PERIOD.search(free_sentence) if free_match else None
            if free_match and period and hourly:
                value = period.group(1) or period.group(3)
                unit = period.group(2) or period.group(4)
                values["Cost Type"] = "Free then paid"
                values["Tariff Type"] = "Free period, then hourly"
                values["Tariff Detail"] = (
                    f"Free for {_minutes(value, unit)} mins, "
                    f"then £{float(hourly.group(1)):.2f} per hour")
                values["Price Status"] = "Published"
                values["Prices Stated"] = "Yes"
            else:
                # The page names a charge this reader cannot write in the
                # template, so no tariff is invented.
                values["Cost Type"] = "Unknown"
                values["Price Status"] = "Not published"
                values["Prices Stated"] = "No"
                notes.append(f"Charges stated but not in a template: {charge_sentence}")
                flags.append("Tariff wording needs a person to read it")
        else:
            values["Cost Type"] = "Unknown"
            values["Price Status"] = "Not published"
            values["Prices Stated"] = "No"

        if qualified_free:
            notes.append(f"Free only at stated times, not read as a price: {qualified_free}")
            flags.append("Parking is free only at stated times: a person must read it")

        if stay_match:
            values["Max Stay (mins)"] = str(_minutes(stay_match.group(1), stay_match.group(2)))
            notes.append(f"Max stay from the branch page: {stay_sentence}")
        if spaces_match:
            count = spaces_match.group(1) or spaces_match.group(2)
            notes.append(f"Branch page states {count} parking spaces: {spaces_sentence}")

        operator = OPERATOR.search(text)
        if operator:
            values["Operator"] = operator.group(1).strip().rstrip(".")
        pcn = PCN_AMOUNT.search(text)
        if pcn:
            values["PCN (Penalty Charge Notice) amount (£)"] = pcn.group(1)

        caution_match, caution_sentence = find(CAUTION, found)
        if caution_match:
            notes.append(caution_sentence)

        evidence = [quote]
        for sentence in (charge_sentence, stay_sentence, spaces_sentence):
            if sentence and sentence not in evidence:
                evidence.append(sentence)
        quote = " | ".join(evidence)
        values["Evidence Detail (what the source shows)"] = quote
        return values, notes, flags, quote


# ---------------------------------------------------- brand store pages

STORE_TAGS = ("website", "contact:website")


def official_store_urls(conn, host):
    """{place_id: url} for store pages on one host, from the identity match.

    The url is the one the OpenStreetMap anchor published, so no store finder
    is guessed and no row name becomes a path. A place with more than one url
    on that host is left out, the way the station list drops an ambiguous
    name."""
    from urllib.parse import urlsplit

    found = {}
    for row in conn.execute(
            "SELECT place_id, quote FROM evidence WHERE field = 'Brand'"
            " AND quote LIKE '%website=%' ORDER BY id"):
        tags = dict(part.split("=", 1) for part in row["quote"].split("; ") if "=" in part)
        for tag in STORE_TAGS:
            url = (tags.get(tag) or "").strip()
            if not url.startswith("http"):
                continue
            if (urlsplit(url).hostname or "").lower() != host:
                continue
            found.setdefault(row["place_id"], set()).add(url)
    return {place_id: next(iter(urls)) for place_id, urls in found.items() if len(urls) == 1}


class StoreFetcher(VenueFetcher):
    """A supermarket brand's own store page, for rows the identity match named.

    The page states the store's facilities, so it can say that the store has a
    car park. It does not state who may park or what it costs, and a chain
    parking policy page is never read here: it describes most stores, not this
    one, and rules R7, R9 and R10 refuse Free, Anyone and a maximum stay
    without evidence for the exact site."""

    def __init__(self, brand, host, lookup=None, verified_by="Code (page fetch)"):
        super().__init__(host, verified_by=verified_by, brand=brand)
        self.host = host
        self.lookup = lookup

    def branch_url(self, row):
        return (self.lookup or {}).get((row.get("Place ID") or "").strip(), "")
