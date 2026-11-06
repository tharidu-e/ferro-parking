"""Read-only Grok Queue skip planning. Run: python -m ferro_parking.grok_skip.

This command never writes to Sheets. After approval, apply only through
sheets.write_cells, with fresh Place ID matching and a full queue comparison.
"""
import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import fill, sheets

QUEUE = "Grok Queue"
RESULTS = "Grok Results"
PRIVATE_CATEGORY = "Private / operator car park"
WORDS = ("goods in", "overflow", "deliveries", "delivery", "loading", "depot",
         "yard", "staff", "residents", "residential", "private", "HGV", "lorry",
         "coach", "workshop")
OUT_OF_SCOPE = re.compile(r"\b(?:HGV|lorry|coach)\b", re.I)
NAME_MATCH = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in WORDS) + r")\b", re.I)
REQUIRED = {"Place ID", "Location Name", "Place Category", "Priority", "Official URL",
            "OSM Website", "Ferro Autopay"}
SKIP_COLUMNS = ["Place ID", "Location Name", "Place Category", "Priority", "Reason"]


def skip_reason(row):
    name = row.get("Location Name", "")
    # The explicit 'regardless' rule takes precedence over Autopay and URLs.
    if OUT_OF_SCOPE.search(name):
        return "Out of scope: HGV/coach"
    if row.get("Ferro Autopay", "").strip() == "✅":
        return ""
    if any(row.get(c, "").strip() for c in ("Official URL", "OSM Website")):
        return ""
    if row.get("Place Category", "").strip() == PRIVATE_CATEGORY:
        return "No official or OSM website: private / operator car park"
    match = NAME_MATCH.search(name)
    return f"No official or OSM website: name contains {match.group().lower()}" if match else ""


def validate_input(headers, rows, result_headers, results):
    if not REQUIRED.issubset(headers) or "Place ID" not in result_headers:
        raise ValueError("Missing required queue or result headers")
    if len(headers) != len(set(headers)) or any(not h for h in headers):
        raise ValueError("Blank or duplicate queue headers")
    if "Skip" in headers:
        raise ValueError("Skip already exists: review existing markers before replanning")
    ids = [r.get("Place ID", "").strip() for r in rows]
    if any(not pid for pid in ids) or len(ids) != len(set(ids)):
        raise ValueError("Blank or duplicate queue Place ID")
    if any(r.get("Place ID", "") != r.get("Place ID", "").strip() for r in rows):
        raise ValueError("Queue Place ID contains surrounding whitespace")
    if any(any(str(v).strip() for k, v in r.items() if k != "_sheet_row")
           and not r.get("Place ID", "").strip() for r in results):
        raise ValueError("Nonempty result row has no Place ID")


def second_reading(rows, results, plan):
    """Recompute eligibility without the filter regex or skip_reason helper."""
    completed = {r.get("Place ID", "").strip() for r in results}
    expected = set()
    for row in rows:
        if row["Place ID"] in completed:
            continue
        words = re.findall(r"\w+", row["Location Name"].lower())
        tokens = set(words)
        scope = bool(tokens & {"hgv", "lorry", "coach"})
        restricted = bool(tokens & (set(w.lower() for w in WORDS) - {"goods in"}))
        restricted |= "goods in" in row["Location Name"].lower() and bool(
            re.search(r"\bgoods in\b", row["Location Name"], re.I))
        no_urls = not row["Official URL"].strip() and not row["OSM Website"].strip()
        private = row["Place Category"].strip() == PRIVATE_CATEGORY
        if scope or (no_urls and (private or restricted) and row["Ferro Autopay"].strip() != "✅"):
            expected.add(row["Place ID"])
    actual = {e["place_id"] for e in plan}
    if actual != expected or len(actual) != len(plan):
        raise ValueError("Independent skip reading disagrees with the plan")
    return {"expected": len(expected), "planned": len(plan), "mismatches": 0}


def build_plan(headers, rows, result_headers, results):
    validate_input(headers, rows, result_headers, results)
    completed = {r.get("Place ID", "").strip() for r in results}
    plan, undo, skips = [], [], []
    for row in rows:
        if row["Place ID"] in completed:
            continue
        reason = skip_reason(row)
        if not reason:
            continue
        new = {"Skip": "Yes"}
        fill.assert_not_protected(new)
        plan.append({"sheet_row": row["_sheet_row"], "place_id": row["Place ID"],
                     "name": row["Location Name"], "new": new})
        undo.append({"sheet_row": row["_sheet_row"], "place_id": row["Place ID"],
                     "old": {"Skip": ""}})
        skips.append({**{c: row[c] for c in SKIP_COLUMNS if c != "Reason"}, "Reason": reason})
    reading = second_reading(rows, results, plan)
    return plan, undo, skips, reading


def _save_json(path, value):
    with path.open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)


def _save_csv(path, headers, rows):
    with path.open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        # Report typography only; the original snapshot and plan remain exact.
        writer.writerows({k: str(v).replace(chr(8211), "-").replace(chr(8212), "-")
                          for k, v in row.items()} for row in rows)


def prepare(queue, results, out):
    headers, rows = queue
    result_headers, result_rows = results
    plan, undo, skips, reading = build_plan(headers, rows, result_headers, result_rows)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    _save_json(out / "snapshot.json", {QUEUE: queue, RESULTS: results})
    _save_json(out / "plan.json", {"tab": QUEUE, "headers_before": headers,
               "add_column": {"header": "Skip", "after_header": headers[-1], "initial_value": ""},
               "rows": plan})
    _save_json(out / "undo.json", {"tab": QUEUE, "rows": undo,
               "header_before": "", "header_after": "Skip",
               "note": "Restore values and blank the new header; never delete a column automatically"})
    _save_csv(out / "skip_list.csv", SKIP_COLUMNS, skips)
    dry = [{"Place ID": e["place_id"], "Column": "Skip", "Current value": "", "New value": "Yes"}
           for e in plan]
    _save_csv(out / "dry_run.csv", ["Place ID", "Column", "Current value", "New value"], dry)
    report = {"queue_rows": len(rows), "result_rows": len(result_rows),
              "queue_rows_already_in_results": sum(r["Place ID"] in {
                  x.get("Place ID", "").strip() for x in result_rows} for r in rows),
              "skip_count": len(skips), "per_priority": dict(Counter(r["Priority"] for r in skips)),
              "reasons": dict(Counter(r["Reason"] for r in skips)),
              "autopay_out_of_scope": [r["Place ID"] for r in rows if r["Ferro Autopay"].strip() == "✅"
                                      and r["Place ID"] in {e["place_id"] for e in plan}],
              "second_reading": reading, "rejects": [],
              "parking_checks": "Not applicable: queue markers do not set parking answers or finish rows",
              "samples": skips[:15]}
    _save_json(out / "report.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="Use a previously saved read-only snapshot")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.snapshot:
        tabs = json.loads(args.snapshot.read_text())
    else:
        service = sheets.get_service()
        tabs = {tab: sheets.read_tab(service, tab=tab) for tab in (QUEUE, RESULTS)}
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    out = args.out or Path("data/runs") / today / "grok_skip"
    print(json.dumps(prepare(tabs[QUEUE], tabs[RESULTS], out), indent=2, ensure_ascii=True))
    print(f"Dry run saved to {out}. No sheet changes. Awaiting go.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
