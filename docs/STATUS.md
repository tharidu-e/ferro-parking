# Current work

Updated 15 November 2026. Read this for priorities and remaining work only.

## Next session, first actions

Read `docs/LAUNCH_PLAN.md` first. It owns the process agreed on 14 and 15
November: the sheet is the one store, the bots write parking answers only,
and airports come first.

1. Read this file, then `docs/PLAN.md`. Nothing else is needed to start.
2. Ask the owner whether PP has sent the NCP v2 folder. If it has, check it
   the way the NCP section below describes, then run `discover`.
3. If v2 has not arrived, do the identity work instead. Run `osm-identity`
   over the 675 blank rows in the large-format supermarket, shopping centre,
   hospital and hotel categories, because every one of them has no Brand and
   no source can be chosen without one.
4. The publication plan from 13 November is still waiting for the owner's go.
   It is `data/runs/2026-11-13_40/publish/`, 1,193 rows, zero drift.
5. Do not start a second operator until NCP round 1 is accepted.
Counts describe the local database, not a fresh Google Sheet export.
Historical documents remain available in Git history. Run evidence stays under `data/runs/`.

Team onboarding diagrams are in `docs/diagrams/index.html`, with an editable
`docs/diagrams/ferro-system-design.excalidraw` and reading notes in that folder.
They describe the architecture and explain the research and publication delays.
Their counts retain the 12 November snapshot date; they are not live totals.

## 15 November 2026, evening: the bots write the sheet themselves

The import chain is out of the loop. A bot now reads a page and writes the
cell, through three scripts in `tools/`, and `grok-import`, `db-apply` and
`publish` are no longer part of a research round.

- `bot_self_check.py` holds every rule `grok-import` held, so the two cannot
  disagree. It takes a fresh export as a second argument and checks each row
  as it will read after the write.
- `sheet_write.py` plans from an export with no credentials and names every
  cell in `plan.csv`. It writes only a blank, Unknown or Not yet checked cell,
  refuses identity and payment columns, refuses a Place ID outside the round's
  queue, stops over `--max-cells`, and logs every write.
- `sheet_undo.py` undoes one round from that log, cell by cell, skipping a
  cell somebody changed since.

hospital1 is the first round through this path. 95 places researched, 1,325
cells written across 77 rows, 0 skipped, every target cell blank beforehand.
Showable rose from 3,158 to 3,167 and complete from 1,129 to 1,138. Nine new
showable places for a round that took most of an evening, which is the measure
of how little the web publishes for this category.

Seven rows hold a Tariff Type and Tariff Detail in the sheet that do not match
each other, including PP-001964, PP-001633, PP-001737 and PP-003447. This
round wrote none of those cells. They need a cleanup pass.

Airports are covered except London City. Heathrow reads 66 showable of 97
rows, Gatwick 12 of 16, Luton 5 of 7. Stansted's five open rows are Meet and
Greet, Valet, JetParks, Long Stay and a pick-up zone, and our own scope rules
exclude the first three. London City blocks us. The Southend rows sit outside
Greater London.

## 15 November 2026, afternoon: the showable bar and the category publication

The owner set the showable bar: Can Park? Yes or Conditional, a usable pin and
a known Who Can Park. Hours and price are not required, and the app writes
"hours not published" or "price not published" instead. `readiness.bars` holds
it and `docs/LAUNCH_PLAN.md` section 5 states it. Showable reads 3,158 and
complete 1,129.

2,296 rows held a Place Category in the database that the sheet never received.
Run `categories-20261110-authorised` filled them on 10 November. Three places
in the code refused to publish them, each with a row-wide rule stricter than
`fill.finished_column_refusal`, which is per column and lets a finished row
gain a blank cell. `publish.build` and `fill._apply_write` now use the
project's own two rules, and `publish` takes `--columns` so one approved column
publishes on its own. All 2,296 cells are now in the sheet, in two runs of 133
and 2,163, with zero drift, zero refusals and both readbacks passed. Blank
Place Category fell from 2,420 to 124, and the 123 that remain are supermarket
rows whose name states no store format.

