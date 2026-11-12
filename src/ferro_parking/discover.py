"""Fetch, London filter, deduplicate and draft. No Google Sheets access."""
import argparse
import csv
from datetime import datetime, timezone
import json
import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

from . import fill, rules
from .formats import parse_tariff, parse_hours, parse_stay
from .london import BoroughFilter, LondonFilter
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


def source_urls(value):
    """Normalise individual URLs without removing query parameters."""
    result = set()
    for item in re.split(r';|\s+', value or ''):
        try:
            url = urlsplit(item.strip())
        except ValueError:
            continue
        if url.scheme in ('http', 'https') and url.netloc:
            result.add(urlunsplit((url.scheme.lower(), url.netloc.lower(), url.path.rstrip('/'), url.query, '')))
    return result


def rank_names(source, hits):
    """A unique exact name wins; fuzzy leaders need a meaningful score and gap."""
    if len(hits) < 2:
        return hits
    name = rules.norm_chain_key(normalize_name(source.get('name', '')))
    if not name:
        return hits
    normalised = [(row, rules.norm_chain_key(normalize_name(row.get('Location Name', '')))) for row in hits]
    exact = [row for row, candidate in normalised if candidate == name]
    if exact:
        return exact
    def score(candidate):
        if not candidate:
            return 0
        source_terminal = re.search(r'\bterminal (\d+)\b', name)
        candidate_terminal = re.search(r'\bterminal (\d+)\b', candidate)
        if source_terminal and candidate_terminal and source_terminal[1] != candidate_terminal[1]:
            return 0
        left, right = set(name.split()), set(candidate.split())
        return 0.6 * SequenceMatcher(None, name, candidate).ratio() + 0.4 * len(left & right) / len(left | right)
    ranked = sorted(((score(candidate), index, row) for index, (row, candidate) in enumerate(normalised)),
                    key=lambda item: (-item[0], item[1]))
    if ranked[0][0] >= 0.40 and ranked[0][0] - ranked[1][0] >= 0.08:
        return [ranked[0][2]]
    return hits


def dedupe(source, rows, non_identifying_urls=frozenset()):
    """Prefer decisive stages; keep unresolved multi-hit evidence while trying later stages."""
    place_id = str(source.get('place_id') or source.get('Place ID') or '').strip()
    urls = source_urls(source.get('url', '')) - non_identifying_urls
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
        ('Place ID', lambda row: place_id and place_id == row.get('Place ID', '').strip()),
        ('Source URL', lambda row: bool(urls & source_urls(row.get('Source URLs (primary first)', '')))),
        ('postcode', lambda row: postcode and postcode == normalize_postcode(row.get('Postcode', ''))),
        ('name+street', lambda row: name and street and name == normalize_name(row.get('Location Name', ''))
         and street == normalize_name(row.get('Street Address', ''))),
        ('pin within 50 m', lambda row: distance(source, row) <= 50),
        ('same brand within 100 m', lambda row: brand and brand == brand_for(row.get('Location Name', ''), row.get('Brand', ''))
         and distance(source, row) <= 100),
    ]
    ambiguous = None
    for reason, predicate in stages:
        matches = [row for row in rows if predicate(row)]
        if not matches:
            continue
        if len(matches) == 1:
            return matches, reason
        # Duplicate stable IDs are a data error, not weak geographic evidence.
        if reason == 'Place ID':
            return matches, reason
        ranked = rank_names(source, matches)
        if len(ranked) == 1:
            return ranked, reason + '+name'
        if ambiguous is None:
            ambiguous = matches, reason
    return ambiguous if ambiguous is not None else ([], '')


def plain_dashes(text):
    return text.translate({0x2013: '-', 0x2014: '-'}) if isinstance(text, str) else text


