"""Replay owner-provided exceptions.csv source records through discovery.

No sheet access. Uses a local CSV export and postcodes.io's existing cache/client.
The baseline is the table supplied in the 9 Nov 2026 task, not a reconstructed run.
"""
import argparse
import csv
import json
from pathlib import Path

from ferro_parking.discover import plain_dashes, run, write_table
from ferro_parking.london import LondonFilter
from ferro_parking.run_paths import new_run_dir, reserve_output

BASELINE = {'heathrow': (20, 0, 20), 'lcy': (4, 0, 4), 'nr3': (125, 0, 125), 'havering': (27, 0, 27), 'col': (5, 0, 5)}
REVIEW_BASELINE = {'heathrow': (20, 4, 16), 'lcy': (4, 2, 2), 'nr3': (125, 121, 4), 'havering': (27, 0, 27), 'col': (5, 0, 5)}


def replay(sheet_csv, batches, output, london_filter):
    with Path(sheet_csv).open(newline='', encoding='utf-8-sig') as stream:
        sheet_rows = list(csv.DictReader(stream))
    names_by_id = {row.get("Place ID", ""): row.get("Location Name", "") for row in sheet_rows}
    comparison = []
    for name, file in batches.items():
        with Path(file).open(newline='', encoding='utf-8-sig') as stream:
            records = [json.loads(row['source']) for row in csv.DictReader(stream)]
        folder = reserve_output(output / name)
        sources = folder / 'sources.json'
        with sources.open('x') as stream:
            json.dump(records, stream, indent=2)
        summary = run(records, sheet_rows, folder, london_filter)
        with (folder / 'matches.csv').open(newline='', encoding='utf-8') as stream:
            checks = [{'Place ID': match['Place ID'], 'source_name': match['name'],
                       'sheet_name': plain_dashes(names_by_id.get(match['Place ID'], '')),
                       'method': match['method']} for match in csv.DictReader(stream)]
        write_table(folder / 'spot_checks.csv', checks, ['Place ID', 'source_name', 'sheet_name', 'method'])
        baseline = BASELINE[name]
        comparison.append({'batch': name, 'before': {'listed': baseline[0], 'matched': baseline[1], 'exceptions': baseline[2]},
                           'previous_review': dict(zip(('listed', 'matched', 'exceptions'), REVIEW_BASELINE[name])),
                           'after': {key: summary[key] for key in ('listed', 'matched', 'exceptions')},
                           'same_listed_count': summary['listed'] == baseline[0],
                           'majority_matched': summary['matched'] > summary['listed'] / 2})
    with (output / 'comparison.json').open('x') as stream:
        json.dump({'baseline_source': 'Owner-provided 9 Nov 2026 task table', 'batches': comparison}, stream, indent=2)
    return comparison


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet-csv', required=True)
    parser.add_argument('--runs-dir', required=True, help='Root containing 2026-11-09-heathrow, -lcy, -nr3, -havering and -col')
    parser.add_argument('--cache', default='data/cache/postcodes')
    parser.add_argument('--out')
    args = parser.parse_args(argv)
    batches = {name: Path(args.runs_dir) / f'2026-11-09-{name}' / 'exceptions.csv' for name in BASELINE}
    missing = [str(path) for path in batches.values() if not path.is_file()]
    if missing:
        parser.error('Missing batch inputs: ' + ', '.join(missing))
    output = reserve_output(args.out) if args.out else new_run_dir('discovery_replay')
    comparison = replay(args.sheet_csv, batches, output, LondonFilter(args.cache))
    for row in comparison:
        print(f"{row['batch']}: before={row['before']} previous_review={row['previous_review']} after={row['after']} majority={row['majority_matched']}")
    print(f'Replay outputs: {output}')
    return 0 if all(row['same_listed_count'] and row['majority_matched'] for row in comparison) else 1


if __name__ == '__main__':
    raise SystemExit(main())
