# Plan to fill London parking information

Updated 11 November 2026. Read `AGENTS.md`, `docs/STATUS.md`, then this plan.
STATUS.md owns current counts, inputs and holds. This file owns execution order.
Use `python -m ferro_parking --help` and subcommand help before changing code.
Take the first unblocked task in your track. Continue past held cases without
asking the owner for next steps. Read only the documents that task needs.

## Goal and progress

The goal remains one record for every London car park, supported parking
answers, and approved Sheet publication. Keep these three measures in STATUS.md:

1. Coverage: 33 borough rows with official counts and zero or owner-accepted gaps.
   Unknown counts, old lists and limited lists remain explicit limits.
2. Evidence: evidence-supported showable records, separate from legacy counts.
   A showable record needs supported Can Park?, Who Can Park and Cost Type.
   Remaining evidence gaps stay on-site, no_evidence or locked.
3. Publication: applied changes published after approval, with zero mismatches
   on independent re-export. An unperformed comparison is not zero mismatches.

## Driver information standard

Check each place against this standard, using evidence for the exact site:

| Information | What to record when supported |
|---|---|
| Location | Address and postcode for the parking place; distinguish a nearby venue or head office. |
| Can Park? | Parking available, conditional access or an explicit statement of no parking, using existing allowed values. |
| Who Can Park | Eligible users and conditions: customers, guests, members, visitors or public access. |
| Cost Type | Free, paid or free then paid, including any purchase or validation requirement. |
| Maximum stay | Site-specific limit and any no-return restriction. |
| Tariffs and extra charges | Published rates, charging periods and mandatory additional charges, with their conditions. Keep penalties separate from the cost of parking. |
| Hours and access | Opening hours and stated access restrictions that affect parking use. |
| Evidence | Supporting quote, source URL and date checked, with existing evidence metadata. |

Each item has a supported answer, an explicit unknown in the research outcome,
or a justified not-applicable outcome. Use only existing allowed cell values;
a research gap does not authorize a placeholder write or a new column. Unknown
never means free, unlimited, unrestricted or no extra charge. Preserve protected
payment and captured-text columns; use the existing permitted field mapping.

Research complete for now means available useful sources were checked, supported
answers saved and remaining gaps recorded with a reason and revisit trigger.
Move on when a source is silent or blocked; revisit for new evidence or access.
Driver information complete means location and all applicable information needed
to use that car park safely are supported. An unknown applicable tariff or limit
is still a gap, even if research is complete for now. Explicit no-parking answers
remain useful, with dependent fields handled under the existing rules.

Save partial answers without waiting for every detail. Report these two outcomes
separately from existing showable and complete counts. This standard does not
change readiness calculations, validation, finished-row locks or Verification
Result rules. The controls in `docs/PP_rules_and_pilot.md` still apply.

## Working order

1. Run `git status`. Preserve and report unrelated work. Commit only your files.
2. Read the owner holds. Leave them unchanged and continue with other records.
3. Before a web request or code change, inspect the current database and saved
   inputs. Name the target Place IDs and missing driver answers, or show the
   reviewed candidate is a new place. Reuse downloaded pages, captured text and
   accepted evidence first. Skip records meeting the driver information standard
   unless evidence is stale or conflicting. Fetch only pages needed for a named gap;
   repeat a download only with a recorded reason. Use batches of up to 25 places.
4. Review the batch, save its outcome and undo, update STATUS.md and commit the
   finished task. Repeat until your remaining tasks are done or blocked.
5. Keep exceptions separate from routine processing. A refusal blocks that plan,
   not other valid plans. Use the existing checks to prepare a fresh accepted
   plan when needed. Never bypass a refusal or apply a rejected plan.

Keep source files, quotes and run evidence. Keep `data/runs/` append-only.
Keep Grok payment fields blank. No retirement or deletion without owner approval.
Sheet writes always require the existing six controls and the owner's explicit go.

## Ownership

Codex owns Track A. Claude owns Tracks B and C unless the owner reassigns them.
Codex does not edit `osm_identity.py`, `fill.py`, `plan.py`, `fetch_fill.py`,
`publish.py`, `sources/fetch.py`, `sources/venue.py` or `evaluation.py`.
Claude does not edit `discover.py`, `sources/__init__.py`, `gaps.py`,
`osm_places.py`, `create.py` or the Source imports table.
Both agents keep shared status edits small. Commit with explicit file paths.

## Track A: coverage

Coverage work resumes when a usable new list, changed extract or new evidence
can resolve a gap. Counting an existing site is coverage progress, not a new
place or a filled parking answer. Keep these counts separate.

1. Use local official lists first. Try a missing official download once and
   save its response. A blocked response or incomplete index is an input hold.
   Retry only when new input or a changed access method gives a reason.
2. Reuse an existing adapter or generic import. Add an adapter only when the
   actual input format prevents import. Read MAP.md and the owning module first.
3. Run `discover`. Read its summary, matches and exceptions. Review exact site
   names, coordinates and source URLs. A shared postcode alone is not identity.
4. Resolve an existing-site match in the review. Use `db-duplicate` only for
   two database records proved to be the same place. If an OSM-created record
   refuses that command, leave it held, record the owner decision and continue.
5. Use `db-create` only after an exact name or coordinate review and accepted
   dry run. Create identity only, with the official source URL. Invent no pin.
6. Update the borough's count, scope, gap and OSM-derived column. Commit separately.

Reuse saved OSM candidates when the extract and eligibility rules are unchanged.
Run the existing creation dry run against the current database. Re-extract with
`osm-gaps` and `osm-places` when their inputs or rules change. Apply only accepted
reviewed identities. Never reactivate an inactive reference to increase coverage.

