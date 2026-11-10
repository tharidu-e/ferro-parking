# GPT execution guide for London parking data

Prepared 10 November 2026. This document is an execution handoff, not a record
of completed expansion. Preparing it does not authorise database changes.
The owner can start the work by pasting the prompt below in a new session.

Section order superseded on 10 November 2026. Work the steps in the order set
by `EXECUTION_CHECKLIST.md` in the repository root. That file resequences this
guide so the database insert runs before the research work. The content of each
section below stays correct. The checklist also names the gates it cut and the
gates that stay.

## Start the session

Open this repository on `feature/db-router`. Select GPT-6.1 Sol for the main
coding session. Use GPT-6 Astra for difficult evidence decisions and a separate
review of safety-critical changes. These are recommended roles, not a claim
that either model has passed the parking evaluation.

A parent session does not need to switch its own model. If the runtime exposes
model selection for subagents, it can assign a supported GPT model to a new
agent. If it does not, use the selected GPT model in separate contexts and
record that limitation. Model agreement never substitutes for source evidence.

The lead owns integration, full tests, commits and all live database actions.
Workers can own separate modules and tests. Give each worker an explicit file
boundary. Only the lead changes shared CLI wiring or runs database applies.
Reviewers read the original evidence and final diff, not just the author's
explanation. Tests use local fixtures and no network.

## Paste this prompt

```text
Implement and run docs/GPT_LONDON_EXECUTION_GUIDE.md, starting with the ordered
steps below, in the ferro-parking repository on feature/db-router.

Use GPT models only. GPT-6.1 Sol is recommended for implementation and GPT-6
Astra for difficult evidence and independent review, where available. You may
delegate separate tasks to subagents. If model selection is unavailable, use
separate contexts with the available GPT model and report the limitation.

Read AGENTS.md, CLAUDE.md, docs/HANDOVER.md, docs/PP_rules_and_pilot.md,
docs/2026-11-10_IMPLEMENTATION_REPORT.md, docs/DB_EXPANSION_PLAN.md and this
guide. Follow this guide's explicit amendments to the previous expansion spec.

I authorise implementation and the guarded local database applies described
here, including local pilot inserts and subsequent eligible batches. Back up
the database before each apply. Do not push. Do not write anything to Google
Sheets. Produce the final publish dry run and stop for my explicit approval
of a 20-row pilot. Do not ask me to build a new evaluation set: reuse the
existing 43 manually checked Acton records and their evidence.

Proceed through the steps without routine approval questions. Stop on a
named safety guard, an unresolvable failing test, or a required unavailable
capability. Missing optional sources can be reported and skipped. Respect
runtime permission requirements; this prompt does not bypass them. Save a
precise continuation state if an external blocker prevents completion.

Do not count a source URL or a passing schema validator as proof of a claim.
Do not mark unknowns correct merely because they avoid making a claim.
Finish with the report specified in the guide, full tests and local commits.
```

## Rules for the execution

- Existing protected columns, finished rows and personally verified rows stay
  unchanged. Preserve all Tharidu rows, including prefix variants, and other
  personal checks such as Deshan's pilot. Report their issues as proposals.
- Never propose or write the four owner payment/countdown fields. New records
  leave them blank. New-record identity fields may be set only at creation.
  Existing identity or address corrections go to proposals, not automatic edits.
- Use the current exact dropdown values, existing validators, second reading,
  writers, routing, OSM evidence rules and source adapters. Do not create a
  second implementation of an existing component.
- Every substantive database mutation uses an auditable plan and db-apply,
  including insertions, source attachments and duplicate metadata. Cache and
  routing writes retain their existing documented operational interfaces.
- Before each apply, create a unique timestamped consistent SQLite backup in
  ~/ferro-parking-backups/. Use the SQLite backup API or an equivalently safe
  method that includes committed WAL state. Verify it opens and passes an
  integrity check. A failed backup blocks apply.
- No row/file deletion, history rewriting, push or overwriting run artifacts.
  Allocate a new run directory for every attempt. Undo appends reversal state;
  IDs remain reserved. Keep credentials out of logs, artifacts and commits.
- Use plain hyphens in authored text. Preserve original source bytes in caches
  and reference snapshots; normalise dashes only in proposed cell text.
- Fetch at most once per second per domain, including retries. Use a normal
  User-Agent, bounded timeouts/retries, caching and no bot-protection workaround.
  Record failed fetches and cache status separately from extracted answers.
  A 403, 429, timeout or challenge is not evidence that parking is unavailable.

## 0. Verify the starting state

Check the branch, working tree, available tools, actual CLI help and full test
suite. Preserve unrelated work. The relevant remote is company; origin is the
older personal remote. Report remote comparison if obtainable, but do not push.

