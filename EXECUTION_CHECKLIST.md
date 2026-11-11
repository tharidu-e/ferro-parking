# London parking execution checklist

Read the current continuation section for the latest identity work and open
items. Preserved reference sections at the end are historical snapshots.
Code ownership is in `docs/MAP.md`. Pending document deletions are listed in
`docs/CLEANUP_PROPOSAL.md`; all originals remain until Deshan approves deletion.

This checklist replaces the step order in `docs/GPT_LONDON_EXECUTION_GUIDE.md`.
The guide's content stays correct. Its sequence does not. Work the steps below
in this order. The guide section for each step is named in the step heading.

Keep evidence, run IDs, test results and commit hashes in the execution
checkpoint. Record the measured count at every filter.

## Why the order changed

The old order put research accuracy work and official source readers in front
of the database insert. The insert needs only a name, a coordinate and a source
ID. It does not need any tariff research. The real blocker is the record model:
`db.py` rebuilds `places` and `parking` from imported sheet rows, so a record
created in the database has nowhere to live. Step 1 fixes that. Step 2 then
inserts the map.

Measured from `data/raw/greater-london-latest.osm.pbf` on 10 November 2026:
18,050 `amenity=parking` features in the extract, 7,279 excluded by a private,
permit or residents access tag, 2,297 excluded as street side or lane parking,
2,954 eligible under the public access test, and 5,520 undecided until the
polygon area test runs.

## The gates that stay

Do not remove, weaken or work around these. Each one prevents a real loss.

- The access filter. A private, permit, residents, employees, delivery, staff
  or students tag excludes the feature. Street side, lane, kerb and shoulder
  parking is excluded. Writing those 7,279 private car parks as parkable sends
  a driver to a place that fines them.
- Creation does not establish parking permission. A new record gets a name, a
  point, a borough, provenance and an OSM ID. Can Park?, Who Can Park, Cost
  Type, Tariff Detail, Max Stay and Hours stay blank. OSM proves that a car
  park exists. It does not prove who can use it or what it costs.
- Rules R7, R9 and R10 in `docs/PP_rules_and_pilot.md`. Never set Free, Anyone
  or a maximum stay without site-specific evidence. Silence is not No.
- Place ID uniqueness and repeat safety. A repeated or interrupted apply
  creates no second record.
- Undo is a logged deactivation. Undo never deletes a row and never reuses
  an ID.
- Protected columns, the "ALL LONDON" tab, and every row whose Verified By is
  Tharidu stay unchanged. Report their issues instead.
- No Sheet write without a dry run, a saved undo file, Verification Result
  written last, and an independent re-export compare afterwards.
- Every bug fix gets a regression test. All tests pass before a commit.

## The gates that were cut

- The separate 20 row insertion pilot is now an automated check inside the same
  run. A pilot of records whose parking answers are all blank proved nothing
  that the repeat-apply test does not prove.
- The 300 to 15,000 anomaly guard stays as an assertion in the code and no
  longer stops the work for a report. The measured count is about 2,954.
- Per-field extraction accuracy no longer blocks insertion. It blocks research
  applies only, which is step 5.
- Identity attachment no longer blocks creation. Uncertain matches go on a hold
  list and the clean remainder proceeds.

## 1. Add the created-record path (guide section 3)

Done on 10 November 2026. See the run record below.

- [x] Extend the authoritative record model so a record created in the database
  survives `rebuild`, `export_csv`, routing and `next_place_id`.
- [x] Keep created records distinct from imported sheet snapshots.
- [x] Allocate IDs transactionally across imports, created records, reversed
  records and reservations.
- [x] Commit validation, allocation, provenance, audit and derived-state rebuild
  atomically. Make a repeated or interrupted apply safe.
- [x] Make undo a logged deactivation. Refuse a stale undo when later changes
  supersede it.
- [x] Reconcile a later sheet reimport that contains a published created ID.
- [x] Add offline integration tests for apply, undo, rebuild, export, stale
  plans, concurrent allocation, duplicates and reimport.

**Accept step 1 when:** the integration tests prove atomicity and repeat safety,
undo never deletes or reuses an ID, and existing exported rows are unchanged.

## 2. Insert the eligible OSM car parks (guide section 4)

Done on 10 November 2026. See the run record below.

- [x] Test true Greater London geometry containment. Postcode classification
  alone is not a boundary test. Inspect `london.py` before reuse.
