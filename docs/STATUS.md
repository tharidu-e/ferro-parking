# Current work

Updated 12 November 2026. Read this for priorities and remaining work only.
Counts describe the local database, not a fresh Google Sheet export.
Historical documents remain available in Git history. Run evidence stays under `data/runs/`.

Team onboarding diagrams are in `docs/diagrams/index.html`, with an editable
`docs/diagrams/ferro-system-design.excalidraw` and reading notes in that folder.
They describe the architecture and explain the research and publication delays.
Their counts retain the 12 November snapshot date; they are not live totals.

## Remaining places

| Measure | Places |
|---|---:|
| Total records | 11,560 |
| Blank Verification Result | 6,192 |
| Needs on-site check | 1,176 |
| Active OSM-created records | 3,951 |

The latest saved route is `route-20261112T211421Z`.
Its 5,437 routed rows comprise 4,037 Grok, 862 no_evidence, 237 default,
244 website reader and 57 station rows. 6,123 rows are skipped, of which 47
are personal locks and 1,186 need an on-site check. The Grok stage fell from
4,846 to 4,037 on 12 November, because the imported batches finished those
rows. The station count fell
from 113, because 56 station pages state that the station has no parking.
A filled verification result does not prove that every parking detail is known.
For current counts, run the read-only example in README.md. Saved routing can lag behind data changes.

## Readiness, two ways

| Measure | Places |
|---|---:|
| Legacy showable | 1,606 |
| Legacy complete | 1,098 |
| Evidence-supported showable | 1,038 |
| Evidence-supported complete | 0 |

Legacy counts read the sheet's own cells, through `readiness.counts` over a
`db-export`. Evidence-supported means the `evidence` table holds a quote for
Can Park?, Who Can Park and Cost Type on that place. 1,038 rows reach that bar:
50 from the website readers and 988 from the 12 November Grok batches. 121 of
them state that the station has no car park, which is a useful answer and never
a showable car park. The
other legacy answers predate the evidence table, so do not read 1,573 as 1,573
checked car parks.

The Asda rows are not legacy showable, because their Cost Type reads Unknown.
The store page states a car park and no price.

## Next work, in order

Follow `docs/PLAN.md` for batch steps and the engineering gate. The next work is
supported parking answers on existing places, using the readers already built.
Before fetching or coding, name the missing driver answers on current records
or a reviewed new-place candidate. Reuse downloaded pages first. The driver
information standard and two completion outcomes are defined in PLAN.md.
Use that standard for every category, including leisure centres, station car parks,
hotels, gyms, supermarkets, shopping centres and private operator sites. Check
missing details and new or conflicting evidence; keep locked records held.

1. The M&S batch is done for now. Five of the 15 held records carry a supported
   category and parking answers. Ten remain held for a category the sources do
   not support. Do not rerun that reader without new evidence.
2. Readable brand and venue sources are close to exhausted. Before any new
   fetch, read the measured dead sources below and in `fetch_fill.SKIPPED_HOSTS`.
   Choose a batch only where a named record gap meets a source that states that
   site. Recorded reader plans are already applied; do not repeat unchanged work.
3. Change code only for a reproduced blocker in the selected batch. The station
   context issue is an exception task, not a reason to redesign all validation.
4. Import Grok when its results arrive. Missing results do not block other readers.
   Grok apply and every Sheet write still require the owner's explicit go.
5. Resume coverage only when new usable input or evidence can resolve a gap.
   Prepare publication from accepted batches with the existing controls.

Report places checked, places improved, supported answers added, newly showable
places and held cases. For each category reviewed, also distinguish research
complete for now from driver information complete, and name categories not yet
checked. No category review counts have been refreshed by this documentation edit.
Include five reviewed examples. Partial supported answers
count as progress; they do not count as showable until that bar is met.

## Free-source validation, 12 November 2026

Three parallel read-only reviews checked the external source shortlist. No
records were created, changed or published. No new reader is justified yet.

- The unnamed ArcGIS layer is Hillingdon's existing 28-site inventory. Live
  records match saved examples. Its 0.40 first-hour prices conflict with the
  council's 2026/27 fees schedule. June 2026 item metadata is not tariff freshness.
  Keep the four owner holds. Follow up current operational fees, not another import.
  Source: https://services1.arcgis.com/vBu1s2ZA7rxzmHBD/ArcGIS/rest/services/Car_Park__CPZ_and_Railways_WFL1/FeatureServer/8
  Fees lead: https://modgov.hillingdon.gov.uk/documents/s65764/Appendix%20H1%20-%20Fees%20and%20Charges%202026-27.pdf
  Proposed schedule rates need confirmation before use.
