"""Publication safety, using the actual guarded writer with an in-memory sheet."""
import copy
import csv
import json
from pathlib import Path

import pytest
from ferro_parking import db, publish, sheets

FIXTURE = Path(__file__).parent / 'fixtures/db_sheet_sample.csv'
PID = 'PP-000004'


@pytest.fixture
def setup(tmp_path):
    conn = db.connect(tmp_path / 'db.sqlite')
    db.import_sheet_csv(conn, FIXTURE)
    headers, rows = db.current_rows(conn)
    for index, row in enumerate(rows, 2):
        row['_sheet_row'] = index
    conn.execute("INSERT INTO changes(run_id,place_id,column_name,old_value,new_value,stage,applied_at) VALUES ('categories', ?, 'Place Category', '', 'Restaurant / pub / cafe', 'default', '2026-11-10')", (PID,))
    conn.commit()
    return conn, headers, rows


def test_metadata_publication_has_six_checks_and_undo(setup):
    conn, headers, rows = setup
    report = publish.build(conn, headers, rows)
    assert len(report['checks']) == 6
    assert all(report['checks'].values())
    assert report['plan'][0]['new'] == {'Place Category': 'Restaurant / pub / cafe'}
    assert report['undo'][0]['old'] == {'Place Category': ''}
    assert not report['second_reading']


def test_drift_blocks_every_row_before_planning(setup):
    conn, headers, rows = setup
    rows[-1]['Place Category'] = 'Other'
    report = publish.build(conn, headers, rows)
    assert report['drift'] and not report['plan']


@pytest.mark.parametrize('change', ['finished', 'person', 'duplicate', 'missing'])
def test_row_locks_and_identity_guards(setup, change):
    conn, headers, rows = setup
    if change == 'finished':
        rows[-1]['Verification Result'] = 'Confirmed'
    elif change == 'person':
        rows[-1]['Verified By'] = 'Deshan'
    elif change == 'duplicate':
        rows.append(dict(rows[-1]))
    else:
        rows.pop()
    if change == 'duplicate':
        with pytest.raises(ValueError):
            publish.build(conn, headers, rows)
    else:
        result = publish.build(conn, headers, rows)
        assert result['refused'] or result['drift']


def test_pilot_selection_and_invalid_limit(setup):
    conn, headers, rows = setup
    assert len(publish.build(conn, headers, rows, limit=1, place_ids=[PID])['plan']) == 1
    with pytest.raises(ValueError):
        publish.build(conn, headers, rows, limit=0)
    with pytest.raises(ValueError):
        publish.build(conn, headers, rows, place_ids=['PP-nonexistent'])


def fake_sheet(monkeypatch, rows, headers, out, extra_change=False):
    calls = []
    monkeypatch.setattr(sheets, 'read_tab', lambda *a, **kw: (headers, copy.deepcopy(rows)))
    def read_cells(service, cells, headers):
        return {(r, c): next(x for x in rows if x['_sheet_row'] == r).get(c, '') for r, c in cells}
    def write_cells(service, headers, cells):
        assert (out / 'undo.json').is_file()
        assert (out / 'checks.json').is_file()
        calls.extend(cells)
        for r, c, value in cells:
            next(x for x in rows if x['_sheet_row'] == r)[c] = sheets._cell_value(c, value)
        if extra_change:
            rows[0]['Notes'] = 'Unexpected edit'
    monkeypatch.setattr(sheets, 'read_cells', read_cells)
    monkeypatch.setattr(sheets, 'write_cells', write_cells)
    return calls


