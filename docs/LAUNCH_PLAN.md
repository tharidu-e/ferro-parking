# December launch plan

Written 15 November 2026. This file owns the process we agreed with the owner
on 14 and 15 November. It replaces the parts of `docs/PLAN.md` that describe
the database as the store and the bots as research helpers. Read it before you
start a bot round. `docs/STATUS.md` still owns the counts.

## 1. Decisions that are now fixed

1. The Google Sheet tab "ALL LONDON (clean)" is the one store. Every other
   copy is derived from it.
2. The local SQLite database is a read-only mirror. Rebuild it from the sheet
   after every write, with `db-import`, so the two cannot drift.
3. Bot result files and saved pages are inputs. They are never a store.
4. The bots write parking answers. The bots never write identity. Identity is
   the name, the address, the postcode and the coordinate.
5. Code fills identity here, from the coordinate, the OpenStreetMap extract
   and postcodes.io. No bot opens a page for identity.
6. A derived postcode lives in its own column, "Postcode (derived from pin)",
   with its distance in "Pin to postcode distance (m)". It never feeds a match
   rule and it never feeds a duplicate check.
7. OpenStreetMap tags fill only cautious values. `fee=yes` gives Cost Type
   "Paid". `access=customers` gives Who Can Park "Customers only". `fee=no`
   never gives "Free" and `access=yes` never gives "Anyone".
8. Airport places use the Place Type column, with four values: Car park,
   Drop-off zone, Pick-up area, Holding area. A drop-off zone reads Can Park?
   "No", because our dropdown has no "stopping only" value. The stopping rule
   goes in Rules Summary.
9. Three more airport columns exist: Terminal, Penalty Note and Entry Note.
10. The bot never decides what exists. A named source states that a place
    exists, and the bot reads that source.

## 2. The bot loop, one round

Follow these steps in order. One source per round.

1. Name the source. Examples: an airport's own parking pages, a council
   inventory, an operator's site list.
2. Run the yield test before any fetch. Match the source's page list against
   the rows we hold. Count the cells that are Unknown today and that this
   source can fill. If the count is below 0.5 new cells per page, do not run
   the round.
3. Run the source check. Open three pages and make sure that the fields you
   need are in the page's own data. The NCP round failed this test late, after
   346 pages.
4. Fetch. Open pages at a fixed spacing, at least 3 seconds apart. Use 25
   seconds for a site that challenges us. Save every page. Stop at the first
   block, name the blocked address, and do not retry.
5. Fill only what the page states. A detail the page does not state stays
   Unknown or Not published.
6. Run `tools/bot_self_check.py` on the result before writing. Copy that one
   file to the bot's computer and run `python3 bot_self_check.py results.csv`.
   It checks the dropdown values, the tariff strings, the opening-hours
   strings and the rule pairs. Send the file only when it exits 0.
7. Write the answers to the sheet.
8. Check a sample. The checking bot re-reads the saved pages, never the live
   site, for 15 to 20 percent of the rows, and only for the judgment cells,
   which are Can Park?, Who Can Park and the tariff reading. If that sample
   needs a fix on more than 5 percent of rows, run a full pass.
9. Rebuild the database from the sheet and record the round in STATUS.md.

## 3. Rules the bot must follow

- Return the page, not typed fields. We parse the fields here.
- One field for each evidence cell. Never join hours and rates into one cell.
- A blank day is not an opening time. If a page lists closed days and leaves
  the rest blank, Can Park? reads "Unknown". The row then needs an on-site check.
- A price that fits no tariff template goes in Rules Summary, word for word.
- "Anyone (paid)" needs a price published on that car park's own page.
- Do not report Location Status unless the page states that the place is closed
  or temporarily closed.
- Take on-the-day and hourly rates. Never take a pre-book price, because it
  changes by date and it is not a tariff.

## 4. Order of work

1. Airports, by hand, from each airport's own pages. Heathrow is done. Gatwick,
   Stansted, Luton and London City follow.
2. Council car parks, which are 406 showable of 476 already.
3. Stations.
4. Large-format supermarkets and shopping centres, where identity now allows a
   source to be chosen.
5. Everything else, after launch.

## 5. What a driver sees at launch

A row is showable when Can Park? is Yes or Conditional, the place has a usable
pin, Who Can Park is known, and the hours are known. A published price is not
required. A row with Price Status "Not published" still helps a driver.
Every other row is hidden from drivers. Hidden is not deleted. A "No evidence"
row stops anyone researching that place twice.

## 6. Airport places: what earns a row

Earns a row: the short stay car park at each terminal, the drop-off zone at
each terminal, the private hire holding area, and any official free waiting
area. A long stay car park earns a row when it takes drive-up cars at a
published rate.

Does not earn a row: a pre-book-only car park, a meet-and-greet bay, and a
perimeter hotel car park. A hotel car park stays a Hotel record.

## 7. Stop rules

Stop and ask the owner when any of these happen.

- The site blocks us.
- A page contradicts itself or another page of the same site. Record both
  values and pick neither.
- A write would change a finished row's existing answer, or a cell a person
  checked.
- A source turns out to publish nothing we need, which ends the round.

## 8. Who does what

- The writing bot reads sources and writes parking answers.
- The checking bot re-reads saved pages for the sample.
- Claude fills identity, runs the yield test, writes airport rows by hand,
  rebuilds the database and reports the counts.
- The owner approves a new source, a scope change and any deletion.

## 10. What a bot may write in the sheet

This is the write contract. It was closed on 15 November.

1. A bot addresses a row by its Place ID and by nothing else. A bot never
   matches on a name, an address or a postcode.
2. A bot writes only these columns: Can Park? (Yes/No/Conditional), Who Can
   Park, Location Status, Rules Summary, Cost Type, Price Status, Tariff Type,
   Tariff Detail, Max Stay (mins), Hours, Hours Basis, Parking Control Type,
   Operator, PCN amount, Evidence Type, Evidence Detail, Source URLs, Source
   Tier, Specificity, Rules Stated, Prices Stated, Evidence Age, Agreeing
   Sources, Conflict, Evidence Level, Notes, Review Flag, Decision Reason,
   Verification Result, Verified By, Verified Date, Place Type, Terminal,
   Penalty Note and Entry Note.
3. A bot never writes identity: Location Name, Brand, Place Category, Street
   Address, Postcode, Borough, Latitude, Longitude, the Geo columns, Place ID,
   OSM ID and the two derived postcode columns. The sheet now protects those
   columns, so an attempted write fails.
4. A bot never writes the payment columns: Ferro Autopay, Parking Charge and
   Total incl. Ferro Fee. The sheet protects those too.
5. A bot never adds a row and never deletes a row.
6. A bot never changes a cell that already holds a value, unless the owner
   asked for that row to be re-researched. It fills empty cells and cells that
   read Unknown.
7. A place the sheet does not hold goes in the "NEW PLACE CANDIDATES" tab, one
   row per place, with the source and the evidence sentence. Ferro reviews that
   tab, creates the row and assigns the Place ID.
8. After each round, Ferro rebuilds the database from the sheet and compares
   the two. A change outside this contract is reverted from the sheet's own
   version history.

## 11. Still open

- Gatwick, Stansted and Luton sit outside Greater London. The owner accepted
  them for the airport round. No other place outside Greater London is in scope.
- The bot self-check is `tools/bot_self_check.py`. It is written and tested.
  Send it to the bot's computer before the next round.
- The United Kingdom outside London is a scope decision for after launch.