- [x] Apply the access and parking-type exclusions to nodes, ways and relations.
  Handle relation members, polygon holes and conditional tags conservatively.
- [x] Run the polygon area test on the 5,520 undecided features. Do not infer
  public permission from a name or a polygon size.
- [x] Match typed OSM identity first. Put every ambiguous proximity or name
  match on the hold list. Do not attach identities in this step.
- [x] Create geometry pins with provenance, cautious postcode and category
  handling, and retained tags. Invent no parking answers. Do not move an
  existing pin.
- [x] Report the count after every filter and every matching outcome.
- [x] Back up, apply, rebuild, compare exports independently, and prove that
  repeat planning creates no duplicate.

**Accept step 2 when:** the active count increase is exact, provenance is
complete, no existing row changed without an explanation, and a second planning
run creates nothing.

## 3. Resolve the hold list (guide sections 4 and 6)

- [ ] Review the held ambiguous matches, including the 240 possible duplicates
  and 106 held car parks from `data/runs/2026-11-05/discovery_new_places/`.
- [ ] Attach an OSM identity to an existing blank field only on a confident
  unique match, and only through its own audited plan.
- [ ] Persist duplicate metadata through audited plans. Never move an existing
  pin.

**Accept step 3 when:** every held case has an outcome, attachments are separate
from creations, and no pin moved.

## 4. Fix the extractors (guide sections 1 and 2)

- [ ] Fix charge association in `sources/venue.py`. The recorded failure is
  `VenueFetcher('puregym.com')` reading a £40 personal training price as a
  parking tariff. Add the regression fixture first.
- [ ] Fix free-period versus maximum-stay handling and customer-only access
  interpretation.
- [ ] Enforce the station denial guard, the official station lookup and the
  unresolved station label.
- [ ] Make page-fetch metadata accurate and applied only to quoted fields.
- [ ] Enforce the finished-row and personal-verification locks for every
  mutation, including undo. Hold unknown verifier identities.
- [ ] Add offline fixtures for negative, ambiguous, contradictory,
  unrelated-price and blocked-page cases.
- [ ] Run the replay evaluation with expected answers and human notes hidden
  from the extractor. Report per-field supported accuracy with denominators.

**Accept step 4 when:** the fixtures pass, the replay is repeatable, and the
unrelated-price failure is fixed and retested. No research apply happens before
this step passes.

## 5. Research the new records (guide sections 5 and 6)

- [ ] Confirm the current TfL endpoint and terms from official documentation.
  Report missing credentials as a skipped optional source.
- [ ] Route the full active database. Reuse the supported council and operator
  adapters.
- [ ] Keep the quote, canonical URL, retrieval time and cached page hash per
  field. Measure requests, failures, cache hits and real throughput.
- [ ] Apply only evidence-supported plans through `db-apply`. Save every refusal
  with its reason.
- [ ] Report legacy readiness and evidence-supported readiness separately,
  including unknown and contradictory counts.
- [ ] Refresh the Grok queue in its exact layout, with blank payment fields and
  blank row numbers for database-only places.

**Accept step 5 when:** source claims pass the field-level controls, refusals
are recorded, protected rows are unchanged, and readiness does not treat an
OSM-only record as verified public parking.

## 6. Build the publication dry run (guide section 7)

- [ ] Extend the publisher for new-row append plans with fresh sheet identity
  and drift tests, limit and Place ID filters, grid growth plans, and recovery
  from a partial write without deleting a row.
- [ ] Prevent a duplicate Place ID. Distinguish a database-only ID from an
  imported ID that is missing in the live sheet.
- [ ] Preserve the protected and payment columns and the owner formulas.
  Prepare `plan.json`, `dry_run.csv` and `undo.json`.
- [ ] Exercise the six controls, the independent second reading, the
  verification-last ordering, the readback and the independent re-export
  compare, using offline tests.
- [ ] Test the OSM attribution and licensing terms against primary sources.
  List unresolved product sign-off as a publication blocker.
- [ ] Produce a full publish dry run and a separately selectable 20 row pilot.
  Report cells, appends, drift and blockers. Do not write to Sheets.

**Accept step 6 when:** both dry runs are reviewable, all controls pass,
licensing blockers are disclosed, and no Sheet write happened. Then stop for
Deshan's explicit approval of the 20 row publication pilot.

## Work already finished