Read the database without schema mutation for the initial audit. Record active
place count, applied runs, latest import, routing counts, legacy readiness and
published baseline. Historical expectations are 7,607 places and the category
run categories-20261110-authorised with 2,903 changes. Verify them rather than
assuming they are current. Record the OSM extract hash and available date.

Completion: fresh baseline artifacts, cleanly understood local changes and a
passing full test suite. Do not repeat an already completed apply on resume.

## 1. Reuse the Acton checks before expanding

Read the spreadsheet through the existing Sheets client, without writes:
spreadsheet 1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o,
tab ID 184241746, Acton (test run). Also read Acton (clean) as the formatted
comparison. Resolve titles from metadata. Both had 43 rows on 10 November;
both are reference material, not two independent sets of checks.

The original has 43 checks by Tharidu and 43 evidence notes. Evidence labels
are 18 official clear, 9 official partial, 6 Google Maps only and 10 no info.
There are 22 Confirmed, 20 Corrected and one Needs on-site check. Preserve
source values, reviewer, evidence notes, URL, checked date and snapshot hash.
These counts describe recorded labels, not independently proven correctness.

Build a repeatable local evaluation command. Reconcile original, clean and DB
records using identity evidence, not row positions. There were only 35 exact
normalised-name matches from original to clean; report unresolved mappings.
Do not silently pair the remaining eight by ordering. Use names, address,
postcode, source identity and coordinates to support unique mappings.

Evaluate individual fields: Can Park?, Who Can Park, Cost Type, Tariff Detail,
Max Stay and relevant operating restrictions. Classify reference fields as
supported, unsupported, conflicting or unresolved. An official-page label does
not prove every field. Keep original labels immutable; save any proposed
reference correction separately with evidence and the reason.

For example, Tesco Acton has Free based on chain policy and an evidence note
mentioning paid parking on Google Maps. This is a conflict to investigate,
not a target answer to teach the model. A temporary closure is also distinct
from a site having no car park. Preserve the human row and report issues.

Hide expected answers and human notes from the extractor. Give it the source
page and minimal identity information. The reviewer compares its claims with
the reference and source. Fresh page changes are source drift, not automatically
extraction failures. Cache source versions and evaluate replay on frozen pages.

Report correct supported values, wrong values, unsupported positive claims,
abstentions and unevaluable fields with denominators, by field. Report supported
answer coverage separately so an all-Unknown extractor cannot pass as accurate.
Critical false claims about access, Free, prices or stay limits block that
extractor's apply until fixed and retested. Unresolved reference disputes are
held and excluded from accuracy denominators, with their count visible.

The 43 cases are a regression reference, not a representative London benchmark.
Do not describe cases previously used to develop rules as an unseen holdout.
Grok-derived additions are research candidates, not independent ground truth.
For fetchers outside Acton's coverage, add offline source fixtures for negative,
ambiguous, contradictory and blocked-page cases as well as successful cases.

Completion: reference snapshot, identity mapping report, field assessment,
replayable evaluation and automated regression tests. The owner need not label
new examples. Unsupported cases remain unresolved rather than model-certified.

## 2. Fix and apply eligible existing research

Address the earlier review findings in package code, with regression tests:

- Enforce finished-row and personal-verification locks centrally for every
  mutation type. Existing recognition of only Tharidu is insufficient. Unknown
  verifier identities must be held for review unless explicitly recognised as
  an automated producer; do not guess that a human name is an automation.
- Associate charge statements with parking. Gym membership prices and penalty
  charges are not parking tariffs. A genuine later parking charge means Free
  then paid if the tariff fits the existing templates; otherwise use Unknown,
  Notes and Review Flag. A free period never becomes Max Stay without a separate
  explicit stay limit. Customer parking does not permit unrelated driver waiting.
- Keep the station denial guard: blank Charges (as published), blank or Not
  published Tariff Detail, and fresh OSM coverage proving no mapped car park
  within 50 m. Missing OSM coverage is not a negative match. Otherwise hold the
  answer, add the specified conflict flag and route to the research queue.
- Use National Rail Brand only for values from that station's own official
  page. Use the cached official station list, with no guessed URL slugs.
  Replace the misleading unresolved label not National Rail with Station
  lookup unresolved. Preserve routing to research; do not classify the venue
  as outside National Rail merely because lookup failed.
- Successful page extraction uses Verified By Code (page fetch), Evidence Level
  Verified, Source Tier official and Specificity Site-specific where supported
  by the schema. These metadata do not grant unquoted fields verified status.

Re-run route, all four fetchers and default-fill against the current database.
Run validation, independent second reading and the relevant evaluation. Apply
eligible whole-row plans through db-apply after backup. Refusals must not be
bypassed by removing required lines or weakening checks. Re-plan eligible rows
separately when other rows are refused; save every refusal with its reason.
Report the formerly held 60 stations using current outcomes, not old counts.

