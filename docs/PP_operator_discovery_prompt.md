# Master bot prompt: operator car park discovery, round 1 (NCP)

Paste everything below the line into the master bot. It assigns the work to
PP and to PP Checker. The target this round is NCP only. Do not start another
operator until Ferro accepts this batch.

---

## Job

Find every NCP car park in London and record what NCP itself publishes about
each one. NCP is the operator. Its own website is the only list source for
this job.

Two bots work on this job.

- PP reads the pages and writes the result files.
- PP Checker reads the sources again, on its own, and gives a verdict per cell.

## What PP must do

1. Open NCP's own car park finder on `ncp.co.uk`. Collect every car park it
   lists with a London address.
2. Open each car park's own page on that site. Read the page.
3. Record what the page states. Do not infer a value from another site.
4. Write the four files named below. One folder, named
   `ferro-<YYYYMMDD>-ncp1`.

Return every car park you find. Do not try to remove car parks that Ferro
already holds. Ferro deduplicates against its database on its own side. A
duplicate costs Ferro one review. A real site that you drop never reaches
Ferro at all.

Do not search the open web for London car parks. A car park with no NCP page
behind it does not belong in this batch.

Do not invent a coordinate, a postcode or a price. If NCP does not state it,
leave the field empty or write `Not published`, as the column rules below say.

## File 1: the places

Name it `ncp1-places.csv`. Use these column names exactly, in this order.

`name,address,postcode,lat,lon,url,tariff,hours,max_stay,brand`

- `name`: the car park name as NCP writes it, for example
  `NCP London Victoria`.
- `address`: the street address as NCP writes it.
- `postcode`: the postcode as NCP writes it. Leave it empty if NCP does not
  state one.
- `lat` and `lon`: decimal degrees, only if the page or its map states them.
  Leave both empty otherwise. Never estimate a position.
- `url`: the car park's own page on `ncp.co.uk`. One URL per row.
- `tariff`: the price text as published, copied, not reshaped.
- `hours`: the opening hours text as published.
- `max_stay`: the maximum stay text as published.
- `brand`: write `NCP` on every row.

One row per car park. No blank rows. No totals row.

## File 2: the parking answers

Name it `ncp1-results.csv`. Use the 34 columns of the Ferro results format,
with one change. These are new places, so they have no Place ID yet. Replace
the `Place ID` column with a `Ref` column and put the car park's NCP page URL
in it. Ferro maps `Ref` to a Place ID after it creates the records.

Columns, in this order:

`Ref,Location Name,Can Park?,Who Can Park,Location Status,Rules Summary,Cost Type,Price Status,Tariff Type,Tariff Detail,Max Stay (mins),Hours (OpenStreetMap opening_hours format),Hours Basis,Parking Control Type,Operator,PCN amount (£),Evidence Type,Evidence Detail,Source URLs,Source Tier,Specificity,Rules Stated,Prices Stated,Evidence Age,Agreeing Sources,Conflict,Evidence Level,Notes,Review Flag,Decision Reason,Proposed Result,Fields Found,Minutes Spent,Researched Date`

### Allowed values

Use one of these values exactly. Any other value makes Ferro reject the row.

- Can Park?: `Yes`, `No`, `Conditional`, `Unknown`
- Who Can Park: `Anyone`, `Anyone (paid)`, `Customers only`, `Guests only`,
  `Patients and visitors`, `Permit holders`, `Not applicable`, `Unknown`
- Cost Type: `Free`, `Paid`, `Free then paid`, `Not applicable`, `Unknown`
- Price Status: `Published`, `Not published`,
  `Chain policy (not store-specific)`, `Not applicable`
- Tariff Type: `Hourly rate`, `Flat rate per 24 hours`,
  `Flat rate per night`, `Banded by stay length`, `Free with time limit`,
  `Free (time limit not published)`, `Free period, then hourly`,
  `Not published`, `Not applicable`