The baseline from the old step 1 stands. It is recorded in
`data/runs/2026-11-10/gpt_execution_220752/`. The database holds 7,607 places.
The latest routing is `route-20261110T191632Z`. The OSM extract SHA256 is
`75e4840a9c9d957649664ea85b16df02e2f2d5f20ee3ff810410421639ca2616`.
The Acton snapshots are saved and 41 of 43 rows map under the current
normalizer. The two unresolved rows are Sainsbury's Ealing Acton Town Station
Local and Southfields Recreation Ground. That work now belongs to step 4.
Do not repeat `categories-20261110-authorised`. It already holds 2,903 changes.


## Run record: steps 1 and 2, 10 November 2026

The database holds 11,552 places. It held 7,607 before this work. The 3,945 new
records are car parks discovered in OpenStreetMap. Every parking answer on them
is blank.

Commands, in order:

```
python -m ferro_parking osm-places data/raw/greater-london-latest.osm.pbf
python -m ferro_parking db-create --plan <candidates_pilot20.jsonl> --apply
python -m ferro_parking db-create --plan <candidates_strong.jsonl> --apply
python -m ferro_parking db-create --plan <candidates_area_only.jsonl> --apply
python -m ferro_parking db-create-redo --run <each run id> --apply
python -m ferro_parking route
```

Three create runs, so the weakest group stays undoable on its own:

| Run | Proposed | Created | What qualified them |
|---|---|---|---|
| create-20261110T225542Z | 20 | 6 | pilot, taken from the strong set |
| create-20261110T225635Z | 2,891 | 2,092 | an access tag, a name, an operator, a fee, a capacity or a type |
| create-20261110T225717Z | 1,941 | 1,847 | polygon area alone, the weakest evidence |

Candidate counts, measured from the extract whose SHA256 is
`75e4840a9c9d957649664ea85b16df02e2f2d5f20ee3ff810410421639ca2616`:

| Stage | Count |
|---|---|
| amenity=parking in the extract | 18,050 |
| excluded by an access tag | 6,040 |
| excluded as street side, lane or kerb | 3,548 |
| excluded as disused or proposed | 1,866 |
| excluded as lorry or coach only | 12 |
| excluded as outside Greater London | 138 |
| excluded with no qualifier | 3,460 |
| proposed | 4,852 |
| skipped, an existing place already names the feature | 446 |
| held as a possible duplicate within 30 m | 461 |
| created | 3,945 |

Of the 3,945 created, 436 carry an OpenStreetMap name and 3,509 are unnamed.

## The duplicate defect, found and fixed on 10 November 2026

The first apply created all 4,852 records and 907 of them were duplicates. The
create path checked only its own `created` table for a source reference it had
already used. It never read the `OSM ID` column on the places that came from
the sheet, and 2,140 of those carry one. So 446 car parks were created a second
time, including whole rows an earlier discovery round had already appended.

The fix is one guard in `create.check_plan`, which every caller routes through.
A record whose OpenStreetMap reference already belongs to a place is skipped. A
record whose pin lands within 30 m of an existing place is held for a person,
which is the rule the guide already stated and which the first version did not
implement. Two candidates in the same plan within 30 m of each other are held
the same way, because one car park is often mapped as both a node and an area.

Two further defects were found and fixed at the same time. `db-rebuild` never
deleted a derived row, so a deactivated created record stayed in `places` and
every count of places kept reporting it. The rebuild now clears the derived
rows of deactivated created records only, and an imported Place ID that a newer
import dropped still keeps its last values. And a plain `db-create` cannot
bring back an undone record, which is correct, so `db-create-redo` reactivates
a run's records after a fix, re-running both guards and keeping each existing
Place ID.

All three create runs were undone, the guards were added with tests, and the
records were reactivated. The hold list of 461 records is in
`data/runs/2026-11-10_19/hold_list/held_all.csv` and is step 3 of this
checklist. It contains real duplicates the name normalizer misses, such as
`QPark Chinatown` 12 m from the existing `Q-Park Chinatown`, and
`Hayes Station Car Park` 14 m from the existing `Hayes Station` row.

## Verification of steps 1 and 2

- The backup is `data/db/ferro_parking.sqlite.backup-20261110T1730`.
- The baseline export is `data/runs/2026-11-10/baseline_export_before_create`.
- The final export is `data/runs/2026-11-10_19/export_final2`.
- All 7,607 imported rows are byte for byte identical in both exports.
- Zero places share an OpenStreetMap reference.
- Zero created records carry a parking answer.
- Rerunning a create plan creates nothing.
- The full apply, repeat, export and undo cycle was rehearsed on a copy of the
  real database first. Undo restored the baseline export exactly and kept every
  row, deactivated, with no Place ID freed.
