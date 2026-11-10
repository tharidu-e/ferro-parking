"""Publish applied database changes through the existing guarded sheet writer.

Dry run by default. Saved plan approval is mandatory for --apply. Identity is
resolved again by Place ID, drift is checked first, and the existing writer
writes Verification Result last and reads back. A separate full export compare
must pass before recording the published baseline. No inserts or deletes.
"""
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db, fill, fill_round2, sheets, sync, validation
from .grok_apply import unique
from .run_paths import new_run_dir, reserve_output


def baseline(conn):
    raw = db.raw_rows(conn, db.latest_import_id(conn))
    values = {(pid, col): value for pid, (_, row) in raw.items() for col, value in row.items()}
    values.update({(r['place_id'], r['column_name']): r['value'] for r in conn.execute('SELECT * FROM published')})
    return values


def build(conn, headers, rows, limit=None, place_ids=None):
    """Drift first, followed by six controls and an independent second reading."""
    if limit is not None and limit < 1:
        raise ValueError('--limit must be positive')
    if len(headers) != len(set(headers)) or fill.PLACE_ID not in headers:
        raise ValueError('Missing or duplicate headers')
    live = unique(rows)
    old = baseline(conn)
    desired = db.owned_changes(conn)
    selected = set(place_ids or [])
    available = {pid for pid, _ in desired}
    if selected - available:
        raise ValueError('Requested Place IDs have no applied database changes')
    wanted = sorted(selected or available)
    if limit is not None:
        wanted = wanted[:limit]
    wanted = set(wanted)
    # A drift on a selected owned cell blocks the entire publication.
    drift = []
    for (pid, column), change in desired.items():
        if pid not in wanted:
            continue
        if pid not in live or column not in headers:
            drift.append(f'{pid}: missing row or column {column}')
        elif str(sheets._cell_value(column, live[pid].get(column, ''))) != str(sheets._cell_value(column, old.get((pid, column), ''))):
            drift.append(f'{pid}: {column} differs from the last published/imported value')
    if drift:
        return {'plan': [], 'undo': [], 'drift': drift, 'refused': [], 'checks': {'drift': False}, 'second_reading': []}

    plan, undo, refused, contexts = [], [], [], {}
    _, effective = db.current_rows(conn)
    current = {row[fill.PLACE_ID]: row for row in effective}
    for pid in sorted(wanted):
        target = live[pid]
        new = {col: current[pid].get(col, '') for p, col in desired if p == pid
               and str(sheets._cell_value(col, current[pid].get(col, ''))) != str(sheets._cell_value(col, target.get(col, '')))}
        if not new:
            continue
        if target.get(fill.VERIFICATION_RESULT, '').strip():
            refused.append(f'{pid}: finished row')
            continue
        if target.get(fill.VERIFIED_BY, '') not in ('', 'PP (validation)'):
            refused.append(f'{pid}: reviewer is protected by the existing writer')
            continue
        entry = {'place_id': pid, 'sheet_row': target['_sheet_row'],
                 'name': target.get(fill.LOCATION_NAME, ''), 'new': new,
                 'old': {col: target.get(col, '') for col in new}}
        fill.validate_write_columns([entry])
        # Validate the complete applied research context, but only actual new
        # columns for category-only plans. Old text is never silently rewritten.
        context = dict(new)
        if set(new) - {'Place Category', 'Brand'}:
            context = {col: current[pid].get(col, '') for col in fill.RESEARCH_COLUMNS
                       if current[pid].get(col, '') != ''}
        errors = [f for f in validation.validate_rows([{**entry, 'new': context}], plan=True)
                  if not validation.is_warning(f)]
        if errors:
            refused.extend(f"{pid}: {e['rule']}: {e['message']}" for e in errors)
            continue
        contexts[pid] = context
        plan.append(entry)
        undo.append({'place_id': pid, 'sheet_row': target['_sheet_row'], 'old': entry['old']})
    second_input = {e['place_id']: (live[e['place_id']], contexts[e['place_id']]) for e in plan}
    _, second = fill_round2.second_reading(second_input, 'publish')
    checks = {'identity': True, 'columns': True, 'locks': not refused,
              'drift': True, 'validation': not refused, 'second_reading': not second}
    return {'plan': plan, 'undo': undo, 'drift': [], 'refused': refused,
            'checks': checks, 'second_reading': second}


def save(out, report):
    for name, value in [('plan.json', report['plan']), ('undo.json', report['undo']), ('checks.json', report)]:
        with (out / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, ensure_ascii=True)
    with (out / 'dry_run.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['Place ID', 'column', 'old', 'new'])
        writer.writeheader()
        for entry in report['plan']:
            for column, value in entry['new'].items():
                writer.writerow({'Place ID': entry['place_id'], 'column': column,
                                 'old': entry['old'][column], 'new': value})


def execute(conn, service, out, limit=None, place_ids=None, approved=None):
    headers, rows = sheets.read_tab(service, value_render_option='FORMULA')
    report = build(conn, headers, rows, limit, place_ids)
    save(out, report)
    if report['drift'] or report['refused'] or report['second_reading']:
        return report
    if approved is None:
        return report
    approved_plan = json.loads(Path(approved).read_text(encoding='utf-8'))
    canonical = lambda entries: {e['place_id']: {'new': e['new'], 'old': e['old']} for e in entries}
    if canonical(approved_plan) != canonical(report['plan']):
        raise ValueError('Fresh publication differs from the approved plan')
    # The writer checks locks, identities and every undo cell again immediately
    # before writing. Resolve current positions from the fresh export, never the
    # row numbers recorded in the approved file.
    result = fill._apply_write(service, headers, report['plan'],
                               {e['sheet_row']: e for e in report['undo']}, apply=True)
    after_headers, after = sheets.read_tab(service, value_render_option='FORMULA')
    mismatches = sync.compare_updates(headers, rows, after_headers, after, report['plan'])
    with (out / 'compare.json').open('x', encoding='utf-8') as stream:
        json.dump({'mismatches': mismatches, 'writer_exit': result}, stream, indent=2)
    if result or mismatches:
        raise ValueError('Publication readback or independent export compare failed')
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    for entry in report['plan']:
        for column, value in entry['new'].items():
            conn.execute('INSERT OR REPLACE INTO published VALUES (?, ?, ?, ?)',
                         (entry['place_id'], column, str(sheets._cell_value(column, value)), now))
    conn.commit()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=str(db.DB_PATH))
    parser.add_argument('--out')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--place-ids', nargs='+', help='Place IDs, separated by spaces or commas')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approved-plan', help='Previously reviewed plan.json, required with --apply')
    args = parser.parse_args(argv)
    if args.apply and not args.approved_plan:
        parser.error('--apply requires --approved-plan after owner approval')
    ids = [pid for value in (args.place_ids or []) for pid in value.split(',') if pid]
    conn = db.connect(args.db)
    out = reserve_output(args.out) if args.out else new_run_dir('publish')
    report = execute(conn, sheets.get_service(), out, args.limit, ids,
                     args.approved_plan if args.apply else None)
    print(f"{len(report['plan'])} planned rows, {len(report['drift'])} drift errors, "
          f"{len(report['refused'])} refusals, {len(report['second_reading'])} second-reading failures. {out}")
    return 1 if report['drift'] or report['refused'] or report['second_reading'] else 0
