# Code ownership map

This file says which module owns what. For what the tool can already do, run
`python -m ferro_parking --help`. That list is the capability index and it is the
first thing to read before building anything.


Read this before adding a module. Paths below are relative to `src/ferro_parking/`, except `config/` entries. CLI means dispatch from `__main__.py`. This is an ownership index, not a new execution order; use `docs/STATUS.md` for current priorities.

## Import and export

- `db.py`: Owns lossless CSV snapshots, current-row overlays, created records, derived SQLite tables and IDs; used by routing, plans, creation and publication.
- `sheets.py`: Owns authenticated sheet reads, header lookup, cell writes and verification-last ordering; called by export, fills, sync and approved publication.
- `sync.py`: Owns captured-row reconciliation, append plans and independent append/update export comparison; called by CLI sync, tranche writing and publication.
- `config/sheets.toml`: Owns non-secret spreadsheet and tab identities; loaded by settings and sheet clients.

## Discovery

- `discovery.py`: Owns category loading/classification, the OSM collector, named matching and `match_unnamed_car_parks`; used by gaps, tranche selection, policy and identity matching.
- `discover.py`: Owns source ingestion orchestration, London filtering, deduplication and draft candidates; CLI discover calls source adapters and format parsers.
- `osm_match.py`: Owns row-to-OSM venue/car-park matches, metric projection, name/brand helpers and research packets; CLI match and other geometry modules reuse it.
- `gaps.py`: Owns unmatched public/customer OSM car-park reports; CLI osm-gaps reuses discovery matching.
- `tranche1.py`: Owns filtering, scoring and review of discovery's first missing-place tranche; called by CLI tranche1 before append planning.
- `london.py`: Owns cached postcode lookup and coordinate fallback for London eligibility; discover calls its LondonFilter.
- `sources/__init__.py`: Owns discovery adapter registry, generic input and City of London finder conversion; discover calls ADAPTERS.
- `config/discovery_categories.toml`: Owns OSM tag rules and sheet category vocabulary for 16 groups; discovery loads it for matching, routing and identity proposals.
- `config/london.toml`: Owns the London borough allowlist; gaps reads it to exclude neighbouring authority polygons.

## Creation

- `osm_places.py`: Owns parking eligibility, exclusions, London geometry and identity-only db-create candidates; CLI osm-places and holds reuse these rules.
- `create.py`: Owns creation validation, duplicate/proximity guards, transactional IDs and audited deactivate/reactivate; CLI db-create, db-create-undo and db-create-redo call it.
- `holds.py`: Owns evidence bundles, deterministic hold decisions, reviewer merging and action reports; CLI holds-bundle/holds-merge and creation reuse persisted verdicts.
- `osm_identity.py`: Owns geometry-to-anchor identity plans for active OSM-created rows; CLI osm-identity reuses discovery and plan checks without applying changes.
- `config/holds_decisions.csv`: Owns persisted verdicts keyed by OSM reference; holds and creation consult it before asking reviewers again.

## Routing

- `route.py`: Owns one latest research stage per Place ID, source_key and routing reports; CLI route calls evidence checks and the fetcher registry.
- `triage_blanks.py`: Owns blank-answer buckets and nearby OSM evidence reports; route and category proposal tools reuse its classification.
- `car_park_evidence.py`: Owns positive parking-existence checks from cached pages, matched OSM and names; route uses it before cautious defaults.
- `grok_queue.py`: Owns local latest-stage queue export in the bot layout, including blank payment fields; CLI grok-queue reads routing and database rows.

## Research