- Routing run route-20261110T230913Z covers all 11,552 places. No active
  created record is unrouted.
- Test suite: 1,383 passed.

Nothing was written to the Google Sheet. No created record can reach it yet:
publication matches applied changes against the live sheet by Place ID, and a
created record has no sheet row, so it reports drift instead of writing. New-row
append plans are step 6.

## Run record: step 3, the hold list, 11 November 2026

Nothing was applied. The database is unchanged and nothing reached the Google
Sheet. This run decided the cases. The apply is the next step and it waits for
Deshan.

Commands, in order:

```
python -m ferro_parking holds-bundle --pbf data/raw/greater-london-latest.osm.pbf
./scripts/run_codex_reviewer.sh docs/holds_reviewer_prompt.md \
    data/runs/2026-11-11_3/holds/review data/runs/2026-11-11_3/reviews/codex
python -m ferro_parking holds-merge \
    --a data/runs/2026-11-11_3/reviews/reviewer_a.csv \
    --b data/runs/2026-11-11_3/reviews/reviewer_b.csv \
    --bundle data/runs/2026-11-11_3/holds/bundle.jsonl
```

Reviewer A is Claude Opus 5, run as six parallel agents over the same batches
and the same instructions. Reviewer B is Codex. Neither reviewer saw the rule
verdicts, the other reviewer's answers, or the web.

The four source files hold 801 distinct cases, not the 807 the earlier step
estimated. Nine references appear in two files.

| Source file | Pending | Already created |
|---|---|---|
| held_all.csv, from step 2 | 461 | 0 |
| possible_duplicates.csv, from 2026-11-05 | 193 | 47 |
| held_car_parks_strict.csv | 1 | 105 |
| held_car_parks_names.csv | 1 | 7 |

Two questions live in those files, and they have different safe answers. A
creation question asks whether a car park the database does not hold is already
in it under another row. An attachment question asks whether an OpenStreetMap
venue is the same business as a place the database holds. The 2026-11-05 report
carries 110 supermarkets, 22 gyms, 20 hotels, 15 stations, 15 DIY stores and 2
fast food outlets, which are attachment cases. None of them is a car park.

| Stage | Count |
|---|---|
| cases | 801 |
| creation cases | 617 |
| attachment cases, a separate plan | 184 |
| settled by a rule | 169 |
| judged by the two reviewers | 448 |

Rule outcomes:

| Rule | Cases | Verdict |
|---|---|---|
| already_same_ref | 108 | duplicate |
| pin_inside_candidate_same_brand | 58 | duplicate |
| same_feature_twice | 1 | duplicate |
| protected_row | 2 | unresolved, reported to a person |

The two reviewers gave the same verdict on 316 of the 448 creation cases, which
is 71 percent. They never contradicted each other. In every one of the 132
disagreements, one reviewer committed and the other said the evidence does not
settle it. No case had one reviewer say duplicate and the other say distinct.

| Reviewer A | Reviewer B | Cases |
|---|---|---|
| unresolved | unresolved | 192 |
| duplicate | duplicate | 114 |
| distinct | unresolved | 66 |
| duplicate | unresolved | 61 |
| distinct | distinct | 10 |
| unresolved | duplicate | 5 |

Final verdicts, after the agreement gate:

| Verdict | Count | What it means |
|---|---|---|
| duplicate | 258 | the database already holds this car park. Create nothing. |
| distinct | 9 | a separate car park. These are the only creations. |
| unresolved | 534 | the evidence does not settle it. Nothing happens. |

The 534 unresolved hold 184 attachment cases, 348 creation cases where the
reviewers did not fully agree at high confidence, and the 2 hand checked rows.

Three defects were found and fixed during this run. Each one carries a
regression test.

1. The first rule settled all 47 created records on their own creation. A place
   carried the candidate reference, and that place was the record the candidate
   itself created. The open question, whether that created record repeats an
   older row beside it, was never asked. The rule now fires on a candidate's own
   creation only when no other place is near.
2. A rule ended a case as unresolved when every place near it was geocoded to a
   postcode centroid. On the real list that rule decided 311 of 801 cases, and
   222 of those shared a brand token with the place beside them. It discarded
   the easiest duplicates in the set. The protection was never in that rule, so
   the rule is deleted and those cases go to the reviewers.
