# PP safety and discovery changes

- `README.md`: Document export, discovery, validation, exception review and approved writing; describe adapters and configuration.
- `config/discovery_categories.toml`: Reuse the existing OSM category definitions required by the boundary and discovery collector.
- `config/london.toml`: List London boroughs and the City of London so neighbouring council boundaries cannot qualify.
- `config/rules.toml`: Configure exact dropdown values for standalone validation.
- `config/sheets.toml`: Move sheet ID, working/original tab names and gid into non-secret configuration.
- `docs/HANDOVER.md`: Repair the missing handover pointer with current workflow and safety references.
- `docs/PP_IMPLEMENTATION.md`: Record the complete file-by-file change summary and validation evidence.
- `src/ferro_parking/__main__.py`: Register discover, validate and osm-gaps; remove the row-698 debug output.
- `src/ferro_parking/capture_extract.py`: Use Not published for absent maximum stays, require explicit unlimited wording and refuse output replacement.
- `src/ferro_parking/capture_fill.py`: Reuse strict tariff templates and allocate fresh run directories.
- `src/ferro_parking/clear_unverified.py`: Require both wipe flags, report affected rows and exclude personal verifiers.
- `src/ferro_parking/discover.py`: Orchestrate adapters, London checks, ordered dedupe and draft/match/exception/summary outputs.
- `src/ferro_parking/discovery.py`: Reuse existing OSM collection, boundary lookup and category matching without sheet writes; reserve fresh outputs.
- `src/ferro_parking/evidence_level.py`: Reserve a new directory for each backfill plan.
- `src/ferro_parking/fill.py`: Protect geo and owner columns, allowlist loaded plans, guard live identity/completion, leave OSM unfinished and require wipe confirmation.
- `src/ferro_parking/formats.py`: Conservatively parse and validate tariff templates, minute limits and supported OSM hours.
- `src/ferro_parking/gaps.py`: Report public/customer OSM gaps within London using existing 40 m and brand-aware 150 m matching.
- `src/ferro_parking/london.py`: Cache and rate-limit bulk postcode lookups, with terminated-postcode and coordinate fallback.
- `src/ferro_parking/osm_match.py`: Reuse cautious cost derivation, share whole-word matching and reserve fresh output paths.
- `src/ferro_parking/page_fill.py`: Remove invented Geo Precision defaults.
- `src/ferro_parking/policy_fill.py`: Send map-absence cases to exceptions and reuse the shared word matcher.
- `src/ferro_parking/run_paths.py`: Allocate append-only date folders with numeric suffixes; refuse existing explicit outputs.
- `src/ferro_parking/settings.py`: Load sheet configuration with FERRO_* environment overrides.
- `src/ferro_parking/sheets.py`: Read sheet identity and tab settings from configuration.
- `src/ferro_parking/sources/__init__.py`: Add generic CSV/JSON import and the official City of London structured finder adapter.
- `src/ferro_parking/sync.py`: Prove unique Place ID or name+postcode alignment, remove positional joins and require an explicit append plan.
- `src/ferro_parking/validation.py`: Wrap existing capture and consistency validators; emit field-level CSV failures and clean/failure exit codes.
- `tests/conftest.py`: Block network connections throughout the test suite.
- `tests/fixtures/discovery_sample.osm`: Reuse the small OSM discovery and borough fixture.
- `tests/fixtures/discovery_sample_rows.csv`: Reuse sheet rows for OSM matching tests.
- `tests/fixtures/official_city_finder.json`: Provide an offline official finder schema fixture.
- `tests/fixtures/source_locations.csv`: Provide an offline generic source fixture.
- `tests/test_capture_extract.py`: Regress absent, explicit and merely unstated unlimited stays.
- `tests/test_discovery.py`: Verify the reused OSM discovery collector, matching and fresh output behavior.
- `tests/test_fill.py`: Regress protected writes, OSM draft completion and live identity/verifier guards.
- `tests/test_osm_match.py`: Require unknown cost for OSM-only free-parking suggestions.
- `tests/test_policy_fill.py`: Require exception review instead of presumed no-parking values.
- `tests/test_pp_workflow.py`: Cover adapters, dedupe order, mocked London lookup/cache, formats, validation, wipe guards and OSM gaps.
- `tests/test_sync.py`: Regress identity joins and refusal of unprovable alignment.

Verification: 345 tests pass with network connections forbidden. Offline CLI smoke tests
produced one candidate, validated it with zero failures, and wrote gaps.csv.
No live sheet access or apply command was used.

The PR targets current upstream main in an isolated worktree. Unrelated local Grok,
tranche and round-two work is excluded. Existing OSM discovery code and fixtures are
included as dependencies rather than implemented a second time.

Unsupported hours syntax and generic source claims require exception review.
No candidate appending is implemented or performed by discovery.
