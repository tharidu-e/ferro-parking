"""Summarize local research plans and run the existing database refusal checks."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from datetime import date
from .rules import load_rules
from . import db, fill, plan, category_default, fill_round2
from .run_paths import reserve_output

STAGES = [('station', 'station'), ('better', 'fetcher:better.org.uk'),
          ('thegymgroup', 'fetcher:thegymgroup.com'), ('puregym', 'fetcher:puregym.com'),
          ('default', 'default')]


def plain(value):
    return str(value).replace(chr(8211), '-').replace(chr(8212), '-')


def write_csv(path, rows, headers):
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows({key: plain(row.get(key, '')) for key in headers} for row in rows)


def build(conn, runs):
    _, rows = db.current_rows(conn)
    current = {r[fill.PLACE_ID]: r for r in rows}
    _, routing = db.latest_routing(conn)
    summary, examples, rejected, second_failures = [], [], [], []
    for name, stage in STAGES:
        lines = plan.read_plan(Path(runs) / name / 'plan.jsonl')
        grouped = defaultdict(dict)
        details = {}
        for line in lines:
            grouped[line['place_id']][line['column']] = line['new_value']
            details[line['place_id']] = line
        report = plan.apply_plan(conn, lines, 'research-review', apply=False)
        rejected.extend({'stage': stage, **row} for row in report['rejected'])
        _, second = fill_round2.second_reading({pid: (current[pid], new) for pid, new in grouped.items()}, stage)
        second_failures.extend(second)
        if name == 'default':
            candidates = [r for r in rows if routing.get(r[fill.PLACE_ID]) == stage]
            attempted = len(candidates)
            held = attempted - len(grouped)
        else:
            counts = json.loads((Path(runs) / name / 'summary.json').read_text())['counts']
            attempted = counts['rows attempted']
            held = counts['rows held for a person']
            candidates = [current[pid] for pid in grouped]
        summary.append({'stage': stage, 'rows': attempted, 'plan lines': len(lines),
                        'rows with values': len(grouped),
                        'Can Park?': json.dumps(dict(Counter(new.get(fill.CAN_PARK, '(not set)') for new in grouped.values())), sort_keys=True),
                        'Cost Type': json.dumps(dict(Counter(new.get('Cost Type', '(not set)') for new in grouped.values())), sort_keys=True),
                        'held': held, 'refused': len({r['Place ID'] for r in report['rejected']}),
                        'refusal entries': len(report['rejected']), 'second reading failures': len(second)})
        for row in candidates[:10]:
            pid = row[fill.PLACE_ID]
            values = grouped.get(pid, {})
            line = details.get(pid, {})
            reason = ''
            if not values:
                _, _, reason = category_default.plan_lines_for(row, {}, load_rules(), date.today())
            examples.append({'stage': stage, 'Place ID': pid, 'Location Name': row.get(fill.LOCATION_NAME, ''),
                             'Can Park?': values.get(fill.CAN_PARK, ''), 'Cost Type': values.get('Cost Type', ''),
                             'quote': line.get('quote', ''), 'URL': line.get('source_url', '') or row.get(fill.SOURCE_URLS, ''),
                             'Review Flag': values.get('Review Flag', ''), 'outcome': reason or 'proposed',
                             'values': json.dumps(values, ensure_ascii=True, sort_keys=True)})
    return summary, examples, rejected, second_failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(db.DB_PATH))
    parser.add_argument('--runs', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    conn = db.connect(args.db)
    summary, examples, rejects, second = build(conn, args.runs)
    out = reserve_output(args.out)
    write_csv(out / 'summary.csv', summary, list(summary[0]))
    write_csv(out / 'examples.csv', examples, list(examples[0]))
    write_csv(out / 'refused.csv', rejects, ['stage', 'Place ID', 'column', 'new value', 'reason'])
    write_csv(out / 'second_reading.csv', second, ['Place ID', 'Location Name', 'Fill Type', 'Violations'])
    text = ['Research plans. Nothing applied.', '', '| Stage | Rows | Plan lines | Rows with values | Can Park? | Cost Type | Held | Refused rows |', '|---|---:|---:|---:|---|---|---:|---:|']
    for row in summary:
        text.append('| ' + ' | '.join(plain(row[key]) for key in ['stage', 'rows', 'plan lines', 'rows with values', 'Can Park?', 'Cost Type', 'held', 'refused']) + ' |')
    text += ['', 'Station attempts include station rows already routed to Grok for unresolved names or conflicting evidence.',
             'A flag-only proposal is counted as values, with Can Park? and Cost Type not set.',
             'Default held means no classification or required context. Missing quotes are not invented.',
             'A refusal blocks its entire plan. Counts describe proposals, not approved updates.', '']
    for stage in [s for _, s in STAGES]:
        text += [stage, '', '| Place ID | Name | Can Park? | Cost Type | Quote | URL | Outcome |', '|---|---|---|---|---|---|---|']
        for row in [r for r in examples if r['stage'] == stage]:
            text.append('| ' + ' | '.join(plain(row[key]).replace('|', '/').replace('\n', ' ') for key in ['Place ID', 'Location Name', 'Can Park?', 'Cost Type', 'quote', 'URL', 'outcome']) + ' |')
        text.append('')
    with (out / 'report.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(text))
    for row in summary:
        print(json.dumps(row))
    print(out / 'report.md')
    return 0
