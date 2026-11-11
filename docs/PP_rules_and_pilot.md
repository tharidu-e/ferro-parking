# PP parking data: rules from the OSM pilot (2 Nov 2026)

## Pilot

- 10 route C rows in "ALL LONDON (clean)" written on 2026-11-02 (rows 698, 1111, 1278, 1303, 1363, 1395, 1447, 1591, 1881, 3491).
- Filter them with Verified By = "OSM script (pilot)" (OSM only) or "Deshan (pilot, manual check)" (sign photo checked by hand).
- All 10 have Review Flag "OSM pilot row: verify by hand" and Flag Status Open.
- Undo copy of the original values: pilot_undo.json (kept with the pilot files).
- Sheet changes made with the pilot: "OpenStreetMap" added to the Source Tier dropdown, "OpenStreetMap only" to Evidence Type, and the Confidence (1-5) formula now scores OpenStreetMap like Google Maps - About (25).

### Manual check results (Google Maps sign photos, 5 rows)

| Row | Place | Result |
|---|---|---|
| 698 | Sainsbury's Hornsey | Correct: 90 min max stay, camera enforced |
| 1111 | Tesco Hackney Morning Lane | Correct on all four: customers only, free, 1 hr, Horizon Parking. Sign (Sept 2022) also gives no return within 2 hrs, ANPR + patrols, PCN £70 |
| 1363 | Waitrose Nine Elms | Wrong max stay: OSM 120 mins, sign 60 mins |
| 1303 | Morrisons Southwark | Wrong operator: OSM "Morrisons", sign shows Euro Car Parks |
| 3491 | Currys Brentford | Can't tell (no sign visible) |

Of the checkable facts: 7 right, 2 wrong. Place matching was right on all 10.

## Rules

| # | Rule | Source |
|---|---|---|
| R1 | A store's car park is for its customers by default: supermarket, shop, retail park, fast food or gym = Customers only; hotel = Guests only; hospital = Patients and visitors. An official source saying otherwise wins. | Deshan; every checked store row |
| R2 | Parking signs do not expire: a sign photo of any age counts as current unless a newer source disagrees. Evidence Age still records the date. | Brandon: parking rules very rarely change |
| R3 | If OSM's operator tag is the store itself (Morrisons, Asda, M&S, McDonald's, Currys...), it is the landowner, not the parking company: Operator = Not published. | Morrisons Southwark was Euro Car Parks |
| R4 | An OSM max stay is never shown on its own: it goes to Notes until a sign photo, the store page or a chain rule confirms it. A wrong max stay gets drivers fined. | Waitrose Nine Elms: OSM 120, sign 60 |
| R5 | A readable sign photo beats OSM wherever they disagree. A blurry photo only supports the single fact it shows (e.g. operator). | Waitrose Nine Elms, Morrisons Southwark |
| R6 | Chain rules come only from finished rows with a strong, Site-specific source (1,115 rows), ignoring Unknown / Not applicable / Not published, and need 8+ rows at 80%+ agreement. Applied as chain policy (Specificity "Chain-wide"), never over site-specific evidence. Max stay is NEVER a chain rule: it varies by store (see below). | Chain analysis, 2 Nov 2026 |
| R7 | A mistake that costs the driver money or a fine needs stronger evidence than a cautious one. "Free" needs site-specific evidence: an official or operator page, a readable sign photo, or OSM fee=no on a store's customers-only car park (access=customers or destination). OSM fee=no on a public or untagged car park gives Cost Type Unknown. If a chain rule says Paid and OSM says free, Cost Type Unknown plus a Review Flag. "Anyone can park" and any max stay need a strong site-specific source. A chain rule or category default never makes a row Free or Anyone. Cautious values (Customers only, Guests only, Paid, Unknown) can come from weaker evidence. | Deshan, 2 Nov 2026 |
| R8 | Text PP already captured from an official page counts as evidence from that page. This applies to the "(as captured)" columns, Charges (as published), Enforcement Details and Notes. It was captured 30-31 Oct 2026. Rule R2 says parking rules rarely change, so this evidence stays current. Only text about this exact site is site-specific. Chain-wide policy text gives Specificity "Chain-wide" and Price Status "Chain policy (not store-specific)", and under R7 it never sets Free or a max stay. Text that reads "UNCLEAR", "not published", "not stated", "VERIFY" or "TBC" is not evidence for that value. TfL's own data counts as Source Tier "Operator / council site". When in doubt, leave the row for Grok. | Deshan, 3 Nov 2026 |
| R9 | Can Park? = No needs an explicit statement on the official page, such as "no car park", "no customer parking" or "parking not available". A page that does not mention parking at all is silence, not evidence of No. Capture shorthand such as "N/A on site" or "no parking facility listed" is also silence. It records the absence of a mention, not an explicit denial. Leave the row for Grok in both cases. | Deshan, 3 Nov 2026 |
| R10 | Every row gets an Evidence Level. "Verified" means evidence about this exact site. That evidence can come from an official page, the operator, a sign photo, captured page text, or OSM data for this site. Confidence (1-5) shows the strength of that evidence. "Chain policy" means the chain's published rule applied to a branch. "Presumed" means a category guess plus the map, with no page or sign read at all. Chain policy needs the branch format. Large formats (Tesco Superstore, Tesco Extra, Sainsbury's superstore, Lidl, Aldi, Asda, Morrisons) count as having a car park. Convenience formats (Express, Local, Metro, Little Waitrose, Simply Food, Co-op) count only if OSM maps a car park within 40 m of that branch. Chain policy and Presumed rows can only set cautious values. Allowed values are Who Can Park Customers only or Guests only, Cost Type Unknown or Paid, and Max Stay Not published. Put the typical chain rule in Notes, for example "Usually free for customers, max stay set per store, check signs." A Presumed "Can Park? = No" is allowed only for a small venue. Small venues are a cafe, a pub, a restaurant, a convenience shop, or fast food without a drive-thru. It also needs no OSM car park within 40 m. That row uses Evidence Level "Presumed" and Rules Summary "No parking listed (none mapped nearby). Check on arrival." | Deshan, 3 Nov 2026 |