- Barnet's CSV was retrieved: 20 names with capacity and free/paid classification.
  Publisher metadata explicitly dates it December 2014 and specifies OGL v2.
  It remains historical cross-check material, not current parking-rule evidence.
  https://open.barnet.gov.uk/dataset/parking-restrictions-and-spaces-in-barnet-23lk2
- City COMPASS saved data has tariff fields for all five already-held sites,
  PP-000192 through PP-000196. All five are finished and locked; Minories also
  has an owner hold. Old GIS rates conflict with newer official/operator material.
  Zero new places and zero eligible unlocked rows from these five matches.
- National Rail Knowledgebase is free to registered Rail Data Marketplace users.
  Its documented station XML schema supports separate car parks and charges,
  including hourly/daily/season values and notes. The historical Kings Cross
  sample has N/A tariffs and can reference nearby parking. No current feed was
  obtained; populated London charges and product reuse terms remain unverified.
  Next test: obtain a current feed and its licence, then inspect 25 existing
  London station records before building a reader. Existing station.py reads
  website text and does not consume this feed.
  https://www.nationalrail.co.uk/developers/knowledgebase-data-feeds/

Validation: python -m pytest tests/ -q passed, 1,619 tests. These source reviews
made no changes to coverage, evidence-supported readiness or publication totals.

## Source imports

Coverage: 33 borough rows, 20 zero gaps within the named official inventories;
13 remain unknown or held. This is not complete London coverage. Council lists
exclude unlisted private sites. Bexley has a headline conflict, Ealing is dated
2024, and Southwark's two-site list excludes park facilities. No gap is owner-accepted.
OSM-derived is a separate count of active created identities, never permission.

| Borough | Official inventory | Published official | Official sites we hold | Official gap | OSM-derived |
|---|---|---:|---:|---|---:|
| Barnet | Current page blocked | Unknown | Unknown | Unknown | 375 |
| Hillingdon | Council points, refreshed | 28 | 24 | Unresolved (4) | 259 |
| Bromley | 30 official site pages | 30 | 30 | 0 | 254 |
| Hounslow | Council lists, refreshed | 21 | 21 | 0 | 229 |
| Enfield | HTTP 403 | Unknown | Unknown | Unknown | 209 |
| Havering | Council site links | 24 | 24 by name | 0 by name | 204 |
| Bexley | Council sections | 19 listed, 18 headline | 19 | 0 of 19 listed | 176 |
| Croydon | Council map markers | 19 | 19 | 0 | 176 |
| Greenwich | Official directory markers | 17 | 17 | 0 | 153 |
| Redbridge | Council site codes | 18 | 18 | 0 | 146 |
| Newham | Five areas, eight site pages | 8 | 8 | 0 | 134 |
| Waltham Forest | Council grouped site headings | 11 | 11 | 0 | 129 |
| Sutton | HTTP 403 | Unknown | Unknown | Unknown | 117 |
| Richmond upon Thames | All 11 council area lists | 25 | 25 | 0 | 116 |
| Ealing | Official PDF dated 12 Dec 2024 | 18 dated | 18 | 0 in dated list | 112 |
| Merton | Council site-by-area table | 13 | 13 | 0 | 110 |
| Harrow | Named council car park sections | 14 | 14 | 0 | 101 |
| Tower Hamlets | Current off-street tariff headings | 7 | 7 | 0 | 100 |
| Brent | Complete public directory response | 11 | 11 | 0 | 91 |
| Barking and Dagenham | HTTP 403 | Unknown | Unknown | Unknown | 86 |
| Southwark | Two paid council sites only | 2 scoped | 2 | 0 in scoped list | 83 |
| Lewisham | HTTP 403 | Unknown | Unknown | Unknown | 81 |
| Kingston upon Thames | Both council directory pages | 12 | 12 | 0 | 76 |
| Wandsworth | Tariffs and unlabelled park map; full inventory missing | Unknown | Unknown | Unknown | 73 |
| Haringey | Council RingGo site codes | 11 | 10 separate, C grouped | 1 mapping hold | 68 |
| Westminster | Operator links only, no complete named list | Unknown | Unknown | Unknown | 59 |
| Camden | HTTP 403 | Unknown | Unknown | Unknown | 53 |
| Kensington and Chelsea | Guide names examples, no complete inventory | Unknown | Unknown | Unknown | 45 |
| Lambeth | HTTP 403, including direct inventory | Unknown | Unknown | Unknown | 42 |
| Hackney | Eight listed plus Amhurst closed notice | 9 named | 9 | 0 named sites | 35 |
| Hammersmith and Fulham | Linked page HTTP 404 | Unknown | Unknown | Unknown | 34 |
| Islington | Council three-site enforcement statement | 3 | 3 | 0 scoped sites | 19 |
| City of London | COMPASS layer 2 | 5 | 5 | 0 | 6 |