def draft(source):
    flags = {}
    try:
        kind, detail = parse_tariff(source.get('tariff', ''))
    except ValueError:
        kind, detail = 'Not published', 'Not published'
        flags['tariff_unparsed'] = True
    def parse_field(parser, key, flag):
        try:
            return parser(source.get(key, ''))
        except ValueError:
            flags[flag] = True
            return 'Not published'
    hours = parse_field(parse_hours, 'hours', 'hours_unparsed')
    stay = parse_field(parse_stay, 'max_stay', 'max_stay_unparsed')
    # Imported files cannot certify their own authority. Keep the identity
    # match, retain source quotes, and quarantine only the unsupported claims.
    if not source.get('official'):
        if detail != 'Not published':
            flags['tariff_unverified'] = True
            kind, detail = 'Not published', 'Not published'
        if hours != 'Not published':
            flags['hours_unverified'] = True
            hours = 'Not published'
        if stay != 'Not published':
            flags['max_stay_unverified'] = True
            stay = 'Not published'
    if kind == 'Free with time limit' and not stay.isdigit():
        flags['tariff_inconsistent'] = True
        kind, detail = 'Not published', 'Not published'
    if not source.get('name'):
        raise ValueError('Missing location name')
    values = {
        'flags': json.dumps(flags, sort_keys=True),
        'Location Name': source['name'], 'Street Address': source.get('address') or 'Not published',
        'Postcode': source.get('postcode') or 'Not published',
        fill.CAN_PARK: 'Unknown', 'Who Can Park': 'Unknown', 'Cost Type': 'Unknown',
        'Tariff Type': kind, 'Tariff Detail': detail,
        'Price Status': 'Not applicable' if detail == 'Not applicable' else ('Published' if detail != 'Not published' else 'Not published'),
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

    return {key: plain_dashes(value) for key, value in values.items()}


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
    # A feed URL shared by the whole import identifies the list, not a site.
    # One row alone cannot establish that a URL is shared.
    non_identifying_urls = (set.intersection(*(source_urls(row.get('url', ''))
                                             for row in source_rows))
                            if len(source_rows) > 1 else set())
    for source, region in london_filter.classify(source_rows):
        if region != 'London':
            exceptions.append({'name': source.get('name', ''), 'reason': 'Outside London' if region else 'London region unresolved', 'source': json.dumps(source)})
            continue
        in_london += 1
        hits, reason = dedupe(source, sheet_rows, non_identifying_urls)
        if len(hits) > 1:
            exceptions.append({'name': source['name'], 'reason': f'Ambiguous {reason}', 'source': json.dumps(source)})
            continue
        try:
            row = draft(source)
            from .validation import validate_rows
            failures = validate_rows([row])
            if any(problem['rule'] == 'charging-hours' and not problem['message'].startswith('WARNING:') for problem in failures):
                # Charging periods are not proof of opening hours. Preserve the
                # place identity and withhold only the questionable time field.
                row[HOURS] = row['Hours Basis'] = 'Not published'
                flags = json.loads(row['flags'])
                flags['hours_context_unresolved'] = True
                row['flags'] = json.dumps(flags, sort_keys=True)
                failures = validate_rows([row])
            failures = [problem for problem in failures if not problem["message"].startswith("WARNING:")]
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
            matches.append({'Place ID': existing['Place ID'], 'name': plain_dashes(source['name']), 'method': reason,
                            'improvements': json.dumps(improvements), 'flags': row['flags'], 'source': json.dumps(source)})
        else:
            # Compare later listings against earlier new candidates as well as the sheet.
            duplicate, method = dedupe(source, seen, non_identifying_urls)
            if duplicate:
                exceptions.append({'name': source['name'], 'reason': f'Duplicate source listing: {method}', 'source': json.dumps(source)})
                continue
            candidates.append(row)
            seen.append({**row, 'Latitude': source.get('lat', ''), 'Longitude': source.get('lon', ''), 'Brand': source.get('brand', '')})
    write_table(output / 'candidates.csv', candidates, ['Location Name', 'Postcode'])
    write_table(output / 'matches.csv', matches, ['Place ID', 'name', 'method', 'improvements', 'flags', 'source'])
    write_table(output / 'exceptions.csv', exceptions, ['name', 'reason', 'source'])
    summary = {'listed': len(source_rows), 'in_london': in_london, 'matched': len(matches),
               'new': len(candidates), 'exceptions': len(exceptions), 'started_at': started,
               'ended_at': datetime.now(timezone.utc).isoformat()}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    return summary


def existing_rows(sheet_csv=None, db_path=None):
    """The places to deduplicate against.

    The database by default, because it holds every sheet row and also the
    car parks the project created itself. A sheet export holds only the sheet
    rows, so deduplicating against one cannot see a created record and would
    add a car park the database already holds. create.check_plan reads the
    database for the same reason, and both guards have to see the same world.
    """
    if sheet_csv:
        with open(sheet_csv, newline='', encoding='utf-8-sig') as stream:
            return list(csv.DictReader(stream)), f'sheet export {sheet_csv}'
    from . import db
    path = db_path or db.DB_PATH
    conn = db.connect(path)
    try:
        _, rows = db.current_rows(conn)
    finally:
        conn.close()
    if not rows:
        raise ValueError(f'nothing imported into {path}: run db-import first')
    return rows, f'database {path}'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, choices=ADAPTERS)
    parser.add_argument('--input')
    parser.add_argument('--sheet-csv', default=None,
                        help='deduplicate against this sheet export instead of '
                             'the database. The export cannot see a created '
                             'record, so prefer the database')
    parser.add_argument('--db', default=None)
    parser.add_argument('--out')
    parser.add_argument('--boroughs-from', default=None,
                        help='an OpenStreetMap extract. Build the borough '
                             'polygon cache from it once, then every later run '
                             'tests London membership offline')
    parser.add_argument('--postcode-lookup', action='store_true',
                        help='classify London by postcodes.io instead of borough '
                             'geometry. Needs network access, and a postcode is '
                             'not a boundary test')
    parser.add_argument('--cache', default='data/cache/postcodes')
    args = parser.parse_args(argv)
    if args.source == 'generic' and not args.input:
        parser.error('--source generic requires --input')
    sources = ADAPTERS[args.source](args.input)
    sheet, against = existing_rows(args.sheet_csv, args.db)
    print(f'deduplicating {len(sources)} source rows against {len(sheet)} '
          f'places from the {against}')
    if args.postcode_lookup:
        london = LondonFilter(args.cache)
        print('London membership by postcodes.io lookup')
    else:
        london = BoroughFilter(args.boroughs_from)
        print(f'London membership by borough polygon, {len(london.boroughs)} boroughs')
    output = reserve_output(args.out) if args.out else new_run_dir('discover')
    print(json.dumps(run(sources, sheet, output, london), indent=2))
    print(f'Outputs: {output}')
    return 0