## R6 chain rules found (chain_rules_candidates_v2.csv)

| Chain / group | Who Can Park | Cost Type | Operator |
|---|---|---|---|
| Tesco, Sainsbury's | Customers only | - | - |
| Asda | Customers only | Free | - |
| The Gym Group | Customers only | Free | - |
| PureGym | - | Free | - |
| Premier Inn, Travelodge | Guests only (80%) | - | - |
| Morrisons | - | - | Euro Car Parks (11 of 11; matches the Southwark sign) |
| Euro Car Parks, NCP sites | Anyone (paid) | Paid | Euro Car Parks / NCP |
| Council car parks (Bromley, Bexley, Croydon, Merton, Ealing, Brent, Greenwich, Kingston, City of London, Barnet, Enfield) | Anyone (paid) | Paid | the council |
| Harrow Council | Anyone (paid) | Free then paid | Harrow Council |
| Station car parks (National Rail, Southeastern, Southern, TfL) | Anyone (paid) | Paid | APCOA for National Rail (80%) and Southern (92%): treat as likely, not certain |
| Gatwick Airport | Anyone (paid) | Paid (86%) | Gatwick Airport Ltd |

Max stay spread proves it is store-specific: PureGym 90 to 240 mins, Morrisons 90 to 180, Richmond Council 120 to 1440. The earlier "Sainsbury's = 120 mins (95%)" disappeared once chain-wide-sourced rows were excluded: it was the chain policy page repeated, and Sainsbury's Hornsey's sign says 90.

Under R7, the Free and Anyone (paid) entries above are hints only: they go in Notes and never set Cost Type = Free or Who Can Park = Anyone on their own.

R1, R3 and R4 are built into osm_parking_match.py (packet suggestions). R5 and R6 belong in the rules engine (Stage 3 of PP_architecture_OSM_first.md).

## What manual checking showed

- Street View rarely shows signs at readable size; Google Maps Photos of the car park sign are the best manual source (about 5 minutes per row).
- Sign photos give far more than OSM (no-return rules, enforcement type, PCN amount, Blue Badge rules), so a sampled manual check (or a vision model reading sign photos) is the quality gate, not OSM alone.


## Cell and publication controls

These controls override weaker historical examples above. Read this section before preparing any data plan.

- Find sheet columns by header text in row 1, never by letter or position. Match rows by Place ID, never by row number.
- Protected columns, never in any plan: Postcode Area, Confidence (1-5), Free Stay Countdown (mins), Ferro Autopay, Parking Charge (£), Total incl. Ferro Fee (£), Captured By, Date Captured, Latitude, Longitude, Place ID, every column ending "(as captured)", Charges (as published), Enforcement Details.
- A filled Verification Result means the row is finished. Never fill it just to mark progress, and never change finished rows or rows whose Verified By is a person's name.
- Dropdown columns take only their exact allowed values.
- No en dashes or em dashes in any cell, file or message. Use a plain hyphen.
- Tariff Detail templates, prices always with £ and two decimals: `Free` / `Free for up to 2 hrs` / `Free for 30 mins, then £1.00 per hour` / `£1.30 per hour` / `£18.00 per 24 hours` / `£15.00 per night` / bands `0-2 hrs £5.00; 2-3 hrs £6.50` (closed ranges only) / `Not published` / `Not applicable`.
- "Free", Can Park? "Yes" and Who Can Park "Anyone" / "Anyone (paid)" need a strong source for that exact site: official branch page, operator or council page, or a readable sign photo. Never from chain-wide text, reviews, forums, Parkopedia or booking listings (YourParkingSpace, JustPark).
- Can Park? "No" needs an explicit statement that the site has no car park. Silence is not No.
- A max stay is never copied from another branch or a chain-wide page.

The original ALL LONDON tab stays read-only. New columns go only at the end.
Every Sheet change needs plan.json, dry_run.csv and undo.json in a fresh run folder.
Run the existing six checks and independent second reading. Show counts, samples and rejects, then wait for the owner's explicit go.
Use the existing writer. Write Verification Result last, then independently re-export and require zero mismatches.
Stop on any mismatch. Keep the undo and comparison artifacts.
