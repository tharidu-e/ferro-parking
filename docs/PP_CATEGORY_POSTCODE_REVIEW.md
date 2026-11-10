# Category and postcode review proposals

Reviewer: Deshan.

- `README.md`: Document both CSV-only commands, directory columns, conflict handling, nearest-centroid limits and review requirements.
- `docs/PP_CATEGORY_POSTCODE_REVIEW.md`: Record this file-by-file summary, local dry-run counts, supplied targets and missing-input limitations.
- `src/ferro_parking/__main__.py`: Wire propose-categories and fill-postcodes into the dispatcher and help text.
- `src/ferro_parking/fill_postcodes.py`: Read local centroid aliases, reject invalid directory rows, find the exact haversine nearest centroid and produce review-only postcode proposals or explicit skips.
- `src/ferro_parking/propose_categories.py`: Map captured type families to configured dropdown values; emit proposals, unclassified rows and conflicts; optionally attach existing OSM evidence.
- `tests/fixtures/postcode_centroids.csv`: Supply three synthetic centroid records for offline tests, not a real postcode directory.
- `tests/test_fill_postcodes.py`: Cover nearby/far centroids, circular centroid pins, filled postcodes, invalid pins, column aliases, ties, exact haversine selection and unchanged inputs.
- `tests/test_propose_categories.py`: Cover each requested type group, safe fallback, brand refinement, Station-name precedence, conflicts, dropdown membership, optional OSM observations and unchanged inputs.
- `tests/test_readiness_triage.py`: Extend the shared entrypoint test to both new commands and forbid Google service authentication.

## Local dry-run counts versus supplied targets

| Measure | Supplied 7,607-row reference target | Available local 6,924-row export |
|---|---:|---:|
| Blank Place Category | 3,032 | 3,600 |
| Distinct types among those blanks | 110 | 147 |
| Category proposals | About 3,031 | 3,599 |
| Unclassified blank categories | At least 1 | 1 |
| Category conflicts | Not specified | 347 |
| Existing categories outside dropdown | 2 | 0 |
| Blank postcode with a usable pin | 1,458 | 1,057 |
| Postcode centroid pins excluded | 42 | 45 |
| Candidates after centroid exclusion | About 1,416 | 1,012 |

All 146 nonblank type strings in the available blank-category subset mapped through
the explicit table at high confidence. The remaining row has a blank type. Conflicts
are review records only; no existing category was overwritten.

No real Code-Point Open or ONS centroid CSV is available locally. The postcode CLI
was therefore exercised with a header-only directory to verify safe handling of
missing lookup data. It proposed 0 and skipped 1,057: 45 circular centroid pins and
1,012 rows with reason `no postcode directory loaded`. Those are eligibility and
safe-skip results, not a completed nearest-postcode dry run. Nearby/far postcode
proposals are verified against the small synthetic fixture in tests only.

The supplied 7,607-row counts and 110-type coverage remain to be checked against
that exact export. The different local export is not relabelled as the reference.
A real centroid directory is required to measure actual postcode proposals at 250 m.
Neither the full sheet export nor local review CSVs are committed.

## Validation and safety

526 tests pass. The suite blocks network connections; new command tests also
reject any call to fill.sheets.get_service. Both CLIs were run on the available
local CSV and wrote new outputs under /private/tmp. Fixtures verify original input
bytes and centroid directory bytes remain unchanged. Existing --out directories
raise FileExistsError. No write, sync-apply, clear-unverified or live Google Sheet
commands were run. No dependencies or Google auth were added. Writer functions,
protected-column checks, captured-field write paths and coordinate fields are unchanged.

The postcode spatial tree only supplies a seed upper bound. All candidate centroids
inside the corresponding safe latitude belt are ranked using sync.haversine_m;
projected distance never determines the proposed postcode. Tied different postcodes
are skipped. Even a close postcode remains a review candidate, not proof of the site.