Two faults in the mirror were fixed the same morning. `effective_rows` counted
every appended OpenStreetMap record twice, so the database read 15,515 rows for
11,562 places. A stale applied change also beat the sheet on 1,231 cells. A
change now wins only while the sheet value is one the change chain itself held.

`docs/BOT_CHARTER.md` holds the rules the bots run on, one section per settled
decision.

## 15 November 2026: the sheet becomes the store, and airports

The Google Sheet tab "ALL LONDON (clean)" is now the one store, and the
database is a mirror rebuilt from it. `docs/LAUNCH_PLAN.md` owns the process.

Written to the sheet on 15 November:

- The approved publication plan: 20,671 cells across 1,193 existing rows, zero
  drift, zero refusals, second reading passed.
- The 3,953 places the sheet did not hold, appended from row 7609. The sheet
  and the database now hold the same 11,560 Place IDs.
- Identity filled by code, with no bot: 2,156 cells from OpenStreetMap tags
  (1,145 Who Can Park, 394 Cost Type, 347 Operator, 270 Hours), 4,214 street
  addresses, 2,800 rows renamed from "Car park (unnamed)" to "Car park,
  <street>", and 4,301 postcodes derived from the pin. 1,088 pins had no
  postcode close enough and stay blank.
- Six new columns: Postcode (derived from pin), Pin to postcode distance (m),
  Place Type, Terminal, Penalty Note and Entry Note.
- Identity and payment columns are now protected ranges. Place Type takes only
  its four values.
- A new tab, "NEW PLACE CANDIDATES", receives any place a bot finds that the
  sheet does not hold. Ferro creates the row and the Place ID.

Airports. Heathrow is done by hand from its own pages: 11 rows filled and the
Authorised Vehicle Area created as PP-012462. Gatwick, Stansted and Luton are
done from PP's saved pages: 270 cells across 14 rows, plus the Gatwick private
hire waiting area as PP-012463, which has no coordinate yet. London City
blocked both PP and a direct request on 15 November, so it waits.

Two recorded conflicts: Stansted's Short Stay page says pre-booking only while
its Turn Up & Park page prices the Blue and Green zones, and Luton's taxi page
says £7 for 10 minutes while three other pages say £9 for 12 minutes.

NCP round 2 closed with little yield: 89 rows mapped to held places and all 89
skipped as finished, so the round produced 6 fillable cells and 4 new place
candidates. The identity work for it is
`data/raw/ncp_round2_20261114/ncp1-identity-resolved.csv`.

Next: rebuild the database from the sheet, run the yield test for the first
category round, and start shopping centres and large-format supermarkets.

## Remaining places

| Measure | Places |
|---|---:|
| Total records | 11,560 |
| Blank Verification Result | 2,396 |
| Needs on-site check | 1,430 |
| Active OSM-created records | 3,951 |

The blank count fell from 6,192 and the on-site count rose from 1,176 on
13 November, because batches 9 to 26 closed the rest of the queue.

The latest saved route is `route-20261112T211421Z`.
Its 5,437 routed rows comprise 4,037 Grok, 862 no_evidence, 237 default,
244 website reader and 57 station rows. 6,123 rows are skipped, of which 47
are personal locks and 1,186 need an on-site check. The Grok stage fell from
4,846 to 4,037 on 12 November, because the imported batches finished those
rows. The station count fell
from 113, because 56 station pages state that the station has no parking.
A filled verification result does not prove that every parking detail is known.
For current counts, run the read-only example in README.md. Saved routing can lag behind data changes.
That saved route is stale after the 13 November applies. Run `route` again
before you pick the next research work.

## Readiness, two ways

Measured on the 15 November sheet export, under the showable bar the owner set
that day: Can Park? Yes or Conditional, a usable pin and a known Who Can Park.
`docs/LAUNCH_PLAN.md` section 5 owns that bar.

