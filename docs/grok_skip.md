# Grok skip filter

Evaluated on 2026-11-06 and not applied, by the owner's decision. No Skip
column was added. The original rule would have skipped 93 researched rows:
45 had fields found and 41 were marked Verified. The tightened rule would
have skipped 39 researched rows: 12 had fields found (30.8%) and 10 were
marked Verified. It selected only 56 unresearched rows, saving about an hour
of Grok time, so the observed loss of useful findings outweighed the saving.
Code and the original and revised run folders are retained unchanged.

Part 1 only. `python -m ferro_parking.grok_skip` reads Grok Queue and Grok
Results and creates a new dated `grok_skip` run folder. It has no write mode.
Use `--out` for a new suffixed folder if the default already exists.
`--snapshot` replays a saved snapshot without network access.

Only unresearched Place IDs qualify. HGV, lorry and coach whole-word name
matches take precedence over URLs and Autopay. Otherwise a row needs both
websites blank, Autopay unchecked, and either the exact private/operator
category or one of the requested whole-word name matches. Category guesses
are not made for blank categories. The category-only rule now keeps any row
with a public-name phrase (Car Park, Multi Storey, NCP, Q-Park, Euro Car Parks,
APCOA, Saba, Council, Station, Shopping Centre or Retail Park), fee=yes,
any nonempty operator tag, or access=yes/public/permissive. Restrictive
keywords and the HGV/coach rule are unchanged and take precedence.

OSM tags come from exact main-sheet OSM IDs in the local extract, reusing
osm_match.Collector, and existing match packets joined by Place ID. These
are conservative keep signals, not claims of public access. The CLI reads
the main sheet for OSM IDs as well as the two Grok tabs. Its default packet
paths are the two 4 November runs; pass --osm-packets explicitly for newer
inputs. Snapshots used by the CLI must include the main sheet.

`python -m ferro_parking.grok_skip_review --help` describes the offline
backtest command. It compares original and revised eligibility on the same
result population, and breaks down the original approved-for-review plan
by keyword versus category only. Five initial test IDs outside the queue
are evaluated from main-sheet category and name when those alone conclusively
rule out skipping; missing website inputs are never invented for a candidate.
The report preserves every would-be-skipped row, its Fields Found, Source
Tier and Evidence Level. These are Grok's reported labels, not revalidated
evidence assessments. Original artifacts remain unchanged.

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
