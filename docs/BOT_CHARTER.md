# Bot charter, draft

Started 15 November 2026. This file holds the rules the bots run on, one
section per settled decision. It is a draft. Dr Eggbot reviews it, Claude
finalizes it, and then the bots run on it.

The bots cannot reach this project's repository, so this file never sends them
to another file in it. Everything a bot must obey is written here. Ferro keeps
`docs/LAUNCH_PLAN.md` for its own side of the work.

Status: questions 1 to 4 settled, and Dr Eggbot's first review is applied.
Open questions are at the end.

## 1. What a driver sees, settled 15 November 2026

A place is showable when three things are true.

1. Can Park? reads Yes or Conditional.
2. The place has a usable pin.
3. Who Can Park is known.

Hours and price are not required. The app shows them where we know them. The
app writes "hours not published" or "price not published" where we do not.

Can Park? and Who Can Park are two different answers. Can Park? says whether a
driver can park at all. Who Can Park says which drivers may park, for example
Customers only or Permit holders. A place needs both before it shows.

3,158 places pass this bar on the 15 November export. 800 of them carry known
hours, 1,619 a known Cost Type and 308 a known Max Stay. `readiness.bars` holds
this bar in code on Ferro's side.

Fill every field the page states on one visit. The fields are Can Park?, Who
Can Park, Cost Type, Price Status, Tariff Type, Tariff Detail, Max Stay (mins),
Hours, Operator, PCN amount and Rules Summary. Do not return for one field
later.

## 2. How a bot writes to the sheet, settled 15 November 2026

A bot writes parking answers into the tab "ALL LONDON (clean)" itself. Three
limits apply. Three layers hold each of the first two: the sheet, the bot, and
a check by Ferro after the round.

### Limit 1: answer columns only, never identity

Identity is the name, the street address, the postcode and the coordinate.

- The sheet holds this limit. Each bot gets its own Google account with editor
  access. The identity and payment columns stay protected ranges that only the
  owner edits. A bot write to an identity column fails at the API.
- The bot holds this limit too. Read the header row before any write. Match
  every target column against a fixed allowlist. If one column is not on the
  list, stop the whole write and report it.
- Ferro detects a breach. After each round, `db-import` reports changed cells
  and Place ID changes, so a moved identity cell is named in the report.

Example of why. On 15 November, PP read The Market Place's own site, which
gives 12 Myrtle Road, E6 1HU. Our pin sits 9 m from E6 1HJ and about 47 m from
E6 1HU. A bot with identity access would have replaced a pin-matched postcode
with a worse one. The site's postal address belongs in Notes.

### Limit 2: every write carries its round name

- Stamp the round in Decision Reason, but only on a row that gained a value and
  only where that cell is blank. Write it as "Route: <round>", for example
  "Route: hospital1". The word Route is required, because `page_fill` refuses a
  Decision Reason without it. Where the cell already holds text, leave it: the
  round log and the write time carry the attribution.
- Keep a round log. One line per row, with the Place ID, the column, the old
  value, the new value and the time in GMT. Report the first and last write
  time of the round.
- Ferro compares the sheet's changed cells with the round log after the round.
  A changed answer cell with no round name is a write nobody claimed, and it is
  reported.

A round is then reversible three ways: the sheet version history pinned to the
round window, the import diff, and the round log's old values.

### Limit 3: the row rules

- Address a row by its Place ID only. Never by its sheet row number, its name
  or its address, because a row moves and a name repeats.
- Never overwrite a cell that already holds a value. Fill a blank cell, or a
  cell that reads Unknown or Not yet checked, and leave every other cell as it
  stands. A stronger source does not change this: report the conflict instead.
- Never add a row and never delete a row. A place the sheet does not hold goes
  in the tab "NEW PLACE CANDIDATES". Ferro creates the row and the Place ID.
- Run `python3 bot_self_check.py results.csv` on the result before you send it,
  and send only when it exits 0. It checks the dropdown values, the tariff
  strings, the opening-hours strings and the rule pairs.
- Then build a copy of the database from the snapshot Ferro sends that day and
  run `grok-import` against that copy. Report the three numbers it prints.
  The snapshot must be the full 66-column export, not an identity-only file.

### The bot that researches a row never signs it off

The checking bot re-reads the saved pages, never the live site. Where the two
bots disagree, hold the row and name it in the report.

Reason, from 15 November. PP met a challenge page that returned HTTP 200, so
its detector missed the block and six more pages went out. The self check then
printed "64 rows checked, 0 problems", because that script reads format and
never asks whether the page was real.

Treat a page as blocked by the rule in section 4, under "Pace and blocks".
Stop on the first real block.

## 3. Order of work, settled 15 November 2026

