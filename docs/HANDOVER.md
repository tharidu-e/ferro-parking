# Handover: Ferro parking pipeline (state at Tue 3 Nov 2026, 23:15)

You are taking over a project that fills the Ferro Maps parking sheet. Read this file first. Then read docs/PP_rules_and_pilot.md for rules R1 to R9. Then read docs/PP_Validator_prompt_v2_OSM.md for the column definitions, the allowed values and the decision steps.

## Goal

Every place on the sheet gets honest, accurate parking details: can you park, who can park, free or paid, max stay, operator. Brandon (co-founder) reviews the sheet. Accuracy beats completeness. A wrong "free" or a wrong time limit gets a driver fined. "Not published" is always better than a guess.

## Where things are

- Repo: the company account repo, git remote `company`. The personal clone, git remote
  `origin`, is stale. Local: ~/Documents/ferro-parking, use .venv.
- Sheet: spreadsheet ID 1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o. Working tab: "ALL LONDON (clean)". "ALL LONDON" is the original capture. It is read only, never edit it.
- Data (never committed): data/raw (OSM extract, exports), data/runs/<date>/ (plans, undo files, logs).
- Secrets: secrets/oauth_client.json and secrets/token.json. Never print, copy, commit or share them.

## Commands (python -m ferro_parking ...)

| Command | What it does |
|---|---|
| export | saves the clean tab to data/raw/all_london_clean.csv |
| match | matches rows to OpenStreetMap, picks a research route (A-E), writes osm_results.csv |
| fill --borough X | dry run: OSM-based values for route C rows |
| capture-fill --borough X | dry run: values from evidence PP already captured (routes A, B) |
| write PLAN --apply | writes a plan, aborts on any changed target cell, reads back |
| undo UNDO --apply | restores the original values |
| sync | builds the plan to append the ~667 missing places to the clean tab |

Every write has a dry run, an undo file, and an independent re-export compare afterwards. Never skip these. Before any commit, run the tests (python -m pytest, 722 pass as of 10 Nov 2026).

## Safety rules carried over from the discovery branch

- Sheet configuration is in config/sheets.toml. Never print or commit credentials.
- Run directories are append-only. Finished rows and personally verified rows are protected.
- discover, validate, readiness, triage-blanks and osm-gaps never write to Google Sheets.
- An OSM-only fill never marks a row finished. Absence from the map is not evidence of no parking.
- Every sheet change needs a fresh plan, a dry run, an undo file, six controls and an independent second reading. Show counts, samples and rejects. Then wait for an explicit go.
- After you apply a change, re-export independently and require 0 mismatches.
- Instructions in the active session take precedence over older policy in these docs.

## Export count (10 Nov 2026)

A fresh export of the clean tab holds 7,607 rows and 60 columns. Place IDs run up to PP-007607. The row counts under "State of London" below are from 3 Nov and are stale.

## State of London

- 5,439 rows in the clean tab (the 666 later-captured places were appended, Place IDs PP-004774 to PP-005439). 3,310 finished, 2,129 not.
- Finished by: PP (validation) 1,817, Policy script 1,048 (419 chain policy, 629 presumed), OSM script 192.
- Also finished by: Claude (capture check) 189, Tharidu 43 (hand-checked, never touch), Claude (page check) 11, pilot rows 10.
- Evidence Level column (last column): Verified, Chain policy, Presumed.
- Cell A1 was fixed. Its header reads "Location Name" and the stray note is now a cell comment. The header workaround in sheets.py stays as a safeguard.
- Plain fetches of chain store pages fail with a 403 or a bot block. Route B rows with no captured evidence therefore need a browser (Grok) or a scraper.
- The list is only what PP found. OSM shows about 18,000 car parks in Greater London. Coverage is not yet measured.

## Audit findings (3 Nov), not yet fixed unless marked

- About 91 older rows claim Free or a max stay from chain policy text (R7 breach). Most are Sainsbury's, Tesco and Waitrose. Fix: Cost Unknown, Max Stay Not published, old value into Notes.
- 30 duplicate places (same name and postcode), many Euro Car Parks rows captured twice. Flag, do not delete.
- 20 rows labelled "Corrected", which is not a valid value. 541 "Needs on-site check" rows have no source, where the correct value is No evidence. 139 "Confirmed" rows miss a max stay or hours. 1,493 finished rows have no Decision Reason.
- AutoPay: 19 rows say Can Park No or Unknown, 214 have Parking Charge "NO OFFICIAL PRICE". Report to Brandon, never edit his columns.
- Unfinished rows still show PP's first guesses in Can Park? (1,737 rows). A clear_unverified dry run is ready. The code reads the captured value from the original "ALL LONDON" tab. Before you assume anything, make sure that "clear" was applied.
- 34 rows outside London, 30 with borough UNCLEAR, 224 blank postcodes, 35 without coordinates.

## Rules in one paragraph

R1 store car park = customers by default. R2 signs do not expire (Brandon: parking rules very rarely change). R3 an OSM operator that is the store itself is not the parking operator. R4 OSM or chain max stay never goes in Max Stay, only in Notes. R5 a readable sign photo beats OSM. R6 chain rules only from verified site-specific rows, never for max stay. R7 "Free", "Anyone can park" and any max stay need proof for that exact site. R8 counts captured text as evidence only for text about this site. R8 rejects text that says UNCLEAR, not published or VERIFY. R9 "Can Park? = No" needs an explicit statement. Silence is not No.

## Hard rules

