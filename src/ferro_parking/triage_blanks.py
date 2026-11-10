"""Read-only research buckets for blank Can Park? rows, with optional local OSM evidence."""
import argparse
import csv
import json

from shapely.strtree import STRtree

from . import discovery, osm_match
from .discover import source_urls, write_table
from .fill import CAN_PARK, SOURCE_URLS
from .readiness import usable_pin
from .run_paths import new_run_dir, reserve_output

VENUES = {'supermarket', 'convenience_store', 'hotel', 'hospital', 'gym', 'restaurant',
          'pub', 'cafe', 'fast_food', 'diy_store', 'retail_park', 'petrol_station', 'cinema'}
OPERATORS = ('apcoa', 'ncp', 'saba', 'q park', 'euro car parks', 'horizon parking', 'citipark', 'indigo parking')
HEADERS = ['Place ID', 'Location Name', 'Place Category', 'Type (as captured)', 'Borough',
           'Postcode', 'Source URL', 'bucket', 'reason']


def bucket(row, categories):
    category = discovery.classify_sheet_row(row, categories)
    text = osm_match.norm(' '.join(str(row.get(key) or '') for key in ('Location Name', 'Place Category', 'Type (as captured)')))
    urls = source_urls(row.get(SOURCE_URLS, ''))
    if category == 'station' or (category != 'petrol_station' and osm_match.contains_word(text, 'station')):
        return 'station', 'Station category or station wording; research the station-specific source'
    if any(osm_match.contains_word(text, word) for word in ('council', 'borough council')):
        return 'council', 'Council identity in the category or captured venue text'
    operator = any(osm_match.contains_word(text, name) for name in OPERATORS)
    operator_host = any(any(name in url.split('/')[2].replace('-', '').replace('.', '')
                           for name in ('apcoa', 'ncp', 'saba', 'qpark', 'eurocarparks', 'horizonparking', 'citipark')) for url in urls)
    if urls and (operator or operator_host or 'operator car park' in text):
        return 'operator with a URL', 'Operator-style identity with an existing source URL'
    if category in VENUES or any(osm_match.contains_word(text, word) for word in (
            'shop', 'retail', 'hotel', 'gym', 'hospital', 'restaurant', 'pub', 'cafe', 'school', 'college')):
        return 'likely venue customers-only', 'Venue research queue only; customer/guest restrictions still need site-specific evidence'
    return 'unknown', 'No clear venue, station, council or operator identity in the exported fields'


def nearby_evidence(row, parks, tree):
    if not usable_pin(row):
        return []
    point = discovery.row_point_m(row)
    evidence = []
    for index in tree.query(point.buffer(osm_match.BRAND_PARK_M)):
        park = parks[index]
        if park['tags'].get('parking') in ('street_side', 'lane'):
            continue
        distance = park['geom'].distance(point)
        brand_hit, _ = osm_match.name_score(row, park['tags'], osm_match.brand_key(row))
        if distance <= osm_match.ADJACENT_M or (brand_hit and distance <= osm_match.BRAND_PARK_M):
            evidence.append({'url': osm_match.osm_url(park), 'distance_m': round(distance, 1), 'tags': park['tags']})
    return sorted(evidence, key=lambda item: (item['distance_m'], item['url']))


def triage(rows, categories=None, parks=None):
    categories = categories if categories is not None else discovery.load_categories()
    tree = STRtree([park['geom'] for park in parks]) if parks is not None else None
    results = []
    for row in rows:
        if str(row.get(CAN_PARK) or '').strip():
            continue
        group, reason = bucket(row, categories)
        result = {key: row.get(key, '') for key in HEADERS[:6]}
        result.update({'Source URL': row.get(SOURCE_URLS, ''), 'bucket': group, 'reason': reason})
        if parks is not None:
            result['OSM evidence'] = json.dumps(nearby_evidence(row, parks, tree), sort_keys=True)
        # Display formatting only. The input CSV and captured values are never written back.
        results.append({key: str(value or '').translate({0x2013: '-', 0x2014: '-'}) for key, value in result.items()})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet-csv', required=True)
    parser.add_argument('--out')
    parser.add_argument('--pbf')
    args = parser.parse_args(argv)
    parks = None
    if args.pbf:
        collector = osm_match.Collector()
        collector.apply_file(args.pbf, locations=True)
        parks = collector.parks
    with open(args.sheet_csv, newline='', encoding='utf-8-sig') as stream:
        results = triage(csv.DictReader(stream), parks=parks)
    output = reserve_output(args.out) if args.out else new_run_dir('triage_blanks')
    write_table(output / 'triage_blanks.csv', results, HEADERS + (['OSM evidence'] if parks is not None else []))
    print(f'{len(results)} blank rows. Output: {output / "triage_blanks.csv"}')
    return 0
