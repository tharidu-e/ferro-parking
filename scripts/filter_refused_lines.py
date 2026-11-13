"""Drop the lines db-apply refuses, so one refusal stops only its own cell.

    python scripts/filter_refused_lines.py <plan.jsonl> <output dir>

One refused line blocks a whole plan. This reads the plan back through
db-apply's own checks, drops the cells it refuses, and writes the rest to
<output dir>/plan.jsonl with every dropped line in held_lines.json. A
'required' refusal, or one db-apply reports against the whole row ('*'),
drops that place, because the row cannot pass without the column and dropping
one cell can leave the rest inconsistent.

Used for every Grok batch on 12 November 2026. It writes no database row: run
db-apply on the output as usual, first as a dry run.
"""

import json, sys
from pathlib import Path
from ferro_parking import db, plan as plan_mod

src, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
lines = [json.loads(l) for l in src.read_text(encoding='utf-8').splitlines() if l.strip()]
conn = db.connect()
held = []
for attempt in range(6):
    rejects = plan_mod.check_plan(conn, lines)[1]
    if not rejects:
        break
    drop_cells, drop_places = set(), set()
    for r in rejects:
        if r['reason'].startswith('required') or r['column'] == '*':
            drop_places.add(r['Place ID'])
        else:
            drop_cells.add((r['Place ID'], r['column']))
        held.append({'place_id': r['Place ID'], 'column': r['column'], 'reason': r['reason']})
    lines = [l for l in lines
             if l['place_id'] not in drop_places
             and (l['place_id'], l['column']) not in drop_cells]
(out_dir / 'plan.jsonl').write_text(
    ''.join(json.dumps(l, sort_keys=True) + '\n' for l in lines), encoding='utf-8')
(out_dir / 'held_lines.json').write_text(json.dumps(held, indent=2), encoding='utf-8')
places = {l['place_id'] for l in lines}
print(f'kept {len(lines)} lines across {len(places)} places; held {len(held)} lines')
