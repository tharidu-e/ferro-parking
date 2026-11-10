"""Read-only showable and complete counts from a local sheet CSV."""
import argparse
from collections import defaultdict
import csv
import math
import re

from .fill import CAN_PARK, SOURCE_URLS
from .validation import HOURS

MISSING = {'', 'Unknown', 'Not published'}


def known(value):
    return str(value or '').strip() not in MISSING


def usable_pin(row):
    try:
        lat, lon = float(row.get('Latitude', '')), float(row.get('Longitude', ''))
        return math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
    except (ValueError, TypeError):
        return False


def bars(row):
    showable = (row.get(CAN_PARK) in ('Yes', 'Conditional') and usable_pin(row)
                and known(row.get('Who Can Park')) and known(row.get('Cost Type')))
    has_source = known(row.get(SOURCE_URLS)) and str(row.get(SOURCE_URLS, '')).strip() != 'Not applicable'
    def time_known(column):
        value = str(row.get(column) or '').strip()
        return known(value) or (value == 'Not published' and has_source)
    complete = showable and time_known(HOURS) and time_known('Max Stay (mins)') and known(row.get('Tariff Detail'))
    return bool(showable), bool(complete)


def postcode_district(postcode):
    match = re.fullmatch(r'([A-Z]{1,2}\d[A-Z\d]?)(?:\s*\d[A-Z]{2})?', str(postcode or '').strip().upper())
    return match[1] if match else 'Unknown'


def counts(rows):
    def empty():
        return {'rows': 0, 'showable': 0, 'complete': 0}
    total, boroughs, districts = empty(), defaultdict(empty), defaultdict(empty)
    for row in rows:
        showable, complete = bars(row)
        for counter in (total, boroughs[str(row.get('Borough') or '').strip() or 'Unknown'],
                        districts[postcode_district(row.get('Postcode'))]):
            counter['rows'] += 1
            counter['showable'] += showable
            counter['complete'] += complete
    return {'total': total, 'by_borough': dict(boroughs), 'by_district': dict(districts)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet-csv', required=True)
    args = parser.parse_args(argv)
    with open(args.sheet_csv, newline='', encoding='utf-8-sig') as stream:
        result = counts(csv.DictReader(stream))
    def print_count(label, values):
        print(f"{label}: rows={values['rows']} showable={values['showable']} complete={values['complete']}")
    print_count('Total', result['total'])
    for title, key in (('Borough', 'by_borough'), ('Postcode district', 'by_district')):
        print(title)
        for name, values in sorted(result[key].items()):
            print_count(name, values)
    return 0
