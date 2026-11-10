"""Conservative supported tariff and opening-hours grammar. Never infer a rate."""
import re
from decimal import Decimal

MONEY = r'£\d+\.\d{2}'
BAND = rf'(\d+)-(\d+) hrs ({MONEY})'
TARIFF_PATTERNS = {
    'Free (time limit not published)': r'Free',
    'Free with time limit': r'Free for up to \d+ (?:hrs|mins)',
    'Free period, then hourly': rf'Free for \d+ mins, then {MONEY} per hour',
    'Hourly rate': rf'{MONEY} per hour',
    'Flat rate per 24 hours': rf'{MONEY} per 24 hours',
    'Flat rate per night': rf'{MONEY} per night',
    'Banded by stay length': rf'{BAND}(?:; {BAND})*',
    'Not published': r'Not published', 'Not applicable': r'Not applicable',
}


def tariff_valid(kind, detail):
    if not re.fullmatch(TARIFF_PATTERNS.get(kind, r'(?!)'), str(detail)):
        return False
    if kind == 'Banded by stay length':
        bands = [(int(a), int(b)) for a, b in re.findall(r'(\d+)-(\d+) hrs', detail)]
        return all(a < b for a, b in bands) and all(bands[i][1] == bands[i+1][0] for i in range(len(bands)-1))
    return True


def parse_tariff(text):
    if not text.strip():
        return 'Not published', 'Not published'
    text = text.strip()
    for kind in TARIFF_PATTERNS:
        if tariff_valid(kind, text):
            return kind, text
    # Only a complete simple rate is normalised; leftover conditions cause review.
    match = re.fullmatch(r'£(\d+(?:\.\d{1,2})?)\s*(?:per|/)\s*(hour|24 hours|night)', text, re.I)
    if match:
        detail = f'£{Decimal(match[1]):.2f} per {match[2].lower()}'
        return parse_tariff(detail)
    raise ValueError('Unparseable tariff; review complete source text')


DAY = r'(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)'
DAYS = rf'{DAY}(?:-{DAY})?(?:,{DAY}(?:-{DAY})?)*'
TIME = r'(?:[01]\d|2[0-3]):[0-5]\d|24:00|sunrise|sunset'
SPAN = rf'(?:{TIME})-(?:{TIME})'
RULE = rf'(?:{DAYS} )?(?:{SPAN}(?:,{SPAN})*|off|open)'


def hours_valid(value):
    return value in ('24/7', 'Not published', 'Not applicable') or bool(re.fullmatch(rf'{RULE}(?:; {RULE})*', str(value)))


def parse_hours(text):
    if not text.strip():
        return 'Not published'
    if hours_valid(text.strip()):
        return text.strip()
    raise ValueError('Unsupported or invalid OSM hours; review source')


def parse_stay(text):
    text = text.strip()
    if not text or text == 'Not published':
        return 'Not published'
    if re.fullmatch(r'(?:No limit|no maximum stay|unlimited parking)', text, re.I):
        return 'No limit'
    match = re.fullmatch(r'(\d+)\s*(minutes?|mins?|hours?|hrs?)?', text, re.I)
    if match:
        return str(int(match[1]) * (60 if (match[2] or '').lower().startswith(('h',)) else 1))
    raise ValueError('Unparseable max stay; review source')
