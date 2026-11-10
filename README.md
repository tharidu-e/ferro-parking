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