| Measure | Places |
|---|---:|
| Showable | 3,158 |
| Complete | 1,129 |
| Of the showable, hours known | 800 |
| Of the showable, Cost Type known | 1,619 |
| Of the showable, Max Stay known | 308 |
| Evidence-supported showable | 1,038 |
| Evidence-supported complete | 0 |

The showable count rose from 1,649 because the bar no longer asks for a price,
not because of new research. 944 of the showable rows lack hours only, 125 lack
the Cost Type only and 1,414 lack both, so hours are the next research target.

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

## Category coverage, 13 November 2026

The owner asked how we make sure that we cover every parking place, category by
category: take all the Tesco stores in London, collect their parking
information, exclude the places we already hold, then repeat for other chains
and categories. The shape of that plan is right. Two parts of it already exist
in the code, and one part is a measured dead end.

What exists. `discover --source generic` fetches a source list, filters it to
London, deduplicates it against the database and drafts the new places. Use
`--boroughs-from` once to build the borough polygons, then every later run tests
London membership offline. Do not build a second source register.
`policy-fill` is rule R10, which applies a chain's published rule to a branch.
R10 counts a large format (Tesco Superstore, Tesco Extra, Sainsbury's
superstore, Lidl, Aldi, Asda, Morrisons) as having a car park, and a convenience
format only if OpenStreetMap maps a car park within 40 m of the branch.

What does not work. `www.tesco.com` and `stores.sainsburys.co.uk` are already
in `fetch_fill.SKIPPED_HOSTS`, with `iceland.co.uk`, `primark.com`,
`tkmaxx.com`, `screwfix.com`, `mcdonalds.com`, `kfc.co.uk`, `nandos.co.uk` and
others. Those chain sites were measured and they do not state parking for one
named store. Asda and IKEA behave the same way: IKEA publishes one chain-wide
free parking line, and the Asda rows are not showable because Cost Type reads
Unknown. So asking the bot to read Tesco's own website store by store will
return nothing new.

Where the real gap is. The gap is the parking detail on places we hold. This
section once said that chain place coverage is already good. That was not
measured, and the 13 November section below withdraws it. The database holds 173 Tesco, 175
Sainsbury's, 93 Co-op, 66 Lidl, 62 M&S, 57 Iceland and 43 Asda records.

Every category, measured with the project's own readiness bar over a fresh
`db-export` on 13 November. Showable means Can Park? Yes or Conditional, a
usable pin, a known Who Can Park and a known Cost Type. Complete adds hours,
maximum stay and tariff detail.

| Category | Records | Showable | Complete | Blank result | No evidence | On-site |
|---|---:|---:|---:|---:|---:|---:|
| Private / operator car park | 4,681 | 409 | 232 | 929 | 2,912 | 317 |
| Supermarket - convenience | 1,051 | 36 | 28 | 20 | 57 | 280 |
| Supermarket - large format | 954 | 91 | 77 | 447 | 4 | 123 |
| Station | 841 | 130 | 117 | 94 | 149 | 73 |
| Petrol station | 610 | 4 | 2 | 10 | 6 | 121 |
| Fast food / drive-thru | 570 | 7 | 4 | 117 | 0 | 41 |
| Hotel | 558 | 167 | 141 | 118 | 0 | 76 |
| Gym / leisure centre | 488 | 98 | 38 | 250 | 2 | 85 |
| Council car park | 476 | 406 | 338 | 6 | 17 | 27 |
| Other | 446 | 81 | 40 | 148 | 21 | 89 |
| Retail warehouse / DIY / trade | 325 | 16 | 14 | 82 | 69 | 109 |
| Hospital / health centre | 236 | 129 | 29 | 46 | 2 | 44 |
| No category | 124 | 13 | 7 | 60 | 25 | 0 |
| Shopping centre | 121 | 42 | 36 | 64 | 7 | 14 |
| School / college | 30 | 6 | 1 | 2 | 0 | 5 |
| Restaurant / pub / cafe | 24 | 4 | 4 | 0 | 3 | 14 |
| Council park / open space | 22 | 13 | 12 | 0 | 0 | 12 |
| Park / open space | 2 | 0 | 0 | 0 | 0 | 0 |
| Business park / office | 1 | 0 | 0 | 0 | 0 | 0 |
| Total | 11,560 | 1,652 | 1,120 | 2,393 | 3,274 | 1,430 |