3. The merge reported all 184 attachment cases as cases both reviewers failed to
   judge. It now names the attachment question and counts them on their own line.

Test suite: 1,438 passed.

What is not done. The apply is not written and has not run. No record was
created, no record was deactivated, and no identity was attached. The 184
attachment cases need their own prompt and their own audited plan. The 2 hand
checked rows are in
`data/runs/2026-11-11_3/holds/protected_rows.csv` and need Deshan.

## Run record: step 3 applied, 11 November 2026

A read only Codex audit of the first run found three faults. Every claim it
made that could be checked was true. Each fix carries a regression test.

1. way/92793027 is tagged access=staff and named Staff Parking, and it reached
   a creation verdict. The 2026-11-05 hold lists predate some exclusion rules
   and nothing re-applied them. The rules now live in one function,
   `osm_places.creation_excluded`, which the proposer and the hold list both
   read. A second candidate, way/11847178, named HGVs, is excluded as well.
2. Two car parks both called "Car park (unnamed)" shared the token "unnamed"
   and read as one place. That settled four cases as duplicates on a word that
   names no business.
3. way/129582660, Queens Hospital Surface, is a separate car park from the
   multi-storey 72 m away and is already place PP-008489. Both reviewers were
   right and the action was wrong. A case the database already holds now ends
   as "keep", which does nothing.

Three more faults were found by running the apply. Each would have changed the
database.

4. The hold list called a deactivated record "pending". All 461 cases from step
   2 are records an early run created, whose run was undone, and which the
   fixed guards then held. A reviewer calling one a separate car park asks for
   that record back, not for a new one.
5. The proximity guard read only the closest place. Both Belvedere Medical
   Centre candidates sit 22 to 25 m from a Co-op car park the review cleared,
   and 26 m from each other, so each hid behind the Co-op.
6. An already active record was skipped before it entered the place index, so
   later records in the same batch could not see it. The second run brought
   back the record the first run held, which breaks the repeat safety gate.

Retiring a record now needs real evidence. A duplicate verdict on a record the
database holds retires it, and a wrong one loses a real car park. Eight of the
nine retirements in the first run rested on a brand name shared at 50 to 245 m.
Westfield London Car Park C sits 227 m from a row called Westfield London Car
Parks, and Tesco Hammersmith 244 m from Tesco Hammersmith Superstore. That is
one business with several car parks as readily as one car park entered twice.
Retiring now needs the pin inside the candidate polygon, the same OpenStreetMap
reference, or a distance inside 30 m. The other eight are unresolved and
reported for a person.

Every decision that acts is recorded in `config/holds_decisions.csv`, keyed by
the OpenStreetMap reference and kept under version control. A reload of the
same evidence reproduces all 801 verdicts from that file alone, and 255 cases
are settled without asking a reviewer again. An unresolved case is not
recorded, so the next run can ask again with better evidence. The access gate,
the fact that a place already carries the reference, and the hand check
protection all run before a recorded decision.

Final verdicts over the 801 cases:

| Verdict | Count | Action |
|---|---|---|
| duplicate | 247 | create nothing |
| distinct | 7 | bring the record back |
| keep | 1 | the record stands, do nothing |
| excluded | 2 | a driver may not park here, never create |
| unresolved | 544 | nothing happens |

Commands, in order:

```
python -m ferro_parking holds-bundle --pbf data/raw/greater-london-latest.osm.pbf
./scripts/run_codex_reviewer.sh docs/holds_reviewer_prompt.md \
    data/runs/2026-11-11_6/holds/review_delta data/runs/2026-11-11_6/reviews_delta/codex
python -m ferro_parking holds-merge \
    --a data/runs/2026-11-11_6/reviews/reviewer_a.csv \
    --b data/runs/2026-11-11_6/reviews/reviewer_b.csv \
    --bundle data/runs/2026-11-11_6/holds/bundle.jsonl
python -m ferro_parking db-export --out <baseline>
python -m ferro_parking db-create-redo --reviewed config/holds_decisions.csv
python -m ferro_parking db-create-redo --reviewed config/holds_decisions.csv --apply
python -m ferro_parking db-export --out <after>
```

Verification of the apply:

- The backup is `data/db/ferro_parking.sqlite.backup-20261111T1425`.
- The baseline and final exports are in
  `data/runs/2026-11-11_9/create_reviewed/`.
