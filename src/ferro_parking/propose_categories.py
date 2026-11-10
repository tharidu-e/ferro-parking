"""Prepare category review CSVs from captured types; never write to Sheets."""
import argparse
import csv
import json
import re

from shapely.strtree import STRtree

from . import discovery, osm_match
from .discover import write_table
from .fill import PLACE_ID
from .run_paths import new_run_dir, reserve_output
from .triage_blanks import nearby_evidence
from .validation import dropdowns

CATEGORY = 'Place Category'
CAPTURED_TYPE = 'Type (as captured)'
HEADERS = [PLACE_ID, 'Location Name', 'Brand', CATEGORY, CAPTURED_TYPE,
           'proposed_place_category', 'reason', 'confidence']

# Explicit type families, tested in order. These are semantic type labels,
# not a fuzzy match against arbitrary venue names. Specific overrides come first.
TYPE_RULES = (
    (r'hospital\b.*|health centre\b.*', 'Hospital / health centre'),
    (r'hotel\b.*', 'Hotel'),
    (r'gym(?: \(.+\))?|leisure centre.*|leisure / private car park \(.+\)', 'Gym / leisure centre'),
    (r'retail - trade/diy|retail / trade & diy|retail - diy|diy / home improvement store|diy / home store|retail warehouse|retail - warehouse club \(members\)|garden centre|retail \(dobbies\)', 'Retail warehouse / DIY / trade'),
    (r'retail / shopping centre|retail park', 'Shopping centre'),
    (r'station car park(?: \(.+\))?|station(?: \(.+\))?', 'Station'),
    (r'(?:fuel|petrol) station(?: \(.+\))?', 'Petrol station'),
    (r'(?:retail / )?private car park \(operator .+\)(?: / station)?|car park \(apcoa\)', 'Private / operator car park'),
    (r'public car park \(council[^)]*\)|council car[ -]?park(?: \(.+\))?', 'Council car park'),
    (r'fast food\b.*', 'Fast food / drive-thru'),
    (r'pub-restaurant|restaurant(?: \(.+\))?|pub|cafe|coffee shop', 'Restaurant / pub / cafe'),
    (r'university|college(?: \(.+\))?|school(?: \(.+\))?', 'School / college'),
    (r'(?:other retail|retail store|retail)(?: \(.+\))?|retail [/-] (?:discount.*|clothing.*|furniture.*)', 'Other'),
    (r'park / attraction|cinema|stadium / arena|place of worship|airport|ev charging\b.*|car wash\b.*|cemetery\b.*|crematorium', 'Other'),
)


def normalise_type(value):
    return ' '.join(str(value or '').translate({0x2013: '-', 0x2014: '-'}).strip().casefold().split())


def category_proposal(row, categories=None, allowed=None):
    categories = categories if categories is not None else discovery.load_categories()
    allowed = set(allowed if allowed is not None else dropdowns()[CATEGORY])
    typ = normalise_type(row.get(CAPTURED_TYPE))
    if not typ:
        return '', 'Type is blank; no safe mapping', ''

    def result(value, reason, confidence='high'):
        if value not in allowed:
            return '', f'Mapping value {value!r} is not in the configured dropdown', ''
        return value, reason, confidence

    # Brand evidence refines a supermarket type only; a Station name cannot
    # turn a retail or supermarket type into a railway station.
    if re.fullmatch(r'(?:retail / )?supermarket(?: \(.+\))?', typ):
        small = categories.get('supermarket', {}).get('sheet_small_format_brands', [])
        keys = [osm_match.brand_key(row), osm_match.brand_key({CAPTURED_TYPE: typ})]
        if any(osm_match.contains_word(key, osm_match.norm(brand)) for key in keys for brand in small):
            return result('Supermarket - convenience', 'Explicit supermarket type with a configured small-format brand')
        return result('Supermarket - large format', 'Explicit supermarket type; no configured small-format brand')

    if re.fullmatch(r'restaurant \(.+\)', typ):
        brands = categories.get('fast_food', {}).get('sheet_brand_in', [])
        key = osm_match.brand_key({CAPTURED_TYPE: typ})
        if any(osm_match.contains_word(key, osm_match.norm(brand)) for brand in brands):
            return result('Fast food / drive-thru', 'Explicit restaurant type with a configured fast-food brand')

    if re.fullmatch(r'park car park(?: \(.+\))?', typ):
        text = typ + ' ' + normalise_type(row.get('Location Name'))
        value = 'Council park / open space' if osm_match.contains_word(text, 'council') else 'Other'
        return result(value, 'Explicit Park Car Park type' + (' with council wording' if value != 'Other' else ' without council wording'))

    for pattern, value in TYPE_RULES:
        if re.fullmatch(pattern, typ):
            return result(value, f'Explicit type table: {typ!r} maps to {value!r}')

    # Ignore the current category while researching a possible conflict.
    group = discovery.classify_sheet_row({**row, CATEGORY: ''}, categories)
    values = categories.get(group, {}).get('sheet_place_categories', [])
    if group not in ('car_park', 'other') and len(values) == 1:
        return result(values[0], f'Single-valued discovery category {group!r} from a nonblank type', 'medium')
    return '', f'No explicit or single-valued mapping for type {typ!r}', ''


def proposals(rows, categories=None, parks=None):
    categories = categories if categories is not None else discovery.load_categories()
    allowed = set(dropdowns()[CATEGORY])
    tree = STRtree([park['geom'] for park in parks]) if parks is not None else None
    proposed, unclassified, conflicts = [], [], []
    for row in rows:
        value, reason, confidence = category_proposal(row, categories, allowed)
        raw_current = str(row.get(CATEGORY) or '')
        current = raw_current if raw_current.strip() else ''
        if current and current in allowed and (not value or current == value):
            continue
        review = {key: row.get(key, '') for key in HEADERS[:5]}
        review.update({'proposed_place_category': value, 'reason': reason, 'confidence': confidence})
        if parks is not None:
            review['OSM evidence'] = json.dumps(nearby_evidence(row, parks, tree), sort_keys=True)
        if current:
            review['current_place_category'] = row.get(CATEGORY, '')
            review['reason'] = f'Current {current!r}; proposed {value!r}. ' + ('Current value is outside dropdown. ' if current not in allowed else 'Values disagree. ') + reason
        review = {key: str(item or '').translate({0x2013: '-', 0x2014: '-'}) for key, item in review.items()}
        (conflicts if current else proposed if value else unclassified).append(review)
    return proposed, unclassified, conflicts


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
        proposed, unclassified, conflicts = proposals(csv.DictReader(stream), parks=parks)
    output = reserve_output(args.out) if args.out else new_run_dir('propose_categories')
    headers = HEADERS + (['OSM evidence'] if parks is not None else [])
    for file, rows in [('propose_categories.csv', proposed), ('unclassified.csv', unclassified), ('conflicts.csv', conflicts)]:
        write_table(output / file, rows, headers + (['current_place_category'] if file == 'conflicts.csv' else []))
    print(f'proposed={len(proposed)} unclassified={len(unclassified)} conflicts={len(conflicts)} output={output}')
    return 0
