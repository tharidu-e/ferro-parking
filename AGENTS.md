# AGENTS.md: house rules for any coding agent in this repo

This repo is `ferro_parking`, the parking data pipeline for Ferro Maps, a London app for drivers. It reads and writes the Google Sheet "PP Parking places" (https://docs.google.com/spreadsheets/d/1VHtzY1001e0aRSXE6s_-IJU9YioJtjSNZ5WCOt1IO-o/edit) through the Google Sheets API. Wrong data costs real drivers fines or overcharges, so safety beats speed.

## Never without the owner's explicit "go"

- Never write to, append to, delete from, sort or reorder anything in the Google Sheet.
- Never delete files, rewrite git history, force-push, or overwrite anything under `data/runs/`.
- Never print, copy or commit credentials (service account JSON, tokens, `.env`).

## How every sheet change is made

1. Build a dry run: `plan.json`, `dry_run.csv` and `undo.json` in a new folder `data/runs/<YYYY-MM-DD>/<task_name>/`.
2. Run the existing six checks plus the independent second reading on the plan.
3. Show the owner counts, samples and any rejects. Stop and wait for "go".
4. Apply with the existing writer, then run the independent re-export compare. It must show 0 mismatches.

Reuse the existing modules (writer, checks, second reading, re-export compare, policy fill, OSM match). Do not write a parallel version of something that exists. Read `docs/HANDOVER.md` and the `src/ferro_parking/` modules before changing anything.

## Data rules

- Find sheet columns by header text in row 1, never by letter or position. Match rows by Place ID, never by row number.
- Protected columns, never in any plan: Postcode Area, Confidence (1-5), Free Stay Countdown (mins), Ferro Autopay, Parking Charge (£), Total incl. Ferro Fee (£), Captured By, Date Captured, Latitude, Longitude, Place ID, every column ending "(as captured)", Charges (as published), Enforcement Details.
- A filled Verification Result means the row is finished. Never fill it just to mark progress, and never change finished rows or rows whose Verified By is a person's name.
- Dropdown columns take only their exact allowed values.
- No en dashes or em dashes in any cell, file or message. Use a plain hyphen.
- Tariff Detail templates, prices always with £ and two decimals: `Free` / `Free for up to 2 hrs` / `Free for 30 mins, then £1.00 per hour` / `£1.30 per hour` / `£18.00 per 24 hours` / `£15.00 per night` / bands `0-2 hrs £5.00; 2-3 hrs £6.50` (closed ranges only) / `Not published` / `Not applicable`.
- "Free", Can Park? "Yes" and Who Can Park "Anyone" / "Anyone (paid)" need a strong source for that exact site: official branch page, operator or council page, or a readable sign photo. Never from chain-wide text, reviews, forums, Parkopedia or booking listings (YourParkingSpace, JustPark).
- Can Park? "No" needs an explicit statement that the site has no car park. Silence is not No.
- A max stay is never copied from another branch or a chain-wide page.

## Code rules

- Fix bugs at the root in the package, with a regression test. No one-off edits of output files.
- All tests must pass before you report done. Add tests for every new rule.
- Commit each finished task as its own commit with a clear message.
- When you finish, give a file-by-file summary of everything created or changed.