- The database holds 11,558 places. It held 11,552 before.
- Six records came back, each keeping the Place ID it already had: PP-009500,
  PP-009510, PP-010009, PP-010090, PP-010091 and PP-010423.
- The export gained exactly those six rows. No row was removed and no earlier
  row changed.
- Every one of the six carries no parking answer.
- A second run changed nothing.
- Zero places share an OpenStreetMap reference.
- The seventh cleared record, way/1123932197, stays held at 26 m from
  PP-010091 and is for a person.
- Test suite: 1,461 passed.

Nothing was written to the Google Sheet.

What is still open.

- One retirement survives the evidence test: PP-008072, New Barnet Sainsbury's
  Car Park, whose pin falls inside a candidate 31.8 m from PP-000734. Retiring
  a live record waits for Deshan.
- The eight weak retirements are reported, not acted on.
- The 184 attachment cases need their own prompt and their own audited plan.
- The 2 hand checked rows are in
  `data/runs/2026-11-11_6/holds/protected_rows.csv`.
- Routing run route-20261111T143442Z covers all 11,558 places.
  One row needs a person, in `data/runs/2026-11-11_12/route/proposals.csv`.


## Current continuation: identity and remaining research, 11 November 2026

The identity command now builds read-only db-apply plans. See
`docs/OSM_IDENTITY_BRIEF.md` for the contract and `docs/MAP.md` before creating
any new module. Identity establishes a venue association, not a parking answer.
Only active OSM-created records are candidates. Existing filled values and
finished or personal checks stay untouched. Filled Notes cannot be appended by
this weak-evidence plan under the existing replacement guard; evidence remains
in the per-line quote and review CSV.

Step 4 items 1 and 2 have been implemented in the venue reader: unrelated
prices cannot become tariffs, free periods cannot become maximum stays, and
conflicting parking sentences yield no answer. The remaining station guards,
fetch metadata, shared finished/personal locks and replay evaluation remain open.

Carry these unresolved items forward from the retired handover:

- PP-008072, New Barnet Sainsbury's Car Park, is a proposed retirement only.
  It waits for Deshan. Eight weaker retirements remain report-only.
- The 184 attachment cases in
  `data/runs/2026-11-11_6/holds/attachment_cases.csv` need their own prompt and
  audited plan. Identity matching here does not apply those attachments.
- Two hand-checked rows remain in
  `data/runs/2026-11-11_6/holds/protected_rows.csv` for a person.
- One routing row needs a person, in
  `data/runs/2026-11-11_12/route/proposals.csv`.
- The latest recorded created-place population is 11,558, including 3,951
  OSM-created car parks. This is a dated count, not a readiness claim.
- Build future source adapters from identity proposal counts. Identity alone
  never supplies permission, prices or time limits for the research queue.

## Run record: OSM identity dry run, 11 November 2026

Final output: `data/runs/2026-11-11_14/osm_identity/`. The earlier rehearsal
is preserved in `data/runs/2026-11-11_13/osm_identity/`.

- Active OSM-created candidates: 3,951.
- Proposed: 704 places and 704 Brand lines. Existing categories and Notes
  are filled, so this run leaves them unchanged.
- Methods: inside the car park 23, inside the site 134, beside it 547.
- Held: 3,247. No nearby anchor 2,211, competing identities 761, no mapped
  sheet category 275. Absent references: 0.
- Existing plan.read_plan and plan.check_plan accept the saved plan with
  zero refusals. The database was opened in read-only mode. No plan applied.
- counts.csv contains every proposed brand count. The command prints the
  top 20. Leading brands: Sainsbury's 33, Lidl 25, Tesco Express 19,
  Tesco 17 and Asda 15.
- Full offline suite: 1,504 passed, including 27 new identity tests.
- docs/MAP.md covers all 59 source/configuration files in 83 lines.
  docs/CLEANUP_PROPOSAL.md covers all 23 original Markdown files. Selected
  reference content is preserved below. No original file was removed.
- The parent session created branch feat/osm-identity-map-cleanup and handled
  commits outside the nested Codex sandbox, which blocks .git writes.
  No push was made. Commit messages carry the requested co-author trailer.

## Preserved execution guide detail

Copied from the old guide for reference. The checklist order and current
session authority govern. Nothing in this copy grants a new database or sheet
apply. Earlier pilot requirements and completed-step instructions are history.