What the table says. Council car parks are done at 406 showable of 476, and
council parks and open spaces are the next best. Private and operator car parks
are exhausted, because 2,912 of them already read No evidence. Petrol stations
and fast food sites score almost zero, and their chain sites are measured dead,
so they are poor targets and low value to a driver. Restaurants, pubs and cafes
are only 24 records, so that category is too small to plan around. The big
unworked categories are large-format supermarkets, gyms and hotels.

The blocker on the three big targets is identity, not research. Every one of the
447 blank large-format supermarket rows has no Brand, and so do all 64 blank
shopping centre rows, all 46 blank hospital rows and all 118 blank hotel rows.
Without a Brand we cannot pick the source that states the site. `osm-identity`
already proposes Brand, Place Category and Notes from the OpenStreetMap
geometry, and `data/raw/greater-london-latest.osm.pbf` is on disk, so that pass
is read-only and needs no new code.

Gyms are the one target with a reader already built. Of their 250 blank rows,
37 are Better, 15 are PureGym and 14 are The Gym Group, and `fetch-fill` has a
registered reader for each of those three hosts. A dry run on those 66 rows
costs nothing and needs no new code.

An OpenStreetMap fee pass is not the unlock. The London extract holds 17,988
`amenity=parking` objects, but only 1,824 carry a `fee` tag and only 115 carry
`maxstay`. Those tags cannot fill 954 supermarket records.

Recommended order:

1. Run `osm-identity` over the 675 blank rows in the four branded categories,
   to get a Brand on large-format supermarkets, shopping centres, hospitals and
   hotels. Read-only, no new code.
2. Run `fetch-fill` as a dry run for `better.org.uk`, `puregym.com` and
   `thegymgroup.com` over the 66 branded gym rows.
3. Route again, then take shopping centres as the first bot batch. There are
   only 64 blank rows, centre pages publish tariffs, and batch 6 and batch 7
   proved the bot reads them well.
4. Then take large-format supermarkets with the brands now known, and decide
   the source first. The chain websites are dead, so this batch needs a source
   decision from the owner, not another pass over the same pages.

## How complete is each category, 13 November 2026

The owner asked the right question: the category counts are a sample, not the
whole of London. Our 11,560 records come from the sheet's own history plus the
records created from OpenStreetMap. Nothing in the project has ever held an
authoritative list of the places that exist, so we cannot state coverage as a
percentage. The earlier line in this document that said chain place coverage
"is already good" was not supported by a measurement. Treat it as withdrawn.

OpenStreetMap is not a denominator either. The London extract was measured on
13 November with `data/raw/greater-london-latest.osm.pbf`.

| Brand in OpenStreetMap | London stores | With a mapped car park within 60 m | Records we hold |
|---|---:|---:|---:|
| Tesco | 511 | 128 | 173 |
| Sainsbury's | 408 | 88 | 175 |
| Co-op | 238 | 61 | 93 |
| Lidl | 121 | 50 | 66 |
| Marks and Spencer | 176 | 36 | 62 |
| Waitrose | 102 | 32 | - |
| Morrisons | 68 | 24 | - |
| Asda | 68 | 20 | 43 |
| Aldi | 61 | 23 | - |

Read the Tesco row carefully. OpenStreetMap maps 511 Tesco stores in London and
a car park beside only 128 of them, yet we hold 173 Tesco records. Both numbers
are wrong in opposite directions: OpenStreetMap misses stores, and it misses
far more car parks, because almost every Tesco Extra and Superstore has one. So
OpenStreetMap can find places, but it cannot tell us how many we are missing.

