# Ferro parking pipeline

Ferro parking researches parking places for Ferro Maps.
The local SQLite database holds imported Sheet rows, created places and audited changes.
Google Sheet publication requires separate owner approval.

## Setup

Use Python 3.11 or later from the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -q
```

Keep credentials outside Git. Do not print their contents.
Local inputs belong in `data/raw/`:

- `all_london_clean.csv`: an export of the ALL LONDON (clean) Sheet tab.
- `greater-london-latest.osm.pbf`: the London extract from [Geofabrik](https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf).
- Source exports and cached evidence needed by the selected research command.

The Sheet identity and tab names are in `config/sheets.toml`.
For a new database, import a saved export with:

```bash
python -m ferro_parking db-import --sheet-csv data/raw/all_london_clean.csv
```

This writes the local database. It does not write to Sheets.

## How many places remain?

Run this from the project root with the environment active.
It opens the existing database read-only and uses the package's current-row logic.

```bash
python -B - <<'PYCOUNTS'
from collections import Counter
from pathlib import Path
import sqlite3
from ferro_parking import db

with sqlite3.connect(Path(db.DB_PATH).resolve().as_uri() + "?mode=ro", uri=True) as conn:
    conn.row_factory = sqlite3.Row
    _, rows = db.current_rows(conn)
    run, stages = db.latest_routing(conn)
    results = Counter(row.get("Verification Result", "").strip() or "(blank)" for row in rows)
    print("Total places:", len(rows))
    print("Remaining with blank verification:", results["(blank)"])
    print("Verification results:", dict(results))
    print("Latest saved routing:", run)
    print("Saved stages:", dict(Counter(stages.values())))
PYCOUNTS
```

Blank verification measures unfinished research. On-site checks are a separate queue.
A filled result does not mean every parking fact is known or independently verified.
Saved routing can be older than the current data. `route` refreshes it and writes local routing records.

## Common commands

Commands run from the project root. Use `python -m ferro_parking COMMAND --help` for arguments.
Outputs use fresh folders under `data/runs/`. Existing runs remain untouched.

| Purpose | Command | Effect |
|---|---|---|
| List commands | `python -m ferro_parking --help` | Prints help |
| Export local data | `python -m ferro_parking db-export --out NEW_PATH.csv` | Writes a new local export |
| Refresh research stages | `python -m ferro_parking route` | Writes local routing and reports |
| Propose OSM identities | `python -m ferro_parking osm-identity --pbf data/raw/greater-london-latest.osm.pbf` | Writes a plan, never applies |
| Check a database plan | `python -m ferro_parking db-apply --plan PLAN.jsonl` | Dry run |
| Research with a reader | `python -m ferro_parking fetch-fill --key station` | Fetches and caches pages, writes a plan |
| Assess category defaults | `python -m ferro_parking default-fill` | Writes a plan |
| Export the Grok queue | `python -m ferro_parking grok-queue --out NEW_DIRECTORY` | Writes a local queue |
| Assess readiness | `python -m ferro_parking readiness --sheet-csv EXPORT.csv` | Prints legacy readiness measures |
| Prepare publication | `python -m ferro_parking publish --limit 20` | Dry run |

Apply commands change data. Review their plans and follow AGENTS.md and the relevant guide before using `--apply`.
Sheet publication needs plan.json, dry_run.csv, undo.json, six checks and independent second reading before the owner's go.
After publication, independent re-export must show zero mismatches.
Creation proposes identity only. It never establishes parking permission, prices or maximum stay.
The identity matcher proposes Brand, Place Category and Notes only. Filled values remain protected.
Ambiguous matches are held. Evidence stays in the plan and review reports.

## Read only what the task needs

| Task | Document |
|---|---|
| Agent safety and development rules | [AGENTS.md](AGENTS.md) |
| Priorities, blockers and last measured counts | [STATUS.md](docs/STATUS.md) |
| Find existing code before adding a module | [MAP.md](docs/MAP.md) |
| Parking evidence, cell restrictions and publication controls | [Parking rules](docs/PP_rules_and_pilot.md) |
| Create, undo or restore places | [Creation runbook](ADD_PLACES_RUNBOOK.md) |
| Change identity matching | [Identity contract](docs/OSM_IDENTITY_BRIEF.md) |
| Run independent hold reviews | [Reviewer prompt](docs/holds_reviewer_prompt.md) |
| Prepare or import Grok research | [Bot prompt](docs/PP_Validator_prompt_v2_OSM.md), [Importer guide](docs/grok_import.md) |
| Investigate rejected skip rules | [Skip decision](docs/grok_skip.md) |
| Discuss the long-term architecture | [Architecture](docs/PP_architecture_OSM_first.md) |

Do not read every guide at startup. Historical plans and reports are in Git history.
Detailed run evidence remains under `data/runs/`. Current command behavior is in code and `--help`.