- `fill.py`: Owns OSM draft derivation, research/protected column allowlists and guarded sheet write/undo; CLI fill/write/undo and all planners reuse its controls.
- `page_fill.py`: Owns page-derived row values and shared parking consistency checks; capture, policy, fetchers and validators call it.
- `capture_extract.py`: Owns conservative extraction of previously captured evidence into structured records; CLI capture-extract and fill-round2 call it.
- `capture_fill.py`: Owns captured-record eligibility, evidence scope validation and row plans under R8; CLI capture-fill, extraction and validation reuse it.
- `policy_fill.py`: Owns cautious R1/R10 chain/presumed classification and nearby-car-park guards; CLI policy-fill, category_default and fill_round2 reuse it.
- `category_default.py`: Owns db-apply plans for latest default-stage rows using existing policy rules; CLI default-fill and research_report call it.
- `fill_round2.py`: Owns combined dry-run passes, six controls and independent second reading; CLI fill-round2, importer, publisher and research reports reuse it.
- `category_plan.py`: Owns blank-category db plans with supermarket format guards and current routing stages; CLI category-plan consumes propose-categories output.
- `propose_categories.py`: Owns review-only categories from captured types and nearby evidence; CLI propose-categories supplies category_plan inputs.
- `fill_postcodes.py`: Owns offline nearest-centroid postcode proposals with distance limits; CLI fill-postcodes writes review CSVs only.
- `clear_unverified.py`: Owns plans to clear unfinished answers, with saved undo and explicit wipe confirmation; CLI and round-two fill call it.
- `evidence_level.py`: Owns Evidence Level header/dropdown planning and finished-row backfill; CLI evidence-level-column/backfill call it.
- `fetch_fill.py`: Owns registered fetcher orchestration, routed selection and evidence-backed db plans; CLI fetch-fill, route and reporting share its registry.
- `sources/fetch.py`: Owns bounded, rate-limited fetches, cached pages, source-domain URL selection and challenge detection; fetch_fill and probe call it.
- `sources/station.py`: Owns National Rail station parking extraction and conservative identity/conflict handling; fetch_fill calls StationFetcher.
- `sources/station_list.py`: Owns cached official station-list lookup, ambiguity refusal and finder slugs; StationFetcher uses it instead of guessed URLs.
- `sources/venue.py`: Owns supported gym/council venue-page extraction, quote association and negation guards; fetch_fill calls VenueFetcher.
- `probe.py`: Owns small source-key page probes and saved fixtures before adapter development; CLI probe reuses routed rows and source fetching.
- `grok_import.py`: Owns conservative Grok Results mapping, validation, rejects and dry-run artifacts; module CLI and db plan conversion call it.
- `grok_skip.py`: Owns read-only unresearched-queue skip proposals, snapshots and independent recomputation; module CLI and skip review call it.
- `grok_skip_review.py`: Owns offline skip-rule backtests against saved researched rows; its module CLI calls grok_skip without applying markers.
- `research_report.py`: Owns combined local plan counts, examples, refusals and second-reading reports; CLI research-report consumes reader/default outputs.
- `evaluation.py`: Owns offline reference reconciliation, frozen-page replay and field-level evidence diagnostics; its module CLI evaluates without granting apply authority.
- `rules.py`: Owns typed R1-R10 policy loading, chain normalisation and branch-format checks; fill, policy, category and discovery planning call it.
- `config/rules.toml`: Owns policy values, format lists, risky-value restrictions and exact dropdowns; rules and validation load it.
- `config/grok_value_map.toml`: Owns Grok-to-sheet mappings, accepted values and automation verifier identities; grok_import loads it, and osm_identity reuses its automation verifier list.

## Publication

- `plan.py`: Owns JSONL db plans, stage/column/replacement refusals, audited apply and undo; CLI db-apply/db-undo and all database planners reuse it.
- `publish.py`: Owns approved applied-change publication planning, drift guards, pilot filters and independent comparison; CLI publish reuses the guarded sheet writer.
- `tranche1_write.py`: Owns selected-place append plans, store-car-park attachment guards and approved append application; CLI tranche1-write/-apply reuses sync.
- `grok_apply.py`: Owns saved Grok-plan preflight, approved dropdown extensions and guarded application; module CLI calls existing writer and export comparison.

## Support

- `__init__.py`: Defines the pipeline package; Python imports it before module entry points.
- `__main__.py`: Owns CLI help and command dispatch; `python -m ferro_parking` calls each existing command entry point.
- `run_paths.py`: Owns exclusive fresh run-directory allocation and explicit output reservation; planners call it to preserve earlier runs.
- `settings.py`: Owns non-secret settings and FERRO environment overrides; sheet clients and hold configuration use it.
- `formats.py`: Owns conservative tariff, hours and stay grammar; discovery drafting and validation reuse its parsers.
- `validation.py`: Owns offline schema, dropdown, evidence and consistency validation, including identity-only metadata plans; plan/import/publish paths and CLI validate call it.
- `readiness.py`: Owns legacy showable/complete counts and usable-pin checks; CLI readiness, routing, postcode review and queue exports reuse it.
