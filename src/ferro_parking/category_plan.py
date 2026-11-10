"""Turn the propose-categories output into a plan that fills blank categories.

    python -m ferro_parking category-plan --proposals PROPOSE_CATEGORIES.csv

Only blank Place Category cells are filled. A proposal that disagrees with a
value already on the row is rejected: the existing value stays.

One guard sits over the supermarket proposals, because the R10 rules read the
store format from the name, not from the category. A proposal of "Supermarket
- large format" is kept only when rules.format_for reads the name as large. A
name that reads as convenience is proposed as "Supermarket - convenience"
instead. A name the rules cannot read at all is dropped and listed for review.

A row verified by a named person is never touched.

Each plan line carries the stage the latest routing run gave that row, because
db-apply refuses a line that names a different stage. Filling a blank category
is not a parking answer, so it is allowed on a finished row as much as on an
unfinished one.
"""
import argparse
import csv
from pathlib import Path

from . import db, fill, plan as plan_mod
from .rules import load_rules
from .run_paths import new_run_dir, reserve_output

LARGE = "Supermarket - large format"
CONVENIENCE = "Supermarket - convenience"
CATEGORY = "Place Category"
DECISION_REASON = "Decision Reason"
REASON_TEXT = ("Route F: Place Category filled from the captured Type, "
               "no parking answer changed")

DASHES = ("\u2013", "\u2014")

REVIEW_HEADERS = ["Place ID", "Location Name", "Type (as captured)",
                  "proposed category", "reason"]
STAGE_FALLBACK = ""


def guarded_category(proposed, location_name, rules):
    """(category, reason). category is None when the proposal is dropped."""
    if proposed != LARGE:
        return proposed, ""
    fmt = rules.format_for(location_name)
    if fmt == "large":
        return LARGE, ""
    if fmt == "convenience":
        return CONVENIENCE, "the name reads as a convenience format, not a large one"
    return None, ("the rules cannot read a store format from this name, so the "
                  "large-format proposal is dropped")


def read_proposals(path):
    with open(path, newline="", encoding="utf-8-sig") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def build(conn, proposals, rules=None):
    """(lines, review, counts). review lists every row left for a person."""
    rules = rules or load_rules()
    _, rows = db.current_rows(conn)
    by_place_id = {(row.get(fill.PLACE_ID) or "").strip(): row for row in rows}
    _, routing = db.latest_routing(conn)

    lines, review, counts = [], [], {}
    for proposal in proposals:
        place_id = (proposal.get("Place ID") or "").strip()
        row = by_place_id.get(place_id)
        proposed = (proposal.get("proposed_place_category") or "").strip()

        def hold(reason):
            review.append({"Place ID": place_id,
                            "Location Name": (row or {}).get(fill.LOCATION_NAME, ""),
                            "Type (as captured)": (row or {}).get("Type (as captured)", ""),
                            "proposed category": proposed, "reason": reason})

        if row is None:
            hold("the database has no such Place ID")
            continue
        if fill.is_named_person(row.get(fill.VERIFIED_BY)):
            hold(f"Verified By is {row.get(fill.VERIFIED_BY)!r}, a named person")
            continue
        if (row.get(CATEGORY) or "").strip():
            hold("Place Category is already filled, so the existing value stays")
            continue
        if not proposed:
            hold("the proposal is blank")
            continue

        category, note = guarded_category(proposed, row.get(fill.LOCATION_NAME, ""), rules)
        if category is None:
            hold(note)
            continue
        if note:
            review.append({"Place ID": place_id,
                            "Location Name": row.get(fill.LOCATION_NAME, ""),
                            "Type (as captured)": row.get("Type (as captured)", ""),
                            "proposed category": category,
                            "reason": f"changed from {proposed!r}: {note}"})

        # validate_rows asks every plan entry for a Decision Reason naming the
        # route, and it sees only the plan's own columns. A row that already
        # has one keeps it, restated as context. A row whose existing reason
        # names no route cannot take ours without replacing real text, so it
        # waits for a person.
        existing = (row.get(DECISION_REASON) or "").strip()
        if not existing:
            reason_value = REASON_TEXT
        elif any(dash in existing for dash in DASHES):
            # The dash is already in the sheet. Restating it would fail the
            # validator, and rewriting somebody's sentence is not this
            # command's job, so the row waits with the reason named.
            hold("the existing Decision Reason holds an en or em dash, "
                 "which the validator refuses")
            continue
        elif "Route" in existing:
            reason_value = existing
        else:
            hold(f"Decision Reason reads {existing[:60]!r}, which names no route")
            continue

        stage = routing.get(place_id, STAGE_FALLBACK)
        for column, value in ((CATEGORY, category), (DECISION_REASON, reason_value)):
            lines.append({
                "place_id": place_id, "column": column, "new_value": value,
                "quote": proposal.get("reason", ""), "source_url": "",
                "stage": stage, "verified_by": "Category policy script",
            })
        counts[category] = counts.get(category, 0) + 1
    return lines, review, counts


def examples(conn, lines, per_category=10):
    """Up to ten example rows per category, for the report."""
    _, rows = db.current_rows(conn)
    by_place_id = {(row.get(fill.PLACE_ID) or "").strip(): row for row in rows}
    seen, out = {}, []
    for line in lines:
        if line["column"] != CATEGORY:
            continue
        category = line["new_value"]
        if len(seen.setdefault(category, [])) >= per_category:
            continue
        row = by_place_id[line["place_id"]]
        seen[category].append(line["place_id"])
        out.append({
            "proposed category": category,
            "Place ID": line["place_id"],
            "Location Name": row.get(fill.LOCATION_NAME, ""),
            "Type (as captured)": row.get("Type (as captured)", ""),
            "Brand": row.get("Brand", ""),
            "stage": line["stage"],
        })
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plan the blank Place Category fills.")
    parser.add_argument("--proposals", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    proposals = read_proposals(args.proposals)
    lines, review, counts = build(conn, proposals)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("category_plan")
    plan_mod.write_plan(out_dir / "plan.jsonl", lines)
    with open(out_dir / "category_review.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_HEADERS)
        writer.writeheader()
        writer.writerows(review)
    example_rows = examples(conn, lines)
    with open(out_dir / "examples.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["proposed category", "Place ID", "Location Name",
                                 "Type (as captured)", "Brand", "stage"])
        writer.writeheader()
        writer.writerows(example_rows)

    print(f"{len(proposals)} proposals read from {args.proposals}")
    print(f"{sum(counts.values())} rows planned, {len(lines)} plan lines")
    print(f"{len(review)} rows in category_review.csv\n")
    print("Planned categories")
    for category, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {category}: {count}")
    print(f"\nTen examples per category: {out_dir / 'examples.csv'}")
    print(f"Plan: {out_dir / 'plan.jsonl'}")
    print("Dry run only. Check it with db-apply, which needs --apply to write.")
    return 0
