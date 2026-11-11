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

Official counts cover the named council inventory, not every private car park.
We hold counts distinct listed sites after name or coordinate review, not raw
record counts. Unknown is not zero. OSM-derived means active OSM-created records
in `data/runs/2026-11-11_25/coverage/borough_order.csv`; it proves identity only.
Greenwich creation added two identity-only records; no Sheet changes were made.

| Borough | Official inventory | Published official | Official sites we hold | Official gap | OSM-derived |
|---|---|---:|---:|---|---:|
| Barnet | Current page blocked | Unknown | Unknown | Unknown | 375 |
| Bexley | Council sections | 19 listed, 18 headline | 19 | 0 of 19 listed | 176 |
| Bromley | 30 official site pages | 30 | 30 | 0 | 254 |
| Croydon | Council map markers | 19 | 19 | 0 | 176 |
| Havering | Council site links | 24 | 24 by name | 0 by name | 204 |
| Hillingdon | Council points, refreshed | 28 | 24 | Unresolved (4) | 259 |
| Hounslow | Council lists, refreshed | 21 | 21 | 0 | 229 |
| Greenwich | Official directory markers | 17 | 17 | 0 | 153 |
| City of London | COMPASS layer 2 | 5 | 5 | 0 | 6 |

Discovery uses current database rows and cached borough polygons. A shared
feed URL is non-identifying. Use `--input` for local official files. Barnet's
2014 CSV is cross-check only; both current HTML downloads are interruption
pages. Save the actual current page as `data/raw/barnet_car_parks_current.html`.
Reviews under `data/runs/`: Barnet `2026-11-11_49/coverage_barnet/`, Bexley
`2026-11-11_62/coverage_bexley/`, Bromley `2026-11-11_73/coverage_bromley/`,
Croydon `2026-11-11_104/coverage_croydon/`, Havering `2026-11-11_109/coverage_havering/`.
Bexley's 19 region exceptions are resolved by exact name and borough review.
Bromley and Croydon had zero exceptions. Croydon's Waddon PP-000214 has a
1.9 km pin disagreement, left unchanged. Hillingdon's four holds are Civic
Hall, Hayes Pool, Kingsend South short stay and Falling Lane; Cedars and Tesco
are distinct sites. Prior review: `2026-11-11_27/coverage_review/hillingdon_review.csv`.

Slaney Road PP-009347 remains held without retirement. PLAN.md explicitly
allows coverage work to continue past OSM-created duplicate refusals.
Hillingdon reimport: 28 listed, 24 reviewed held sites, four unchanged owner
cases. Fresh review: `data/runs/2026-11-11_113/coverage_hillingdon/`. Hounslow
refresh resolves all 21 region exceptions by exact site-name review: `data/runs/2026-11-11_114/coverage_hounslow/`.

Download batch: 18 of 25 pages saved under `data/raw/2026-11-11_112/official_lists/`;
seven failed. Manifest: `data/runs/2026-11-11_112/official_downloads/download_results.json`.
Greenwich: 17 reviewed sites, two new identities, gap zero.
Review: `data/runs/2026-11-11_117/coverage_greenwich/`; create run `create-20261111T220331Z`.

Owner download links and remaining input work, one borough per line. Save complete HTML plus
linked site/list pages in `data/raw/`; an index alone is not a site inventory.
Counts remain unknown until reviewed. These links are download requests only.

