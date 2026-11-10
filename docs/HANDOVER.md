# Handover: Ferro parking pipeline (state at Tue 3 Nov 2026, 23:15)

You are taking over a project that fills the Ferro Maps parking sheet. Read this file first, then docs/PP_rules_and_pilot.md (rules R1-R9) and docs/PP_Validator_prompt_v2_OSM.md (column definitions, allowed values, decision steps).

## Goal

Every place on the sheet gets honest, accurate parking details (can you park, who, free or paid, max stay, operator). Brandon (co-founder) reviews the sheet. Accuracy beats completeness: a wrong "free" or time limit gets a driver fined, so "Not published" is always better than a guess.

## Where things are

- Repo: https://github.com/tharidu-e/ferro-parking (private). Local: ~/Documents/ferro-parking, use .venv.
- Sheet: spreadsheet ID 1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o. Working tab: "ALL LONDON (clean)". "ALL LONDON" is the original capture: read only, never edit.
- Data (never committed): data/raw (OSM extract, exports), data/runs/<date>/ (plans, undo files, logs).
- Secrets: secrets/oauth_client.json and secrets/token.json. Never print, copy, commit or share them.

## Commands (python -m ferro_parking ...)

| Command | What it does |
|---|---|
| export | saves the clean tab to data/raw/all_london_clean.csv |
| match | matches rows to OpenStreetMap, picks a research route (A-E), writes osm_results.csv |
| fill --borough X | dry run: OSM-based values for route C rows |
| capture-fill --borough X | dry run: values from evidence PP already captured (routes A, B) |
| write PLAN --apply | writes a plan; aborts if target cells changed; reads back |
| undo UNDO --apply | restores the original values |
| sync | builds the plan to append the ~667 missing places to the clean tab |

Every write has a dry run, an undo file, and an independent re-export compare afterwards. Never skip these. Run the tests (python -m pytest, 140 should pass) before any commit.

## State of London

- 5,439 rows in the clean tab (the 666 later-captured places were appended, Place IDs PP-004774 to PP-005439). 3,310 finished, 2,129 not.
- Finished by: PP (validation) 1,817, Policy script 1,048 (419 chain policy, 629 presumed), OSM script 192, Claude (capture check) 189, Tharidu 43 (hand-checked, never touch), Claude (page check) 11, pilot rows 10.
- Evidence Level column (last column): Verified, Chain policy, Presumed.
- Cell A1 was fixed (header "Location Name"; the stray note is now a cell comment). The header workaround in sheets.py stays as a safeguard.
- Plain fetches of chain store pages fail (403 or bot checks), so route B rows with no captured evidence need a browser (Grok) or a scraper.
- The list is only what PP found. OSM shows about 18,000 car parks in Greater London. Coverage is not yet measured.

## Audit findings (3 Nov), not yet fixed unless marked

- About 91 older rows claim Free or a max stay from chain policy text (R7 breach), mostly Sainsbury's, Tesco and Waitrose. Fix: Cost Unknown, Max Stay Not published, old value into Notes.
- 30 duplicate places (same name and postcode), many Euro Car Parks rows captured twice. Flag, do not delete.
- 20 rows labelled "Corrected" (not a valid value), 541 "Needs on-site check" rows with no source (should be No evidence), 139 "Confirmed" rows missing max stay or hours, 1,493 finished rows with no Decision Reason.
- AutoPay: 19 rows say Can Park No or Unknown, 214 have Parking Charge "NO OFFICIAL PRICE". Report to Brandon, never edit his columns.
- Unfinished rows still show PP's first guesses in Can Park? (1,737 rows). A clear_unverified dry run is ready; code reads the captured value from the original "ALL LONDON" tab. Check whether "clear" has been applied before assuming.
- 34 rows outside London, 30 with borough UNCLEAR, 224 blank postcodes, 35 without coordinates.

## Rules in one paragraph

R1 store car park = customers by default. R2 signs do not expire (Brandon: parking rules very rarely change). R3 an OSM operator that is the store itself is not the parking operator. R4 OSM or chain max stay never goes in Max Stay, only in Notes. R5 a readable sign photo beats OSM. R6 chain rules only from verified site-specific rows, never for max stay. R7 "Free", "Anyone can park" and any max stay need proof for that exact site. R8 captured text counts as evidence only if it is about this site, and never if it says UNCLEAR, not published, VERIFY. R9 "Can Park? = No" needs an explicit statement; silence is not No.

## Hard rules

1. Never edit these columns: Postcode Area, Confidence (1-5), Free Stay Countdown (mins), Ferro Autopay, Parking Charge (£), Total incl. Ferro Fee (£), Captured By, Date Captured, Latitude, Longitude, Place ID, every "(as captured)" column, Charges (as published), Enforcement Details.
2. Find columns by header text, match rows by Place ID. Never insert, delete, sort or reorder rows or columns.
3. Dropdown columns accept only the exact allowed values. No en or em dashes.
4. Write Verification Result last. Never mark a row finished without a Decision Reason.
5. Do not write to the sheet without Deshan's approval of the dry run. Do not delete files.
6. Do not open the original "ALL LONDON" tab for writing.

## Rules added since the first handover

R7 and R8 and R9 as written in docs/PP_rules_and_pilot.md, plus R10: every row has an Evidence Level; chain policy and presumed rows may only set cautious values (Customers only, Guests only, Cost Unknown or Paid, Max Stay Not published); a presumed "no parking listed" is only for small venues with no OSM car park within 40 m.

## Next steps, in order

1. Confirm the clear_unverified step was applied. Then run the cleanup (R7 breaches, duplicates, old labels, consistency), dry run first.
2. Discovery count (read-only): count London places per category in OSM against the sheet, then append missing places and run the fills on them.
3. Hotel page scraper and council and operator car park page scraper, each tested on finished rows before use.
4. National Rail Knowledgebase stations feed (needs Deshan to register on the Rail Data Marketplace).
5. Fri 6 Nov 10:54: Grok (PP bot) gets only the residue, with docs/PP_Validator_prompt_v2_OSM.md Part 2 (it starts with a 20-row test run), plus a random sample check of data/runs/2026-11-02/evaluation_sample.csv.
6. UK: one tab or one spreadsheet per region (a Google Sheet holds about 170,000 rows). Brandon to choose.
7. Brandon's questions: AutoPay columns for the new rows, rows with no price.

## How Deshan likes to work

Direct and blunt, no padding, no em dashes. Prefers structured outputs with reasons. Wants a file-by-file summary after any task, and self-contained prompts for agent tools. Destructive actions need explicit sign-off.