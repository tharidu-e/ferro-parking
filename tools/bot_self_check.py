#!/usr/bin/env python3
"""Check a bot results file before it reaches the sheet.

One file, standard library only. Copy it to the bot's computer and run:

    python3 bot_self_check.py results.csv
    python3 bot_self_check.py results.csv live.csv

The second form reads a fresh export of the tab as well, and checks each row
as it will read after the write. A blank cell in the results file means "keep
the sheet's value", so use this form whenever the export is to hand.

It prints one line per problem and exits 1 when anything is wrong. Fix every
line, run it again, and only send the file when it exits 0.

    python3 bot_self_check.py --demo     runs the file's own checks

Column names may be the short bot names ("Can Park?", "Proposed Result") or the
full sheet names ("Can Park? (Yes/No/Conditional)", "Verification Result").
"""
import csv
import re
import sys

ALIASES = {
    "Can Park?": "Can Park? (Yes/No/Conditional)",
    "Proposed Result": "Verification Result",
    "Hours": "Hours (OpenStreetMap opening_hours format)",
    "Parking Control Type": "Parking Control Type (Cameras / Barrier / Patrol)",
    "PCN amount (£)": "PCN (Penalty Charge Notice) amount (£)",
    "Evidence Detail": "Evidence Detail (what the source shows)",
    "Source URLs": "Source URLs (primary first)",
    "Researched Date": "Verified Date",
}

DROPDOWNS = {
    "Can Park? (Yes/No/Conditional)": ["Conditional", "No", "Unknown", "Yes"],
    "Who Can Park": ["Anyone", "Anyone (paid)", "Customers only", "Guests only",
                     "Not applicable", "Patients and visitors", "Permit holders", "Unknown"],
    "Cost Type": ["Free", "Free then paid", "Not applicable", "Paid", "Unknown"],
    "Tariff Type": ["Banded by stay length", "Flat rate per 24 hours", "Flat rate per entry",
                    "Flat rate per night", "Free (time limit not published)",
                    "Free period, then hourly", "Free with time limit", "Hourly rate",
                    "Not applicable", "Not published"],
    "Price Status": ["Published", "Not published", "Chain policy (not store-specific)",
                     "Not applicable"],
    "Parking Control Type (Cameras / Barrier / Patrol)": [
        "ANPR (Automatic Number Plate Recognition) camera", "Barrier", "Not applicable",
        "Not published", "Patrol", "Pay and display"],
    "Hours Basis": ["Car park hours", "Not applicable", "Not published", "Site hours",
                    "Store hours"],
    "Verification Result": ["Confirmed", "Confirmed, details not published",
                            "Needs on-site check", "No evidence"],
    "Specificity": ["Site-specific", "Chain-wide", "Area only"],
    "Evidence Level": ["Verified", "Chain policy", "Presumed"],
    "Location Status": ["Open", "Temporarily closed", "Closed", "Unknown"],
    "Place Type": ["Car park", "Drop-off zone", "Pick-up area", "Holding area"],
    "Rules Stated": ["Yes", "No"],
    "Prices Stated": ["Yes", "No"],
    "Conflict": ["Yes", "No"],
    "Evidence Age": ["Under 12 months", "1-2 years", "Older or undated"],
}

# An answer column. A row with one of these filled writes to the sheet, so it
# carries the round stamp. Bookkeeping columns alone do not.
STAMPED_COLUMNS = (
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type", "Price Status",
    "Tariff Type", "Tariff Detail", "Max Stay (mins)",
    "Hours (OpenStreetMap opening_hours format)", "Hours Basis", "Operator",
    "PCN (Penalty Charge Notice) amount (£)", "Rules Summary", "Location Status",
    "Parking Control Type (Cameras / Barrier / Patrol)", "Verification Result",
)

STRONG_SOURCE_TIERS = {"Official site - text", "Operator / council site",
                       "Official site - logo or icon", "Google Maps - tariff photo"}

MONEY = r"£\d+\.\d{2}"
BAND = rf"(\d+)-(\d+) (hrs|mins) ({MONEY})"
TARIFF_PATTERNS = {
    "Free (time limit not published)": r"Free",
    "Free with time limit": r"Free for up to \d+ (?:hrs|mins)",
    "Free period, then hourly": rf"Free for \d+ mins, then {MONEY} per hour",
    "Hourly rate": rf"{MONEY} per hour",
    "Flat rate per 24 hours": rf"{MONEY} per 24 hours",
    "Flat rate per night": rf"{MONEY} per night",
    "Flat rate per entry": rf"{MONEY} per entry",
    "Banded by stay length": rf"{BAND}(?:; {BAND})*",
    "Not published": r"Not published",
    "Not applicable": r"Not applicable",
}

DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)"
DAYS = rf"{DAY}(?:-{DAY})?(?:,{DAY}(?:-{DAY})?)*"
TIME = r"(?:[01]\d|2[0-3]):[0-5]\d|24:00|sunrise|sunset"
SPAN = rf"(?:{TIME})-(?:{TIME})"
RULE = rf"(?:{DAYS} )?(?:{SPAN}(?:,{SPAN})*|off|closed)"
HOURS = rf"(?:24/7|{RULE}(?:; {RULE})*)"


def tariff_valid(kind, detail):
    """True when the detail matches its type's template, bands included."""
    if not re.fullmatch(TARIFF_PATTERNS.get(kind, r"(?!)"), detail):
        return False
    if kind == "Banded by stay length":
        found = re.findall(r"(\d+)-(\d+) (hrs|mins)", detail)
        if len({unit for _, _, unit in found}) > 1:
            return False
        bands = [(int(a), int(b)) for a, b, _ in found]
        return (all(a < b for a, b in bands)
                and all(bands[i][1] == bands[i + 1][0] for i in range(len(bands) - 1)))
    return True


def hours_valid(text):
    return bool(re.fullmatch(HOURS, text))


def normalise(row):
    out = {}
    for key, value in row.items():
        out[ALIASES.get((key or "").strip(), (key or "").strip())] = (value or "").strip()
    return out


def max_stay_strong(value):
    """True when Max Stay states a real limit, which needs strong evidence."""
    return bool(value) and value not in ("Not published", "Not applicable")


