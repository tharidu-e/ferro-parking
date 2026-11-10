"""List public/customer OSM car parks inside London, with no sheet match."""
import argparse
import csv
from pathlib import Path

from . import discovery, osm_match
from .discover import write_table
from .run_paths import new_run_dir, reserve_output


def find_gaps(parks, boroughs, rows):
    from .settings import CONFIG_DIR
    import tomllib
    with (CONFIG_DIR / 'london.toml').open('rb') as stream:
        names = set(tomllib.load(stream)['boroughs'])
    def canonical(name):
        for prefix in ('Royal Borough of ', 'London Borough of ', 'City of '):
            name = name.removeprefix(prefix)
        return name
    boroughs = [borough for borough in boroughs if canonical(borough['name']) in names]
    if not boroughs:
        raise ValueError('No London borough boundaries in extract; cannot prove Greater London membership')
    borough_of = discovery.build_borough_lookup(boroughs)
    points = [(row, discovery.row_point_m(row)) for row in rows if row.get('Place ID')]
    gaps = []
    for park in parks:
        tags = park['tags']
        if tags.get('parking') in ('street_side', 'lane'):
            continue
        if tags.get('access') not in ('yes', 'public', 'permissive', 'customers', 'destination'):
            continue
        borough = borough_of(park['geom'].representative_point())
        if not borough:
            continue
        matched = False
        for row, point in points:
            if point is None:
                continue
            distance = park['geom'].distance(point)
            brand_hit, _ = osm_match.name_score(row, tags, osm_match.brand_key(row))
            if distance <= osm_match.ADJACENT_M and (osm_match.is_car_park_row(row) or not osm_match.other_owner(row, tags, osm_match.brand_key(row))):
                matched = True
            if brand_hit and distance <= osm_match.BRAND_PARK_M:
                matched = True
            if matched:
                break
        if not matched:
            gaps.append({'OSM Link': osm_match.osm_url(park), 'Name': tags.get('name', 'Not published'),
                         'Borough': borough, 'Access': tags['access'],
                         'Latitude': park['ll'].y, 'Longitude': park['ll'].x})
    return gaps


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pbf')
    parser.add_argument('--sheet-csv', required=True)
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    collector = osm_match.Collector()
    collector.apply_file(args.pbf, locations=True)
    boundaries = discovery.DiscoveryCollector(discovery.load_categories())
    boundaries.apply_file(args.pbf, locations=True)
    with open(args.sheet_csv, newline='', encoding='utf-8-sig') as stream:
        rows = list(csv.DictReader(stream))
    gaps = find_gaps(collector.parks, boundaries.boroughs, rows)
    output = reserve_output(args.out) if args.out else new_run_dir('osm_gaps')
    write_table(output / 'gaps.csv', gaps, ['OSM Link', 'Name', 'Borough', 'Access', 'Latitude', 'Longitude'])
    print(f'{len(gaps)} gaps. Output: {output / "gaps.csv"}')
    return 0
