# Plan to expand the local parking database

Status: proposed for review. No new places will be inserted and nothing will
be published while preparing this plan. Push remains on hold.

## Where we are

The local database contains 7,607 places imported from the Sheet. The latest
applied run changed 2,903 Place Category cells without adding a place.

The database, routing, change plans, undo, category defaults and four website
readers exist. The readers cover National Rail, Better, Gym Group and PureGym.
The current research plans passed database checks and the independent second
reading, but remain unapplied. The local Grok queue contains 873 rows.

The publisher is implemented and tested for updates to existing Sheet rows.
It has not run against the Sheet. It cannot append a database-only place.

The full suite passed with 1,273 tests before this documentation change.

## What already exists

These are existing components to reuse, not a proposal to rebuild them:

| Component | Existing code | Current boundary |
|---|---|---|
| OSM discovery and London/category filtering | discovery.py, tranche1.py, gaps.py | Produces candidate and review files |
| Matching and duplicate checks | discover.py, discovery.py, tranche1.py, tranche1_write.py | Uses exported records and candidate files |
| Store-car-park attachment checks | tranche1_write.py | Can attach a candidate to an existing venue instead of creating another place |
| Sheet append plans and verification | tranche1_write.py, sync.py | Adds rows to the Sheet, not directly to SQLite |
| Next unused Place ID | db.next_place_id | Reads IDs from imported raw rows |
| Existing-place database updates | plan.py | Refuses unknown Place IDs |
| Website research and routing | route.py, fetch_fill.py, sources/ | Operates on places already in the database |
| Existing-place publication | publish.py, fill.py, sync.py | Updates only; no append path |

The recent work connected the database to research and guarded update publishing.
It did not connect discovery candidates to creation of new database places.

## Intended result

A repeatable local run discovers eligible London places, distinguishes new
places from existing ones, and creates a reviewable insertion plan. Approved
new records enter SQLite before any Sheet publication. Research can then fill
parking details. Unknown parking details do not prevent a valid place from
being stored, and do not become guessed answers.

The first release covers eligible London parking places and associated venues
from the existing OSM category rules. It does not import every OSM feature.
Private parking, individual bays, duplicate geometries and uncertain identities
remain explicitly classified for review or exclusion.

## Step 1: measure the current discovery gap

1. Export the current database to a fresh run folder.
2. Run the existing discovery tools against the available London OSM extract
   and that export. Record the extract date and file hash.
3. Report counts by category: existing matches, likely new places, possible
   duplicates, attachments to existing venues, out-of-area and unresolved.
4. Inspect examples from every outcome, including unnamed parking and
   multiple OSM features belonging to one site.

Acceptance: a reproducible coverage report with no database or Sheet writes.
Do not treat an old candidate file as the current count of missing places.

## Step 2: connect discovery to a database insertion plan

1. Feed the existing discovery and selection outputs into a database-facing
   planner. Reuse the matching and duplicate rules instead of writing another
   matcher. Extract reusable functions from Sheet-specific code where needed.
2. Match by existing OSM identity first, then the existing supported identity
   and location checks. Check duplicates within the batch as well as against
   the database. Hold ambiguous matches instead of choosing one silently.
3. Preserve the distinction between attaching a car park to an existing venue
   and creating a separate public car park.
4. Extend the database's authoritative record model to support discovered
   records separately from imported Sheet snapshots. Rebuild and export must
   include both. Do not pretend a discovered record came from a Sheet import.
5. Store source identities and provenance. Multiple source observations must
   be able to refer to one place without creating duplicate place records.
6. Extend next_place_id to consider all stored and reserved IDs. Allocate IDs
   transactionally at insertion. Revalidate any preview IDs before apply and
   reject a stale allocation instead of reusing an ID.
7. Produce plan.json, dry_run.csv, undo.json, duplicates.csv, attachments.csv,
   rejects.csv and summary.json in a fresh run folder. Unknown parking values
   remain unknown and Verification Result stays blank.

Acceptance tests: duplicate OSM IDs, duplicates within a batch, uncertain nearby
sites, venue attachments, missing names/postcodes, London boundaries, source
provenance, ID collisions, preserved Sheet-owned values and lossless export of
existing records. Repeated planning must not propose the same accepted place
again after insertion.

## Step 3: validate and insert a small local pilot

1. Run the existing validators and independent second reading where applicable.
   Keep creation checks separate from parking-answer requirements: creating
   an identity does not claim that parking is free or open to anyone.
2. Show a pilot of up to 20 suitable places across several categories, with
   duplicates, holds, source links and exact proposed fields.
3. Wait for explicit approval before inserting the pilot into the live database.
4. Apply in one transaction, retain the insertion audit and undo information,
   then independently export and compare the result.
5. Verify that only the approved new identities were added. Existing records
   and owner-managed fields must remain unchanged.
6. Rerun discovery and require zero repeated insertions from the pilot.

Undo must be non-destructive: append an inactive/reversed state for a created
record and preserve its history and ID. Never delete a record or reuse its ID.

Acceptance: the count grows by exactly the approved pilot size, the export
contains the same existing 7,607 records, and repeat import is safe.

## Step 4: research the new places

1. Route the pilot records through the existing router.
2. Run the existing OSM, captured-evidence, website and cautious policy tools
   where their eligibility rules allow them.
3. Send unresolved public parking and station cases to the Grok queue.
   Keep venues without parking evidence in no_evidence.
4. Report added-place counts separately from researched, displayable and
   complete counts. A new place is not automatically a verified parking answer.
5. Prepare field updates as dry runs and wait for approval before applying.

Acceptance: every new active Place ID has one stage. No unsupported Free,
public-access, maximum-stay or No-parking claim is introduced.

## Step 5: expand beyond the pilot and add source adapters

1. Use the pilot findings to fix any identity or coverage failures in the package,
   with regression tests.
2. Prepare the next larger OSM batch as an insertion dry run. Show counts,
   examples and rejects, then wait for approval.
3. Reuse the existing official-source discovery adapters for additional council
   and operator lists. Match those observations to OSM and database records
   before proposing new places.
4. Add source adapters in priority order based on measured coverage gaps.
   Website readers for existing branches alone do not discover every missing
   branch.

Acceptance: reports distinguish genuinely new places from added evidence about
an existing place. Repeated source imports do not inflate the place count.

## Step 6: publish new places only when requested

1. Keep new records local until Sheet publication is separately approved.
2. Extend publication with a distinct new-row plan, reusing the existing append,
   undo and independent verification modules. Do not turn the current update
   writer into an unchecked append implementation.
3. Check current Sheet identities and IDs immediately before append. Preserve
   existing rows and their order. Define how approved new rows receive owner
   payment columns and formulas without writing to existing protected cells.
4. Support a small append pilot with limit and Place ID filters.
5. Show the append plan, six controls, independent second reading and undo
   artifacts. Wait for explicit go before any Sheet write.
6. Require zero mismatches in the independent re-export comparison.

Acceptance: database-only places can be published without duplicate rows or
changes to existing protected fields. Drift blocks publication.

## Execution order and approval boundaries

Start with the coverage report, then implement the local insertion planner and
its tests. Review a 20-place dry run before any insertion. Prove repeat safety,
then expand local coverage and research. Sheet publication is a separate final
step. Each finished implementation task gets its own commit and full test run.
No pushes while the owner's hold remains active.

No numerical growth target or completion date is promised until the fresh
coverage report establishes the eligible, non-duplicate candidate count.