Fresh inputs: `data/raw/2026-11-11_112/official_lists/`. Of 25 landing-page
requests, 18 succeeded and seven failed; linked area/site pages, Ealing's PDF
and Brent's public JSON were then downloaded. Manifest and request definitions:
`data/runs/2026-11-11_112/official_downloads/`. Every usable full inventory was
imported with an adapter and reviewed. Exact-name reviews resolved pinless lists;
no coordinates were invented. A landing page alone was not counted as an inventory.
Greenwich created two reviewed identity-only records in `create-20261111T220331Z`:
North Greenwich Station Car Park and Woolwich Lidl Car Park. Parking answers
stay blank. Per-borough reviews remain in their own append-only run folders.
Coverage snapshot: `data/runs/2026-11-11_151/coverage_snapshot/`.

OSM fallback: `data/runs/2026-11-11_115/coverage_osm/` ran both existing commands
against a current database export. All 4,852 eligible references are already
processed: 3,951 active and 901 inactive. The db-create dry run accepted zero,
refused zero and created zero (`2026-11-11_122/db_create/`). All 30 spatial
gaps are excluded from the stricter creation plan; original tags and reviews
are saved in `2026-11-11_149/coverage_osm_review/` and
`2026-11-11_150/coverage_osm_review/`. No inactive record was reactivated.

Owner holds stay unchanged: Slaney Road PP-009347, the four Hillingdon cases,
Minories, Waddon, New Barnet and the other PLAN.md decisions. Stoneleigh A and B
have separate records; C appears only in grouped PP-000383. Its linked RingGo
page returned unrelated Westminster content, so C's mapping remains held.

Remaining input blocks, not requests for next-step decisions:

