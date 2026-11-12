# Ferro parking data pipeline: OSM-first architecture (ASCII, for LLM context)

Design reference only. Built/planned labels are historical. Read STATUS.md for current work.
Consult this document only for architecture decisions.

Legend:
  [CODE]   deterministic script, no LLM, near-zero cost
  [LLM]    language model (Grok PP bot, or Claude), costs tokens
  [HUMAN]  Deshan / Brandon
  [BUILT]  exists today      [TO BUILD]  planned
  Sheet = Google Sheet "PP Parking places", working tab "ALL LONDON (clean)"

Goal: fill the sheet for London, then other UK cities, with code doing almost all
of the work. The LLM bot only handles the small residue that code cannot settle.

## Diagram 1: target architecture (end to end)

```
 FREE DATA SOURCES                         EXISTING DATA
 +-------------------------------+         +-------------------------------+
 | OSM extract per region        |         | ALL LONDON (read-only)        |
 | (Geofabrik .osm.pbf, free)    |         | original capture              |
 | London now, UK regions later  |         +---------------+---------------+
 +---------------+---------------+                         |
                 |                                         v
 +---------------+---------------+         +-------------------------------+
 | Official feeds [TO BUILD]     |         | ALL LONDON (clean)            |
 | - National Rail Knowledgebase |         | one row per place, Place ID   |
 |   stations feed (car parks)   |         | rows 2-44 Acton: hand-checked,|
 | - operator location lists     |         |   never touched               |
 |   (NCP, Euro, APCOA...)       |         | rows with Verification Result:|
 | - council car park pages      |         |   finished, never touched     |
 +---------------+---------------+         +---------------+---------------+
                 |                                         |
                 |              export CSV (manual now,    |
                 |              Sheets API later)          |
                 v                                         v
 +---------------------------------------------------------------------------+
 | STAGE 1  MATCH + ROUTE   [CODE] [BUILT]  osm_parking_match.py (on a Mac)  |
 | for each unfinished row:                                                  |
 |  - find the place in OSM by brand/name near its coordinates               |
 |    (250 m search if the pin is a postcode centroid, 80 m if precise)      |
 |  - station rows only match OSM stations; non-park rows never match parks  |
 |  - find the place's car park (adjacent <= 40 m, or brand-named <= 150 m)  |
 |  - read tags: access, fee, maxstay, opening_hours, operator, capacity     |
 |  - closure hints (disused:/was: tags), official URL, OSM website          |
 |  - chains = names repeated 5+ times in the sheet                          |
 |  - assign ROUTE: Skip / A / B / C / D / E   (see Diagram 2)               |
 | output: osm_results.csv = one "packet" per row                            |
 | London result: 2,913 rows; place found 63%; car park found 962 (33%)      |
 |  routes A 834 | B 1,156 | C 665 | D 79 | E 178 | Skip 1                   |
 +-------------------------------------+-------------------------------------+
                                       |
                                       v
 +---------------------------------------------------------------------------+
 | STAGE 2  EVIDENCE COLLECTORS (all [CODE], text only, no browser)          |
 |                                                                           |
 |  2a OSM filler        [BUILT as suggestions]  route C rows                |
 |     tags -> Can Park? Conditional, Who Can Park (Customers only if        |
 |     access=customers, else Unknown), Cost Type, Max Stay, Hours,          |
 |     Operator, Source Tier = OpenStreetMap                                 |
 |                                                                           |
 |  2b Page fetcher      [TO BUILD]  routes A, B, C                          |
 |     HTTP GET the official URL (no browser), extract text, look for        |
 |     parking facts: "car park", "free parking", "max stay", tariff tables, |
 |     P icon alt text. Per-chain parsers for structured store finders       |
 |     (Co-op, Sainsbury's, Tesco, Lidl, Aldi...). Per-operator parsers      |
 |     for tariff pages (NCP, Euro Car Parks, APCOA, councils).              |
 |                                                                           |
 |  2c Chain rules table [TO BUILD]  route B                                 |
 |     one row per chain + format (e.g. "Lidl, any": 90 min free, ANPR).     |
 |     Researched ONCE per chain ([HUMAN] or a single [LLM] call), then      |
 |     applied to every branch as "Chain policy (not store-specific)".       |
 |                                                                           |
 |  2d Predictions       [TO BUILD]  any row still "Unknown"/"Not published" |
 |     baseline: most common verified value per chain + format, with the     |
 |     agreement rate. Written ONLY to separate "Predicted ..." columns,     |
 |     never into the verified columns.                                      |
 +-------------------------------------+-------------------------------------+
                                       |
                                       v
 +---------------------------------------------------------------------------+
 | STAGE 3  RULES ENGINE   [CODE] [TO BUILD]                                 |
 | the PP validator rules, written as code instead of a prompt:              |
 |  - merge evidence, strongest source first                                 |
 |  - Yes only from official / operator / council page or tariff photo       |
 |  - OSM and Maps About are weak: Conditional at most, never Confirmed      |
 |  - conflicts: newest dated source wins, else Needs on-site check with     |
 |    the cautious value (No > Conditional > Yes, higher price wins)         |
 |  - Verification Result steps 1-3, consistency checks 1-13                 |
 |  - Autopay rows: compare first price with Parking Charge (GBP), flag diff |
 |  - anything it cannot settle -> RESIDUE QUEUE (not guessed)               |
 +------------------+--------------------------------------+-----------------+
                    | settled                              | not settled
                    v                                      v
 +--------------------------------+      +-----------------------------------+
 | STAGE 4  QUALITY GATE [CODE]   |      | RESIDUE QUEUE                     |
 | - dropdown values valid        |      | routes D/E, silent pages,         |
 | - no protected column touched  |      | conflicts, Autopay non-car-parks, |
 |   (Brandon's 4, Lat/Long,      |      | possible closures                 |
 |   as-captured, Place ID,       |      | target: under 10% of rows         |
 |   formulas)                    |      +-----------------+-----------------+
 | - Decision Reason present      |                        |
 +-------+---------------+--------+                        v
         | pass          | fail             +-----------------------------------+
         v               v                  | [LLM] PP bot with browser, only   |
 +---------------+ +---------------+        | when credits allow, using the v2  |
 | STAGE 5       | | back to rules | <------+ prompt (routes D/E)               |
 | WRITER [CODE] | | engine with   |        | or [HUMAN] review for a handful   |
 | Sheets API,   | | the reason    |        +-----------------------------------+
 | batch of 25,  | +---------------+
 | Verification  |
 | Result LAST,  |
 | read back,    |
 | 0 mismatches  |
 | = logged      |
 +-------+-------+
         |
         v
 +---------------------------------------------------------------------------+
 | STAGE 6  REVIEW + USE                                                     |
 | [HUMAN] Review Flag queue (Flag Status = Open)                            |
 | Later: coverage map sync, Ferro Autopay pricing, UK rollout (Diagram 4)   |
 +---------------------------------------------------------------------------+
```

