# Brief: src/ferro_parking/osm_identity.py and tests/test_osm_identity.py

Repo: /Users/deshan/Documents/ferro-parking. Read CLAUDE.md,
docs/PP_rules_and_pilot.md, src/ferro_parking/osm_places.py,
src/ferro_parking/discovery.py (the category machinery and classify_osm),
src/ferro_parking/plan.py (the plan file format and every refusal),
src/ferro_parking/route.py (source_key), and src/ferro_parking/fill.py
RESEARCH_COLUMNS, before writing code.

Do not touch src/ferro_parking/sources/*, src/ferro_parking/fetch_fill.py,
src/ferro_parking/holds.py or src/ferro_parking/create.py. Other workers own
those right now.

## The problem

The database holds 3,951 car parks the project created from OpenStreetMap.
3,495 of them have no real name and 4,817 rows in the research queue have no
brand. A car park with no name and no brand has no website, so no fetcher and
no council page can ever answer who may park there or what it costs. The
research pipeline is blocked on identity, not on extractors.

OpenStreetMap usually knows what the car park belongs to, because a named
supermarket, hospital, station or retail park sits inside the car park polygon
or right beside it. This module reads that and proposes an identity.

## What it may write, and what it may never write

It writes a db-apply plan. Only these columns:

- `Brand`: the anchor's `brand` tag when present, else its `name`.
- `Place Category`: the sheet category the anchor's OpenStreetMap category maps
  to, read from `config/discovery_categories.toml` `sheet_place_categories`.
  Skip the proposal when that category has no sheet category.
- `Notes`: one sentence of evidence, appended, never replacing.

It must never write Can Park?, Who Can Park, Cost Type, Tariff Detail, Max
Stay, Hours or any other parking answer. A supermarket next door proves what
the car park belongs to. It proves nothing about who may park there or what it
costs. Rules R7, R9 and R10.

It must never write `Operator`. A supermarket operates the shop. Whether it
operates the car park is a separate fact the extract does not state.

Only records in the `created` table with `active = 1` are candidates. Never
propose a change to an imported sheet row in this pass.

## A. The collector

Write an osmium handler that reads the extract once and keeps two things.

1. Every `amenity=parking` feature, keyed `f"{type}/{id}"`, with its geometry.
   Reuse `osm_places.is_parking`.
2. Every anchor: a feature that has a non-empty `name` tag and whose tags match
   an `osm_rules` entry of a category in `config/discovery_categories.toml`
   other than `car_park`. Keep its name, its `brand` tag, its matched category
   name and its geometry. Reuse `discovery.load_categories` and
   `discovery.classify_osm`. Do not write your own tag table.

## B. The match, strongest evidence first

For each candidate record, find its parking geometry by source reference. A
reference the extract does not hold is reported and skipped.

Three methods, in this order of strength:

1. `inside the car park`: the anchor's representative point falls inside the
   car park polygon.
2. `inside the site`: the car park geometry falls inside the anchor's polygon,
   which is how a hospital campus or a retail park is mapped.
3. `beside it`: the anchor geometry is within 40 m of the car park geometry.

Take the strongest method that found anything. If exactly one anchor matched at
that strength, propose its identity. If several matched at that strength and
they all carry the same brand or name, propose that one. Otherwise hold the
case, because a car park between a Tesco and a Lidl belongs to one of them and
the geometry does not say which.

Use `shapely.STRtree` for the search. The extract holds hundreds of thousands
of anchors, so a loop over every pair will not finish.

## C. The plan file

One line per column changed, in the format `plan.read_plan` accepts. Each line
carries `place_id`, `column`, `new_value`, `quote`, `source_url`, `stage` and
`verified_by`.

- `quote`: the anchor's own tags as evidence, for example
  `name=Tesco Extra; shop=supermarket; 14 m from the car park`.
- `source_url`: the anchor's OpenStreetMap url.
- `stage`: the stage the latest routing run gave that Place ID. Read it from
  the `routing` table. A plan whose stage differs from the routed stage is
  refused by `plan.check_plan`, so read it, never guess it.
- `verified_by`: `OSM identity match`.

`db-apply` refuses replacing a value that is already there, so propose a column
only when the row's current value is blank or a placeholder. Read the current
value from `db.current_rows`.

## D. Outputs and the command

`run_paths.new_run_dir("osm_identity")`. Write `plan.jsonl`, `proposals.csv`
(place_id, source ref, anchor name, anchor category, method, metres, brand,
place category), `held.csv` with the reason, `absent.csv` for references the
extract does not hold, and `counts.csv`.

Add the command `osm-identity` to `src/ferro_parking/__main__.py` in the
existing style, with `--pbf`, `--db`, `--out` and `--limit`. It is read only:
it writes a plan and never applies it. Applying is `db-apply`, which already
has the audit trail and the undo.

Print the count per method, the count held, the count absent, and the top 20
brands by proposal count. That last number is what tells a person which
adapters are worth building next.

## E. Tests, tests/test_osm_identity.py

Fixtures only. No real extract, no real database, no network. Write a small
`.osm` XML fixture the way `tests/fixtures/holds_extract.osm` does.

Cover:
- An anchor point inside a car park polygon gives `inside the car park`.
- A car park inside an anchor polygon gives `inside the site`.
- An anchor 20 m away gives `beside it`, and one 60 m away gives nothing.
- Two different brands at the same strength hold the case, and the held reason
  names both.
- Two anchors of the same brand at the same strength propose that brand.
- The strongest method wins when two strengths both match.
- An anchor with no name is never used.
- A car park anchor is never used as an anchor.
- The plan writes only Brand, Place Category and Notes, and never a parking
  column. Assert the plan contains no key from a list of the parking columns.
- The plan never proposes a column that already has a value.
- The plan's stage equals the routed stage for that Place ID.
- An imported sheet row is never proposed.
- The plan `plan.read_plan` accepts, and `plan.check_plan` refuses nothing, on
  a fixture database.

Run `python -m pytest tests/ -q` and make the whole suite pass. It is at 1,461
tests now.

## Hard rules

No em dash and no en dash in any file. No network. Nothing writes to the
database or the Google Sheet in this module. Nothing under data/runs is deleted
or moved. Commit on your branch with a plain English message ending:

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
