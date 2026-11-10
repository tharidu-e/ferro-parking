# PP matching and readiness follow-up

- `README.md`: Document matching priorities, field flags, validator warnings, triage, readiness and replay usage.
- `docs/PP_DISCOVERY_FOLLOWUP.md`: Record the file-by-file changes, measured fixture evidence and pending live-batch acceptance.
- `scripts/replay_discovery_batches.py`: Reconstruct sources from the five original exceptions files, replay the existing pipeline and verify listing counts plus a majority matched.
- `src/ferro_parking/__main__.py`: Register and describe the two new read-only commands.
- `src/ferro_parking/discover.py`: Match Place ID and source URLs first; resolve shared postcode/pin hits by a clear name winner; retain identities and withhold only unparsed/unverified fields with structured flags.
- `src/ferro_parking/policy_fill.py`: Make the obsolete map-absence no-parking builder raise instead of constructing a writeable record.
- `src/ferro_parking/readiness.py`: Count showable and complete rows overall, by borough and by postcode district.
- `src/ferro_parking/sources/__init__.py`: Preserve either Place ID spelling in generic sources and repair only City tariff question marks before digits.
- `src/ferro_parking/triage_blanks.py`: Bucket every blank parking answer using local metadata, optionally attaching raw nearby OSM evidence.
- `src/ferro_parking/validation.py`: Gate optional identity checks; add price-status, charging-hours, cost-type and required identity fields; distinguish warnings from errors.
- `tests/fixtures/discovery_match_cases.json`: Add small explicitly synthetic Place ID, URL and name-disambiguation cases; no full sheet export.
- `tests/test_discovery_followup.py`: Regress matching, parser fallbacks, currency repair, disabled presumed builder and validator rules, including warning-only exit status.
- `tests/test_pp_workflow.py`: Update prior behavior assertions for field-level fallback and an optional identity column.
- `tests/test_shared_source_matching.py`: Regress shared-URL ranking, weak-stage fallback, Baynard House, Heathrow terminal identity, true/near ties, dash normalisation and preserved official replay evidence.
- `tests/test_readiness_triage.py`: Test both readiness bars, source exceptions, districts, triage buckets, optional local OSM evidence and CSV-only command routing.

## Validation evidence

- Initial regression command `PYTHONPATH=src python -m pytest tests/test_discovery_followup.py -q`: 7 failed, 1 passed against the reported failure paths.
- Final suite after review fixes: 438 passed with socket connections blocked by tests/conftest.py.
- Four synthetic matching cases replayed through both original and current discover.run: before listed=4, matched=0, exceptions=4; after listed=4, matched=4, exceptions=0. These are not the four live batches.
- Both command smoke tests ran against the available local export: 6,924 rows; 2,451 blank rows triaged; showable=1,060 and complete=782. The original CSV remains an input only.
- No apply, sync-apply, clear-unverified or live-sheet commands were run. No auth was added. The writer, protected-column policy, sync.py, sheets.py and clear_unverified.py are unchanged.

## PR review follow-up

The reviewer measured these results for a99bf49 against the live 7,607-row export
(gid 1850000003). These figures are supplied by the reviewer, not rerun here:

| Batch | Listed | Original matched | Review matched | Review exceptions | After this revision listed / matched / exceptions |
|---|---:|---:|---:|---:|---|
| Heathrow | 20 | 0 | 4 | 16 | Not measured: source files unavailable |
| LCY | 4 | 0 | 2 | 2 | Not measured: source files unavailable |
| NR3 | 125 | 0 | 121 | 4 | Not measured: source files unavailable |
| Havering | 27 | 0 | 0 | 27 | Not measured: source files unavailable |
| City of London | 5 | 0 | 0 | 5 | Not measured: source files unavailable |

The review reports that the four unique-URL matches spot-checked were correct.
It attributes most remaining exceptions to shared URLs. This revision ranks every
non-ID multi-hit stage by name, tries later stages when no winner is clear, and
uses score >= 0.40 with margin >= 0.08 instead of score >= 0.80 with margin >= 0.12.
Exact ties and near ties remain unresolved. Conflicting terminal numbers cannot
win a fuzzy name match. Duplicate Place IDs remain an immediate ambiguity.

New regression command before the fix:
`PYTHONPATH=src python -m pytest tests/test_shared_source_matching.py -q`
produced 5 failures and 1 pass. The same supplied Baynard House, Terminal 2 and
Hackney dash patterns now pass, with terminal 2 selecting its own fixture row
rather than terminals 3/4/5. These are targeted regression checks, not live batch
Place ID spot-checks.

The Mac checkout still has no `2026-11-09-{heathrow,lcy,nr3,havering,col}` source
folders or `/home/box/ferro-parking`. Its available export has 6,924 rows, not the
reference 7,607. The new five-batch majority acceptance remains unverified until
the original inputs are supplied and replayed:

```bash
PYTHONPATH=src python scripts/replay_discovery_batches.py --runs-dir PATH_TO_RUNS --sheet-csv PATH_TO_7607_ROW_EXPORT
```

Replay now preserves the decoded records' existing official provenance, includes
City of London, and records original, previous-review and newly measured counts.
No after counts or live Place ID spot-check results are fabricated from fixtures.

Every replay also writes `spot_checks.csv` pairing each matched Place ID with
the source name and exported sheet Location Name for the required identity review.