Completion: run IDs, exact applied cells, refusals, per-field source support
and independent before/after export comparisons, with protected rows unchanged.

## 3. Implement audited database insertion

Extend the existing authoritative record model and db-apply, not just derived
places/parking tables. Keep discovered records distinct from imported sheet
snapshots. Rebuild, export, route and next_place_id must include active new
records. Source identities need a stable association with the created place.

Allocate unique IDs transactionally across imports, created records, reversed
records and reservations. Revalidate the plan's source identities, fingerprint
and ID allocation at apply; stale plans must fail safely. Within-batch duplicate
checks and repeated-run checks are required. An interrupted or repeated apply
must not create a second record. Undo is logged deactivation, never deletion
or ID reuse. Reimporting a sheet containing a published new ID must reconcile
that identity instead of creating a second authoritative record.

Validation under the write lock, allocation, source associations, audit and
derived-state updates must commit atomically. Refactor existing helper commits
where necessary; do not leave a committed log with stale derived tables.
Undo must detect later superseding changes and refuse stale reversal rather
than overwriting newer evidence. Cover this with transaction failure tests.

Keep insertion validation separate from updating protected identity fields.
Creation establishes identity; it does not establish parking permission. Initial
research values must pass existing OSM-only rules. Verification Result stays
blank. Store source provenance and retain compatibility with existing plans.

Completion: offline integration tests for create/apply/undo/rebuild/export,
stale and concurrent allocation, repeated inputs, recovery, protected fields
and later sheet reimport. Existing exported rows remain exactly unchanged except
for separately approved attachment or research plans, which are compared apart.

## 4. Discover and insert eligible OSM car parks

Reuse the existing extract reader and discovery boundary geometries. Inspect
london.py before reuse: postcode classification alone is not a geometry boundary
check. Test coordinate containment against the Greater London boundary.
Include amenity=parking nodes, ways and relations inside Greater London.
Exclude access private/no/residents/permit/employees/delivery/staff/students;
street_side/lane/on_street/kerb/shoulder parking; individual parking_space;
HGV/coach/lorry-only parking; and disused/abandoned/proposed/construction sites.
Interpret actual access restrictions conservatively, including ambiguous or
conditional tags. Do not infer public permission from a name or polygon size.

Eligible access values are yes/public/permissive/customers. With access missing,
require name, operator, fee, capacity at least 10, multi-storey/underground type
or polygon area at least 500 square metres. These qualify a candidate identity,
not a public-access claim. Calculate area and distance in a suitable projected
coordinate system and handle relations and holes correctly.

Match exact typed OSM identity first. A pin within 30 m is a possible duplicate,
not proof: different businesses, levels and adjacent car parks can be nearby.
Require supporting identity evidence before linking. Same normalised name plus
nonblank postcode also needs ambiguity checks. Hold uncertain matches. Check
relations/member ways and multiple source features representing one facility.
Attach an OSM identity to an existing blank field only on a confident unique
match and when row protections permit it, through its own audited plan.

Use OSM name, else operator car park, else Car park, <addr:street>, else Car park
(unnamed). Use the source point for nodes. For polygons use a validated centroid
or a documented point inside the polygon if the centroid falls outside. Mark
this as car-park geometry, not an entrance. Do not move existing pins.
Use existing postcode/borough lookups with provenance; a nearby postcode is an
estimate, not an exact address. Leave unsupported exact postcodes blank.
Use council, operator or venue category only when tags support the association.
Retain relevant tags, operator and capacity without inventing parking answers.
New records get OSM source URL and creation provenance; owner fields stay blank.

Print counts after each filter and matching outcome. If the final proposed new
count is below 300 or above 15,000, stop before live insertion and report why.
This is an anomaly guard, not proof that filters are correct. Do not manipulate
filters to meet the range. First exercise a diverse local pilot of up to 20,
with backup, apply, rebuild, independent export comparison and repeat planning.
Then apply the remaining eligible batch when the pilot checks pass. No extra
approval is needed for these local actions once the start prompt is issued.

Completion: exact active-count increase, source/category breakdown, zero
unexplained changes to existing rows and zero repeated accepted insertions.

## 5. Add official sources and research new records

Confirm TfL's current car-park endpoint, availability and terms using official
documentation. Skip with a reason if a required key is unavailable. Reuse working
existing discovery adapters, including City of London where supported. Feed
them through the same identity matching and insertion plans. TfL can support
site-specific facts it actually publishes; an official list is not proof of
every parking field. Existing matches receive blank-field proposals only,
subject to row protections and field evidence checks.

Route the full active database, then run registered fetchers and default-fill.
Probe three distinct pages for unsupported source keys with at least 30 routed
rows. Build a small reader only if the source supports reliable branch-specific
extraction and reuse of the existing reader makes sense. Three positive probes
are a feasibility check, not validation: add negative, missing, contradictory,
unrelated-price and blocked-page fixtures before applying its answers.

