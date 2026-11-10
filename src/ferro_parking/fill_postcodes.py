"""Prepare offline nearest-centroid postcode review CSVs; never write to Sheets."""
import argparse
from bisect import bisect_left, bisect_right
import csv
import math
import re

from shapely.geometry import Point
from shapely.strtree import STRtree

from .discover import write_table
from .fill import GEO_PRECISION, PLACE_ID, POSTCODE
from .osm_match import to_m
from .readiness import usable_pin
from .run_paths import new_run_dir, reserve_output
from .sync import EARTH_RADIUS_M, haversine_m, normalize_postcode

HEADERS = [PLACE_ID, 'Location Name', GEO_PRECISION, 'Geo Source', POSTCODE,
           'proposed_postcode', 'distance_m', 'method', 'reason']


def load_directory(path):
    with open(path, newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        headers = {name.strip().casefold(): name for name in (reader.fieldnames or [])}
        def header(*aliases):
            for alias in aliases:
                if alias in headers:
                    return headers[alias]
            raise ValueError(f'Postcode directory needs a column named one of {aliases}')
        code_col, lat_col, lon_col = header('postcode', 'pcds'), header('lat', 'latitude'), header('lon', 'longitude')
        records = []
        for line, row in enumerate(reader, start=2):
            code = normalize_postcode(row.get(code_col, '') or '')
            match = re.fullmatch(r'([A-Z]{1,2}\d[A-Z\d]?|GIR)(\d[A-Z]{2})', code)
            if not match or not usable_pin({'Latitude': row.get(lat_col), 'Longitude': row.get(lon_col)}):
                raise ValueError(f'Invalid postcode or centroid coordinates on directory line {line}')
            records.append({'postcode': match[1] + ' ' + match[2], 'lat': float(row[lat_col]), 'lon': float(row[lon_col])})
    return PostcodeDirectory(records)


class PostcodeDirectory:
    """Spatial seed, then exact haversine ranking inside a provably safe latitude belt."""
    def __init__(self, records):
        self.records = sorted(records, key=lambda row: row['lat'])
        self.latitudes = [row['lat'] for row in self.records]
        self.tree = STRtree([to_m(Point(row['lon'], row['lat'])) for row in self.records])

    def nearest(self, lat, lon):
        if not self.records:
            return None
        seed = self.records[int(self.tree.nearest(to_m(Point(lon, lat))))]
        upper = haversine_m(lat, lon, seed['lat'], seed['lon'])
        # Great-circle distance is at least the meridional latitude distance.
        # Every possible closer centroid is therefore inside this belt. The
        # projected tree only supplies an upper bound, never the final answer.
        delta = math.degrees(upper / EARTH_RADIUS_M) + 1e-9
        left, right = bisect_left(self.latitudes, lat - delta), bisect_right(self.latitudes, lat + delta)
        scored = [(haversine_m(lat, lon, row['lat'], row['lon']), row['postcode']) for row in self.records[left:right]]
        distance = min(item[0] for item in scored)
        codes = {code for metres, code in scored if abs(metres - distance) <= 1e-6}
        return (next(iter(codes)) if len(codes) == 1 else '', distance)


def postcode_proposals(rows, directory, max_distance_m=250):
    if not math.isfinite(max_distance_m) or max_distance_m < 0:
        raise ValueError('max-distance-m must be a finite non-negative number')
    proposed, skipped = [], []
    for row in rows:
        if str(row.get(POSTCODE) or '').strip() or not usable_pin(row):
            continue
        result = {key: row.get(key, '') for key in HEADERS[:5]}
        result.update({'proposed_postcode': '', 'distance_m': '', 'method': '', 'reason': ''})
        if str(row.get(GEO_PRECISION) or '').strip().casefold() == 'postcode centroid':
            result['reason'] = 'postcode centroid pin; reverse lookup would be circular'
        else:
            closest = directory.nearest(float(row['Latitude']), float(row['Longitude']))
            if closest is None:
                result['reason'] = 'no postcode directory loaded'
            else:
                code, distance = closest
                result.update({'distance_m': f'{distance:.1f}', 'method': 'nearest centroid'})
                if distance > max_distance_m:
                    result['reason'] = 'nearest postcode is too far'
                elif not code:
                    result['reason'] = 'nearest postcode is ambiguous; equidistant centroids'
                else:
                    result.update({'proposed_postcode': code, 'reason': 'Nearby centroid is a review candidate, not proof of the site postcode'})
        result = {key: str(value or '').translate({0x2013: '-', 0x2014: '-'}) for key, value in result.items()}
        (proposed if result['proposed_postcode'] else skipped).append(result)
    return proposed, skipped


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet-csv', required=True)
    parser.add_argument('--postcodes-csv', required=True)
    parser.add_argument('--out')
    parser.add_argument('--max-distance-m', type=float, default=250)
    args = parser.parse_args(argv)
    directory = load_directory(args.postcodes_csv)
    with open(args.sheet_csv, newline='', encoding='utf-8-sig') as stream:
        proposed, skipped = postcode_proposals(csv.DictReader(stream), directory, args.max_distance_m)
    output = reserve_output(args.out) if args.out else new_run_dir('fill_postcodes')
    write_table(output / 'fill_postcodes.csv', proposed, HEADERS)
    write_table(output / 'skipped.csv', skipped, HEADERS)
    print(f'proposed={len(proposed)} skipped={len(skipped)} output={output}')
    return 0