The same measurement by category, for every place type that can have a car park:

| Place type in OpenStreetMap | London objects | With a mapped car park within 60 m |
|---|---:|---:|
| Restaurant, pub, cafe, bar | 19,975 | 3,482 |
| Fast food | 6,192 | 1,147 |
| Convenience shop | 5,358 | 1,040 |
| Gym or sports centre | 1,823 | 400 |
| Retail warehouse, DIY, trade | 1,478 | 296 |
| Hotel or motel | 1,473 | 325 |
| Supermarket | 1,269 | 355 |
| Hospital or clinic | 685 | 183 |
| Petrol station | 489 | 99 |
| Shopping mall | 297 | 88 |

### The method that does give a denominator

The owner's Tesco plan is the right method, with one correction. A chain's own
store list and a chain's parking statement are two different uses of the same
website. `fetch_fill.SKIPPED_HOSTS` holds `www.tesco.com` because the site does
not state parking for one named store. That does not rule out the store list.
A store list gives the denominator, and the parking answer then comes from a
different source.

Reachability was measured on 13 November, one request per host:

| Chain | robots.txt | Store list |
|---|---|---|
| Lidl | 200 | `https://www.lidl.co.uk/s/en-GB/store-finder/sitemap.xml`, 1,150 URLs for the whole country |
| Morrisons | 200 | Sitemap reachable, store pages not yet counted |
| Tesco | 403 | Blocked |
| Aldi | 403 | Blocked |

So the plan works brand by brand, and it will work for some brands and not
others. Where a chain blocks us, the denominator stays unknown, and we must say
unknown rather than claim completeness.

### Proposed coverage register

Build one table, brand by brand and category by category, with five columns: the
list source, the national list count, the London count after the borough filter,
the records we already hold, and the gap. `discover --source generic` already
fetches a list, filters it to London, deduplicates it against the database and
drafts the new places, so this needs no new module. Run it once per brand with
the store list as `--input`, and the run's own output is the coverage row.

Two limits to state in that register. For categories with no chain, which are
independent restaurants, pubs and private car parks, no authoritative list
exists, so coverage stays unknown for them permanently. Second, a store is not a
parking place: a Tesco Express with no car park must not become a record, so the
London filter needs the R10 format test, which counts a large format as having a
car park and a convenience format only when a car park is mapped within 40 m.

Driver value should pick the order, not list size. 19,975 restaurants is the
largest category in OpenStreetMap and close to the least useful, because a
driver does not search for restaurant parking. Supermarkets, shopping centres,
hospitals and council car parks are what a driver needs.

## The finding method, agreed 13 November 2026

This is how Ferro covers a category. It was agreed with the owner on
13 November and it replaces any plan that treats the bot as a search engine.

The principle. A place earns a record only when a named source states that it
exists. The bot reaches and reads. Ferro decides, deduplicates and writes.
The bot is never the authority on what exists, because a find with no page
behind it cannot be checked.

Scope, decided by the owner on 13 November.

- A place with no parking space is out of scope.
- A private, residents-only or permit-only space is out of scope, because no
  Ferro driver can enter it.
- On-street and kerbside bays are out of scope for this database. The owner
  collects those separately.
- A place we examined and found no parking at still earns a record, so that
  nobody researches it twice. Coverage itself is a count in a register, never
  a row for a place nobody checked.

The six steps, per source.

1. Choose one named source: an operator's own site list, a council
   inventory, or a chain's store list. One source per round.
2. The bot opens that list and every site page under it. It returns the
   places file, the parking answers, the raw page data, a page log and a
   report. It does not deduplicate against our database, because a duplicate
   costs one review while a dropped site never arrives.
3. PP Checker reads the sources again and returns OK, FIX or CANNOT VERIFY
   per cell.
