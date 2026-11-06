# Grok skip filter

Part 1 only. `python -m ferro_parking.grok_skip` reads Grok Queue and Grok
Results and creates a new dated `grok_skip` run folder. It has no write mode.
Use `--out` for a new suffixed folder if the default already exists.
`--snapshot` replays a saved snapshot without network access.

Only unresearched Place IDs qualify. HGV, lorry and coach whole-word name
matches take precedence over URLs and Autopay. Otherwise a row needs both
websites blank, Autopay unchecked, and either the exact private/operator
category or one of the requested whole-word name matches. Category guesses
are not made for blank categories.

The run contains a complete input snapshot, skip list, per-cell dry run,
plan, undo data and counts with an independent recomputation. Run folders
and files are created exclusively, so existing artifacts are never overwritten.
JSON preserves source text using ASCII escapes; CSV reports use plain hyphens.

Parking-answer consistency checks and fill eligibility checks apply to the
main sheet, not queue markers. They cannot validate this change: the queue
does not contain parking-answer or verification columns. The queue planner
instead validates headers and unique Place IDs, excludes researched IDs,
enforces Autopay exceptions, asserts protected-column safety, emits only
Skip=Yes, and independently recomputes the selected IDs. Do not describe
the main-sheet checks as having passed for a queue plan.

## Applying after the owner's explicit go

The plan is a queue-specific envelope, not input to the main-sheet `write`
command. Never send it to that command, which targets ALL LONDON (clean).

1. Read both live tabs again. Match by Place ID, not saved sheet row.
   Abort for changed headers, duplicate IDs, reordered/missing queue IDs,
   changed queue data, an existing Skip header, or newly researched selected
   IDs. If research progressed, prepare a new plan for approval.
2. Add only the Skip header after the last existing header using
   `sheets.write_cells` with the extended header list. Resolve the physical
   column from those header names; do not hard-code a letter.
3. Write only Yes markers to the selected IDs using `sheets.write_cells`.
   The newly added column is blank for all other queue rows. Do not insert,
   delete, sort, reorder, or rewrite whole rows. Do not change Grok Results.
4. Read back the whole queue independently. Compare headers, row sequence,
   every original cell, and every Skip cell against the snapshot plus plan.
   Require zero mismatches. Save the readback and comparison in new files.
   Stop on any mismatch.

The existing `sync.verify_append` is for new main-sheet rows and is not
usable for a queue column. Reuse `sheets.read_tab` for the independent full
re-export instead. Undo requires separate approval: restore the Skip cells
and blank the header using the saved undo data, without deleting a column.