- Barnet: [current list](https://www.barnet.gov.uk/parking/car-parks-and-street-parking-locations) saved an interruption page twice; 2014 CSV is cross-check only.
- Enfield: [car parks](https://www.enfield.gov.uk/services/parking/car-parks), including map data; HTTP 403.
- Sutton: [car parks](https://www.sutton.gov.uk/streets-transport-and-parking/parking/car-parks); HTTP 403.
- Barking and Dagenham: [parking](https://www.lbbd.gov.uk/parking) and linked inventory; HTTP 403.
- Lewisham: [council list](https://lewisham.gov.uk/myservices/parking/carparks/car-parks-managed-by-the-council); HTTP 403.
- Camden: [contract parking](https://www.camden.gov.uk/contract-parking) and complete off-street list; HTTP 403.
- Lambeth: [direct inventory](https://www.lambeth.gov.uk/parking/parking-restrictions/where-you-can-park/car-parks); HTTP 403.
- Hammersmith and Fulham: [provided parking link](https://www.lbhf.gov.uk/parking) returned 404; a current official inventory is missing.
- Wandsworth: [tariffs](https://www.wandsworth.gov.uk/parking/parking-bays/paying-to-park/parking-tariffs/) names two sites; linked Battersea map does not name its car parks. Complete inventory still missing.
- Westminster: [visitor parking](https://www.westminster.gov.uk/parking/visitor-parking-information) links private operators, not a complete site list.
- Kensington and Chelsea: [guide](https://www.rbkc.gov.uk/parking-permissions/visitor-parking-and-pay-phone/guide-parking) names examples, not a complete inventory.
- Southwark park facilities: the paid council inventory excludes them; a separate list is missing.

## Grok hand-off

The bots research and check. This project owns the queue, the identity match,
validation, the database and publication. The bots never reach the database.

The current queue is `data/runs/2026-11-12/grok_queue/grok_queue_for_bot.csv`,
4,823 rows from route-20261112T110736Z. It is the full 4,846-row queue minus
the 23 places the bots already answered. Ferro Autopay and Parking Charge stay
blank. Upload that file to the bot and ask for the 34 Grok Results columns back
as CSV.

The 199 earlier results are saved as `data/raw/grok_results_2026-11-12.csv`.
`grok-import` accepted none of them: 172 places are already finished in the
database and 27 break the allowed value rules. Three of them found real answers
that the format rejected: Warren Evans car park, London Zoo Parking and Lloyd
Park. Those three wait for a hand fix.

The first 25-place pilot ran on 12 November. Results:
`data/raw/grok_results_batch_20261112.csv`. The bot found a field on 20 rows
and nothing on 5, and reported no new place. `grok-import` accepted 9, skipped
11 as finished rows and rejected 5. Run `apply-20261112T145532Z` wrote 232
changes and 232 evidence rows across those 9 shopping centre car parks, with
`db-undo` available.

Two held cells in that batch: PP-001028's Hours, where the charging-hours check
asks for a person, and Evidence Age on all 9 rows, which the bot set to Under
12 months on undated pages against its own rule. Both are in
`data/runs/2026-11-12/grok_import_batch1_final/held_lines.json`.

The pilot found two importer bugs and one rule problem, all fixed on
12 November:

- A blank PCN amount or Max Stay was read as an invalid number and refused the
  whole row. 13 of the 25 pilot rows failed on an empty cell.
- The grok plan did not restate Brand and Place Category, which `validate_rows`
  asks for on a Yes or Conditional row, because it sees only the plan's columns.
- Brand was required on every Yes or Conditional row. 3,526 of the 4,095 queued
  places with no Brand are private or operator car parks, and 360 are stations.
  Those places carry an Operator and no brand. `config/rules.toml` now holds
  `identity.brand_required_categories`, and Brand is required only for those
  chain categories. Place Category stays required for every such row.

Still to settle for the next batch: the bots must leave Evidence Age as Older
or undated on an undated page, and the two personas still read and write tabs
their own text forbids.

Batch 2 ran the same day: 200 rows, 71 minutes, results in
`data/raw/grok_results_batch2_20261112.csv`. The bot applied all four pilot
corrections, including Evidence Age. `grok-import` accepted 82, skipped 12 as
finished and rejected 106. Run `apply-20261112T154646Z` wrote 2,307 changes and
2,307 evidence rows across 78 places, with `db-undo` available. Evidence
supported showable rose from 59 to 137.

Batch 2's 106 rejects have two main causes, both the bot's own formatting:

- 64 rows: the Tariff Detail text does not match a template in
  `formats.TARIFF_PATTERNS`. The published amounts are real. Examples are a
  trailing "each additional day £50.00", "Up to 1 hr £2.00" instead of
  "0-1 hrs £2.00", and whole pounds without decimals.
- 39 rows: Proposed Result "No evidence" with a Source Tier that is not
  "None found".

49 more lines were dropped at the apply step and held in
`data/runs/2026-11-12/grok_import_batch2_filtered/held_lines.json`: 30 Notes
and Review Flag lines that would replace existing text, 8 Hours lines the
charging-hours check holds, 7 Evidence Level values of "Reported" that the
sheet dropdown does not list, and 4 rows missing a Brand their chain category
needs.

Batch 2 corrections and batch 3 followed the same day.

| Batch | Rows | Accepted | Applied changes | Run |
|---|---:|---:|---:|---|
| Pilot, rows 1 to 25 | 25 | 9 | 232 | `apply-20261112T145532Z` |
| Batch 2, 200 rows | 200 | 82 | 2,307 | `apply-20261112T154646Z` |
| Batch 2 corrections | 114 | 91 | 2,399 | `apply-20261112T162907Z` |
| Batch 3, rows 226 to 425 | 200 | 173 | 5,254 | `apply-20261112T162940Z` |
| Batch 3 corrections | 18 | 13 | 400 | `apply-20261112T165334Z` |
| Batch 4, rows 426 to 625 | 200 | 31 applied | 837 | `apply-20261112T165338Z` |
| Batch 4 reread | 162 | 27 | 837 | `apply-20261112T183210Z` |
| Batch 5, rows 626 to 825 | 200 | 117 | 3,277 | `apply-20261112T183214Z` |
| Batch 6, rows 826 to 1025 | 200 | 188 | 5,409 | `apply-20261112T211304Z` |
| Station rows under the new R9 | 562 | 121 | 3,751 | `apply-20261112T2114*Z` |
| Batch 7, rows 1026 to 1225 | 200 | 160 applied | 4,662 | `apply-20261112T214843Z` |
| Batch 8, rows 1226 to 1245 | 20 | 20 | 587 | `apply-20261112T224221Z` |

The bot reshaped 75 Tariff Detail strings and fixed 39 "No evidence" rows, so
batch 2 recovered from 82 accepted to 91. Batch 3 was accepted at 173 of 200,
because the two new rules were in place before the research ran. Each batch
keeps its own `db-undo` run.

Batch 4 needs a reread, not an import. It returned 162 rows as "No evidence"
and finished in about four minutes, which cannot be 200 pages read properly.
Importing them would close those 162 places on a shallow miss, so only the 38
rows with a stated fact went forward, and 31 of those applied. The held list is
`data/runs/2026-11-12/grok_import_batch4_found_only/held_shallow_rows.csv`.
Those 162 places stay on the Grok stage until a slower reread.

The batch 4 reread answered the shallow-miss worry. The bot opened 710 pages in
30 minutes and found a fact on 137 of the 162 places. Only 27 imported, because
112 of those answers are Can Park? No from a Transport for London station
record that reads `"Car park": "no"`, and rule R9 does not list that wording.
The owner approved that wording on 12 November, and
`r9.explicit_no_parking_phrases` now holds `car park": "no`. The quotes are
part of the phrase, so it cannot match prose about a car park, and two tests
cover both directions. Re-importing the three affected files then applied 121
station rows under `apply-20261112T211407Z`, `apply-20261112T211408Z` and
`apply-20261112T211409Z`.

Batch 5 also refused 45 rows that pair Source Tier "None found" with
Verification Result "Needs on-site check". Those are the places where no page
loaded at all. The bot must use "No evidence" there and name the blocked URL in
Notes.

Batch 6 was accepted at 188 of 200, the best rate so far. 164 of its rows found
nothing: 47 name a blocked URL in Notes and 117 read a page that says nothing
about parking, mostly unnamed car parks, bus stations and piers. Those rows now
carry Verification Result "No evidence", which is research complete for now and
not driver information complete.

Batch 6 review items: the Barbican centre page says a £13 fixed evening and
weekend rate where Saba says £15; Sloane Square has no 7 to 8 hour band, so the
row reads "7-24 hrs £52.50"; Westfield Car Park C takes its tariff from the
centre-wide page; Paddington's Tube record says no car park while the mainline
record says there is one; the two Hammersmith bus station rows read No from the
whole interchange's record. Two more car parks are outside the queue, Alexandra
Road in Hounslow and Holly Road in Twickenham.

Batch 7 covers mostly unnamed car parks, so 182 of its 200 rows found nothing.
33 of those cite only an OpenStreetMap map entry, with no site page opened at
all, so they are held in
`data/runs/2026-11-12/import_batch7_without_weak/held_map_only_rows.csv` and
stay on the Grok stage. The bot itself flagged them as its weakest calls.

The bot now checks its own file before sending it. It clones the repo, builds a
copy of the database with `db-import` from a `db-export` snapshot, and runs
`grok-import` against that copy. Batch 8 was the test: the bot reported 20
accepted, 0 skipped and 0 rejected, and the same import here gave the same
three numbers and the same 20 dropped Location Status cells. So a batch that
passes on the bot's copy can be applied here without a correction round. The
copy goes stale after every apply, so send a fresh snapshot each day.

Three batch 7 rows read a Barnet bot-check page as silence and carry
Verification Result "No evidence" with no blocked page named: PP-007994
Fitzjohn Avenue, PP-008152 and PP-008153 Stanhope Road. The correction was
skipped, because those rows are finished. Reread them when Barnet is reachable.

1,245 of the 4,823 queue rows are researched. 3,578 remain, which is 18 runs of
200 rows. Use `scripts/filter_refused_lines.py` on each batch plan before
db-apply, so one refused cell no longer blocks a whole batch.

Batch 7 review items: East Finchley (PP-008014) has a conflict, where Saba says
£10.60 a day with camera control and Transport for London still says £5.00 pay
and display, and about 50 spaces close from September to December 2026 for
charger work. Harold Wood station closes on 28 and 29 November. IKEA Croydon
and Wembley read No evidence, because IKEA publishes only a chain-wide free
parking line. PP-008155 and PP-008157 are both named Beckton Triangle Retail
Park. Three more car parks sit outside the queue, including Palace Gardens in
Enfield, which publishes a full tariff.

The apply step still holds some lines, and each held line is listed in that
run's `held_lines.json` under `data/runs/2026-11-12/`. The usual causes are a
Notes or Review Flag line that would replace existing text, an Hours value the
charging-hours check holds, an Evidence Level of "Reported", and a row whose
Tariff Type and Tariff Detail disagree.

Batch 3 found 143 rows with nothing published, 8 newly blocked pages (The O2,
two Barnet car park pages, Lomax George Mews, UEL SportsDock, Tesco West
Cromwell Road, Truman Brewery and Ruskin Square) and four dead links (ExCeL
parking, Epsom and St Helier hospital parking, Ruislip Lido and several
National Rail pages for Tube-only stations). Do not retry those.

Batch 3 review items: nine possible duplicate pairs, including Kings Mall
(PP-005463 and PP-001030), Westfield (PP-005467, PP-005458, PP-001027 and
PP-007793) and the two ExCeL rows (PP-005561 and PP-005562); five rows needing
an on-site check, including Barnet Hospital A and B (PP-005596 and PP-005597),
where the live page contradicts the 8 May 2026 charges notice; and two car
parks not in the queue, Alexandra Palace Paddocks and Dives, in
`data/raw/grok_not_in_queue_batch3_20261112.csv`.

Batch 2 review items, none of them parking answers: the Liberty, Wood Green
East and Chimes postcodes differ from our records; Westfield London, Finsbury
Square and Berners Street may be duplicate records; three car parks are not in
the queue (Honor Oak Recreation Ground, Ham Street and Connaught Water) in
`data/raw/grok_not_in_queue_batch2_20261112.csv`. 22 URLs were blocked,
including Canary Wharf, NCP, Vision RCL behind a captcha and Guy's and
St Thomas'.


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
| marksandspencer.com | 39 | 5 | 80 | `apply-20261112T110025Z` |
| station | 473 | 119 | 2,275 | `apply-20261111T212427Z` |

No plan was refused. Each evidence row carries the quote, the page url, the
retrieval time and the cached page hash, for the fields the page states only.

The M&S store pages state a car park for 15 rows. The pages state the facility
and the opening hours only. They never state the store format, the price, the
maximum stay or who can park. Ten rows stay held, because no source supports a
Place Category, and the validator asks for that column on a Conditional row.
Five rows gained a category from an exact-site OpenStreetMap brand anchor and
then took the reader's answers: PP-001574, PP-001599, PP-001604, PP-001607 and
PP-001608. Each reads Place Category "Supermarket - convenience", Can Park?
Conditional and Who Can Park Customers only, from the quote "Car parking".
Cost Type reads Unknown, so none of the five is showable yet. The anchors,
the proposals and the ten held rows are in `data/runs/2026-11-12/ms_category/`.
`propose-categories` offers "Supermarket - large format" for these rows and the
`category-plan` guard drops it, because `rules.format_for` reads no store format
from a name like "M&S Hornchurch BP - forecourt parking". PP-001565 has an
OpenStreetMap department-store anchor 53.7 m away and needs an owner decision,
because no allowed category reads department store.

Lidl reads every page and writes nothing, which is correct. Its store pages
list accessible bays and no car park.

Eight more sources were measured on 12 November with the existing `probe`
command, three pages each. None supports a reader, so none was built.
Runs are in `data/runs/2026-11-12/probe_*`.

| Source key | Rows | Result |
|---|---:|---|
| virginactive.co.uk | 11 | three pages read, none states parking |
| visionrcl.org.uk | 8 | three pages blocked |
| firmdalehotels.com | 6 | three pages read, no parking text on any |
| bestwestern.co.uk | 6 | three pages blocked |
| canarywharf.com | 4 | three pages read, none states parking |
| odeon.co.uk | 7 | three pages blocked |
| myvue.com | 5 | three pages read, none states parking |
| picturehouses.com | 7 | three pages read, one states on-street parking only |

Twenty rows hold published charges while Cost Type reads Unknown. Each one
records its own reason: an unresolved conflict between a store page and an
operator, amounts for part of the week only, or an unresolved identity. These
are recorded outcomes and not open gaps, so no batch should rewrite them.

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

Engineering exception for a selected blocked batch: `validate_rows` sees only the plan's own
columns, so a planner has to restate a row's existing values as context. That
is why the rows above fail on existing text. Reproduce an affected row first,
then make the smallest context fix and rerun that batch. Keep every validation
rule and lock. Defer broader cleanup.

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

- Haringey Stoneleigh C: PP-000383 groups A/B/C; C needs a separate exact-site mapping. No record changed or retired.

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
The identity matcher generates plans only. The latest full suite check passed 1,619 tests, including concurrent evidence work.
Code ownership is in `docs/MAP.md`. Creation procedures are in `ADD_PLACES_RUNBOOK.md`.
Keep this file current and short. Do not append historical run narratives.
