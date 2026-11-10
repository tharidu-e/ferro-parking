"""Phase 4: the category default, as a plan file for rows routed to "default".

    python -m ferro_parking default-fill

Reads the database, takes only the Place IDs the latest routing run put on
stage "default", and runs the existing R1 and R10 rules from policy_fill on
each one. The result is a plan file for db-apply, never a sheet write. Dry run
only: this command writes no change to the database.

Station rows, grok rows, fetcher rows and every skip row are out of scope, by
the routing table alone. A station car park is not a customer venue, so the
category default must never touch it.

Rule R7 holds throughout, because the rules are policy_fill's own and are used
unchanged: no Free, no Anyone, and no max stay without site-specific evidence.
Each plan also carries the row's Brand and Place Category as context, because
validation.validate_rows sees only the plan's own columns and asks for both
whenever Can Park? is Yes or Conditional.
"""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from . import db, fill, page_fill, plan as plan_mod, policy_fill, rules as rules_mod
from .run_paths import new_run_dir, reserve_output

STAGE = "default"
CONTEXT_COLUMNS = ("Brand", "Place Category")

OUTCOME_CHAIN_POLICY = "chain policy (Conditional)"
OUTCOME_PRESUMED_NO = "presumed no parking (R10)"
OUTCOME_UNCLASSIFIED = "not classified by the rules"

EXAMPLE_HEADERS = ["outcome", "Place ID", "Location Name", "Place Category", "column",
                   "current value", "new value"]
SUMMARY_HEADERS = ["group", "name", "rows"]


def load_osm_rows(path=None):
    """osm_results.csv by Place ID, for policy_fill's nearby car park test.
    An empty dict means no OSM run is available, and every row then reads as
    having no mapped car park nearby."""
    if path is None:
        candidates = sorted(Path("data/runs").glob("*/osm_results.csv"))
        if not candidates:
            return {}, None
        path = candidates[-1]
    with open(path, newline="", encoding="utf-8-sig") as stream:
        rows = {row["Place ID"]: row for row in csv.DictReader(stream) if row.get("Place ID")}
    return rows, str(path)


def default_rows(conn):
    """(rows, run_id) for the Place IDs the latest routing run put on default."""
    run_id, routing = db.latest_routing(conn)
    if run_id is None:
        raise SystemExit("No routing run in the database. Run route first.")
    wanted = {place_id for place_id, stage in routing.items() if stage == STAGE}
    _, rows = db.current_rows(conn)
    return [row for row in rows if (row.get(fill.PLACE_ID) or "").strip() in wanted], run_id


def plan_lines_for(sheet_row, osm_row, rules, today):
    """(outcome, lines, reason). lines is empty for an unclassified row."""
    branch, fields, reason = policy_fill.classify(sheet_row, osm_row, rules)
    if branch == "c":
        return OUTCOME_UNCLASSIFIED, [], reason
    # validate_rows asks for Brand and Place Category whenever Can Park? is
    # Yes or Conditional, and it sees only the plan's own columns. A row with
    # neither on it cannot get a valid plan, and this command will not invent
    # either one, so the row waits for a person.
    missing = [column for column in CONTEXT_COLUMNS
               if not (sheet_row.get(column) or "").strip()]
    if missing:
        return (OUTCOME_UNCLASSIFIED, [],
                f"the row has no {' and no '.join(missing)}, which a Conditional row needs")

    new_values, extra_notes, extra_flags = fields
    new = page_fill.build_row_values(
        sheet_row, {**new_values, "_notes": list(extra_notes), "_flags": list(extra_flags)},
        today, {}, verified_by=policy_fill.VERIFIED_BY_VALUE)
    new[fill.VERIFIED_DATE] = today.isoformat()

    outcome = OUTCOME_PRESUMED_NO if new.get(fill.CAN_PARK) == "No" else OUTCOME_CHAIN_POLICY
    for column in CONTEXT_COLUMNS:
        new.setdefault(column, sheet_row.get(column, ""))

    lines = []
    for column, value in new.items():
        if value is None or str(value).strip() == "":
            continue
        lines.append({
            "place_id": (sheet_row.get(fill.PLACE_ID) or "").strip(),
            "column": column,
            "new_value": str(value),
            "quote": new.get("Evidence Detail (what the source shows)", ""),
            "source_url": sheet_row.get(fill.SOURCE_URLS, ""),
            "stage": STAGE,
            "verified_by": policy_fill.VERIFIED_BY_VALUE,
        })
    return outcome, lines, reason


