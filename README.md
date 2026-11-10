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
