# Current work

Updated 11 November 2026. Read this for priorities and remaining work only.
Counts describe the local database, not a fresh Google Sheet export.
Historical documents remain available in Git history. Run evidence stays under `data/runs/`.

## Remaining places

| Measure | Places |
|---|---:|
| Total records | 11,558 |
| Blank Verification Result | 6,190 |
| Needs on-site check | 1,176 |
| Active OSM-created records | 3,951 |

The latest saved route is `route-20261111T143442Z`.
Its 6,190 unfinished rows comprise 4,824 Grok, 901 no_evidence, 113 station,
173 website reader, 233 default, 43 personal-lock and 1 on-site-hold rows.
A filled verification result does not prove that every parking detail is known.
For current counts, run the read-only example in README.md. Saved routing can lag behind data changes.

## Next work, in order

1. Finish extractor controls before any research apply. Venue charge association,
   free-period handling and contradictory-sentence guards are implemented.
   Station guards, fetch metadata, shared finished/personal locks including undo,
   and offline replay evaluation remain open in the last recorded continuation.
   Inspect code and tests before treating a recorded item as unimplemented.
   Replay must hide expected answers and report supported accuracy per field with denominators.
2. Build source adapters from identity counts. The leading proposals are Sainsbury's 33,
   Lidl 25, Tesco Express 19, Tesco 17 and Asda 15.
   The full list is `data/runs/2026-11-11_20/osm_identity/counts.csv`.
   Preserve each field's quote, canonical URL, retrieval time and cached page hash.
   Report requests, failures, cache hits and measured throughput.
   Make sure that the optional TfL endpoint and its terms allow use. Missing credentials mean skip that source.
3. Refresh routing and research queues after reviewed database changes.
   Report legacy readiness separately from evidence-supported readiness.
   Keep Grok payment fields blank and database-only row numbers blank.
4. Complete publication dry runs for new-row appends before any Sheet approval.
   Cover fresh identity, drift, duplicate IDs, missing imported IDs, protected fields,
   formulas, grid growth and partial-write recovery. Test the six controls offline.
   Make sure that OSM attribution and licensing agree with primary sources. Produce a full dry run
   and a selectable 20-row pilot. Stop for the owner's explicit go before publication.

## Source imports

`discover` imports an official car park list and deduplicates it against the
database. Two changes on 11 November made it usable: it reads
`db.current_rows` instead of a sheet export, so it sees the 3,951 created
records, and it decides London membership from the extract's borough polygons
instead of postcodes.io, so it needs no network. The polygon cache is
`data/cache/boroughs.geojson`. Delete that file to rebuild it from a newer
extract with `--boroughs-from`.

Every https request from the owner's machine currently fails with a
certificate error, so an official list has to be downloaded outside the tool
and passed with `--input`.

| Borough or source | Official list | Published official | Official sites we hold | Official gap | OSM-derived |
|---|---|---:|---:|---:|---:|
| City of London | ArcGIS COMPASS layer 2 | 5 | 5 | 0 | Not counted |

Coverage is complete for City of London, and the import found a duplicate pair
in our own data rather than a gap. 32 boroughs remain uncounted, so there is
still no defensible total for London. Build the table one borough at a time;
the published count per borough is the only honest denominator.

Discovery now ignores URLs shared by every row of a multi-row import when
matching identities, including duplicates within that import. Source evidence
keeps the URLs. Regression coverage includes the saved Minories exception.

Coverage imports await the owner's local official lists and borough gap order.
The specified `data/runs/2026-11-11_14/osm_identity/counts.csv` contains brand
counts, not borough gaps. Only the City of London list is currently in
`data/raw/`. No other borough has been classified as lacking a machine-readable
list, so no OSM fallback has been applied. The Minories borough disagreement
remains held for the owner.

## Applied identity

The identity plan is applied. The run is `apply-20261111T202010Z` and `db-undo
--run apply-20261111T202010Z` restores all 703 values. The plan filled 703
blank Brand cells and nothing else. No row was refused.

The review of the first plan found two anchors that stand in another owner's
car park. A street vendor and a kiosk each named a car park after a food stall.
The matcher now rejects `street_vendor=yes` and `building=kiosk` anchors, so
one case went back to held and PP-008716 reads B&Q instead of Burgers Bar.
The applied plan is `data/runs/2026-11-11_20/osm_identity/plan.jsonl`.

Seven of the 21 inside-car-park brands remain weak and need a person:
PP-008073, PP-008196, PP-008381, PP-009553, PP-010743, PP-011554 and
PP-012272. Each names a small food outlet or a bus stop node that the geometry
places inside a larger car park. Brand is identity only, so no parking answer
depends on them.

## Owner decisions and holds

- PP-008072, New Barnet Sainsbury's Car Park: proposed retirement only, awaiting owner approval.
  Its Brand now reads Sainsbury's. Identity does not act on the retirement hold.
- PP-005457 is recorded as a repeat of PP-000194, the Minories Car Park pair
  the City of London feed exposed. PP-000194 stands because it carries the
  published charges, an evidence level of Verified and the protected payment
  columns. Nothing was deleted and the sheet export is unchanged, so PP-005457
  still exists and now routes to skip_duplicate. Two follow-ups: attaching
  PP-005457's OpenStreetMap reference node/1590148307 to PP-000194 needs its own
  audited plan, and the two rows disagree about the borough, where PP-000194
  says Tower Hamlets and the City of London feed implies City of London.
- Eight weaker retirement proposals remain report-only.
- 184 attachment cases need a separate audited plan:
  `data/runs/2026-11-11_6/holds/attachment_cases.csv`.
- Two personally checked rows need the owner:
  `data/runs/2026-11-11_6/holds/protected_rows.csv`.
- One routing issue needs a person:
  `data/runs/2026-11-11_12/route/proposals.csv`.
- Grok skip rules remain unapplied by owner decision. Read `docs/grok_skip.md` only for that feature.

## Completed foundation

The created-record path, London OSM insertion and hold-list apply are complete.
Created identities do not establish access, prices or time limits.
The identity matcher generates plans only. The coverage change passed 1,525 tests.
Code ownership is in `docs/MAP.md`. Creation procedures are in `ADD_PLACES_RUNBOOK.md`.
Keep this file current and short. Do not append historical run narratives.
