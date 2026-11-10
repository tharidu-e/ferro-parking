"""Validate dry-run plans or candidate files without network or sheet access."""
import argparse
import csv
import json
from pathlib import Path
import re
import tomllib

from . import capture_fill, fill, page_fill
from .formats import tariff_valid, hours_valid
from .settings import CONFIG_DIR
from .sync import normalize_name, normalize_postcode

HOURS = 'Hours (OpenStreetMap opening_hours format)'


def dropdowns():
    with (CONFIG_DIR / 'rules.toml').open('rb') as stream:
        return tomllib.load(stream)['dropdowns']


PRICE_TOKEN = re.compile(r'(?:£|GBP)\s*\d+(?:[.,]\d+)?|\b\d+\.\d{2}\s*(?:per\b|/)|\b\d+\s*(?:pence|p)\b', re.I)
MISSING = {'', 'Unknown', 'Not published', 'Not applicable'}


def charging_hours_message(row):
    """Flag context about charging, without declaring vague enforcement text fact."""
    if str(row.get(HOURS, '')).strip() in MISSING:
        return None
    context = ' '.join(str(row.get(key, '')) for key in (
        'Hours Basis', 'Notes', 'Rules Summary', 'Evidence Detail (what the source shows)',
        'Charges (as published)', 'Enforcement Details'))
    clear = re.search(r'\b(?:charging|chargeable|controlled|enforcement)\s+(?:hours|times)\b|\bcharges apply\b', context, re.I)
    if clear:
        return 'Hours may describe charging/control periods instead of when parking is allowed; review the source'
    if re.search(r'\b(?:charging|charges|controlled|enforcement|paid parking|pay and display)\b', context, re.I):
        return 'WARNING: Charging/control context is ambiguous; confirm these are parking opening hours'
    return None


def is_warning(problem):
    return problem['message'].startswith('WARNING:')


