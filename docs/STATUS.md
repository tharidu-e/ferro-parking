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

The latest saved route is `route-20261111T212456Z`.
Its 6,244 routed rows comprise 4,844 Grok, 866 no_evidence, 233 default,
229 website reader and 57 station rows. 5,314 rows are skipped, of which 47
are personal locks and 1,175 need an on-site check. The station count fell
from 113, because 56 station pages state that the station has no parking.
A filled verification result does not prove that every parking detail is known.
For current counts, run the read-only example in README.md. Saved routing can lag behind data changes.

## Readiness, two ways

| Measure | Places |
|---|---:|
| Legacy showable | 1,500 |
| Legacy complete | 1,055 |
| Evidence-supported showable | 50 |
| Evidence-supported complete | 0 |

Legacy counts read the sheet's own cells, through `readiness.counts` over a
`db-export`. Evidence-supported means the `evidence` table holds a quote for
Can Park?, Who Can Park and Cost Type on that place. 50 rows reach that bar,
all from the website readers. The other 1,450 legacy answers predate the
evidence table, so do not read 1,500 as 1,500 checked car parks.

The Asda rows are not legacy showable, because their Cost Type reads Unknown.
The store page states a car park and no price.

## Next work, in order

1. Build source adapters from identity counts. Asda and Lidl are built.
   Sainsbury's 33, Tesco 17 and Tesco Express 19 are measured and skipped,
   with the reason in `fetch_fill.SKIPPED_HOSTS`.
   The full brand list is `data/runs/2026-11-11_20/osm_identity/counts.csv`.
   Make sure that the optional TfL endpoint and its terms allow use. Missing credentials mean skip that source.
2. Complete publication dry runs for new-row appends before any Sheet approval.
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

| Borough | Official inventory | Published official | Official sites we hold | Official gap | OSM-derived |
|---|---|---:|---:|---|---:|
| Barnet | Current page blocked | Unknown | Unknown | Unknown | 375 |
| Hillingdon | Council point layer 3 | 28 | 24 | 4 held | 259 |
| Bromley | Council directory | 30 | 30 | 0 | 254 |
| Hounslow | Council area lists | 21 | 21 by name | 0 by name | 229 |
| Enfield | Not imported | Unknown | Unknown | Unknown | 209 |
| Havering | Council car park links | 24 | 24 by name | 0 by name | 204 |
| Bexley | Council sections | 19 listed, 18 headline | 19 | 0 of 19 listed | 176 |
| Croydon | Council map markers | 19 | 19 by name | 0 by name | 176 |
| Greenwich | Not imported | Unknown | Unknown | Unknown | 153 |
| Redbridge | Not imported | Unknown | Unknown | Unknown | 146 |
| Newham | Not imported | Unknown | Unknown | Unknown | 134 |
| Waltham Forest | Not imported | Unknown | Unknown | Unknown | 129 |
| Sutton | Not imported | Unknown | Unknown | Unknown | 117 |
| Richmond upon Thames | Not imported | Unknown | Unknown | Unknown | 116 |
| Ealing | Not imported | Unknown | Unknown | Unknown | 112 |
| Merton | Not imported | Unknown | Unknown | Unknown | 110 |
| Harrow | Not imported | Unknown | Unknown | Unknown | 101 |
| Tower Hamlets | Not imported | Unknown | Unknown | Unknown | 100 |
| Brent | Not imported | Unknown | Unknown | Unknown | 91 |
| Barking and Dagenham | Not imported | Unknown | Unknown | Unknown | 86 |
| Southwark | Not imported | Unknown | Unknown | Unknown | 83 |
| Lewisham | Not imported | Unknown | Unknown | Unknown | 81 |
| Kingston upon Thames | Not imported | Unknown | Unknown | Unknown | 76 |
| Wandsworth | Not imported | Unknown | Unknown | Unknown | 73 |
| Haringey | Not imported | Unknown | Unknown | Unknown | 68 |
| Westminster | Not imported | Unknown | Unknown | Unknown | 59 |
| Camden | Not imported | Unknown | Unknown | Unknown | 53 |
| Kensington and Chelsea | Not imported | Unknown | Unknown | Unknown | 45 |
| Lambeth | Not imported | Unknown | Unknown | Unknown | 42 |
| Hackney | Not imported | Unknown | Unknown | Unknown | 35 |
| Hammersmith and Fulham | Not imported | Unknown | Unknown | Unknown | 34 |
| Islington | Not imported | Unknown | Unknown | Unknown | 19 |
| City of London | COMPASS layer 2 | 5 | 5 | 0 | 6 |

