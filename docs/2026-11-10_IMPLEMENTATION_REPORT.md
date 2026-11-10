# Category apply and research review, 10 November 2026

Only the category plan was applied to the live database. Nothing was published
to Google Sheets. Fetcher and default plans remain proposals awaiting go.

## Category result

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

## Research result

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

## File-by-file code summary

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
