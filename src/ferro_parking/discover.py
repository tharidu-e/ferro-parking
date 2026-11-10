"""Fetch, London filter, deduplicate and draft. No Google Sheets access."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

from . import fill, rules
from .formats import parse_tariff, parse_hours, parse_stay
from .london import LondonFilter
from .run_paths import new_run_dir, reserve_output
from .sources import ADAPTERS
from .sync import normalize_name, normalize_postcode, haversine_m

UNKNOWN = {'', 'Not published', 'Unknown'}
HOURS = 'Hours (OpenStreetMap opening_hours format)'


def distance(source, row):
    try:
        return haversine_m(float(source['lat']), float(source['lon']),
                           float(row['Latitude']), float(row['Longitude']))
    except (KeyError, ValueError, TypeError):
        return float('inf')


def dedupe(source, rows):
    """Return all matches at the first successful priority, never choose a tie."""
    postcode = normalize_postcode(source.get('postcode', ''))
    name = normalize_name(source.get('name', ''))
    street = normalize_name(source.get('address', ''))
    chains = rules.load_rules().r6_chains
    def brand_for(name, explicit):
        if explicit:
            return normalize_name(explicit)
        normal = rules.norm_chain_key(name)
        return next((key for key in sorted(chains, key=len, reverse=True)
                     if normal == key or normal.startswith(key + ' ')), '')
    brand = brand_for(source.get('name', ''), source.get('brand', ''))
    stages = [
        ('postcode', lambda row: postcode and postcode == normalize_postcode(row.get('Postcode', ''))),
        ('name+street', lambda row: name and street and name == normalize_name(row.get('Location Name', ''))
         and street == normalize_name(row.get('Street Address', ''))),
        ('pin within 50 m', lambda row: distance(source, row) <= 50),
        ('same brand within 100 m', lambda row: brand and brand == brand_for(row.get('Location Name', ''), row.get('Brand', ''))
         and distance(source, row) <= 100),
    ]
    for reason, predicate in stages:
        matches = [row for row in rows if predicate(row)]
        if matches:
            return matches, reason
    return [], ''


def draft(source):
    kind, detail = parse_tariff(source.get('tariff', ''))
    hours = parse_hours(source.get('hours', ''))
    stay = parse_stay(source.get('max_stay', ''))
    # An imported file cannot certify its own authority. PP must review its evidence.
    if not source.get('official') and any(v != 'Not published' for v in (detail, hours, stay)):
        raise ValueError('Generic source facts require official site evidence review')
    if not source.get('name'):
        raise ValueError('Missing location name')
    return {
        'Location Name': source['name'], 'Street Address': source.get('address') or 'Not published',
        'Postcode': source.get('postcode') or 'Not published',
        fill.CAN_PARK: 'Unknown', 'Who Can Park': 'Unknown', 'Cost Type': 'Unknown',
        'Tariff Type': kind, 'Tariff Detail': detail,
        'Price Status': 'Published' if detail != 'Not published' else 'Not published',
        'Max Stay (mins)': stay, HOURS: hours,
        'Hours Basis': 'Car park hours' if hours != 'Not published' else 'Not published',
        'Operator': 'Not published', 'Rules Summary': 'Not published',
        'Parking Control Type (Cameras / Barrier / Patrol)': 'Not published',
        'PCN (Penalty Charge Notice) amount (£)': 'Not published',
        'Source URLs (primary first)': source.get('url') or 'Not published',
        'Source Tier': 'Operator / council site' if source.get('official') else 'Google search / third-party',
        'Specificity': 'Site-specific',
        'Evidence Detail (what the source shows)': json.dumps({key: source.get(key, '') for key in ('name', 'tariff', 'hours', 'max_stay')}),
        'Decision Reason': 'Route discovery: draft for review',
    }


def write_table(path, rows, headers):
    fields = list(dict.fromkeys(headers + [key for row in rows for key in row]))
    with Path(path).open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run(source_rows, sheet_rows, output, london_filter):
    started = datetime.now(timezone.utc).isoformat()
    candidates, matches, exceptions = [], [], []
    in_london = 0
    seen = []
    for source, region in london_filter.classify(source_rows):
        if region != 'London':
            exceptions.append({'name': source.get('name', ''), 'reason': 'Outside London' if region else 'London region unresolved', 'source': json.dumps(source)})
            continue
        in_london += 1
        hits, reason = dedupe(source, sheet_rows)
        if len(hits) > 1:
            exceptions.append({'name': source['name'], 'reason': f'Ambiguous {reason}', 'source': json.dumps(source)})
            continue
        try:
            row = draft(source)
            from .validation import validate_rows
            failures = validate_rows([row])
            if failures:
                raise ValueError("Draft validation failed: " + "; ".join(problem["message"] for problem in failures))
            if any(chr(c) in str(value) for c in (0x2013, 0x2014) for value in row.values()):
                raise ValueError('Source contains unsupported dash characters')
        except ValueError as exc:
            exceptions.append({'name': source.get('name', ''), 'reason': str(exc), 'source': json.dumps(source)})
            continue
        if hits:
            existing = hits[0]
            if not existing.get('Place ID'):
                exceptions.append({'name': source['name'], 'reason': 'Matched row has no Place ID', 'source': json.dumps(source)})
                continue
            improvements = {key: value for key, value in row.items()
                            if key in fill.RESEARCH_COLUMNS and str(existing.get(key, '')) in UNKNOWN
                            and value not in UNKNOWN and key not in ('Decision Reason', 'Source Tier', 'Specificity')}
            if existing.get('Verification Result') or existing.get('Verified By', '') not in ('', 'PP (validation)'):
                improvements = {}
            matches.append({'Place ID': existing['Place ID'], 'name': source['name'], 'method': reason,
                            'improvements': json.dumps(improvements), 'source': json.dumps(source)})
        else:
            # Compare later listings against earlier new candidates as well as the sheet.
            duplicate, method = dedupe(source, seen)
            if duplicate:
                exceptions.append({'name': source['name'], 'reason': f'Duplicate source listing: {method}', 'source': json.dumps(source)})
                continue
            candidates.append(row)
            seen.append({**row, 'Latitude': source.get('lat', ''), 'Longitude': source.get('lon', ''), 'Brand': source.get('brand', '')})
    write_table(output / 'candidates.csv', candidates, ['Location Name', 'Postcode'])
    write_table(output / 'matches.csv', matches, ['Place ID', 'name', 'method', 'improvements', 'source'])
    write_table(output / 'exceptions.csv', exceptions, ['name', 'reason', 'source'])
    summary = {'listed': len(source_rows), 'in_london': in_london, 'matched': len(matches),
               'new': len(candidates), 'exceptions': len(exceptions), 'started_at': started,
               'ended_at': datetime.now(timezone.utc).isoformat()}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=ADAPTERS)
    parser.add_argument('--input')
    parser.add_argument('--sheet-csv', required=True)
    parser.add_argument('--out')
    parser.add_argument('--cache', default='data/cache/postcodes')
    args = parser.parse_args(argv)
    if args.source == 'generic' and not args.input:
        parser.error('--source generic requires --input')
    sources = ADAPTERS[args.source](args.input)
    with open(args.sheet_csv, newline='', encoding='utf-8-sig') as stream:
        sheet = list(csv.DictReader(stream))
    output = reserve_output(args.out) if args.out else new_run_dir('discover')
    print(json.dumps(run(sources, sheet, output, LondonFilter(args.cache)), indent=2))
    print(f'Outputs: {output}')
    return 0