def validate_rows(entries, plan=False):
    failures, identities = [], set()
    allowed = dropdowns()
    for entry in entries:
        row = entry['new'] if plan else entry
        pid = entry.get('place_id', '') if plan else row.get('Place ID', '')
        old = entry.get('old', {})
        changed = {key for key, value in row.items() if str(value) != str(old.get(key, ''))}
        category_only = plan and bool(changed) and changed <= {'Place Category', 'Brand'}
        def fail(field, rule, message):
            failures.append({'Place ID': pid, 'field': field, 'value': row.get(field, ''), 'rule': rule, 'message': message})
        if not plan:
            metadata = {"Place ID", "Location Name", "Street Address", "Postcode", "Borough", "Location Status"}
            try:
                fill.assert_not_protected(set(row) - metadata)
            except AssertionError as exc:
                fail("*", "protected", str(exc))
        if plan:
            try:
                fill.validate_write_columns([entry])
            except (ValueError, AssertionError) as exc:
                fail('*', 'protected', str(exc))
        for key, value in row.items():
            if value == '' or value is None:
                fail(key, 'blank', 'Touched field is blank')
            if (any(chr(code) in str(value) for code in (0x2013, 0x2014))
                    and not (category_only and key == 'Decision Reason' and key not in changed)):
                fail(key, 'dashes', 'Use a plain hyphen')
            if key in allowed and value not in allowed[key]:
                fail(key, 'dropdown', 'Value must exactly match config/rules.toml')
        if row.get(fill.CAN_PARK) in ('Yes', 'Conditional'):
            for column in ('Brand', 'Place Category'):
                if not str(row.get(column) or '').strip():
                    fail(column, 'required', f'{column} is required when parking is Yes or Conditional')
        if row.get('Price Status') == 'Not published':
            for column in ('Charges (as published)', 'Tariff Detail'):
                if PRICE_TOKEN.search(str(row.get(column, ''))):
                    fail('Price Status', 'price-status', f'{column} contains a price but Price Status is Not published')
        detail = str(row.get('Tariff Detail', '')).strip()
        free_first = re.match(r'Free\b|\d+-\d+\s+(?:hrs|mins)\s+£0\.00(?:;|$)', detail, re.I)
        if row.get('Cost Type') == 'Paid' and free_first:
            fail('Cost Type', 'cost-type', 'Tariff has a free first period; use Free then paid instead of Paid')
        charging_message = charging_hours_message(row)
        if charging_message:
            fail(HOURS, 'charging-hours', charging_message)
        if 'Tariff Detail' in row and not tariff_valid(row.get('Tariff Type'), row['Tariff Detail']):
            fail('Tariff Detail', 'template', 'Invalid tariff template or band ranges')
        if 'Max Stay (mins)' in row and not (re.fullmatch(r'\d+', str(row['Max Stay (mins)'])) or row['Max Stay (mins)'] in ('No limit', 'Not published', 'Not applicable')):
            fail('Max Stay (mins)', 'minutes', 'Use whole minutes, No limit, Not published or Not applicable')
        if HOURS in row and not hours_valid(row[HOURS]):
            fail(HOURS, 'hours', 'Unsupported or invalid OSM opening_hours format')
        risky = (row.get('Cost Type') == 'Free' or row.get('Who Can Park') in ('Anyone', 'Anyone (paid)')
                 or str(row.get('Max Stay (mins)', '')).isdigit() or row.get('Max Stay (mins)') == 'No limit')
        if risky and (row.get('Source Tier') not in page_fill.STRONG_SOURCE_TIERS
                      or row.get('Specificity') != 'Site-specific'
                      or not row.get('Evidence Detail (what the source shows)')):
            fail('*', 'evidence', 'Free, public access and a max stay require quoted strong site-specific evidence')
        if row.get('Max Stay (mins)') == 'No limit' and not re.search(
                r'\b(?:no (?:maximum stay|time limit|limit)|unlimited (?:stay|parking))\b(?!\s+(?:stated|published|specified|listed))',
                row.get('Evidence Detail (what the source shows)', ''), re.I):
            fail('Max Stay (mins)', 'evidence', 'No limit requires explicit source words')
        if row.get('Verification Result') == 'Confirmed' and any(str(row.get(key, '')) in ('', 'Not published', 'Unknown') for key in ('Max Stay (mins)', HOURS, 'Who Can Park')):
            fail('Verification Result', 'confirmed', 'Confirmed requires known max stay, hours and who can park')
        if 'Identity resolved' in row and row.get(fill.CAN_PARK) == 'Yes' and row.get('Verification Result') == 'Needs on-site check' and row.get('Identity resolved') != 'Yes':
            fail(fill.CAN_PARK, 'identity', 'Unresolved identity cannot say Yes')
        if row.get('Location Status') == 'Closed':
            if row.get(fill.CAN_PARK) != 'No':
                fail(fill.CAN_PARK, 'closed', 'Closed requires Can Park? No')
            for key in page_fill.NOT_APPLICABLE_IF_NO_PARKING:
                if row.get(key) != 'Not applicable':
                    fail(key, 'closed', 'Closed requires Not applicable')
        for message in page_fill.consistency_checks(row):
            if category_only and message == 'Decision Reason missing or does not name the route':
                continue
            fail('*', 'consistency', message)
        # Wrap the existing captured-evidence validator with unknown defaults for
        # untouched fields. Quotes remain evidence, never synthesised from values.
        fields = {}
        for name, column in capture_fill.FIELD_TO_COLUMN.items():
            value = row.get(column, 'Not published')
            if column == fill.CAN_PARK and column not in row:
                value = 'Unknown'
            if column in ('Who Can Park', 'Cost Type') and column not in row:
                value = 'Unknown'
            fields[name] = {'value': value, 'scope': 'site' if row.get('Specificity') == 'Site-specific' else 'none',
                            'quote': row.get('Evidence Detail (what the source shows)', '')}
        for message in capture_fill.validate_record({'fields': fields}):
            fail('*', 'capture', message)
        postcode = normalize_postcode(entry.get('postcode', row.get('Postcode', '')) if plan else row.get('Postcode', ''))
        name = normalize_name(entry.get('name', row.get('Location Name', '')) if plan else row.get('Location Name', ''))
        key = postcode, name
        if postcode and name and postcode != 'NOTPUBLISHED':
            if key in identities:
                fail('Location Name', 'duplicate', 'Duplicate postcode+name')
            identities.add(key)
    return failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('--out', help='New validation.csv path; existing files are refused')
    args = parser.parse_args(argv)
    path = Path(args.input)
    if path.suffix == '.json':
        entries, plan = json.loads(path.read_text()), True
    else:
        with path.open(newline='', encoding='utf-8-sig') as stream:
            entries, plan = list(csv.DictReader(stream)), False
    failures = validate_rows(entries, plan)
    output = Path(args.out) if args.out else path.parent / 'validation.csv'
    with output.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['Place ID', 'field', 'value', 'rule', 'message'])
        writer.writeheader()
        writer.writerows(failures)
    errors = sum(not is_warning(problem) for problem in failures)
    warnings = len(failures) - errors
    print(f'{len(entries)} rows, {errors} failures, {warnings} warnings. Report: {output}')
    return 1 if errors else 0
