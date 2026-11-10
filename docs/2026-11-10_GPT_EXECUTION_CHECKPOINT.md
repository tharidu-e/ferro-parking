# GPT execution checkpoint

Stopped on the execution guide critical false-price claim guard. No database
apply, undo, schema mutation, Sheet write or push was performed. Do not repeat
categories-20261110-authorised: it already contains 2,903 changes.

## Verified baseline

Branch feature/db-router; starting HEAD 16984b6. Working tree initially clean.
Cached company tracking comparison: 0 behind, 6 ahead. No fresh remote fetch.
SQLite read-only audit: 7,607 places; latest import 2 at
2026-11-10T13:36:24+00:00, 7,607 rows; published baseline 0 cells.
Legacy readiness: 1,450 showable, 1,055 complete. These are population measures,
not evidence-supported safety counts. Latest routing is route-20261110T191632Z;
full historical and latest stage counts are in baseline.json.
OSM SHA256: 75e4840a9c9d957649664ea85b16df02e2f2d5f20ee3ff810410421639ca2616.
Local extract mtime: 2026-11-02T12:21:21.056214+00:00; not a verified source date.

## Artifacts

All new local artifacts are under data/runs/2026-11-10/gpt_execution_220752/:

- baseline.json: read-only counts, applied runs, imports, routing, OSM hash.
- database_snapshot.json: current headers and records read without schema changes.
- legacy_readiness.json: full legacy counts.
- acton_original.json: 43 original records resolved from tab metadata.
- acton_clean.json: 43 comparison records resolved from tab metadata.
- identity_report.json: provisional name-based mappings and original label counts.
- critical_guard.json: exact offline input and unsafe existing extractor output.

Original snapshot SHA256: 98bc3e46c79f3fbfb3e1702a865863faa1113f12c1cce60b8143060699d6fae3.
Clean snapshot SHA256: d01b82ae389e85c611529dcb2461d2d668b1a26ef80f25c4ee911ccefe873c76.
Recorded labels: 18 official clear, 9 official partial, 6 Maps only, 10 no info;
22 Confirmed, 20 Corrected, 1 Needs on-site check. These are not proven accuracy.
Current normalizer provisionally maps 41/43 original-to-clean, including stripped
parenthetical descriptions. Unresolved: Sainsbury's Ealing Acton Town Station
Local; Southfields Recreation Ground. Mapping is diagnostic, not apply authority.

## Stop guard and restart

VenueFetcher('puregym.com').values('Free parking for 60 mins. Personal training
costs £40 per hour.') incorrectly produces Free then paid and a £40.00 parking
hourly tariff. The price belongs to personal training. Fix sources/venue.py
charge association with regression fixtures before any extractor apply.
Also review penalty-charge amounts, central finished/personal locks including
undo, unknown verifier identities, station missing-coverage denial, unresolved
station label, atomic apply/rebuild and stale undo. Astra found these gaps in
read-only review. No live fixes have been applied.

Resume step 1: validate mappings with identity evidence, translate original
field headers explicitly, freeze and assess per-field official source evidence,
then replay existing extractors without expected answers or human notes.
No field accuracy, supported coverage or throughput measurements exist yet.
The new evaluator is offline diagnostic infrastructure only; it does not bind
cases to a mutation plan and must never authorise an apply by itself.

Steps 2-7 remain unexecuted: no research applies, insertion implementation,
discovery pilot/batch, official-source expansion, duplicate mutation, final queue
or publication dry run. No new records; places remain 7,607. No append pilot is
ready for owner approval. Publication licensing sign-off remains outstanding.
There are no new applied run IDs or before/after mutation comparisons.
No backup was required because no apply was attempted.

## Roles and changed files

Lead retained parent runtime and owned integration and tests. GPT-6.1 Sol worker
implemented evaluation.py and its tests. GPT-6 Astra independently reviewed
original snapshots, current source and final evaluator. A separate Sol worker
inspected lock paths without edits. Model agreement was not source evidence.

- src/ferro_parking/evaluation.py: frozen-page replay, field diagnostics,
  conservative unresolved mapping and provenance checks; no network or DB writes.
- tests/test_evaluation.py: 25 local fixture regressions.
- docs/2026-11-10_GPT_EXECUTION_CHECKPOINT.md: this continuation record.

Baseline suite: 1,273 passed. Expanded suite: 1,298 passed before final diagnostic
flag rename; final suite result and commit are recorded in commit continuation.
