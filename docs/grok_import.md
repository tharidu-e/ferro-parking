# Grok detail-pass importer

Part 1 was evaluated and not applied. This importer never adds a Skip column
or changes the Grok tabs.

Run `.venv/bin/python -m ferro_parking.grok_import`. It reads every current
Grok Results row, the main sheet and the template dropdown validations.
It writes a new `data/runs/<London date>/grok_import` folder exclusively.
For replay, use `--snapshot PATH`; use `--out NEW_PATH` for later runs.
Existing run artifacts are never overwritten. The planning command has no
write mode. After explicit approval, grok_apply provides a separate apply
command with fresh ID/snapshot checks and the existing writer.

The value map is `config/grok_value_map.toml`. Direct mappings, conditional
mapping inputs, tariff transformation patterns and allowed dropdowns are
configured there. Unknown values, including Signed hours, are not guessed.
Tariffs must match the requested templates, with closed, ordered contiguous
bands and two-decimal pound prices. Unsupported tariffs reject the entire
row, even if other mappings succeeded. En/em dashes in any proposed cell,
including merged existing Notes, also reject the row rather than silently
rewriting captured text. JSON preserves exact inputs with ASCII escapes;
CSV and Markdown display typography uses plain hyphens.

Rows match by Place ID. Duplicate/unknown IDs reject; finished rows skip;
reviewers not in the explicit automation allowlist skip as person-locked.
Four manually checked pilot rows overlap the finished-row count in the
6 November input. Skipped rows are not mapped and are excluded from mapping
counts. Counts for individual reject and skip reasons may overlap.

The importer reuses page_fill.consistency_checks, fill's protected-column
guard, capture_extract.matches_r9, and fill_round2.second_reading and
to_write_plan. Location Status is an explicit task-authorized exception to
fill's stricter OSM identity lock; no owner-protected column is proposed.
The existing main-sheet consistency checks and a second reading are run,
followed by exact dropdown, source-strength, specificity, date, numeric,
tariff and typography checks. Free/public/price claims with Fields Found
None reject, even if Grok preserved an earlier guess under an official tier.
An Unclear specificity becomes Site-specific only when an official source
also identifies this site by non-generic name or postcode in its evidence.

Decision Reason is preserved and prefixed with `Route Grok detail pass:`
when it lacks a route label. This names the importer route, without claiming
that Grok followed research route A-E. Existing Notes, flags and URLs are
preserved and merged. Minutes Spent, Fields Found and identity columns are
not imported. Verified By is Grok (detail pass); Verified Date is Researched
Date. Verification Result comes only from Proposed Result.

The API also accepts `verified_by="Code (page fetch)"` for Part 3. It still
uses all the same row checks and skip locks. Filling Verification Result
means rerunning the importer skips that row, including previous imports.

## Artifacts

- plan.json: accepted rows only, existing writer format.
- undo.json: exact target values for every proposed cell.
- dry_run.csv: per-cell target before/after.
- grok_rejects.csv: every rejected row and all reasons.
- grok_skipped.csv: finished and reviewer-locked rows and reasons.
- mapping_audit.csv: every mapping value change, including rejected rows.
- mapped_rows.json: full mapped before/after values and errors.
- report.json and report.md: counts, all mapping rules including zeros, and
  ten samples selected to cover different mappings. Accepted means proposed,
  not written. Evidence labels are imported assertions validated by these
  checks; source pages are not researched again by this command.
- samples.json: full source and proposed values for the ten samples.
- second_reading.json: existing second-reader results.
- snapshot.json and value_map.json: exact inputs and mapping configuration.
- validation_plan.json: add Reported to the main-sheet Evidence Level
  dropdown, preserving its other options. Existing validations are read
  by header name and compared with the configured allowed values.

## Approval and subsequent apply

Stop after presenting the dry run. There have been no writes to the sheet,
including its dropdowns. Approval covers accepted plan rows and the Reported
dropdown addition, not rejected rows or changes to Grok Results.

After explicit go, use a fresh read to resolve Place IDs and recheck finished
and person locks and source/target values. If inputs changed, stop and prepare
a new reviewed plan. The generic existing `write` command currently checks
target values by saved row, so it must not be used on this plan without that
ID-aware preflight. Reuse the existing writer, which writes Verification
Result in a separate final batch. Apply the Reported validation first only
after approval. Preserve the new undo copy and the original plan.

Independently re-export the full main sheet after applying and compare all
planned values plus unplanned cells against the pre-write snapshot, resolving
rows by Place ID. Require zero mismatches and stop on any discrepancy.
The existing sync.verify_append is append-specific, not an update-plan
comparison, so it is not used for this dry run. The independent comparison
is a required post-apply step, not claimed as completed by planning.

## Approved initial application

On 2026-11-06 the owner explicitly approved the initial 100 accepted rows
and the Reported dropdown extension. `grok_apply` resolved IDs afresh,
rechecked reviewer/finished locks, source and full target snapshots, undo
values, consistency checks and second reading before any mutation. It
preserved dropdown rule properties, applied the extension, and used
fill._apply_write and sheets.write_cells, with Verification Result last.
Result: 100 rows, 3,174 cells, zero aborted rows, zero independent re-export
mismatches. Evidence is in data/runs/2026-11-06/grok_import_apply.

The existing sync comparison module now supports update-plan comparisons
alongside append verification. Formula-mode exports compare every unplanned
underlying cell and formula exactly, including protected formulas, while
permitting their calculated results to update from the newly imported data.
The original dry run and undo artifacts were not overwritten.