## Track B: parking answers

The default task is to fill existing places from usable exact-site sources.
A new reader, a category fix or a refactor is an exception to that routine.
Missing Grok results do not block work through existing readers. This applies to
council sites, supermarkets, shopping centres, hotels, gyms, leisure centres and
station car parks, private operator sites, retail parks, hospitals and other
categories already held. Most are existing records: check before proposing a new
place. Review every category for missing standard information and newly available
or conflicting details. A previously applied reader or filled Verification Result
does not prove all details are present; keep locked rows as reported holds.

Use current records and existing reports to record each category's checked,
improved, research-complete-for-now, driver-information-complete and held counts.
Mark categories not yet checked explicitly; do not treat a missing count as zero.
This is a batch review using existing tools, not a new reporting-system task.

1. Start with the named batch and prerequisites in STATUS.md. After that batch,
   select up to 25 unfinished, unlocked places with missing supported answers
   and a usable registered reader. Use current database rows and routing.
   Refresh `route` when database changes make the saved routing stale.
2. Run `fetch-fill --key <registered-key> --limit 25`. Reuse cached pages when
   suitable. Skip already processed unchanged pages and measured blocked or
   silent sources. Rerun them when evidence, input or reader behaviour changes.
3. Review every proposed answer against its exact-site quote and page. Retain
   the quote, URL, retrieval time and page hash. Apply only supported fields.
   Missing price or stay does not withhold a supported availability answer.
   Follow the existing field mapping. Parking existence alone proves neither
   public access nor free parking. Silence never proves Can Park? No.
4. Use the existing validation and `db-apply` dry run. Apply an accepted reader
   plan within existing authorization, with its saved undo. Keep finished rows,
   personal locks and protected columns unchanged. Hold unsafe rows separately.
5. Record the batch outcome, refresh routing after applied changes and measure
   readiness. Count supported partial answers as well as newly showable places.
   Record unresolved standard items and the next evidence needed. Move to the
   next useful batch instead of repeatedly reading unchanged failures.
6. If a specific data gap blocks a useful batch, use existing tools to resolve
   it. Use `propose-categories` and `category-plan` for supported category gaps,
   then rerun the affected reader. Inspect current data before assuming an old
   hold remains open. Leave unsupported categories and Brand blank.
7. If no existing reader can advance the next batch, use the engineering gate
   below. Probe at most five exact-site pages first. A blocked or silent source
   stays held. One stated fact supports that field only, not a complete record.

When Grok results arrive in `data/raw/`, import them as a separate batch with
`grok-import --results-csv <file>`. Report mapped, rejected and skipped counts.
Grok apply still needs the owner's go and a saved undo. The external bot queue is
`data/runs/2026-11-11_48/grok_queue/grok_queue.csv`. Do not manufacture results.

## Engineering gate for all tracks

1. Name the affected places, the failed operation and the next batch it blocks.
   Reproduce the failure from saved input before changing package code.
2. Check the command index, MAP.md and owning module. Reuse the existing path.
   Choose the smallest fix that lets the affected batch proceed.
3. For a new reader, first show exact-site facts on saved pages and a measured
   batch that can use it. Reuse the fetch, evidence and apply controls.
4. Add a regression test for a reproduced bug. Test changed rules or new reader
   behaviour with real failure cases. Reuse existing tests for unchanged paths.
   Documentation edits and routine data batches need no new test files.
5. Run focused checks during the change and `python -m pytest tests/ -q` before
   reporting the finished task. Repeat the full suite only after another change,
   a failure or a concurrent update makes the previous result insufficient.
6. Rerun the affected batch and report the useful answers unlocked. If it still
   makes no progress, record the blocker and continue elsewhere. Broader cleanup
   waits for a separate task. Correctly withholding an unsupported claim is valid.

The validator-context issue belongs here only when it blocks a selected batch.
Its current example is the 19 held station rows in STATUS.md. Preserve the same
validation rules and locks. A code change is complete only after batch replay.

## Track C: publication

Prepare publication when a reviewed batch is ready. It does not depend on all
Grok work or all parking fields being complete. An unknown field stays unknown.

1. Use the existing `publish` dry run for updates and `tranche1-write` dry run
   for new records. Keep these plans separate. Prepare a selectable 20-row pilot.
2. Keep the six checks, saved undo and independent second reading. Show counts,
   five examples and refusals. Wait for the owner's explicit go for each write.
3. After an approved write, independently re-export and require zero mismatches.
   Stop on a mismatch. Record results in STATUS.md before any further write.

## Reporting

Lead each batch report with places checked, distinct places improved, supported
answers added, newly showable places and cases held. Include failed requests
and unchanged places. Unknown fallbacks, no-op writes and repeated evidence do
not count as new supported answers. Separate new places from improved records.
Show five reviewed examples and the main refusal reasons. Keep detailed rows
in the run files. The owner does not need to inspect code or tests to follow work.
End each task with the three goal measures, test result and file-by-file summary.

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

1. Supply the borough inputs still blocked in `docs/STATUS.md`, if available.
   Save downloaded lists in `data/raw/`.
2. Run the Grok bot over the queue file and put the results CSV in `data/raw/`.
3. Answer the Owner decisions above, one line each, in a message to the agent.
4. Say go for each Sheet write after reading the dry run.

## What no tool can do

The 1,176 on-site rows need a visit. The no_evidence rows with no official page need a
person. Report their counts and leave them blank.