Each proposed research field retains its own supporting quote, canonical URL,
retrieval time and cached page hash. Quotes must support the exact claim and
exact site. A row-level Verified label does not upgrade unsupported fields.
Apply only plans passing all controls and relevant evaluation. A blocked page
or unresolved conflict goes to the research queue without guessed answers.
Use the existing grok stage/queue naming for compatibility even though this
execution uses GPT models. Queue creation is not completed research.

Completion: source results, rejects, applied run IDs, coverage and uncertainty
counts. Report fetch time, cache hits, requests, status codes and rows per minute
from actual measurements, distinguishing cached replay from fresh throughput.

## 6. Duplicates, pins and readiness

Build or reuse propose-duplicates and propose-pins as review reports. Automatic
duplicate_of requires either the same typed OSM identity, or identical useful
normalised name plus nonblank postcode and pins within 15 m, with no evidence
of distinct facilities. Generic names are not useful identity proof. Hold
ambiguities. Keeper selection prioritises human verification and stronger
site-specific evidence over populated-field count. Protected-row changes remain
proposals. Check self-links, cycles and already-linked groups. Persist duplicate
metadata through audited plans, undo and rebuild. Never move an existing pin.

Keep legacy readiness counts for before/after comparability. Add separate
evidence-supported counts and explicit unknown/contradictory counts. Field
population alone does not mean safe to display. Do not silently change app
visibility policy to expose OSM-only places as verified public parking.

Write a fresh local grok_queue.csv for every active row routed to grok. Use the
existing exact column layout: Place ID, Row, Location Name, Street Address,
Postcode, Borough, Place Category, Ferro Autopay, Parking Charge (£), Official
URL, OSM Website, Current Can Park?, Current Who Can Park, Current Cost Type,
Missing Fields, Priority. Payment columns stay blank. Row stays blank for
database-only places, since no sheet row exists. Priority 1 is a car park name
or council/operator category; 2 otherwise. Sort named public car parks first
within priority, with a stable Place ID tiebreaker. Never guess public access.

Completion: duplicate/pin proposals, fresh routing and readiness comparisons,
queue counts and clear distinction between discovered, researched and supported.

## 7. Build publication, dry run only

Extend the existing publisher to support new-row append plans, reusing sync.py
and tranche1_write.py helpers where appropriate. Read fresh sheet state, check
IDs and cell drift, and preserve existing row order and protected values.
Support limit and Place ID filters across updates and appends. Distinguish a
database-only ID from an imported row missing from the live sheet; the latter
must not be silently appended. Plan any required grid growth explicitly.

Produce plan.json, dry_run.csv and undo.json before any future write. Define
non-destructive append recovery, including partial-write/retry behaviour, without
deleting rows. Never append the same Place ID twice. Preserve payment columns
and do not invent owner formulas. Use the existing guarded writer, six controls,
independent second reading, Verification Result last, readback and independent
re-export comparison. Exercise these with offline tests; do not call --apply.

Check OSM attribution/licensing obligations against primary sources and report
any unresolved product licence sign-off. Do not treat it as resolved merely
because the data can be fetched. Include it in publication blockers if unresolved.

Completion: a full publish dry run and separate selectable 20-row pilot, with
cell counts, append counts, drift and blockers. Stop for the owner's go.

## Final report and continuation record

Commit each finished task after the full test suite passes. Never push. Save
checkpoint records with exact artifact paths, commit hashes, applied run IDs,
remaining steps and blockers so a restart cannot repeat a live apply.

The final report must include:

- Step, rows touched, plan lines applied, refused, run ID and commit.
- Places before/after, new records by source/category, inactive duplicates.
- Routing before/after and legacy versus evidence-supported readiness counts.
- Acton field-level results, denominators, unsupported claims, abstentions,
  unresolved references and cases outside its coverage.
- Ten examples per fetcher and default-fill with outcome, quote and URL where
  evidence exists. For no-answer cases explicitly report absent evidence.
- Fetch failure handling, real throughput and cache use.
- Queue size and the amount of research still unresolved.
- Publish cells, appended rows, drift, pilot size and blockers.
- Skipped work, model roles actually used, test results, file-by-file summary
  and commit hashes. Do not describe planned work as implemented.

Explicit amendments to the earlier spec: no push; existing Acton reference
instead of new manual labels; field-level evidence and evaluation; guarded
proximity matching; audited non-destructive insertion/undo; geometry pins are
not entrances; exact postcode caution; protected personal/finished records;
local pilot before batch; evidence-based keeper choice; persisted duplicate
metadata; separate attachment comparisons; failure-path fetcher tests; no
unsupported not National Rail label; separate readiness quality measures;
and resumable append publishing. The 300-15,000 guard and final sheet gate remain.
