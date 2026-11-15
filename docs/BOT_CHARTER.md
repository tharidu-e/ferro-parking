# Bot charter, draft

Started 15 November 2026. This file holds the rules the bots run on, one
section per settled decision. It is a draft. Dr Eggbot reviews it, Claude
finalizes it, and then the bots run on it.

Read `docs/LAUNCH_PLAN.md` for the round loop and the stop rules. This file
never repeats a rule table from the repository, because a copy drifts from the
original. It states decisions and limits only.

Status: questions 1 to 4 settled. Open questions are at the end.

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
this bar in code, and `docs/LAUNCH_PLAN.md` section 5 states it.

Fill every field the page states on one visit. The fields are Can Park?, Who
Can Park, Cost Type, Price Status, Tariff Type, Tariff Detail, Max Stay (mins),
Hours, Operator, PCN amount and Rules Summary. Do not return for one field
later.

## 2. How a bot writes to the sheet, settled 15 November 2026

A bot writes parking answers into the tab "ALL LONDON (clean)" itself. Two
limits apply, and three layers hold each limit.

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

- Write the round name into Decision Reason on every row you touch, for example
  `centres1`.
- Keep a round log. One line per row, with the Place ID, the column, the old
  value, the new value and the time in GMT. Report the first and last write
  time of the round.
- Ferro compares the sheet's changed cells with the round log after the round.
  A changed answer cell with no round name is a write nobody claimed, and it is
  reported.

A round is then reversible three ways: the sheet version history pinned to the
round window, the import diff, and the round log's old values.

### The bot that researches a row never signs it off

The checking bot re-reads the saved pages, never the live site. Where the two
bots disagree, hold the row and name it in the report.

Reason, from 15 November. PP met a challenge page that returned HTTP 200, so
its detector missed the block and six more pages went out. The self check then
printed "64 rows checked, 0 problems", because that script reads format and
never asks whether the page was real.

Treat a page as blocked when the body carries challenge text, whatever the HTTP
code. Search for "One moment", "Just a moment", "Enable JavaScript",
"Attention Required" and "you have been blocked". Stop on the first match.

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
| Hospital, school, parks and the rest | 679 | 496 | 158 |

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
- "Anyone (paid)" needs a price published on that car park's own page.
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

A page is blocked when its body carries challenge text, whatever the HTTP code.
Search for "One moment", "Just a moment", "Enable JavaScript", "Attention
Required" and "you have been blocked". HTTP 200 is not proof that a page
loaded.

### What a round returns

- The results file, one row per Ref, including every Ref that returned nothing.
- The raw page data for every page opened, source and rendered text.
- The page log, one line per address with the time and the status.
- A report: pages opened, rows with a value, rows with nothing, blocked
  addresses, conflicts, and any car park found that is not in the queue.

## Open questions

5. Which parts of the checking work Dr Eggbot owns.
6. What happens to a place whose answer needs an on-site check, because 1,430
   places now wait on one.