- Hours Basis: `Car park hours`, `Site hours`, `Store hours`,
  `Not published`, `Not applicable`
- Parking Control Type: `ANPR (Automatic Number Plate Recognition) camera`,
  `Barrier`, `Patrol`, `Pay and display`, `Not published`, `Not applicable`
- Source Tier: `Operator / council site` for an NCP page. Use `None found`
  only when no page loaded at all.
- Evidence Type: `Official site: clear answer`, `Official site: partial info`,
  `Google Maps only`, `OpenStreetMap only`, `No info found`
- Specificity: `Site-specific`, `Chain-wide`, `Area only`
- Evidence Level: `Verified`, `Chain policy`, `Presumed`
- Evidence Age: `Under 12 months`, `1-2 years`, `Older or undated`
- Rules Stated, Prices Stated, Conflict: `Yes` or `No`
- Location Status: `Open`, `Temporarily closed`, `Closed`, `Unknown`
- Proposed Result: `Confirmed`, `Confirmed, details not published`,
  `Needs on-site check`, `No evidence`

### Tariff Detail templates

Tariff Detail must match the template for its Tariff Type, character for
character. Every price needs two decimals. Bands must be closed, in order,
and must touch.

- `Hourly rate`: `£3.70 per hour`
- `Flat rate per 24 hours`: `£27.00 per 24 hours`
- `Flat rate per night`: `£12.00 per night`
- `Banded by stay length`: `0-1 hrs £2.00; 1-3 hrs £5.50; 3-24 hrs £12.00`
- `Free with time limit`: `Free for up to 3 hrs`
- `Free period, then hourly`: `Free for 30 mins, then £2.00 per hour`
- `Free (time limit not published)`: `Free`
- `Not published`: `Not published`
- `Not applicable`: `Not applicable`

Put any condition on a price in Rules Summary, not in Tariff Detail. For
example, write the hourly rate in Tariff Detail and write
`Hourly rate applies from 12:00 Monday to Friday` in Rules Summary.

### Hours format

Use the OpenStreetMap opening_hours format, for example
`Mo-Fr 07:00-19:00; Sa 08:00-18:00` or `24/7`. If the page states a
restriction inside those hours, write the real pattern, not `24/7`.

## The rules that reject rows

Read these before you start. Each one has rejected real rows before.

1. Silence is not No. A page that says nothing about a car park is not
   evidence that there is no car park. Use `Unknown`, and set Proposed Result
   to `No evidence`.
2. Identity is not permission. An NCP page proves that NCP runs the site. It
   does not prove who can park or what it costs.
3. Evidence Age must be `Older or undated` on a page with no date. Do not
   write `Under 12 months` because the page looks current.
4. A `No evidence` row must have Source Tier `None found`. A row with a
   loaded page must not use `None found`.
5. Use plain hyphens everywhere. An en dash or an em dash rejects the row.
6. Write prices as `£` and two decimals. `£5` rejects. `£5.00` passes.
7. Do not write Ferro Autopay or Parking Charge. Leave those out.
8. Set Agreeing Sources to the number of separate sources that state the same
   fact. One NCP page is `1`.
9. Fill Researched Date with the London date you read the page.

## What to do when a page is blocked

Do not guess, and do not fill the row from another website.

1. Write the blocked URL in Notes, with its HTTP status, for example
   `Blocked: https://www.ncp.co.uk/... returned 403`.
2. Set Proposed Result to `No evidence` and Source Tier to `None found`.
3. Keep the car park in `ncp1-places.csv` if the finder listed it. A listed
   site is still a real site.
4. Record the blocked host once in the report, under a heading
   `Blocked sources`.

If the whole of `ncp.co.uk` blocks you, stop and report that. Do not replace
NCP with a third-party parking website.

## File 3: the checker file

PP Checker writes `ncp1-checker.csv` with these columns.

`Ref,Location Name,Field,PP Value,Verdict,Correct Value,Source URL,Quote,Checked Date`