1. Never edit these columns: Postcode Area, Confidence (1-5), Free Stay Countdown (mins), Ferro Autopay, Parking Charge (£), Total incl. Ferro Fee (£), Captured By, Date Captured, Latitude, Longitude, Place ID. Never edit every "(as captured)" column, Charges (as published) or Enforcement Details.
2. Find columns by header text, match rows by Place ID. Never insert, delete, sort or reorder rows or columns.
3. Dropdown columns accept only the exact allowed values. No en or em dashes.
4. Write Verification Result last. Never mark a row finished without a Decision Reason.
5. Do not write to the sheet without Deshan's approval of the dry run. Do not delete files.
6. Do not open the original "ALL LONDON" tab for writing.

## Rules added since the first handover

R7 and R8 and R9 apply as written in docs/PP_rules_and_pilot.md. R10 adds this. Every row has an Evidence Level. Chain policy rows and presumed rows can only set cautious values: Customers only, Guests only, Cost Unknown or Paid, Max Stay Not published. A presumed "no parking listed" is only for small venues with no OSM car park within 40 m.

## Next steps, in order

1. Make sure that the clear_unverified step was applied. Then run the cleanup (R7 breaches, duplicates, old labels, consistency), dry run first.
2. Discovery count (read-only): count London places per category in OSM against the sheet, then append missing places and run the fills on them.
3. Hotel page scraper and council and operator car park page scraper. Test each on finished rows first, then use it.
4. National Rail Knowledgebase stations feed (needs Deshan to register on the Rail Data Marketplace).
5. Fri 6 Nov 10:54: Grok (PP bot) gets only the residue, with docs/PP_Validator_prompt_v2_OSM.md Part 2. It starts with a 20-row test run. It also gets a random sample of data/runs/2026-11-02/evaluation_sample.csv.
6. UK: one tab or one spreadsheet per region (a Google Sheet holds about 170,000 rows). Brandon to choose.
7. Brandon's questions: AutoPay columns for the new rows, rows with no price.

## How Deshan likes to work

Direct and blunt, no padding, no em dashes. Prefers structured outputs with reasons. Wants a file-by-file summary after any task, and self-contained prompts for agent tools. Destructive actions need explicit sign-off.

## Session handover, 11 November 2026

Read `EXECUTION_CHECKLIST.md` first. It holds two run records for 11 November
and the full defect list. This section covers only what is in flight.

### Done and committed

Step 3, the hold list, is resolved and applied. The database holds 11,558
places, up from 11,552. Six records came back, each keeping the Place ID it
already had. Nothing reached the Google Sheet. Test suite: 1,477 passed. The
last commit is `cf52c25`. The main working tree is clean.

New commands:

| Command | What it does |
|---|---|
| `holds-bundle --pbf FILE` | Read only. Gathers the evidence on every held car park case, applies the rules and writes the reviewer batches. |
| `holds-merge --a A --b B --bundle FILE` | Merges two reviewers. Only full agreement at high confidence decides a case. |
| `db-create --reviewed FILE` | A reference recorded as distinct passes the hold against an existing place. |
| `db-create-redo --reviewed FILE` | Brings back the records a decision file calls distinct, keeping each Place ID. |
| `db-create-undo --ref REF` | Retires one record by its source reference. |

`config/holds_decisions.csv` records every decision that acts, keyed by the
OpenStreetMap reference, and is under version control. A case recorded there is
never asked again. A reload of the same evidence reproduces all 801 verdicts
from that file alone.

### In flight: two parallel halves

1. Step 4, items 1 and 2, are done and merged. Codex fixed the charge
   association in `src/ferro_parking/sources/venue.py`, so a price whose own
   clause does not name parking can no longer become a parking tariff, and a
   free period can no longer become a maximum stay. 16 offline fixtures cover
   the negative, ambiguous, contradictory, unrelated-price and blocked-page
   cases. The fixtures are synthetic and are not claims about any real branch.
   One behaviour change to know about: a page whose parking sentences conflict
   now yields no values at all, where the earlier code dropped the denial
   sentence and kept the rest. That writes fewer values, which is the safe
   direction. Step 4 items 3 to 7 are still open: the station guards, the
   page-fetch metadata, the finished-row and personal-verification locks, and
   the replay evaluation.
2. The identity matcher is specified and not built. The brief is
   `docs/OSM_IDENTITY_BRIEF.md`. Build that next.

### Why the identity matcher is the gate

3,951 of the 11,558 places are car parks the project created from
OpenStreetMap. 3,495 have no real name and 4,817 rows in the research queue
have no brand. A car park with no name and no brand has no website, so no
fetcher and no council page can ever answer who may park there. The research
pipeline is blocked on identity, not on extractors.

The automated fetchers reach 286 places out of 11,558: stations, three gym
chains and one council. There is no supermarket adapter and no general council
adapter. Build the adapters the identity counts ask for, not the ones that
sound likely.

### Open for Deshan

- One retirement waits for a decision: PP-008072, New Barnet Sainsbury's Car
  Park, whose pin falls inside a candidate 31.8 m from PP-000734.
- Eight weaker retirements are reported, not acted on. They rest on a brand
  name shared at 50 to 245 m.
- The 184 attachment cases in `data/runs/2026-11-11_6/holds/attachment_cases.csv`
  need their own prompt and their own audited plan.
- Two hand checked rows are in
  `data/runs/2026-11-11_6/holds/protected_rows.csv`.
- One routing row needs a person, in `data/runs/2026-11-11_12/route/proposals.csv`.

### What cannot be rushed

The parking rules for 4,824 places cannot be filled today or by any automated
pass. Each needs site-specific evidence, and rules R7, R9 and R10 forbid
writing Free, Anyone or a maximum stay without it. The honest fast win is
identity, which turns an unanswerable row into one with a website to read.