## Diagram 2: route decision per row (Stage 1, first match wins)

```
 row
  |
  v
 Location Name blank? --------------- yes --> SKIP: flag "blank row" for a person
  | no
  v
 OSM closure hint, or status
 Closed / Temporarily closed? ------- yes --> E: full research + Maps photos
  | no
  v
 car park or station row?
 (type says car park/parking, or name
  says car park but NOT "customer car
  park"; or a station type) --------- yes --> A: operator / council / National Rail
  | no                                         page as text. Autopay = price check
  v
 Autopay row (not a car park)? ------ yes --> E: full research + Maps photos
  | no
  v
 OSM shows this place's car park? --- yes --> C: official page as text; if silent,
  | no                                         use OSM tags (skip Maps About)
  v
 chain (Brand, brand in brackets,
 or name repeated 5+ times)? -------- yes --> B: branch page as text + chain rule
  | no
  v
 D: full research (official, operator, Maps, Parkopedia, search)

 Fallbacks: A, B or C page silent/blocked -> D (E if Autopay).
 Cost: A, B, C need no browser. D, E need the browser (the expensive part).
```

## Diagram 3: pilot before any scale-up (now, no Grok)

```
 +-------------------------------+
 | osm_results.csv (London run)  |
 +---------------+---------------+
                 |
                 v
 +-------------------------------+
 | pick ~10 route C rows         |
 | mixed: access=customers and   |
 | no access tag; different      |
 | boroughs and categories       |
 +---------------+---------------+
                 |
                 v
 +-------------------------------+
 | DRY RUN [CODE]                |
 | exact values per column for   |
 | each row + current values     |
 | (saved as the undo copy)      |
 +---------------+---------------+
                 |
                 v
 +-------------------------------+      no
 | [HUMAN] Deshan approves? -----+--------> fix rules, dry run again
 +---------------+---------------+
                 | yes
                 v
 +-------------------------------+
 | WRITE the ~10 rows            |
 | Verified By = "OSM script     |
 | (pilot)", Verification Result |
 | last, read back               |
 +---------------+---------------+
                 |
                 v
 +-------------------------------+
 | [HUMAN] validate 5 rows by    |
 | hand: official page, Google   |
 | Maps, Street View. Score each:|
 | correct / wrong / can't tell  |
 +---------------+---------------+
                 |
                 v
 +-------------------------------+
 | GO: build page fetcher (2b)   |
 | and writer for all route C,   |
 | then A and B                  |
 | NO-GO: undo from the copy,    |
 | fix the rule that failed      |
 +-------------------------------+
```

## Diagram 4: UK rollout loop (per city or region)

```
 +---------------------------+     +---------------------------+
 | download region extract   | --> | DISCOVER places from OSM  |
 | (Geofabrik, free)         |     | [CODE]: chain brands,     |
 +---------------------------+     | car parks, stations,      |
                                   | retail parks. Replaces    |
                                   | LLM capture of new rows   |
                                   +-------------+-------------+
                                                 |
                                                 v
                                   +---------------------------+
                                   | new rows -> sheet/tab per |
                                   | city, Place IDs assigned  |
                                   +-------------+-------------+
                                                 |
                                                 v
                                   +---------------------------+
                                   | Stages 1-6 as in Diagram 1|
                                   | chain rules table reused  |
                                   | across all cities         |
                                   +-------------+-------------+
                                                 |
                                                 v
                                   +---------------------------+
                                   | residue queue only -> LLM |
                                   | bot or human              |
                                   +---------------------------+
```

## Open decisions

- Licence: OSM is ODbL. Brandon to confirm before OSM-derived values reach the app.
- Writer for scale: Google Sheets API from a script (needs a service account shared on the sheet).
- Sheet size: the UK will outgrow one Google Sheet; a database (e.g. Postgres or SQLite) with the sheet as a view is likely needed.