- Enfield: [Car parks](https://www.enfield.gov.uk/services/parking/car-parks), including the map data; HTTP 403 here.
- Redbridge: [Car parks](https://www.redbridge.gov.uk/parking/car-parks-and-on-street-parking/).
- Newham: [Car park directory](https://www.newham.gov.uk/directory/2/car-parks-in-newham), plus all five area lists and site pages.
- Waltham Forest: [Council car parks](https://www.walthamforest.gov.uk/parking-roads-and-travel/car-parks-and-street-parking/council-car-parks).
- Sutton: [Car parks](https://www.sutton.gov.uk/streets-transport-and-parking/parking/car-parks), plus linked site lists.
- Richmond upon Thames: [Car parks](https://www.richmond.gov.uk/car_parks), plus all area lists.
- Ealing: [Car parks in the borough](https://www.ealing.gov.uk/downloads/download/580/car_parks_in_the_borough), plus the linked charges/spaces list.
- Merton: [Parking charges](https://www.merton.gov.uk/streets-parking-transport/parking/charges), including the council car park table.
- Harrow: [Council car parks](https://www.harrow.gov.uk/parking-permits/council-car-parks-street-parking).
- Tower Hamlets: [Cashless parking](https://www.towerhamlets.gov.uk/FAQs/Parking-Charges/Cashless-parking.aspx), plus a complete current off-street list; this FAQ alone is not a denominator.
- Brent: [Public car parks](https://brent.gov.uk/parking-roads-and-travel/parking/where-you-can-park/car-parks).
- Barking and Dagenham: [Parking index](https://www.lbbd.gov.uk/parking), plus the linked current car park inventory; index is blocked here.
- Southwark: [Car parks](https://www.southwark.gov.uk/parking-streets-and-transport/parking/places-park/car-parks), plus linked park car park lists.
- Lewisham: [Council-managed car parks](https://lewisham.gov.uk/myservices/parking/carparks/car-parks-managed-by-the-council).
- Kingston upon Thames: [Car parks](https://www.kingston.gov.uk/parking/car-parks), plus site pages.
- Wandsworth: [Parking tariffs](https://www.wandsworth.gov.uk/parking/parking-bays/paying-to-park/parking-tariffs/), including the car park section.
- Haringey: [Council car parks](https://www.haringey.gov.uk/parking/car-parks), blocked here.
- Westminster: [Visitor parking](https://www.westminster.gov.uk/parking/visitor-parking-information), plus linked off-street operators; this page is not a full site inventory.
- Camden: [Contract car parks](https://www.camden.gov.uk/contract-parking), plus a current public/off-street list; this page has limited scope.
- Kensington and Chelsea: [Guide to parking](https://www.rbkc.gov.uk/parking-permissions/visitor-parking-and-pay-phone/guide-parking), plus linked off-street site pages.
- Lambeth: [Council-owned car parks](https://www.lambeth.gov.uk/lambeth-data-hub/council-owned-car-parks), plus its linked inventory.
- Hackney: [Council car parks](https://www.hackney.gov.uk/parking-streets-and-transport/where-park/council-car-parks).
- Hammersmith and Fulham: [Parking index](https://www.lbhf.gov.uk/parking), plus linked car park pages; robot-check response here.
- Islington: [Short-stay parking](https://www.islington.gov.uk/parking/where-to-park/pay-for-short-stay-parking), plus the current off-street list or annual report linked from Parking; the page alone is not a full inventory.

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

## Publication dry runs

Nothing reached the Google Sheet. `publish` read the live sheet and wrote no
cell. A write needs `--apply` with a saved approved plan, and the owner's
explicit go.

The full dry run is `data/runs/2026-11-11_103/publish/`. It plans 0 rows and
reports 944 drift errors, which is the correct answer. 943 of the 7,393
applied changes belong to records the sheet does not hold, so the drift check
reads "missing row". A created record reaches the sheet by an approved append,
through `tranche1-write`, and never by an update.

The 20-row pilot is `data/runs/2026-11-11_106/publish_pilot20/`. It plans 20
rows and 20 undo rows, with no drift, no refusal and no second-reading
failure. All six controls pass: identity, columns, locks, drift, validation
and second reading. Every row fills a blank Place Category.

A first 20-row attempt refused 18 of 20 as finished rows, which is the lock
working. 858 of the 3,024 sheet-held places with applied changes are
unfinished, and those are the publication candidates.

The eight scenarios are covered offline in `tests/test_publish.py`: fresh
identity, drift, duplicate IDs, missing imported IDs, protected fields,
formulas, grid growth and partial-write recovery. The last three were added
on 11 November.

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

`default-fill` classified none of the 233 default-stage rows, so there is no
plan to apply. 226 rows are not a recognised chain format or small venue
pattern, and 7 have no Brand, which a Conditional row needs. The run is
`data/runs/2026-11-11_101/default_fill/`. The largest groups are 102
large-format supermarkets, 38 hotels and 26 shopping centres. Rules R1 and R10
refuse to guess a chain policy for them, which is the cautious direction.

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
The identity matcher generates plans only. The latest full suite check passed 1,604 tests, including concurrent evidence work.
Code ownership is in `docs/MAP.md`. Creation procedures are in `ADD_PLACES_RUNBOOK.md`.
Keep this file current and short. Do not append historical run narratives.