Fill the missing values on places we already hold. Then work category by
category. The owner set that order.

Measured on the 15 November export, most missing values have no publisher, so
the round is small. State these numbers before promising a fill.

- 2,358 showable places have unknown hours. 1,841 of them already record Hours
  "Not published" against a source that was read. A reread returns nothing.
- 1,773 places sit one cell from showable. 1,734 already carry a source URL,
  787 read "No evidence", 387 need an on-site check, and 1,190 are private or
  operator car parks, which publish nothing.
- Code can fill small slices today: 16 pins from a postcode, and 38 Who Can
  Park cells where the place is paid, publishes a tariff and names an operator.

So a missing-value round runs only against a cell that no source was ever asked
for. A cell already answered "Not published" is finished, and only an on-site
check can change it.

One fill must come first, because the category plan depends on it. 2,420 rows
have a blank Place Category. A row with no category cannot join a category
round. OpenStreetMap gives the venue kind for those rows, so Ferro proposes a
category per row by code, with no bot. The owner reviews that proposal.

## 4. The job, all of London

The job is every place in London where a driver can park, with the parking
answer a driver needs. The sheet holds 11,562 places on 15 November 2026, and
3,158 of them are showable. The rest of this section states the work that
remains, category by category.

### What earns a row

A place earns a row when a named source states that it exists and a driver can
park there. A place we examined and found no parking at also earns a row, so
nobody researches it twice.

These do not earn a row: a place with no parking space, a private, residents
only or permit only space, an on-street or kerbside bay, a pre-book only car
park, a meet and greet bay, and a perimeter hotel car park, which stays a hotel
record.

### The categories, and the gap in each

"Gap" counts the rows that are not showable and that do not already read "No
evidence". Measured on 15 November 2026.

| Category | Rows | Showable | Gap |
|---|---:|---:|---:|
| Private / operator car park | 4,683 | 586 | 1,185 |
| Supermarket - convenience | 1,051 | 277 | 751 |
| Station | 841 | 130 | 562 |
| Supermarket - large format | 954 | 393 | 557 |
| Fast food / drive-thru | 570 | 96 | 474 |
| Hotel | 558 | 182 | 376 |
| Gym / leisure centre | 488 | 144 | 342 |
| Other | 446 | 158 | 275 |
| Retail warehouse / DIY / trade | 325 | 73 | 189 |
| Petrol station | 610 | 459 | 145 |
| Hospital / health centre | 236 | 140 | 95 |
| Shopping centre | 121 | 44 | 76 |
| Council car park | 476 | 411 | 48 |
| School, parks and the rest | 203 | 65 | 110 |
| Total | 11,562 | 3,158 | 5,185 |

### The order of the rounds

Run a category when a source publishes its parking answers. Run these in order.

1. Hospitals. 95 rows. Trust and hospital pages state visitor parking.
2. Hotels. 376 rows. A hotel's own page states parking for guests.
3. Shopping centres, second pass. 76 rows, after the first pass returned 7 of
   64, with a named source for each centre instead of a guessed domain.
4. Stations. 562 rows. The operator pages, not the aggregators.
5. Gyms and leisure centres. 342 rows. Better, PureGym and The Gym Group have
   readers already, so Ferro runs those and the bot takes the rest.
6. Large-format supermarkets. 557 rows. The chain sites do not state parking
   for one named store, so this round needs a source decision first.
7. Private and operator car parks. 1,185 rows, the largest and the hardest.
   Take them operator by operator, as the NCP rounds did, never one by one.
8. Convenience supermarkets, fast food and petrol stations last. Their chain
   sites are measured dead, and a driver rarely searches for them.

### The fields, every round

Fill all of these that the page states, on one visit.

Can Park?, Who Can Park, Cost Type, Price Status, Tariff Type, Tariff Detail,
Max Stay (mins), Hours, Operator, PCN amount and Rules Summary.

Rules for the values.

- Fill only what the page states. Everything else stays Unknown or Not
  published.
- Take on-the-day and hourly rates. Never a pre-book price.
- Never read Who Can Park from a price. A page that states a tariff says what
  parking costs, not who may park. On 15 November four hospital rows read
  "Anyone (paid)" from a line like "Parking costs £3 for up to four hours",
  and a hospital car park is for patients and visitors.
  Take Who Can Park from an access statement only: "visitor car park",
  "customers only", "permit holders", "open to the public". Where the page
  states a price and no access rule, Who Can Park stays Unknown and Cost Type
  reads Paid.

  One widening, settled 16 November 2026, because the rule as first written
  held 814 places that a driver could use. A venue's own page that lists a car
  park among its facilities states who it is for, by being that venue's page.
  A store page gives "Customers only", a hotel page gives "Guests only", and a
  gym or leisure centre page gives "Customers only". Record those with
  Evidence Level "Chain policy", never "Verified", so the weaker basis stays
  visible and can be filtered or reversed later.

  Still not enough on its own: a price, a photograph, a map entry, and a page
  for a different site in the same retail park.

  An operator car park whose own page says a driver may arrive and pay, for
  example "first come first served" with "payment must be made upon arrival",
  is "Anyone (paid)" with Evidence Level "Verified". Arriving and paying is
  an access statement, not a price.