def build(conn, rules=None, osm_rows=None, today=None):
    """Plan lines for every default-stage row, plus the report."""
    rules = rules or rules_mod.load_rules()
    osm_rows = {} if osm_rows is None else osm_rows
    today = today or date.today()
    rows, run_id = default_rows(conn)

    lines, examples = [], defaultdict(list)
    outcomes, by_category, who_can_park = Counter(), defaultdict(Counter), Counter()
    unclassified_reasons = Counter()
    for sheet_row in rows:
        place_id = (sheet_row.get(fill.PLACE_ID) or "").strip()
        outcome, row_lines, reason = plan_lines_for(
            sheet_row, osm_rows.get(place_id, {}), rules, today)
        outcomes[outcome] += 1
        by_category[sheet_row.get("Place Category", "") or "(blank)"][outcome] += 1
        if outcome == OUTCOME_UNCLASSIFIED:
            unclassified_reasons[reason] += 1
        if outcome == OUTCOME_CHAIN_POLICY:
            planned = {entry["column"]: entry["new_value"] for entry in row_lines}
            who_can_park[planned.get(fill.WHO_CAN_PARK, "(not set)")] += 1
        lines.extend(row_lines)
        if len(examples[outcome]) < 5:
            examples[outcome].append((sheet_row, row_lines, reason))
    return lines, {
        "routing_run": run_id,
        "rows": len(rows),
        "outcomes": outcomes,
        "by_category": by_category,
        "who_can_park": who_can_park,
        "unclassified_reasons": unclassified_reasons,
        "examples": examples,
    }


# ---------------------------------------------------------------- reporting

def example_rows(report):
    out = []
    for outcome in (OUTCOME_CHAIN_POLICY, OUTCOME_PRESUMED_NO, OUTCOME_UNCLASSIFIED):
        for sheet_row, row_lines, reason in report["examples"].get(outcome, []):
            place_id = (sheet_row.get(fill.PLACE_ID) or "").strip()
            name = sheet_row.get(fill.LOCATION_NAME, "")
            category = sheet_row.get("Place Category", "")
            if not row_lines:
                out.append({"outcome": outcome, "Place ID": place_id, "Location Name": name,
                             "Place Category": category, "column": "(no change)",
                             "current value": "", "new value": reason})
                continue
            for entry in row_lines:
                out.append({"outcome": outcome, "Place ID": place_id, "Location Name": name,
                             "Place Category": category, "column": entry["column"],
                             "current value": sheet_row.get(entry["column"], ""),
                             "new value": entry["new_value"]})
    return out


def summary_rows(report):
    out = [{"group": "outcome", "name": name, "rows": count}
           for name, count in report["outcomes"].most_common()]
    for category, counter in sorted(report["by_category"].items()):
        for name, count in counter.most_common():
            out.append({"group": f"category: {category}", "name": name, "rows": count})
    for name, count in report["who_can_park"].most_common():
        out.append({"group": "Who Can Park on chain policy rows", "name": name, "rows": count})
    for name, count in report["unclassified_reasons"].most_common():
        out.append({"group": "reason not classified", "name": name, "rows": count})
    return out


def print_report(report, lines, osm_source):
    print(f"Routing run {report['routing_run']}: {report['rows']} rows on stage {STAGE!r}")
    print(f"OSM results used: {osm_source or 'none found, so no row has a mapped car park nearby'}")
    print(f"{len(lines)} plan lines\n")

    print("By outcome")
    for name in (OUTCOME_CHAIN_POLICY, OUTCOME_PRESUMED_NO, OUTCOME_UNCLASSIFIED):
        print(f"  {name}: {report['outcomes'].get(name, 0)}")

    print("\nWho Can Park on the chain policy rows")
    for name, count in report["who_can_park"].most_common():
        print(f"  {name}: {count}")
    if not report["who_can_park"]:
        print("  none")

    print("\nBy Place Category")
    for category, counter in sorted(report["by_category"].items(),
                                     key=lambda item: (-sum(item[1].values()), item[0])):
        total = sum(counter.values())
        parts = ", ".join(f"{name} {count}" for name, count in counter.most_common())
        print(f"  {category}: {total} ({parts})")

    print("\nWhy a row was not classified")
    for name, count in report["unclassified_reasons"].most_common():
        print(f"  {name}: {count}")
    if not report["unclassified_reasons"]:
        print("  none")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Category default as a plan file. Dry run only.")
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--osm-results", default=None)
    parser.add_argument("--out", help="Output directory. Defaults to a new run folder.")
    args = parser.parse_args(argv)

    conn = db.connect(args.db)
    osm_rows, osm_source = load_osm_rows(args.osm_results)
    lines, report = build(conn, osm_rows=osm_rows)

    out_dir = reserve_output(args.out) if args.out else new_run_dir("default_fill")
    plan_mod.write_plan(out_dir / "plan.jsonl", lines)
    with open(out_dir / "summary.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_HEADERS)
        writer.writeheader()
        writer.writerows(summary_rows(report))
    with open(out_dir / "examples.csv", "x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXAMPLE_HEADERS)
        writer.writeheader()
        writer.writerows(example_rows(report))

    print_report(report, lines, osm_source)
    print(f"\nFive examples per outcome: {out_dir / 'examples.csv'}")
    print(f"Plan: {out_dir / 'plan.jsonl'}")
    print("Dry run only. Nothing written to the database or the sheet.")
    print("Check the plan with db-apply, which is itself a dry run unless you add --apply.")
    return 0
