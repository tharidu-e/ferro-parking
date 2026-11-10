import csv
from pathlib import Path
from ferro_parking import db, grok_queue


def test_queue_matches_layout_priorities_ids_and_blanks_owner_fields(tmp_path):
    conn = db.connect(tmp_path / 'db.sqlite')
    db.import_sheet_csv(conn, Path(__file__).parent / 'fixtures/db_sheet_sample.csv')
    conn.executemany("INSERT INTO routing VALUES ('test', ?, 'grok', 'research')", [('PP-000001',), ('PP-000002',), ('PP-000004',)])
    conn.commit()
    rows = grok_queue.build(conn, {'PP-000002': {'OSM Website': 'https://operator.example'}})
    assert len(rows) == 3
    assert set(rows[0]) == set(grok_queue.HEADERS)
    assert all(r['Ferro Autopay'] == r['Parking Charge (£)'] == '' for r in rows)
    assert [r['Row'] for r in rows] == [2, 3, 5]
    assert rows[1]['Priority'] == 1
    assert rows[-1]['Priority'] == 2
    assert rows[1]['OSM Website'] == 'https://operator.example'