4. Ferro runs `discover --source generic` over the places file. It filters to
   London by borough polygon, deduplicates by coordinates and name, and
   drafts the new places. A person reviews the drafts.
5. `db-create` creates the accepted places with identity only and never a
   parking answer, and assigns each a Place ID. Ferro maps the bot's `Ref`
   values to those Place IDs and runs `grok-import` over the answers.
6. Accepted rows reach the database through `db-apply`, with an undo saved.
   The source's London count goes into the coverage register against what we
   hold, so the gap becomes a number.

Who fetches what. Send the bot only where the site blocks us. Our own plain
requests reached Lidl and Morrisons on 13 November, so those are parsed here
with no bot and no transcription risk. NCP, Tesco, Aldi and the seven
councils returning 403 need the bot's browser.

Never ask the bot to type a field out. It copies the page's structured data
or its text into a raw file, and Ferro parses the fields here with code. See
the NCP section for why this rule exists.

## NCP round 1, 13 November 2026

The first operator list this project has ever taken. Files are in
`data/raw/ncp_round1_20261113/`.

Round 1 returned 120 London car parks. NCP's finder page carries no full
list, so PP used NCP's own sitemap, which lists 346 car parks, and picked 124
by reading their names. 120 have a Greater London address.

Ferro checked all 120 rows. Every mechanical check passes. Every `Ref` is
unique and joins to a `url` in the places file in both directions, every
dropdown value is allowed, every Tariff Detail matches its template with
closed, ordered and touching bands, no cell holds an en dash or an em dash,
and every opening-hours string parses. The six priced rows were compared with
the raw tariff text and their prices are correct.

Round 1 was not imported. Seven corrections are with PP as round 2.

- 69 of the 120 postcodes are incomplete, for example `WC2 N  4B` where the
  real postcode is WC2N 4BJ. The owner opened PP's saved page source and
  found that string in NCP's own HTML, so NCP publishes the broken value.
  About 19 pages in 45 carry only that header address. The rest also carry
  structured fields with a two-part postcode, for example `E1 ` and `7RA`,
  which rebuilds cleanly. Round 2 takes the postcode from those fields.
- No row carries a coordinate, because round 1 read the rendered text, where
  a map widget shows no numbers. The page source carries a `schema.org`
  block with the position.
- NCP's own coordinates can be wrong. Saffron Hill publishes latitude
  1.521066. The postcode EC1N 8XA returns 51.520969 from postcodes.io, so the
  leading 5 is missing from NCP's value. Range-check every coordinate against
  Greater London, about 51.2 to 51.7 north and -0.6 to 0.4 east, and fall
  back to the postcode position when the check fails.
- Cost Type reads Unknown on all 111 unpriced rows, although every one of
  them records a "Pay on the day" heading on the page and some list a season
  ticket price. That heading states the Cost Type. Round 2 sets `Paid` with
  Price Status `Not published`.
- Can Park? reads Unknown on 111 rows, although 87 publish NCP opening times
  on NCP's own car park page. Round 2 sets `Yes` on those.
- Rainham, Upminster and Dagenham Dock publish peak and weekend rates that
  fit no tariff template. Their rates sit in Rules Summary. Round 2 returns
  the raw text so Ferro can decide whether to add a template.
- PP reports 104 of the 120 already held, 48 of them matched on name and
  postcode. The rule that matched the other 56 is still unexplained, and any
  postcode match needs redoing after the postcode fix.

The 16 that do not match are the yield of round 1: twelve Heathrow pages,
Kings Cross, Victoria, Waterloo and Baynard House. Heathrow sits in
Hillingdon and is inside Greater London.

PP Checker could not re-read the pages. It got through two and then hit three
Cloudflare challenges in a row. 2 of its 105 values read OK, none need
fixing, and 103 cannot be verified. It now checks against the page files PP
saves, and it opens 10 pages itself, at least 10 seconds apart, with at least
7 of them short-template pages. A page whose HTML carries no self URL is
identified by its title, its main heading and the car park name in PP's fetch
log URL, and all three must agree.