def check_row(row, context=None):
    """Problems with one normalised row.

    `row` is what this round writes. `context` is that row merged onto the
    sheet's own row, so a rule that asks "is this value known" sees the cell
    the round is keeping. A rule about what the round wrote reads `row`, never
    the context: the sheet holds old en dashes that this round never typed."""
    problems = []
    merged = {**(context or {}), **{k: v for k, v in row.items() if v}}
    get = merged.get

    for column, allowed in DROPDOWNS.items():
        value = get(column, "")
        if value and value not in allowed:
            problems.append(f'{column} is "{value}", which is not an allowed value')

    kind, detail = get("Tariff Type", ""), get("Tariff Detail", "")
    if kind and detail and not tariff_valid(kind, detail):
        problems.append(f'Tariff Detail "{detail}" does not match Tariff Type "{kind}". '
                        "Put the page's own wording in Rules Summary instead")

    hours = get("Hours (OpenStreetMap opening_hours format)", "")
    # "Not applicable" is what a Can Park? No row must hold, so it can never
    # be rejected as a badly formed opening-hours string.
    if hours and hours not in ("Not published", "Not applicable") and not hours_valid(hours):
        problems.append(f'Hours "{hours}" is not a valid opening hours string')

    if get("Price Status", "") == "Published" and "£" not in detail and "free" not in detail.lower():
        problems.append('Price Status is "Published" but Tariff Detail holds no amount')

    cost = get("Cost Type", "")
    if cost == "Free" and kind and not kind.startswith("Free"):
        problems.append(f'Cost Type is "Free" but Tariff Type is "{kind}"')
    if cost == "Free then paid" and kind and kind not in ("Free period, then hourly",
                                                          "Banded by stay length"):
        problems.append(f'Cost Type is "Free then paid" but Tariff Type is "{kind}"')

    if get("Source Tier", "") == "None found":
        for column, want in (("Can Park? (Yes/No/Conditional)", "Unknown"),
                             ("Evidence Type", "No info found"),
                             ("Verification Result", "No evidence")):
            if get(column, "") != want:
                problems.append(f'Source Tier is "None found" but {column} is '
                                f'"{get(column, "")}", expected "{want}"')
    if get("Verification Result", "") == "No evidence" and get("Source Tier", "") != "None found":
        problems.append('Verification Result is "No evidence" but Source Tier is not "None found"')

    if get("Who Can Park", "") == "Anyone (paid)":
        # A stated payment requirement is the evidence, with or without an
        # amount. A page that says "pay on exit" and publishes no price gives
        # Cost Type Paid and Price Status Not published.
        states_payment = ("£" in detail or "£" in get("Rules Summary", "")
                          or cost in ("Paid", "Free then paid"))
        if not states_payment:
            problems.append('Who Can Park is "Anyone (paid)" but the row records no price '
                            'and no Cost Type of "Paid". Use Unknown instead')

    # --- rules folded in from grok-import on 15 November 2026, so the two
    # --- checks can no longer disagree about the same row.
    can = get("Can Park? (Yes/No/Conditional)", "")
    tier = get("Source Tier", "")
    strong = tier in STRONG_SOURCE_TIERS
    site_strong = strong and get("Specificity", "") == "Site-specific"

    if can == "Yes" and not strong:
        problems.append(f'Can Park? is "Yes" but Source Tier is "{tier}", not a strong source')
    if can == "No" and not site_strong:
        problems.append('Can Park? is "No" but the evidence is not a site-specific '
                        "statement from a strong source")
    if can == "No":
        for column in ("Hours (OpenStreetMap opening_hours format)", "Hours Basis",
                       "Parking Control Type (Cameras / Barrier / Patrol)"):
            if get(column, "") not in ("", "Not applicable"):
                problems.append(f'Can Park? is "No" so {column} must read "Not applicable"')

    if get("Location Status", "") == "Closed" and can != "No":
        problems.append('Location Status is "Closed" but Can Park? is not "No"')

    if get("Verification Result", "") == "Confirmed":
        missing = [c for c in ("Who Can Park", "Max Stay (mins)",
                               "Hours (OpenStreetMap opening_hours format)")
                   if get(c, "") in ("", "Unknown", "Not published")]
        if not site_strong or missing:
            problems.append('Verification Result is "Confirmed" but the evidence is not '
                            "complete and site-specific. Missing: "
                            + (", ".join(missing) or "a site-specific strong source")
                            + '. Use "Confirmed, details not published" instead')

    if get("Conflict", "") == "Yes" and not get("Review Flag", ""):
        problems.append('Conflict is "Yes" but Review Flag is blank')
    if get("Review Flag", "") and not get("Flag Status", ""):
        problems.append("Review Flag is set but Flag Status is blank")

    if max_stay_strong(get("Max Stay (mins)", "")) and not site_strong:
        problems.append("Max Stay needs strong site-specific evidence")

    # Only a row that writes something needs the round stamp. A row the round
    # read and did not change writes nothing, so it carries no stamp. On
    # 15 November this rule flagged 66 hospital rows that the round left alone.
    writes_something = any(get(column, "") for column in STAMPED_COLUMNS)
    if (get("Place ID", "") and writes_something and not get("Decision Reason", "")):
        problems.append('Decision Reason is blank. Write the round, as "Route: <round>"')

    agreeing = get("Agreeing Sources", "")
    if agreeing and agreeing not in ("0", "1", "2", "3"):
        problems.append(f'Agreeing Sources is "{agreeing}", which must be 0, 1, 2 or 3')

    for column, value in row.items():
        if "–" in str(value) or "—" in str(value):
            problems.append(f"{column} holds a dash character that the sheet refuses. "
                            "Use a plain hyphen")

    evidence = row.get("Evidence Detail (what the source shows)", "")
    if "£" in evidence and re.search(r"\d{2}:\d{2}", evidence):
        problems.append("Evidence Detail holds a price and an opening time together. "
                        "One field for each evidence cell")

    # "Not published", "Not applicable" and "No limit" are the sheet's own words
    # for a number nobody published.
    words = ("Not published", "Not applicable", "No limit")
    max_stay = get("Max Stay (mins)", "")
    if max_stay and max_stay not in words and not re.fullmatch(r"\d+", max_stay):
        problems.append(f'Max Stay (mins) is "{max_stay}", which is neither a whole '
                        "number of minutes nor one of: " + ", ".join(words))

    pcn = get("PCN (Penalty Charge Notice) amount (£)", "")
    if pcn and pcn not in words and not re.fullmatch(r"\d+(\.\d{1,2})?", pcn):
        problems.append(f'PCN amount is "{pcn}", which is a number without the £ sign, '
                        "or one of: " + ", ".join(words))

    return problems


