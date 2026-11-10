# Ferro parking pipeline

Fills and checks the Ferro Maps parking sheet ("PP Parking places", tab **ALL LONDON (clean)**)
using free data first (OpenStreetMap + rules) and the Grok PP bot only for the rows code cannot settle.

Design: `docs/PP_architecture_OSM_first.md`. Rules R1-R6 and the pilot: `docs/PP_rules_and_pilot.md`.
Bot prompt for the residue rows: `docs/PP_Validator_prompt_v2_OSM.md`.

## Setup (once)

```bash
cd ~/Documents/ferro-parking
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest            # all tests should pass
```

Put the input data in `data/raw/` (never committed):
- `greater-london-latest.osm.pbf` from https://download.geofabrik.de/europe/united-kingdom/england/greater-london-latest.osm.pbf
- `all_london_clean.csv`: export of the ALL LONDON (clean) tab
  (https://docs.google.com/spreadsheets/d/1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o/export?format=csv&gid=1850000003)

## Commands

| Step | Command | Status |
|---|---|---|
| 1. Match + route | `python -m ferro_parking match data/raw/greater-london-latest.osm.pbf data/raw/all_london_clean.csv` | built, tested |
| Export the live sheet | `python -m ferro_parking export` | built, tested |
| 2-3. Fill (rules R1-R7, dry run only) | `python -m ferro_parking fill --borough Haringey` | built, tested |
| 4. Write to the sheet | `python -m ferro_parking write PLAN.json --apply` | built, tested with mocks |
| 4. Undo a write | `python -m ferro_parking undo UNDO.json --apply` | built, tested with mocks |

Outputs go to `data/runs/<date>/`, so nothing is ever overwritten and no `_v2` files are needed.

## Rules

Rules live in `config/rules.toml`, not in code. Change a rule there, add a test in `tests/`, run `python -m pytest`.

## Safety

- The pipeline never edits these columns: Brandon's four (Free Stay Countdown, Ferro Autopay, Parking Charge, Total incl. Ferro Fee), Latitude, Longitude, Place ID, formulas, and the "(as captured)" columns.
- Every write has a dry run and an undo file first, writes Verification Result last, and is read back.
- OSM data (c) OpenStreetMap contributors, ODbL.

## PP workflow

Export -> discover -> validate -> PP reviews `exceptions.csv` -> write dry run -> owner approval -> write --apply.

```bash
python -m ferro_parking export
python -m ferro_parking discover --source city-of-london --sheet-csv data/raw/all_london_clean.csv
python -m ferro_parking discover --source generic --input locations.csv --sheet-csv data/raw/all_london_clean.csv
python -m ferro_parking validate data/runs/<date>/discover/candidates.csv
python -m ferro_parking osm-gaps data/raw/greater-london-latest.osm.pbf --sheet-csv data/raw/all_london_clean.csv
```

Discovery writes `candidates.csv`, `matches.csv`, `exceptions.csv` and `summary.json`.
It never creates or appends sheet rows. The existing OSM category report remains
available as `python -m ferro_parking.discovery PBF CSV`.
Generic CSV columns (or JSON array keys) are `name`, `address`, `postcode`, `lat`,
`lon`, `url`, `tariff`, `hours`, `max_stay`, `brand`. Generic imports cannot certify
source authority: tariff, hours and max-stay claims require PP evidence review.
The official adapter uses the [City of London car park finder](https://www.mapping.cityoflondon.gov.uk/arcgis/rest/services/COMPASS_Driving_and_Cycling/MapServer/2).
Both adapters support `--input` fixtures. Postcodes.io bulk responses are cached in
`data/cache/postcodes`; uncached calls are limited to one per second. Missing or
terminated postcodes use coordinate reverse lookup. Unresolved locations go to exceptions.
Only `region == London` passes. Nearby-postcode reverse lookup is a region check,
not proof of an exact site or a licence to change coordinates.

`validate` returns 0 when clean and 1 for failures, writing `validation.csv`.
It checks the supported conservative OSM hours grammar; unusual valid syntax is
sent for review. Tariff bands require plain hyphens, closed contiguous ranges
and prices with two decimal places. Unknown values stay `Not published` or the
column's exact `Unknown` dropdown value. No Verification Result is assigned to drafts.

After PP reviews the exceptions and source quotes, use the existing fill tools to
prepare `plan.json`, `dry_run.csv` and `undo.json`. Run the six checks and independent
second reading, show counts, samples and rejects, and wait for the owner's explicit
"go". Then:

```bash
python -m ferro_parking validate PATH/plan.json
python -m ferro_parking write PATH/plan.json
# Only after the owner's go:
python -m ferro_parking write PATH/plan.json --apply
```

Run the independent re-export compare after applying; require 0 mismatches.
Clearing cells additionally requires `--confirm-wipe`, including when applying a
saved clear plan through `write`. The clear command prints the affected row count.
Completed and personally verified rows are refused by the writer. Protected and
unknown headers are refused before authentication, including during dry runs.

Run folders are append-only: an existing date gets `_2`, `_3`, etc. Explicit output
directories and validation reports must be new. Sheet settings live in
`config/sheets.toml`; override them with `FERRO_SPREADSHEET_ID`, `FERRO_CLEAN_TAB`,
`FERRO_ORIGINAL_TAB` and `FERRO_CLEAN_GID`. `sync-apply` requires an explicit
`--append-plan` path. Tab joins require unique Place IDs or name plus postcode;
ambiguous identities abort without producing an append plan.

## PP matching and review tools

`discover` now tries exact Place ID, then any listed Source URL, before postcode,
name plus street, nearby pin and brand. Generic CSV/JSON accepts either `place_id`
or `Place ID`. Shared Source URLs, postcodes, pins and other non-ID stages use a unique exact
normalised name or a clear score leader. Fuzzy winners require score >= 0.40 and
a margin >= 0.08; conflicting terminal numbers cannot win a fuzzy match. If no
name wins, matching tries the remaining stages. Unresolved true/near ties remain
exceptions, and duplicate Place IDs are never resolved by name.
A source URL match retains query parameters and ignores fragments/trailing slashes.

An unparseable tariff, hours value or max stay no longer discards the place. The
failed value becomes `Not published`; `flags` names the field (`tariff_unparsed`,
`hours_unparsed`, `max_stay_unparsed`). Raw quotes remain available for PP review.
Drafted display text replaces en/em dashes with plain hyphens without discarding
the identity match; the raw quoted source stays available.
Generic imports still cannot certify source authority: parsed claims without trusted
adapter evidence are withheld with field-specific `*_unverified` flags. City of
London's adapter repairs only `?` immediately before a digit in its tariff field.

`validate` checks published prices against Price Status, paid tariffs with a free
first period, and missing Brand/Place Category on Yes or Conditional rows. The
identity check runs only if `Identity resolved` exists in the input. Clear charging
or controlled-hours context is an error; ambiguous context is a `charging-hours`
warning, written to `validation.csv` with `WARNING:` and excluded from the failure
exit code. Unicode dashes and Closed/parking contradictions remain errors.

```bash
python -m ferro_parking triage-blanks --sheet-csv data/raw/all_london_clean.csv
python -m ferro_parking triage-blanks --sheet-csv data/raw/all_london_clean.csv --pbf data/raw/greater-london-latest.osm.pbf
python -m ferro_parking readiness --sheet-csv data/raw/all_london_clean.csv
```

Two more commands prepare category and postcode review CSVs:

```bash
python -m ferro_parking propose-categories --sheet-csv data/raw/all_london_clean.csv
python -m ferro_parking propose-categories --sheet-csv data/raw/all_london_clean.csv --pbf data/raw/greater-london-latest.osm.pbf
python -m ferro_parking fill-postcodes --sheet-csv data/raw/all_london_clean.csv --postcodes-csv PATH_TO_CENTROIDS.csv
```

`propose-categories` uses an ordered captured-type table and the exact Place
Category dropdown. It writes `propose_categories.csv`, `unclassified.csv` and
`conflicts.csv`. Blank categories receive proposals; existing matching categories
are omitted, and disagreements or invalid existing values become conflicts.
Unknown types stay unclassified unless the existing discovery classifier gives
one unambiguous dropdown value. Optional OSM tags are observations only. The
command never proposes Brand or infers Station from a venue name alone.

`fill-postcodes` only considers blank postcodes with usable pins and excludes
Postcode centroid pins. Its required local directory accepts postcode/Postcode/pcds,
lat/latitude and lon/longitude headers. Coordinates must be WGS84 decimal degrees.
Postcodes are normalised to uppercase with one space before the inward code.
It writes `fill_postcodes.csv` and `skipped.csv`. Haversine distance chooses the
nearest centroid; the default maximum distance is 250 m, adjustable with
`--max-distance-m`. Equidistant different postcodes are skipped. A nearest-centroid
proposal needs human review: it is not proof of the exact site's postcode.
An empty directory produces explicit skips rather than guessed postcodes.

Both commands only write review CSVs to fresh run directories. `--out` must name
a directory that does not exist. Inputs, captured fields, coordinates, protected
column rules and the live sheet remain unchanged. No network or Google auth is
used. The centroid fixture in tests is synthetic and must not be used as a real
postcode directory.

`triage-blanks` writes `triage_blanks.csv` in a fresh run directory. Its buckets
are research queues, not parking answers. It includes every blank Can Park? row;
`--pbf` optionally attaches nearby raw OSM tags. Both commands read local files
only, require no network or Google authentication, and never write to the sheet.

`readiness` prints showable and complete counts, overall and by Borough and
postcode district. Showable needs Yes/Conditional, finite coordinates in range,
and known Who Can Park/Cost Type. Complete additionally needs known Hours, Max Stay
and Tariff Detail. `Not published` counts as documented only for Hours and Max Stay
with a non-empty source; `Not applicable` counts as known. A missing, Unknown or
Not published tariff, access or cost never passes the complete bar.

Replay Heathrow, LCY, NR3, Havering and City of London (`2026-11-09-col`) when
the original local run folders are available:

```bash
PYTHONPATH=src python scripts/replay_discovery_batches.py --runs-dir data/runs --sheet-csv data/raw/all_london_clean.csv
```

This extracts each `exceptions.csv` source JSON into fresh outputs and passes the
decoded records directly to `discover.run`, preserving their existing `official`
provenance. It records both the original supplied baseline and the PR review
replay counts alongside newly measured results in `comparison.json`. Each batch
also writes `spot_checks.csv`
with source name, Place ID and sheet Location Name for manual identity checks.
Exit code 0 requires the expected listing count and a majority matched for every
batch. No batch input or full sheet export
is committed to the repository.

## Local database (Phase 1 of the db-router work)

The database at `data/db/ferro_parking.sqlite` is the single source of truth for
the parking data. The Google Sheet becomes a published view and an inbox for bot
results. The file sits under `data/`, so git ignores it.

```bash
python -m ferro_parking db-import --sheet-csv data/raw/all_london_clean.csv
python -m ferro_parking db-export --out data/runs/2026-11-10/db/export.csv
python -m ferro_parking db-rebuild
```

`db-import` stores each sheet row exactly as read, in the `raw` table. It keeps
one JSON object per Place ID per import. Nothing is ever lost and no row is ever
deleted. Each run creates a new `import_id`, so you can re-import a fresh export
at any time. The command then reports what differs from the previous import: new
Place IDs, Place IDs now absent, changed cells, and conflicts. A conflict means
the sheet value matches neither the old nor the new value of a change the
database owns. That is the signal that somebody edited the sheet by hand.

`db-export` writes the 60 sheet columns in the sheet's own header order and row
order. So `discover`, `readiness`, `triage-blanks` and the other full-export
readers work on the result without a change. When the database owns no changes,
the output is byte-identical to the export it came from.

The typed tables `places` and `parking` are derived from `raw` plus the applied
rows of the `changes` log. Nothing edits them directly. `db-rebuild` recomputes
them, and running it twice gives the same tables. The `sheet_owned` table mirrors
the four columns another owner writes. Those are read-only here and are never
published.

The `db-import` output also prints the next unused Place ID, which later phases
use when they append a new place.

## Router (Phase 2 of the db-router work)

```bash
python -m ferro_parking route
```

`route` reads the database and gives every Place ID exactly one stage. It writes
the `routing` table, writes `data/runs/<date>/route/routing.csv`, and prints the
counts. It never reads or writes the sheet.

Decision order, first match wins:

1. `skip_named`: Verified By starts with "Tharidu". Hand-checked rows are never
   touched. Agent labels such as "Policy script" or "Grok (discovery)" are not
   people, so those rows stay routable.
2. `skip_missing`: the newest import no longer lists this Place ID.
3. `skip_duplicate`: `duplicate_of` is set.
4. `skip_onsite`: Verification Result is "Needs on-site check".
5. `skip_done`: Verification Result is filled, unless rule 6 applies.
6. Priority 2: a public car park that says you can park, but does not say who
   can park or what it costs.
7. Priority 1: Verification Result is blank.

A routed row then gets its stage from its derived source key. The key is the
Operator, else the domain of the first Source URL, else the brand parsed from
the name. A key with a registered fetcher gives `fetcher:<key>`. A station row
gives `station`. A public car park with no fetcher gives `grok`. Everything
else gives `default`.

A station row is one in the Station category, or one whose Type (as captured)
says station car park. The station stage is checked before `grok` and
`default`. A station car park is neither a customer venue nor an ordinary
public car park, so the category default of Phase 4 never touches it.

The brand fallback drops trailing car park wording, so "Sainsbury's Car Park"
keys as `sainsburys` and not as `sainsburys car`. A row left with no usable key
is grouped as `unbranded`, and `unbranded` never matches a fetcher.

No fetcher is registered yet, so the fetcher stage is empty. The key is still
computed and reported, because Phase 5 picks its first fetchers from those
counts. "Known" comes from `readiness.known`, so blank, Unknown and Not
published all read as not known. The reason text comes from
`triage_blanks.bucket`.

`route` also writes `proposals.csv` in the same run folder. It lists routed
rows a person has to look at, such as a row with a blank Location Name. Nothing
in that file is ever written back, because Location Name is a protected
column.

## Plan files (Phase 3 of the db-router work)

```bash
python -m ferro_parking grok-import --results-csv RESULTS.csv
python -m ferro_parking db-apply --plan PLAN.jsonl
python -m ferro_parking db-apply --plan PLAN.jsonl --apply
python -m ferro_parking db-undo --run RUN_ID
python -m ferro_parking db-undo --run RUN_ID --apply
```

A plan file is JSON lines. Each line is one change. The keys are `place_id`,
`column`, `new_value`, `quote`, `source_url`, `stage` and `verified_by`. The
column is the exact sheet header text.

`db-apply` is a dry run unless you add `--apply`. One refusal blocks the whole
plan, and `rejected.csv` lists every refused line with its reason. These lines
are refused:

- an unknown Place ID, or an unknown column
- a column another owner writes, or any other protected column
- a column outside `fill.RESEARCH_COLUMNS`
- a row whose Verified By starts with "Tharidu"
- anything `validation.validate_rows` refuses

A line that replaces a value already in the row needs strong evidence. The
plan's own Source Tier must be in `page_fill.STRONG_SOURCE_TIERS` and its
Specificity must be Site-specific. The row's existing Source Tier belongs to
the value being replaced, so it cannot vouch for the new one. A line that
restates the value already there changes nothing. It stays in the plan as
context for the validator, which sees only the plan's own columns. The change
log skips it.

Verification Result is recorded last, so a row is never finished before its
other values are in place. Every applied change is one row in the `changes`
table, under a single run id. A line with a quote or a source URL also adds an
`evidence` row.

`db-undo --run RUN_ID` appends the reverse of that run, under the run id
`undo-RUN_ID`. Nothing is deleted. A second undo of the same run does
nothing.

`grok-import` wraps the existing `grok_import.build_plan`, so the value
mapping, the validation and the second reading are unchanged. It writes
`plan.jsonl`, plus `skipped.csv`, `rejects.csv` and `dropped_columns.csv`. The
dropped file lists columns `db-apply` can never write, such as Location
Status, and columns the bot left blank. Dropping them keeps the plan usable
instead of blocked.

## Category default (Phase 4 of the db-router work)

```bash
python -m ferro_parking default-fill
```

`default-fill` is a dry run and writes nothing to the database or the sheet.
It reads the Place IDs the latest routing run put on stage `default`. It runs
the existing R1 and R10 rules from `policy_fill` on each one. It then writes a
plan file for `db-apply`.

Station rows, grok rows, fetcher rows and every skip row are out of scope. The
routing table alone decides that. A station car park is not a customer venue,
so the category default never touches one.

The rules are `policy_fill.classify`, `chain_policy_fields` and
`presumed_no_parking_fields`, used unchanged with `config/rules.toml`. Rule R7
therefore holds. No Free, no Anyone and no max stay without site-specific
evidence. A chain policy row sets Can Park? Conditional and Who Can Park per R1. It also sets Cost Type Unknown or Paid, and Max Stay
Not published. Verification Result becomes "Confirmed, details not published",
and Evidence Level becomes "Chain policy".

Each plan also carries the row's Brand and Place Category. They usually change
nothing, but `validation.validate_rows` sees only the plan's own columns and
asks for both whenever Can Park? is Yes or Conditional. A row with neither on it gets no plan and waits for a person.

The run folder holds three files. `plan.jsonl` is the plan. `summary.csv`
holds the counts by outcome and by Place Category. `examples.csv` holds five
example rows per outcome, with each field the plan changes.

`policy_fill` answers "Map absence is not evidence of no parking" for a small
venue and for a convenience format. So R10's presumed No never fires from this
command. The count is reported, and it is 0.
