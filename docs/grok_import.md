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
configured there. Signed hours maps explicitly to Car park hours; unknown
values are not guessed.
Tariffs must match the requested templates, with closed, ordered contiguous
bands and two-decimal pound prices. Unsupported tariffs reject the entire
row, even if other mappings succeeded. As authorized on 2026-11-06, Notes,
Review Flag, Rules Summary, Evidence Detail and Decision Reason normalize
en/em dashes to plain hyphens, including existing merged Notes and flags.
Dropdown values and all other columns never receive this normalization.
Non-plain dashes outside the authorized free-text columns still reject.
JSON preserves exact inputs with ASCII escapes;
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
  dropdown if absent, and propose Third-party only for Evidence Type if
  absent, preserving all existing options. Its changes list contains only
  the extensions still required. Existing validations are read
  by header name and compared with the configured allowed values.
- out_of_scope.csv: rows explicitly marked HGV/coach out of scope in Notes
  or Review Flag, from either Grok or the target row. These are included in
  reject counts and never enter the plan. A car park merely prohibiting HGVs
  is not considered out of scope.
- scope_audit.json and previously_imported_out_of_scope.csv: scope flags on
  rows imported under an earlier approval, outside the current selected IDs.
  Those finished rows are reported only and never changed by the dry run.

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

## Revised dry run on the original rejects only

Use `--rejects-from data/runs/2026-11-06/grok_import/grok_rejects.csv --out NEW_DIR`.
The importer reads the sheet afresh, then selects only the original reject
Place IDs. Missing IDs abort rather than silently reducing the population.
The saved snapshot keeps the full read-only context, while the report and
plan cover only selected rows. Every remaining reject reason includes up to
five samples in report.md (all available samples when fewer than five).

When Fields Found contains findings and the mapped strongest Source Tier is
Google search / third-party, Parkopedia or Google Maps - reviews, Evidence
Type becomes Third-party only. Source Tier, Evidence Level and safety rules
are not upgraded or relaxed. Empty/None findings and strong sources do not
receive this label. The new Evidence Type value is a proposal until approved;
the revised dry run makes no sheet or dropdown changes.

## Final importer pass and Grok Bot handoff

Use `--unimported-only --out NEW_DIR` for the final dry run. It reads all
current Grok Results rows and excludes rows already finished by Grok (detail
pass), matching by Place ID. Finished rows from other reviewers and personal
locks are still reported as skipped. Duplicate target IDs are never hidden
by this selection. Stop for approval before applying any final candidates.

After that final import is approved, applied and independently compared,
Grok Bot will write directly to ALL LONDON (clean) rather than staging new
rows in Grok Results for this importer.

Application metadata reads request uncompressed HTTP content because repeated
dropdown rules can exceed the HTTP client's decompression limit. When a
legacy row has a shorter dropdown list than the template, the approved value
is appended to that row's existing list; existing options, order, strictness
and input messages are preserved.

The approved second batch was applied on 2026-11-06: 47 rows, 1,496 cells,
zero aborted rows and zero independent re-export mismatches. Third-party only
was added to Evidence Type. Evidence is in grok_import_rejects_apply.
The subsequent fresh final dry run read 199 Grok Results rows, excluded 147
completed Grok imports, skipped 18 rows already finished by other passes,
and rejected the remaining 34 (including two HGV/coach scope exclusions).
No further rows passed. Evidence is in grok_import_final; no final-dry-run
rows were written, and the handoff remains pending the owner's next go.