### Rules for the execution

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

### 1. Reuse the Acton checks before expanding

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

### 2. Fix and apply eligible existing research

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

### 5. Add official sources and research new records

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

### 6. Duplicates, pins and readiness

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

### 7. Build publication, dry run only

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

### Final report and continuation record

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


## Preserved checkpoint, 10 November 2026

Historical snapshot. Later run records and the current continuation above
supersede its counts, completion claims and next-step instructions. No apply
is authorised by this snapshot.

### GPT execution checkpoint

Stopped on the execution guide critical false-price claim guard. No database
apply, undo, schema mutation, Sheet write or push was performed. Do not repeat
categories-20261110-authorised: it already contains 2,903 changes.

#### Verified baseline

Branch feature/db-router; starting HEAD 16984b6. Working tree initially clean.
Cached company tracking comparison: 0 behind, 6 ahead. No fresh remote fetch.
SQLite read-only audit: 7,607 places; latest import 2 at
2026-11-10T13:36:24+00:00, 7,607 rows; published baseline 0 cells.
Legacy readiness: 1,450 showable, 1,055 complete. These are population measures,
not evidence-supported safety counts. Latest routing is route-20261110T191632Z;
full historical and latest stage counts are in baseline.json.
OSM SHA256: 75e4840a9c9d957649664ea85b16df02e2f2d5f20ee3ff810410421639ca2616.
Local extract mtime: 2026-11-02T12:21:21.056214+00:00; not a verified source date.

#### Artifacts

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

#### Stop guard and restart

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

#### Roles and changed files

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


## Preserved category and research report, 10 November 2026

Historical snapshot. Later run records and the current continuation above
supersede its counts, completion claims and next-step instructions. No apply
is authorised by this snapshot.

### Category apply and research review, 10 November 2026

Only the category plan was applied to the live database. Nothing was published
to Google Sheets. Fetcher and default plans remain proposals awaiting go.

#### Category result

Run `categories-20261110-authorised` applied 2,903 changes to 2,903 places.
The pre/post exports retain all 7,607 Place IDs in the same order. Only Place
Category differs. Brand and Decision Reason are unchanged. Unexpected changes: 0.

The earlier 2,649 planned rows increased to 2,903. The 588 review entries contain
460 proposals reshaped to convenience and included in the plan, plus 128 dropped
because the name does not establish a store format.

Artifacts: `data/runs/2026-11-10/categories_authorised/`:

- `plan.jsonl`: 2,903 category changes.
- `category_review.csv`: 588 reshaped or dropped proposals.
- `examples.csv`: category examples.
- `pre_apply.csv`, `post_apply.csv`: lossless database exports.
- `export_compare.json`: column counts and zero unexpected changes.
- `dry_run/dry_run.csv`, `dry_run/rejected.csv`: pre-apply validation.
- `applied/dry_run.csv`, `applied/rejected.csv`: applied-run report, zero refusals.

#### Research result

| Reader | Rows | Plan lines | Proposed values | Cost Type | Held | Refused |
|---|---:|---:|---|---|---:|---:|
| Station, including station reviews in Grok | 473 | 2,580 | 57 Yes, 56 No, 25 flag-only | 56 Not applicable, 82 not set | 0 | 0 |
| Better | 84 | 763 | 38 Conditional | 1 Free, 37 Unknown | 0 | 0 |
| The Gym Group | 49 | 280 | 14 Conditional | 14 Unknown | 0 | 0 |
| PureGym | 40 | 286 | 14 Conditional | 14 Unknown | 0 | 0 |
| Default | 233 | 0 | None | None | 233 | 0 |

Every plan passes db-apply dry-run validation and the existing independent
second reading. None was applied. A flag-only station proposal changes no
Can Park?, Cost Type, tariff, access or maximum-stay answer.

Of the 60 previously held stations, 57 now propose Yes and Brand National Rail.
Those proposals do not set Cost Type, tariff or maximum stay. Three are still
unresolved. Their details are in `review/previously_held_stations.csv`.

There are 335 unresolved station rows and 25 conflicts with a National Rail
denial. These are in Grok. Unresolved names use the requested label
"not National Rail", which does not prove that the place is outside National Rail.

Default holds 226 rows not recognised by the existing policy rules and seven
that lack Brand. No new default rule or brand guess was introduced.

Final routing: 4,096 skip_done, 1,175 skip_onsite, 43 skip_named, 901 no_evidence,
873 grok, 233 default, 113 station, 84 Better, 49 Gym Group and 40 PureGym.