Order uses `readiness.counts` over active OSM-created current database rows,
not brand counts or a Sheet export. Snapshot:
`data/runs/2026-11-11_25/coverage/borough_order.csv`.
Official inventories cover their stated council lists, not every private site.
Unknown is not zero. OSM-derived identities do not establish parking permission.

Bromley reimport: 30 per-car-park pages, 30 reviewed existing sites, zero
exceptions or gaps. Review: `data/runs/2026-11-11_73/coverage_bromley/`.

Bexley reimport: all 19 region exceptions resolved by exact site-name and
borough review against PP-000105 to PP-000123. No place needs creation or a
duplicate mark. The page headline still says 18. Review: `data/runs/2026-11-11_62/coverage_bexley/`.

Discovery ignores URLs shared by every row of a multi-row import when matching
identities, including duplicates within the import. Evidence keeps the URLs.

Barnet: the current-page adapter rejects both saved interruption responses.
Current coverage is unknown; the 2014 CSV remains a cross-check only. Owner
must save the actual [current list](https://www.barnet.gov.uk/parking/car-parks-and-street-parking-locations)
as `data/raw/barnet_car_parks_current.html`. Block report: `data/runs/2026-11-11_49/coverage_barnet/review.json`.

Hillingdon lists 28 sites: discovery returned 26 matches, one new candidate and
one ambiguous postcode. Coordinate/name review supports 24 existing sites;
Civic Hall, Hayes Pool, Kingsend South short stay and Falling Lane remain held.
Cedars and Tesco are distinct sites, not duplicates. Review:
`data/runs/2026-11-11_27/coverage_review/hillingdon_review.csv`.
No db-duplicate or db-create changes were applied.
Bromley lists 30 sites, all matched existing named council car parks, with no
exceptions. Hounslow lists 21 sites, all reviewed by name against existing
council car parks; its source has no pins, so discovery retains 21 region
exceptions. Barnet has 17 historical name matches and three held names. Reviews:
`data/runs/2026-11-11_31/coverage_review/`. Enfield download returned HTTP 403;
needs an owner browser download. Havering has 24 listed named sites, with
possible repeated records held; Bexley lists 19 named sites already held but
its headline says 18. Croydon lists 19 named sites already held; Waddon Leisure
Centre has a 1.9 km pin disagreement, left unchanged. Imports are in
`2026-11-11_32`, `_33` and `_37` under `data/runs/`.

Stopped for the owner: the requested db-duplicate dry run for PP-009347
(Slaney Road) keeping PP-000818 refuses an active created record and points to
retirement instead. Zero changes were applied. Report:
`data/runs/2026-11-11_38/db_duplicate/report.json`. No retirement is authorized.
Greenwich is the next borough after this decision.
No OSM fallback is applied until absence of a machine-readable list is established.
Discovery foundation committed as `2f9b24c`; each borough now gets its own commit.

## Grok hand-off

The queue is `data/runs/2026-11-11_48/grok_queue/grok_queue.csv`, 4,807 rows
in the bot's own tab layout. Run the bot over that file outside this project
and put the results CSV in `data/raw/`.

Ferro Autopay and Parking Charge are blank on all 4,807 rows. The Row column
is blank on the 3,936 rows that exist only in the database, and holds a sheet
row number on the other 871. No created record carries a row number.

No results CSV is in `data/raw/` yet, so `grok-import` has not run and there
are no mapped, rejected or skipped counts to report. Nothing from the bot will
be applied.

## Applied research

Every website reader plan is applied, each with its own undo. Use
`db-undo --run <run>` to restore one.

| Source | Rows read | Rows with values | Changes | Run |
|---|---:|---:|---:|---|
| storelocator.asda.com | 17 | 17 | 244 | `apply-20261111T210308Z`, `apply-20261111T211238Z` |
| better.org.uk | 84 | 37 | 635 | `apply-20261111T210620Z` |
| thegymgroup.com | 49 | 14 | 252 | `apply-20261111T210659Z` |
| puregym.com | 40 | 15 | 272 | `apply-20261111T210907Z` |
| nuffieldhealth.com | 15 | 6 | 108 | `apply-20261111T211935Z` |
| www.lidl.co.uk | 25 | 0 | 0 | nothing to apply |
| marksandspencer.com | 39 | 0 | 0 | 15 rows held |
| station | 473 | 119 | 2,275 | `apply-20261111T212427Z` |

No plan was refused. Each evidence row carries the quote, the page url, the
retrieval time and the cached page hash, for the fields the page states only.

The M&S store pages state a car park for 15 rows. All 15 are held, because
the row has no Place Category. The validator asks for that column on a
Conditional row. A guessed category invents identity, so run
`propose-categories` and `category-plan` for those rows instead.

Lidl reads every page and writes nothing, which is correct. Its store pages
list accessible bays and no car park.

The station fetcher owns 473 rows: the 113 on the station stage and every Grok
row that is a station. 138 pages resolved and 335 names did not. 56 rows read
Can Park? No from the exact words "No parking spaces". 48 read Yes from a
stated space count. No station row gained a price, a maximum stay or a Who Can
Park, because the page does not carry them.

19 station rows are reported for a person in
`data/runs/2026-11-11_94/fetch_fill/held.csv`. Each is a finished row whose own
text db-apply refuses. The causes are an en dash, a Decision Reason that names
no route, and an Evidence Level the rules no longer list. One refused line
blocks a whole plan, so the runner now reads its own plan back through
db-apply's checks and drops such a row.

The replay is `data/runs/2026-11-11_98/station_replay/`. The station fetcher
read 104 frozen pages with the reference answers hidden and agreed with the
reference on Can Park? for 104 of 104. Supported accuracy reads 0 percent of
104, because a fresh replay has no attestation for its own answers until a
reviewer reads them.

A structural weakness to fix next: `validate_rows` sees only the plan's own
columns, so a planner has to restate a row's existing values as context. That
is why the rows above fail on text somebody else wrote. Pass the row to the validator as context. That
removes the need for `CONTEXT_COLUMNS` and for the kept-back lines.

## Applied identity

The identity plan is applied. The run is `apply-20261111T202010Z` and `db-undo
--run apply-20261111T202010Z` restores all 703 values. The plan filled 703
blank Brand cells and nothing else. No row was refused. The applied plan is
`data/runs/2026-11-11_20/osm_identity/plan.jsonl`.

The review of the first plan found two anchors that stand in another owner's
car park. A street vendor and a kiosk each named a car park after a food stall.
The matcher now rejects `street_vendor=yes` and `building=kiosk` anchors, so
one case went back to held and PP-008716 reads B&Q instead of Burgers Bar.

Seven of the 21 inside-car-park brands remain weak and need a person:
PP-008073, PP-008196, PP-008381, PP-009553, PP-010743, PP-011554 and
PP-012272. Each names a small food outlet or a bus stop node that the geometry
places inside a larger car park. Brand is identity only, so no parking answer
depends on them.

## Extractor controls

All of step 4 is closed. The station guards were already built and tested, so
nothing was rebuilt there. Three controls were open and are now done.

Page metadata. A plan line carries `retrieved_at` and `page_hash`. Both are
copied while they still describe the page the quote came from. `db-apply`
stores both on the evidence row. The quote, the url and the metadata reach only a
column the fetcher itself read from the page. A bookkeeping column, a column
page_fill derived, and a value such as Unknown carry none of them.

Locks. One verifier test holds any label the automation list in
`config/grok_value_map.toml` does not declare. Four live rows read
"Deshan (pilot, manual check)" and the old prefix test let them through.
`db-apply` also keeps a finished row's result and its existing answers. It
still fills a blank cell on that row. If a finished row has a parking gap,
routing sends it back and asks for that cell.
`db-undo` refuses a row a person checked since the run and
a cell somebody changed after the run wrote it.

Replay. `python -m ferro_parking.evaluation --replay KEY` runs one registered
fetcher over frozen pages and prints supported accuracy per field with its
denominator. The extractor sees the allowlisted identity and the page only. A
fresh replay scores every answer wrong until a reviewer attests it, so the
report adds plain agreement with the supported reference.

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
The identity matcher generates plans only. The latest full suite check passed 1,575 tests, including concurrent evidence work.
Code ownership is in `docs/MAP.md`. Creation procedures are in `ADD_PLACES_RUNBOOK.md`.
Keep this file current and short. Do not append historical run narratives.