def sheet_rows(sheet_path):
    """{Place ID: normalised row} from a downloaded export of the tab."""
    live = {}
    with open(sheet_path, newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            live[str(row.get("Place ID", "")).strip()] = normalise(row)
    return live


def merge_with_sheet(rows, sheet_path):
    """Each result row overlaid on the sheet's own row, by Place ID.

    A blank cell in a result file means "keep the sheet's value". Checking the
    file alone reads that blank as an empty answer, which is what produced 99
    problems on the hospital round of 15 November. The checks run on the row as
    it will read after the write."""
    live = {}
    with open(sheet_path, newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            live[str(row.get("Place ID", "")).strip()] = normalise(row)
    out = []
    for row in rows:
        existing = live.get(str(row.get("Place ID", "")).strip(), {})
        merged = dict(existing)
        merged.update({k: v for k, v in row.items() if v})
        out.append(merged)
    return out


def check_file(path, sheet_path=None):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = [normalise(row) for row in csv.DictReader(handle)]
    live = sheet_rows(sheet_path) if sheet_path else {}
    problems = []
    for number, row in enumerate(rows, start=2):
        name = row.get("Location Name") or row.get("Place ID") or row.get("Ref") or "?"
        context = live.get(str(row.get("Place ID", "")).strip(), {})
        for problem in check_row(row, context):
            problems.append(f"row {number} ({name}): {problem}")
    return len(rows), problems


def demo():
    """The file's own checks. Run with --demo."""
    assert tariff_valid("Banded by stay length", "0-29 mins £8.50; 29-44 mins £12.50")
    assert not tariff_valid("Banded by stay length", "0-29 mins £8.50; 30-44 mins £12.50")
    assert not tariff_valid("Banded by stay length", "0-1 hrs £2.00; 1-2 mins £3.00")
    assert tariff_valid("Flat rate per entry", "£7.00 per entry")
    assert not tariff_valid("Hourly rate", "£2 per hour")
    assert hours_valid("Mo-Fr 07:00-19:00; Sa,Su off")
    assert hours_valid("24/7")
    assert not hours_valid("Monday 7am to 7pm")
    assert check_row({"Price Status": "Published", "Tariff Detail": ""})
    assert check_row({"Who Can Park": "Anyone (paid)", "Tariff Detail": "", "Rules Summary": ""})
    assert not check_row({"Who Can Park": "Anyone (paid)", "Tariff Detail": "£3.00 per hour",
                          "Tariff Type": "Hourly rate", "Price Status": "Published"})
    assert check_row({"Location Name": "A – B"})
    assert not check_row({"Max Stay (mins)": "Not published"})
    assert check_row({"Max Stay (mins)": "about an hour"})
    assert check_row({"Can Park? (Yes/No/Conditional)": "Maybe"})
    # Rules folded in from grok-import, so the two checks agree.
    assert not check_row({"Who Can Park": "Anyone (paid)", "Cost Type": "Paid",
                          "Price Status": "Not published"})
    assert check_row({"Can Park? (Yes/No/Conditional)": "Yes", "Source Tier": "Directory"})
    assert check_row({"Can Park? (Yes/No/Conditional)": "No", "Source Tier": "Official site - text",
                      "Specificity": "Site-specific", "Hours Basis": "Site hours"})
    assert not check_row({"Can Park? (Yes/No/Conditional)": "No", "Source Tier": "Official site - text",
                          "Specificity": "Site-specific", "Hours Basis": "Not applicable"})
    assert check_row({"Location Status": "Closed", "Can Park? (Yes/No/Conditional)": "Yes"})
    assert check_row({"Verification Result": "Confirmed", "Source Tier": "Official site - text",
                      "Specificity": "Site-specific", "Who Can Park": "Anyone",
                      "Max Stay (mins)": "120"})
    assert check_row({"Conflict": "Yes"})
    assert check_row({"Review Flag": "Check the tariff"})
    assert check_row({"Place ID": "PP-1", "Cost Type": "Paid", "Decision Reason": ""})
    assert not check_row({"Place ID": "PP-1", "Cost Type": "Paid",
                          "Decision Reason": "Route: hospital1"})
    # A row the round read and did not change needs no stamp.
    assert not check_row({"Place ID": "PP-1", "Notes": "nothing published"})
    assert check_row({"Agreeing Sources": "4"})
    assert not check_row({"Can Park? (Yes/No/Conditional)": "No",
                          "Source Tier": "Official site - text", "Specificity": "Site-specific",
                          "Hours (OpenStreetMap opening_hours format)": "Not applicable",
                          "Hours Basis": "Not applicable",
                          "Parking Control Type (Cameras / Barrier / Patrol)": "Not applicable"})
    assert not check_row({"Place ID": "PP-1", "Cost Type": "Paid",
                          "Decision Reason": "Route C: operator page"})
    # The merge: a blank in the results file keeps the sheet's value.
    import tempfile, os
    with tempfile.TemporaryDirectory() as folder:
        export = os.path.join(folder, "live.csv")
        with open(export, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["Place ID", "Cost Type",
                                                        "Decision Reason"])
            writer.writeheader()
            writer.writerow({"Place ID": "PP-1", "Cost Type": "Free then paid",
                             "Decision Reason": "Route B: earlier round"})
        merged = merge_with_sheet([normalise({"Place ID": "PP-1",
                                              "Who Can Park": "Anyone (paid)"})], export)
        assert merged[0]["Cost Type"] == "Free then paid"
        assert not check_row(merged[0])
    print("self-check passed")


def main(argv):
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    if argv[1] == "--demo":
        demo()
        return 0
    rows, problems = check_file(argv[1], argv[2] if len(argv) == 3 else None)
    for problem in problems:
        print(problem)
    print(f"{rows} rows checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
