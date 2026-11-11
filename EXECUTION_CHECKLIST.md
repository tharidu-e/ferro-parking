# London parking execution checklist

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