Round 2 covers all 346 sitemap pages, at about 25 seconds each. The owner
approved opening `ncp.co.uk` again for both bots, spaced at least 3 seconds,
stopping if the site blocks them. NCP's `robots.txt` allows those paths, and
the 403 is a Cloudflare challenge rather than a refusal.

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
| Batch 9, rows 1246 to 1445 | 200 | 164 applied | 4,806 | `apply-20261113T105040Z` |
| Batch 10, rows 1446 to 1645 | 200 | 164 applied | 4,787 | `apply-20261113T105043Z` |
| Batch 11, rows 1646 to 1845 | 200 | 154 applied | 4,479 | `apply-20261113T105045Z` |
| Batch 12, rows 1846 to 2045 | 200 | 161 applied | 4,684 | `apply-20261113T105048Z` |
| Batch 13, rows 2046 to 2245 | 200 | 153 applied | 4,449 | `apply-20261113T105051Z` |
| Batch 14, rows 2246 to 2445 | 200 | 171 applied | 4,979 | `apply-20261113T105054Z` |
| Batch 15, rows 2446 to 2645 | 200 | 173 applied | 5,031 | `apply-20261113T105057Z` |
| Batch 16, rows 2646 to 2845 | 200 | 161 applied | 4,689 | `apply-20261113T105100Z` |
| Batch 17, rows 2846 to 3045 | 200 | 159 applied | 4,619 | `apply-20261113T105103Z` |
| Batch 18, rows 3046 to 3245 | 200 | 142 applied | 4,118 | `apply-20261113T105107Z` |
| Batch 19, rows 3246 to 3445 | 200 | 161 applied | 4,669 | `apply-20261113T105110Z` |
| Batch 20, rows 3446 to 3645 | 200 | 152 applied | 4,408 | `apply-20261113T105113Z` |
| Batch 21, rows 3646 to 3845 | 200 | 160 applied | 4,640 | `apply-20261113T105117Z` |
| Batch 22, rows 3846 to 4045 | 200 | 143 applied | 4,147 | `apply-20261113T105120Z` |
| Batch 23, rows 4046 to 4245 | 200 | 148 applied | 4,292 | `apply-20261113T105123Z` |
| Batch 24, rows 4246 to 4445 | 200 | 146 applied | 4,234 | `apply-20261113T105126Z` |
| Batch 25, rows 4446 to 4645 | 200 | 151 applied | 4,379 | `apply-20261113T105130Z` |
| Batch 26, rows 4646 to 4823 | 178 | 127 applied | 3,684 | `apply-20261113T105133Z` |

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

All 4,823 queue rows are researched. Use `scripts/filter_refused_lines.py` on
each batch plan before db-apply, so one refused cell no longer blocks a whole
batch.

## Batches 9 to 26, 13 November 2026

The bot finished the queue overnight: 3,578 result rows over 18 batches, rows
1246 to 4823. The bot's own self-check accepted every row, and `grok-import`
here gave the same three numbers on every batch: 3,578 accepted, 0 skipped and
0 rejected. The Place IDs cover queue rows 1246 to 4823 exactly, with no
duplicate and no extra row. Each batch keeps its own `db-undo` run.

784 rows are held, not applied. Every page opened under those Place IDs was an
OpenStreetMap map entry, so no site, operator or council page was ever tried.
This is the same weak class that held 33 rows in batch 7. The held list for
each batch is `data/runs/2026-11-13_<n>/grok_import_held/held_map_only_rows.csv`,
where `<n>` is the batch number minus 7. Those places stay on the Grok stage.
Most of them are unnamed car parks with no website, so a reread of the same
sources will not help. They need an on-site check or an OpenStreetMap tag rule.

2,790 places were written. 2,448 of them moved from blank to "No evidence",
243 to "Needs on-site check", 95 to "Confirmed, details not published" and 4 to
"Confirmed". Legacy showable rose from 1,606 to 1,649 and legacy complete from
1,098 to 1,117. The research value of this import is low, because the tail of
the queue holds unnamed car parks that publish nothing. Its process value is
that 2,790 places are now research complete for now, so they do not route for
research again.

