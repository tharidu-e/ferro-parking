"""Export the latest Grok research queue locally, never to Google Sheets."""
import argparse
import csv
from . import db, fill, route, readiness
from .category_default import load_osm_rows
from .run_paths import new_run_dir, reserve_output

HEADERS = ['Place ID', 'Row', 'Location Name', 'Street Address', 'Postcode', 'Borough',
           'Place Category', 'Ferro Autopay', 'Parking Charge (£)', 'Official URL',
           'OSM Website', 'Current Can Park?', 'Current Who Can Park', 'Current Cost Type',
           'Missing Fields', 'Priority']
RESEARCH_FIELDS = [fill.CAN_PARK, 'Who Can Park', 'Cost Type', 'Tariff Detail',
                   'Max Stay (mins)', 'Hours (OpenStreetMap opening_hours format)']


def build(conn, osm_rows=None):
    _, routing = db.latest_routing(conn)
    if not routing:
        raise ValueError('Run route first')
    _, rows = db.current_rows(conn)
    positions = {r['place_id']: r['row_index'] + 2 for r in conn.execute(
        'SELECT place_id, row_index FROM raw WHERE import_id = ?', (db.latest_import_id(conn),))}
    out = []
    for row in rows:
        pid = row[fill.PLACE_ID]
        if routing.get(pid) != 'grok':
            continue
        osm = (osm_rows or {}).get(pid, {})
        urls = str(row.get(fill.SOURCE_URLS, '')).split(';')[0].strip()
        out.append({
            'Place ID': pid, 'Row': positions.get(pid, ''),
            **{column: row.get(column, '') for column in HEADERS[2:7]},
            'Ferro Autopay': '', 'Parking Charge (£)': '',
            'Official URL': urls if urls.startswith('http') else '',
            'OSM Website': osm.get('OSM Website', ''),
            'Current Can Park?': row.get(fill.CAN_PARK, ''),
            'Current Who Can Park': row.get('Who Can Park', ''),
            'Current Cost Type': row.get('Cost Type', ''),
            'Missing Fields': '; '.join(column for column in RESEARCH_FIELDS if not readiness.known(row.get(column))),
            'Priority': 1 if ('car park' in row.get(fill.LOCATION_NAME, '').lower()
                              or row.get('Place Category') in route.PUBLIC_CAR_PARK_CATEGORIES) else 2,
        })
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(db.DB_PATH))
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    osm, _ = load_osm_rows()
    rows = build(conn, osm)
    out = reserve_output(args.out) if args.out else new_run_dir('grok_queue')
    with (out / 'grok_queue.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(rows)} rows: {out / "grok_queue.csv"}')
    return 0