Rules for PP Checker.

1. Open the source again yourself. Do not read PP's notes and agree with
   them.
2. Check every row that states a price, and a sample of at least 20 of the
   remaining rows.
3. Use one verdict per cell: `OK`, `FIX` or `CANNOT VERIFY`.
4. On `FIX`, write the correct value and the quote that supports it. Make sure
   that the correct value still matches the templates and allowed values
   above, and that it does not contradict another cell in the same row. A
   price cannot read `Not published` while Price Status reads `Published`.
5. Use `CANNOT VERIFY` when the page does not support the value and does not
   contradict it. A free period is not a maximum stay.
6. Do not change `ncp1-results.csv`. Report the verdict and let Ferro decide.

## File 4: the report

Write `ncp1-report.txt` in plain text. State these numbers.

- How many car parks the NCP finder listed, and how many have a London
  address.
- How many pages you opened, and how many loaded.
- The real time from the first fetch to the last fetch.
- How many rows state a price, and how many state nothing.
- Every blocked URL with its status.
- Any conflict you found between two NCP pages.
- Anything you judged rather than read.

Also write a page log, `ncp1-pagelog.csv`, with these columns.

`Ref,URL,Start (ISO),End (ISO),HTTP Status,Bytes,Note`

## Self-check before you send

Do not run `grok-import` over `ncp1-results.csv`. That importer matches rows
by Place ID, and these places have no Place ID yet, so it would reject every
row as an unknown identifier. That rejection would tell you nothing.

Check the value rules yourself instead, and report the counts.

1. Every value in a dropdown column is one of the allowed values above.
2. Every Tariff Detail matches the template for its Tariff Type, with two
   decimals and closed, ordered, touching bands.
3. No cell holds an en dash or an em dash.
4. Every row with Source Tier `None found` has Proposed Result `No evidence`,
   and no row with a loaded page uses `None found`.
5. Every row has a Researched Date and at least one Source URL, unless the
   page was blocked.
6. Every `Ref` value appears exactly once, and every `Ref` in
   `ncp1-results.csv` also appears as a `url` in `ncp1-places.csv`.

Report how many rows pass all six checks and list every row that fails one.

Ferro runs `grok-import` on its own side, after `db-create` assigns the Place
IDs. The database copy Ferro gave you is still useful for one thing: checking
whether a car park you found is already in the database. Report those matches
as information. Do not remove them from your files.

The copy goes stale after Ferro applies anything. Ask for a fresh snapshot
each day.

## Scope limits for this round

- NCP only. No other operator, no council list, no supermarket.
- London only. Leave a car park outside Greater London out of both files.
- Do not include a private, residents-only or permit-only space that no
  driver can enter. Record it in the report instead.
- Do not include on-street or kerbside bays. Ferro collects those separately.
- Keep your weekly usage under 60 percent. Report the usage at every save.

## What Ferro does with your files

For your understanding, so you know why the fields matter.

1. Ferro runs `discover --source generic` over `ncp1-places.csv`. It filters
   to London by borough polygon, deduplicates against the database by
   coordinates and name, and drafts the new places.
2. A person reviews the drafts. `db-create` then creates the accepted ones
   with identity only and never a parking answer, and it assigns each a
   Place ID.
3. Ferro maps your `Ref` values to those Place IDs and runs `grok-import`
   over `ncp1-results.csv`.
4. Rejected cells are dropped one cell at a time, not one batch at a time.
   Ferro sends you the rejects for a correction round.
5. Accepted rows reach the database through `db-apply`, with an undo saved.
   The owner then decides what reaches the public sheet.

---

# Round 1 correction, NCP

Ferro checked all 120 rows on 13 November. The mechanical checks pass. Every
`Ref` is unique and joins to a `url` in the places file in both directions,
every dropdown value is allowed, every Tariff Detail matches its template
with closed, ordered, touching bands, no cell holds an en dash or an em dash,
and every opening-hours string parses. The six priced rows were compared with
the raw tariff text in the places file and the prices are genuine.