Artifacts: `data/runs/2026-11-10/research_final/`:

- `route/routing.csv`, `route/proposals.csv`: final stages and identity reviews.
- Each of `station/`, `better/`, `thegymgroup/`, `puregym/`: `plan.jsonl`,
  `summary.json`, `examples.csv`, `held.csv`, `unresolved.csv`.
- `default/plan.jsonl`, `default/summary.csv`, `default/examples.csv`: unchanged
  policy rules applied to the current default queue.
- `review/report.md`: combined table and ten example rows for each reader and default.
- `review/examples.csv`: 50 examples, including values, quote, URL and outcome.
- `review/summary.csv`, `review/refused.csv`, `review/second_reading.csv`: checks.
- `review/previously_held_stations.csv`: all 60 previously held station outcomes.

`data/runs/2026-11-10/grok_queue/grok_queue.csv` contains all 873 Grok rows in
the requested tab layout. Payment columns are blank. Priorities follow the
requested name/category rule. Nothing was written to the Grok Queue tab.

The complete public station-list response is cached at
`data/cache/nationalrail_station_list.json`. It is the StationList query used
by National Rail's own finder, rather than a generated list of guessed row URLs.
The public list and the finder's slug implementation were inspected to establish
the lookup. Existing and new pages are kept in the existing page cache.

#### File-by-file code summary

- `src/ferro_parking/category_plan.py`: category plans no longer touch Decision Reason.
- `src/ferro_parking/plan.py`: supplies actual old values to metadata validation.
- `src/ferro_parking/validation.py`: narrow category/brand-only route and typography exception.
- `tests/test_plan.py`: metadata exception, unchanged reasons and non-exempt parking changes.
- `src/ferro_parking/sources/venue.py`: conservative charge detection, negation guards,
  official-domain check, bounded free tariffs, supporting charge and stay quotes.
- `src/ferro_parking/sources/station.py`: positive-count guard, denial conflict guard,
  National Rail brand, official-list-only URL lookup.
- `src/ferro_parking/sources/station_list.py`: cached complete official list, exact
  matching, ambiguous-name refusal, official finder slug conversion.
- `src/ferro_parking/sources/fetch.py`: supports the official station-list JSON query.
- `src/ferro_parking/fetch_fill.py`: fresh OSM guard, station reviews, source URLs,
  ten examples, structured summaries and HTTP failure handling.
- `src/ferro_parking/route.py`: shares fetcher registry and sends unresolved or
  conflicting stations to Grok.
- `src/ferro_parking/page_fill.py`: preserves a free tariff period without treating
  it as maximum stay and supports metadata-only consistency checks.
- `tests/test_fetchers.py`: station conflicts, zero spaces, brand, exact lookup,
  caching, negation, later charges, tariff periods and source-domain regressions.
- `tests/test_route.py`: registered readers and station fallback regression tests.
- `src/ferro_parking/grok_queue.py`: exact-layout local Grok queue export.
- `tests/test_grok_queue.py`: layout, row references, priorities and blank payment columns.
- `src/ferro_parking/research_report.py`: combined dry-run checks and 50 examples.
- `tests/test_research_report.py`: report counts, no-change examples and no database writes.
- `src/ferro_parking/publish.py`: dry-run publisher, pilot filters, drift check,
  approved-plan requirement, existing writer, undo, readback and independent compare.
- `src/ferro_parking/fill.py`: shared write/undo readback compares numeric cells
  using the same conversion used when writing, so 100.00 matches Sheets value 100.
- `src/ferro_parking/fill_round2.py`: the existing independent second reading
  recognises category/brand-only actual changes.
- `tests/test_publish.py`: drift, pilot filters, row locks, protected columns,
  saved approval, fresh identity resolution, undo ordering, readback comparison,
  lock changes during apply and published-baseline protection.
- `src/ferro_parking/__main__.py`: publish, grok-queue and research-report commands.
- `README.md`: current lookup, category, queue, reporting and publish instructions.
- `docs/2026-11-10_IMPLEMENTATION_REPORT.md`: this file with results and artifact inventory.

No publish run was executed. Published baseline rows remain 0. The only applied
database change run is the authorised category run. Data and cache artifacts are
git-ignored. They are available locally and are not included in the push.

Validation: the full suite passes, 1,273 tests. No live publish was executed.