def test_dry_run_never_writes_sheet_or_published_table(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    out = tmp_path / 'dry'; out.mkdir()
    calls = fake_sheet(monkeypatch, rows, headers, out)
    report = publish.execute(conn, object(), out)
    assert report['plan'] and calls == []
    assert conn.execute('SELECT COUNT(*) FROM published').fetchone()[0] == 0


def test_apply_requires_exact_saved_approval_and_resolves_rows_again(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    report = publish.build(conn, headers, rows)
    report['plan'][0]['sheet_row'] = 999
    approval = tmp_path / 'approved.json'; approval.write_text(json.dumps(report['plan']))
    out = tmp_path / 'apply'; out.mkdir()
    calls = fake_sheet(monkeypatch, rows, headers, out)
    publish.execute(conn, object(), out, approved=approval)
    assert calls == [(5, 'Place Category', 'Restaurant / pub / cafe')]
    assert json.loads((out / 'compare.json').read_text())['mismatches'] == []
    assert conn.execute('SELECT COUNT(*) FROM published').fetchone()[0] == 1
    assert publish.build(conn, headers, rows)['plan'] == []


def test_changed_approval_is_refused_before_writing(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    approval = tmp_path / 'approved.json'; approval.write_text('[]')
    out = tmp_path / 'apply'; out.mkdir()
    calls = fake_sheet(monkeypatch, rows, headers, out)
    with pytest.raises(ValueError, match='approved plan'):
        publish.execute(conn, object(), out, approved=approval)
    assert not calls


def test_independent_compare_catches_unrelated_edit_without_recording_publish(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    approval = tmp_path / 'approved.json'; approval.write_text(json.dumps(publish.build(conn, headers, rows)['plan']))
    out = tmp_path / 'apply'; out.mkdir()
    fake_sheet(monkeypatch, rows, headers, out, extra_change=True)
    with pytest.raises(ValueError, match='compare failed'):
        publish.execute(conn, object(), out, approved=approval)
    assert conn.execute('SELECT COUNT(*) FROM published').fetchone()[0] == 0


def test_apply_cli_requires_saved_approval_before_authentication(monkeypatch):
    monkeypatch.setattr(sheets, 'get_service', lambda: pytest.fail('must not authenticate'))
    with pytest.raises(SystemExit):
        publish.main(['--apply'])


def test_protected_database_change_cannot_be_published(setup):
    conn, headers, rows = setup
    conn.execute("INSERT INTO changes(run_id,place_id,column_name,old_value,new_value,stage,applied_at) VALUES ('bad', ?, 'Ferro Autopay', '', 'Yes', 'default', '2026-11-10')", (PID,))
    conn.commit()
    with pytest.raises(AssertionError):
        publish.build(conn, headers, rows)


def test_writer_rechecks_locks_immediately_before_mutation(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    approval = tmp_path / 'approved.json'
    approval.write_text(json.dumps(publish.build(conn, headers, rows)['plan']))
    out = tmp_path / 'apply'; out.mkdir()
    calls = fake_sheet(monkeypatch, rows, headers, out)
    original = sheets.read_cells
    def changed_lock(service, cells, headers):
        result = original(service, cells, headers)
        for key in result:
            if key[1] == 'Verification Result':
                result[key] = 'Confirmed'
        return result
    monkeypatch.setattr(sheets, 'read_cells', changed_lock)
    with pytest.raises(ValueError, match='compare failed'):
        publish.execute(conn, object(), out, approved=approval)
    assert calls == []
    assert conn.execute('SELECT COUNT(*) FROM published').fetchone()[0] == 0


def test_partial_parking_publish_uses_applied_context_and_records_numeric_readback(setup, tmp_path, monkeypatch):
    conn, headers, rows = setup
    fields = {'Brand': 'Pret', 'Can Park? (Yes/No/Conditional)': 'Conditional',
              'Who Can Park': 'Customers only', 'Cost Type': 'Unknown',
              'Source Tier': 'Official site - text', 'Specificity': 'Site-specific',
              'Evidence Detail (what the source shows)': 'Parking is available. PCN £100.',
              'Decision Reason': 'Route B: official branch page'}
    raw = json.loads(conn.execute('SELECT json FROM raw WHERE import_id = 1 AND place_id = ?', (PID,)).fetchone()[0])
    raw.update(fields)
    conn.execute('UPDATE raw SET json = ? WHERE place_id = ?', (json.dumps(raw), PID))
    rows[-1].update(fields)
    conn.execute("INSERT INTO changes(run_id,place_id,column_name,old_value,new_value,stage,applied_at) VALUES ('page', ?, 'PCN (Penalty Charge Notice) amount (£)', '', '100.00', 'default', '2026-11-10')", (PID,))
    conn.commit()
    report = publish.build(conn, headers, rows)
    assert not report['refused'] and not report['second_reading']
    approval = tmp_path / 'approved.json'; approval.write_text(json.dumps(report['plan']))
    out = tmp_path / 'apply'; out.mkdir()
    fake_sheet(monkeypatch, rows, headers, out)
    publish.execute(conn, object(), out, approved=approval)
    assert conn.execute("SELECT value FROM published WHERE column_name LIKE 'PCN%' ").fetchone()[0] == '100'
    assert not publish.build(conn, headers, rows)['drift']
    assert not publish.build(conn, headers, rows)['plan']


@pytest.mark.parametrize('restored,exit_code', [(100, 0), (101, 1)])
def test_numeric_undo_readback_accepts_formatting_but_refuses_another_value(monkeypatch, restored, exit_code):
    from ferro_parking import fill
    column = 'PCN (Penalty Charge Notice) amount (£)'
    def read(service, cells, headers):
        return {(r, c): PID if c == 'Place ID' else restored for r, c in cells}
    monkeypatch.setattr(sheets, 'read_cells', read)
    monkeypatch.setattr(sheets, 'write_cells', lambda *args: None)
    result = fill._apply_undo(object(), ['Place ID', column],
                              [{'place_id': PID, 'sheet_row': 2, 'old': {column: '100.00'}}], True)
    assert result == exit_code
