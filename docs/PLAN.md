# Plan to fill the database with London parking places

Written 11 November 2026. This file is the standing plan for every AI session.
Read `AGENTS.md` first, then `docs/STATUS.md` for current counts, then this file.
Do not ask the owner for the next step. Pick the first unblocked step in your track below.
Do not rebuild anything that `python -m ferro_parking --help` already lists.

## The goal and what "done" means

The goal is one database record for every car park in Greater London. Each record carries
evidence-backed parking answers: Can Park?, Who Can Park and Cost Type. Every record is
published to the Sheet.

Done is measured by three numbers in `docs/STATUS.md`, and nothing else:

1. Coverage: every one of the 33 boroughs has a row in the Source imports table.
   Each row shows an official count, a held count and a gap of 0 or an owner-accepted gap.
2. Evidence: the Evidence-supported showable count equals the number of records a
   reader can reach, and every other record is marked on-site, no_evidence or locked.
3. Publication: every applied change is on the Sheet after an owner-approved pilot and
   full write, with zero mismatches on independent re-export.

Accuracy takes priority over coverage. A blank cell is better than a guessed one.

## How each session works

1. Run `git status`. Commit or report any uncommitted work before you start.
2. Read the Owner decisions section below. Skip any step that waits on one.
3. Take the first unblocked step in your track. Finish it, run `python -m pytest tests/ -q`,
   commit it on its own, and update `docs/STATUS.md`.
4. Repeat until every step in your track is blocked or done. Then report with a
   file-by-file summary and the three numbers above.
5. Never write to the Sheet. Never delete, move or overwrite anything under `data/runs/`.
   Never run a recursive delete. Keep Grok payment fields blank.

Two agents run at once. Codex owns coverage. Claude owns evidence and publication.
Codex does not touch `osm_identity.py`, `fill.py`, `plan.py`, `fetch_fill.py`,
`publish.py`, `sources/fetch.py`, `sources/venue.py` or `evaluation.py`.
Claude does not touch `discover.py`, `sources/__init__.py`, `gaps.py`, `osm_places.py`,
`create.py` or the Source imports table.

## Track A: coverage (Codex)

For each borough, in the order of the Source imports table in `docs/STATUS.md`:

1. If `data/raw/` has no official list for it, skip it. The owner downloads lists by hand
   because https fails on this machine. The download links are in `docs/STATUS.md`.
2. If no adapter exists in `sources/__init__.py`, add one that follows `city_of_london`.
3. Run `discover --source <borough> --input <file>`. Read `summary.json`, `matches.csv`
   and `exceptions.csv`.
4. For an exception that is the same place as a record we hold, run `db-duplicate` after
   a dry run. If `db-duplicate` refuses because the record is OSM-created, leave it held,
   add it to Owner decisions, and continue.
5. For an official site we do not hold, create it with `db-create` after a dry run.
   Create it as identity only, with the official page as source URL. Before creation,
   make sure that the name or the coordinates match the official entry.
6. Add or update the borough row in the Source imports table. Commit.

When every downloaded borough is done, run `osm-gaps` and `osm-places` over
`data/raw/greater-london-latest.osm.pbf` for the boroughs with no official list.
Create the identity-only records that the dry run accepts. Record them in the OSM-derived
column, never in the official column.

## Track B: evidence (Claude)

1. Grok import. When a results CSV appears in `data/raw/`, run
   `grok-import --results-csv <file>`. Report mapped, rejected and skipped counts in
   `docs/STATUS.md`. Apply the plan with `db-apply --apply` and a saved undo only after
   the owner says go. The Grok bot runs outside this project. The queue is
   `data/runs/2026-11-11_48/grok_queue/grok_queue.csv`.
2. Categories for held rows. Run `propose-categories` and `category-plan` over the 15
   held M&S rows and the 7 default rows with no Brand. Apply what the dry run accepts.
   Then rerun `fetch-fill` for marksandspencer.com.
3. Validator context. Pass the existing row to `validate_rows` as context. A planner
   then no longer restates a row's own values. The 19 held station rows in
   `data/runs/2026-11-11_94/fetch_fill/held.csv` can then be planned. Add a test. Then
   rerun the station fetcher.
4. New readers. Read `data/runs/2026-11-11_20/osm_identity/counts.csv` and the
   no_evidence routing bucket. Pick each source key with 10 or more rows, no fetcher
   and no entry in `fetch_fill.SKIPPED_HOSTS`. Run `probe` on it and save fixtures.
   If the page states a car park for one site, build a fetcher. Apply each accepted plan.
5. Large formats. The 233 default rows are mostly large supermarkets, hotels and shopping
   centres with no chain rule. Do not guess. Route each one to a reader built in step 4
   or leave it blank.
6. After each step, run `route` and `readiness`. Report legacy and evidence-supported
   readiness separately.

## Track C: publication (Claude, after Track B step 1)

1. Rerun the 20-row pilot in `publish` on current data. Stop and ask the owner for go.
2. After the pilot is written and re-exported with zero mismatches, run the full
   `publish` dry run for updates. Then run the `tranche1-write` dry run for the created
   records that the Sheet does not hold. Stop and ask the owner for go before each write.
3. After every write, re-export, compare, and record the result in `docs/STATUS.md`.

## Owner decisions

An agent never decides these. Leave the item unchanged and continue with the next step.

- PP-009347 Slaney Road, Havering: `db-duplicate` refuses it because it is OSM-created.
  Keeping PP-000818 means retiring PP-009347. Dry run
  `data/runs/2026-11-11_107/db_duplicate/report.json`.
- PP-008072 New Barnet Sainsbury's: proposed retirement.
- PP-005457 and PP-000194 Minories: borough disagreement.
- PP-000214 Waddon, Croydon: 1.9 km pin disagreement.
- Hillingdon: Civic Hall, Hayes Pool, Kingsend South short stay and Falling Lane.
- Seven weak Brand rows: PP-008073, PP-008196, PP-008381, PP-009553, PP-010743,
  PP-011554, PP-012272.
- 184 attachment cases: `data/runs/2026-11-11_6/holds/attachment_cases.csv`.
- Two protected rows: `data/runs/2026-11-11_6/holds/protected_rows.csv`.
- One routing proposal: `data/runs/2026-11-11_12/route/proposals.csv`.
- Every Sheet write, including the 20-row pilot.

## What the owner does

1. Download the borough lists linked in `docs/STATUS.md` into `data/raw/`.
2. Run the Grok bot over the queue file and put the results CSV in `data/raw/`.
3. Answer the Owner decisions above, one line each, in a message to the agent.
4. Say go for each Sheet write after reading the dry run.

## What no tool can do

The 1,176 on-site rows need a visit. The no_evidence rows with no official page need a
person. Report their counts and leave them blank.
