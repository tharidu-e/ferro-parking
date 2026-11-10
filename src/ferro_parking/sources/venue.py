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
    r"|\bpaid parking\b|\bparking charges\b|£\s?\d", re.I)

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

WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

PARKING_MENTION = re.compile(r"\bcar park\b|\bparking\b", re.I)


def sentences(text):
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def parking_sentences(text):
    return [sentence for sentence in sentences(text) if PARKING_MENTION.search(sentence)]


def _minutes(value, unit):
    number = WORD_NUMBERS.get(value.lower(), None)
    if number is None:
        number = int(value.replace(",", ""))
    return number * 60 if unit.lower().startswith(("hour", "hr")) else number


def _without_pcn(text):
    return PCN_WORDING.sub(" penalty ", text)


def _charge_candidates(text, found):
    """The parking sentences, then the sentence after each of them."""
    every = sentences(text)
    out = list(found)
    for sentence in found:
        try:
            index = every.index(sentence)
        except ValueError:
            continue
        if index + 1 < len(every):
            out.append(every[index + 1])
    return out


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
        return SourceUrlFetcher(self.key).branch_url(row)

    def quotes(self, text, row=None):
        return [sentence for sentence in parking_sentences(text)
                if FREE.search(sentence) or CHARGE.search(_without_pcn(sentence))
                or SPACES.search(sentence) or MAX_STAY.search(sentence)]

    def values(self, text, row=None):
        """(new_values, notes, flags, quote). Empty values mean a silent page."""
        found = parking_sentences(text)
        if not found:
            return {}, [], [], ""

        free_match, free_sentence = find(FREE, found)
        # A charge is often written in the sentence after the parking one
        # ("Parking is free for 60 mins. After that you must pay £2.50 per
        # hour."), which names no car park itself. Only the sentence straight
        # after a parking sentence is read, so a price elsewhere on the page
        # is never mistaken for a parking charge.
        charge_match, charge_sentence = None, ""
        for sentence in _charge_candidates(text, found):
            match = CHARGE.search(_without_pcn(sentence))
            if match:
                charge_match, charge_sentence = match, sentence
                break
        spaces_match, spaces_sentence = find(SPACES, found)
        available_match, available_sentence = find(AVAILABILITY, found)
        # A maximum stay is often written in its own sentence, which names no
        # car park, so this one reads the whole page.
        stay_match, stay_sentence = find(MAX_STAY, sentences(text))

        if not (free_match or charge_match or spaces_match or stay_match
                or available_match):
            return {}, [], [], ""

        quote = (free_sentence or spaces_sentence or charge_sentence
                 or available_sentence or stay_sentence)
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
            values["Price Status"] = "Published"
            values["Prices Stated"] = "Yes"
        elif charge_match:
            hourly = HOURLY.search(charge_sentence) or HOURLY.search(" ".join(found))
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

        return values, notes, flags, quote
