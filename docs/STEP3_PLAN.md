# Step 3 plan: resolve the hold list

Draft for approval. No code and no apply happens until Deshan approves this
plan. Nothing here writes to the Google Sheet.

## The problem

Step 2 held 461 OpenStreetMap candidates because each pin lands within 30 m of
an existing place. Proximity is not proof. The 2026-11-05 discovery round left
240 possible duplicates and 106 held car parks. That is 807 cases.

Deshan cannot hand-check 807 cases. So the plan has to produce accuracy that a
small hand-checked sample can measure.

## Three outcomes

Every case ends in one of three states.

- Duplicate. The candidate is the existing place. The candidate is not created.
- Distinct. The candidate is a different car park. It is created with blank
  parking answers, the same as step 2.
- Unresolved. The evidence does not settle it. Nothing is created and nothing
  is written.

Unresolved is the default. If any part of the evidence is missing or the
reviewers disagree, the case becomes Unresolved. An Unresolved case costs one
missing car park. A wrong Distinct creates a duplicate row. A wrong attachment
writes an OpenStreetMap ID onto a real sheet row, so attachment needs the
highest bar.

## Phase A: build the evidence bundle

This phase is deterministic and uses no AI. For each held case, collect:

- the candidate OpenStreetMap type, ID, every tag, and the geometry,
- the near place Place ID, Location Name, latitude, longitude, postcode,
  existing OSM ID, Geo Precision, Captured By and Verified By,
- the distance in metres, and whether the existing pin falls inside the
  candidate polygon,
- name similarity, with brand tokens separated from generic words such as
  "car park" and "station",
- whether a second candidate in the same plan describes the same feature as a
  node and as an area.

Report the count of cases that lack any field.

## Phase B: deterministic rules first

These rules settle the clear cases with no AI. Report the measured count for
each rule.

- The existing pin falls inside the candidate polygon and the brand tokens
  match. Outcome: Duplicate.
- The candidate node is a member of the candidate way, or the existing place
  already carries the same OpenStreetMap reference. Outcome: Duplicate.
- The same feature appears twice in the plan, as a node and as an area. Keep
  the area. Outcome for the node: Duplicate.
- The existing pin is a postcode centroid, so the distance measures nothing.
  Outcome: Unresolved. Distance is not used on these cases.
- A Tharidu row, or a protected column, is involved. Outcome: Unresolved, and
  the case goes in a report for Deshan.

## Phase C: two independent AI reviewers

Only the remainder reaches this phase. Each case goes to two reviewers, one
Claude and one Codex. Each reviewer gets the same evidence bundle as text.
Neither reviewer sees the other verdict, the sample labels, or the rule output.
Each returns one of the three outcomes, a confidence, and one sentence that
names the evidence it used.

The verdict is accepted only when both reviewers agree and both are confident.
Any disagreement, any low confidence and any refusal becomes Unresolved.

Work splits into batches of about 25 cases per worker, so 807 cases times two
reviewers runs in parallel.

## Phase D: report the sample, do not gate on it

Deshan removed the hand-check gate on 11 November 2026. Two independent
reviewers that must agree are the accuracy control. No person reviews a sample
before the apply.

The run still writes `sample60.csv`, a random sample of 60 resolved cases with
an OpenStreetMap link and the near sheet row. It is a reference, and it blocks
nothing. Known limit: without labels, the reported accuracy is reviewer
agreement alone, and agreement is not proof of correctness.

## Phase E: apply in separate audited plans

Three separate runs, so the weakest group stays undoable on its own.

1. `db-create` for the Distinct set, with blank parking answers.
2. An attach plan that writes only a blank OSM ID column on an existing place,
   on a confident unique match alone. No pin moves. No other column changes.
3. A duplicate metadata plan for the Duplicate set.

Every run gets its own folder under `data/runs/`, a saved undo file, a repeat
run that creates nothing, and an independent export compare.

## Tests

Each Phase B rule gets a regression test built from a real held case. The
`QPark Chinatown` case at 12 m and the `Hayes Station Car Park` case at 14 m
are the first two fixtures. All tests pass before the commit.

## What this plan does not do

- It does not set Can Park?, Who Can Park, Cost Type, Tariff Detail, Max Stay
  or Hours. Rules R7, R9 and R10 stay in force.
- It does not touch the "ALL LONDON" tab or any Tharidu row.
- It does not write to the Google Sheet. New-row appends are step 6.