- One field per cell. Never join hours and rates in one cell.
- A price that fits no tariff template goes in Rules Summary, word for word.
- A blank day is not an opening time. If a page lists closed days and leaves
  the rest blank, Can Park? is Unknown and the row needs an on-site check.
- Do not set Location Status unless the page states that the place is closed.
- Report a conflict between two pages of one site. Record both values and pick
  neither.

### Sources

One named source per round: an operator's site list, a council inventory, a
chain's store list, or a venue's own page.

Before the round, open three pages of that source and say which of the fields
above it publishes. If the three pages publish none of them, the round does
not run. A count of blank cells is not a reason to run a round. The shopping
centre round of 15 November returned 7 rows of 64 because this check was
skipped.

A chain's store list and a chain's parking statement are two different uses of
one website. A store list can give the denominator even where the same site
never states parking.

### Pace and blocks

One page every 3 seconds. 25 seconds for a site that challenges us. Stop at the
first block, name the blocked address, and do not retry it.

A page is blocked when its rendered text carries challenge text, whatever the
HTTP code. HTTP 200 is not proof that a page loaded.

The phrases are "One moment", "Just a moment", "Attention Required" and "you
have been blocked". Search the rendered text only, never the HTML source. A
match counts as a block only when the rendered text is under 500 characters, or
the phrase is in the page title, because a challenge page is short and says so
in its title.

"Enable JavaScript" is not a block phrase. On 15 November it stopped the
hospital round at a contact form whose hidden fallback notice carried that
line, and 14 rows went unread.

### What a round returns

- The results file, one row per Ref, including every Ref that returned nothing.
- The raw page data for every page opened, source and rendered text.
- The page log, one line per address with the time and the status.
- A report: pages opened, rows with a value, rows with nothing, blocked
  addresses, conflicts, and any car park found that is not in the queue.

## 5. The write path, settled 15 November 2026

A bot never writes a cell by hand or by its own judgment. It runs one script,
`sheet_write.py`, and that script holds the guards.

- It reads the live cell immediately before writing, and writes only when that
  cell is blank, "Unknown" or "Not yet checked". An answer is never replaced.
- It refuses every identity and payment column outright, whatever the brief
  says. The sheet's protected ranges are the first layer and this is the
  second.
- It refuses a Place ID that is not in the round's queue.
- It stops the whole round when the plan is larger than `--max-cells`.
- It appends one line per write to the round log: round, Place ID, column, old
  value, new value, time, URL and quote.

Run it without `--apply` first. It plans, prints the counts and writes nothing.

`sheet_undo.py` undoes one round from that log. It restores a cell only when
the cell still holds what the round wrote, so a cell somebody changed since is
left alone and reported. The sheet's version history cannot do this, because it
restores the whole sheet to a moment and wipes everything written since.

`bot_self_check.py` runs before the writer, and it now holds every rule the old
importer held, so the two can no longer disagree about the same row.

The checking bot draws its sample at random with a seed, and the seed goes in
the round log, so nobody can pick the easy rows.

New places take a block of Place IDs reserved before the round starts, for
example PP-013000 to PP-013499, so two bots can never invent the same ID.

## 6. The round loop and the stop rules

One source per round. Follow these steps in order.

1. Name the source.
2. Run the three-page source check. Say which fields those pages publish.
3. Ferro runs the yield test and says whether the round runs.
4. Fetch at the stated pace, save every page, stop at the first block.
5. Fill only what the page states.
6. Run the self check, then the database copy check.
7. Write the answers to the sheet, with the round name in Decision Reason.
8. The checking bot re-reads the saved pages for 15 to 20 percent of the rows,
   and for the judgment cells only, which are Can Park?, Who Can Park and the
   tariff reading. If that sample needs a fix on more than 5 percent of rows,
   run a full pass.
9. Ferro rebuilds the database from the sheet and reports the counts.

Stop and ask the owner when any of these happen.

- The site blocks us.
- A page contradicts itself or another page of the same site. Record both
  values and pick neither.
- A write would change a filled cell, or a cell a person checked.
- The source turns out to publish nothing we need, which ends the round.

## Open questions

7. Which parts of the checking work Dr Eggbot owns.
8. What happens to a place whose answer needs an on-site check, because 1,430
   places now wait on one.