One finding blocks the batch. 69 of the 120 postcodes are corrupted, for
example `WC2 N 4B` for WC2N 4BJ, `NW1 TJ`, `W6 J` and `W5 G`. The page log
says every page was "read in browser, text transcribed", so the transcription
step drops characters. That is not a partial postcode on the page, and it
means no field in this batch is reliable at character level until a second
reading confirms it.

Paste everything below the line into the master bot.

---

## NCP round 1: seven corrections

The mechanical checks all pass and the six priced rows are correct. Seven
items before Ferro accepts this batch. Keep the same file names with `-v2`
added, for example `ncp1-results-v2.csv`.

1. Stop transcribing by eye. 69 of your 120 postcodes lost characters, for
   example `WC2 N 4B` where the real postcode is WC2N 4BJ, and `W6 J` and
   `NW1 TJ`, which are not postcodes at all. The page log says every page was
   "read in browser, text transcribed". Read the page source instead of the
   rendered text, or copy the text into a file and extract the fields from
   that file. Then rebuild the address and postcode on all 120 rows.

2. Look for the structured data, and send it to us raw. NCP's pages very
   likely carry a `schema.org` block in the page source, usually
   `application/ld+json`, holding the name, the street address, the postcode
   and the latitude and longitude. Open one car park page first, search the
   source for `ld+json`, and report what it holds before you do the other
   122. You reported no coordinates, but you were reading the rendered text,
   where a map widget shows no numbers.

   If that block exists, add a fifth file, `ncp1-raw.jsonl`. Write one line
   per car park, as `{"url": "<the page URL>", "ldjson": <the block exactly
   as the page carries it>}`. Copy the block, do not retype it and do not
   tidy it. Ferro parses the address, the postcode and the position from
   that file with code, so no character can be lost on the way.

   If the block does not exist, write the page's visible text to
   `ncp1-raw.jsonl` instead, as `{"url": "...", "text": "<the page text>"}`,
   copied rather than retyped. Ferro extracts the fields here either way.

3. "Pay on the day" means paid. All 111 of your unpriced rows record a
   "Pay on the day" heading on the page, and some also list a season ticket
   price in pounds. A page that says you pay states the Cost Type even when
   it shows no rate. Set Cost Type to `Paid` and Price Status to
   `Not published` on those rows. Do not set a Tariff Detail.

4. Set Can Park? on the rows that publish opening times. 87 rows carry NCP
   opening hours on NCP's own car park page. A car park that NCP lists and
   gives opening times for is a car park a driver can use. Set Can Park? to
   `Yes` on those rows. Leave Who Can Park as it is unless the page states
   who may park.

5. Cover the whole sitemap. You picked 124 car parks out of 346 by reading
   their names, so a London car park with a name that does not sound like
   London is missing. Open all 346 pages, read the address on each, and keep
   every car park with a Greater London address. Report the new total and
   name every car park this step adds.

6. Quote the three rate tables in full. Rainham, Upminster and Dagenham Dock
   publish peak and weekend rates that fit no template. Copy the published
   rate text into Evidence Detail for those three rows, character for
   character, from the page source. Ferro needs the raw text to decide
   whether to add a template.

7. Explain the match rule. You report 104 of 120 already held, with 48
   matched on name and postcode. Say what rule matched the other 56, and
   list those 56 with the Place ID you matched each one to. Note that 69 of
   your postcodes were corrupted, so any match that used a postcode needs
   redoing after item 1.

Leave the 16 unmatched car parks as they are, including the 12 Heathrow
pages, Kings Cross, Victoria, Waterloo and Baynard House. Heathrow sits in
Hillingdon and is inside Greater London. Those 16 are the new places this
round found.

Keep every rule from the original brief. Silence is still not No, so a page
that says nothing about parking does not become `Can Park? No`. Report your
usage at each save.
