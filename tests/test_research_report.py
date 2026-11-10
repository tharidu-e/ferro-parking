import json
from pathlib import Path
from ferro_parking import db, research_report, plan


def test_research_report_counts_plans_refusals_and_no_change_examples(tmp_path):
    conn = db.connect(tmp_path / 'db.sqlite')
    db.import_sheet_csv(conn, Path(__file__).parent / 'fixtures/db_sheet_sample.csv')
    conn.execute("INSERT INTO routing VALUES ('test', 'PP-000004', 'default', 'research')")
    conn.commit()
    runs = tmp_path / 'runs'
    for name, _ in research_report.STAGES:
        folder = runs / name; folder.mkdir(parents=True)
        plan.write_plan(folder / 'plan.jsonl', [])
        (folder / 'summary.json').write_text(json.dumps({'counts': {'rows attempted': 0, 'rows held for a person': 0}}))
    summary, examples, rejected, second = research_report.build(conn, runs)
    assert len(summary) == 5
    assert summary[-1]['rows'] == summary[-1]['held'] == 1
    assert summary[-1]['plan lines'] == 0
    assert len(examples) == 1 and examples[0]['quote'] == ''
    assert not rejected and not second
    assert conn.execute('SELECT COUNT(*) FROM changes').fetchone()[0] == 0