A "No evidence" row here is page-backed. The bot opened about 400 pages per
batch of 200 rows, so this is not the batch 4 shallow-miss pattern. 530 of the
applied rows did open site pages that all failed to load, which is the accepted
blocked-page pattern from batch 6.

The PP Checker read 145 filled cells and returned 137 OK, 4 FIX and 4 CANNOT
VERIFY. All four FIX cells are held and need an owner decision:

- PP-008515 Richmond, PP-008615 Worcester Park and PP-009801 Brentford: the bot
  wrote an hourly Tariff Detail. National Rail states the rate, but sells it
  only through ScanPay and RingGo from 12:00 Monday to Friday and all day at
  the weekend. The checker asks for "Not published". Holding the cell dropped
  the whole place, so these three places were unwritten at first.
- PP-012460 North Greenwich: the bot wrote Hours "24/7". The council page says
  24 hours a day, but season ticket holders only from 01:00 to 11:00 on
  weekdays. The checker asks for
  `Mo-Fr 00:00-01:00,11:00-24:00; Sa,Su 00:00-24:00`.



All four FIX cells are now settled and applied on 13 November. PP-012460 took
the checker's opening hours under `apply-20261113T154013Z`. The three station
rows kept the published hourly rate, because National Rail does state it, and
Rules Summary now carries the condition that the rate runs from 12:00 Monday to
Friday and all day at weekends, through ScanPay or RingGo only
(`apply-20261113T154107Z`, 93 changes across the three places). Blanking the
Tariff Detail was not possible, because "Not published" contradicts Price Status
Published and Tariff Type Hourly rate on the same row.

The four CANNOT VERIFY rows all read a "free parking for 3 hours" or "4 hours"
line as a Max Stay: PP-008226 Greenwich Shopping Park at 180 minutes, and
PP-009014, PP-009015 and PP-009016 Gallions Reach at 240 minutes. A free period
is not a maximum stay. Those cells are applied and need a review.

PP-008587 was also dropped by the refusal filter. The other held cells are the
usual causes: a Notes or Review Flag line that would replace existing text, and
the charging-hours check.

Raw results are `data/raw/grok_results_batch9..26_2026111*.csv`. Each batch also
has a report, a page log and a checker file in the bot's own folder.

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

### 13 November dry runs

An unfiltered dry run is now `data/runs/2026-11-13_39/publish/`. It plans 0 rows
and reports 91,164 drift errors. Every one of them is "missing row" across 3,251
places the sheet does not hold, and none is a real value conflict. One drift
error empties the whole plan, so an unfiltered run can never write.

A second dry run is `data/runs/2026-11-13_40/publish/`. It is filtered with
`--place-ids` to the 3,511 changed places the sheet does hold. Result: 1,193
planned rows, 0 drift errors, 2,318 refusals and 0 second-reading failures, with
`plan.json` and `undo.json` saved. This is the first publication plan that can
write.

The 2,318 refusals break down as follows.

| Cause | Rows | Meaning |
|---|---:|---|
| finished row | 2,165 | The writer protects a finished row. Correct, not a fault. |
| dashes | 126 | An existing Notes cell holds an en dash. |
| dropdown | 26 | A value does not match `config/rules.toml`. |
| protected reviewer | 1 | The writer protects that cell. |

The 126 dash rows are old data, not batch 9 to 26 text. The en dashes sit in
Notes, and also in Location Name and the captured columns on the same records.
Normalize them to plain hyphens before you try to publish those rows.

Two of the six checks read false in `checks.json`: `locks` and `validation`.
They read false because refusals exist, not because a planned row is wrong. The
1,193 planned rows themselves carry no drift and no refusal. The owner's
explicit go is still needed, with an independent second reading, before any
`--apply`.

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
