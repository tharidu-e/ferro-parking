"""Backtest and rebuild a queue skip plan without changing the sheet.

Inputs are saved Sheets snapshots, exact object tags from osm_match.Collector,
and existing OSM match CSVs. No network calls are made by this command.
"""
import argparse
import csv
import json
from pathlib import Path

from . import grok_skip as gs


def write_report(out, report, details):
    lines = ["# Grok skip backtest and revised dry run", "", "No sheet changes.", "",
             "All 199 result IDs evaluated: 194 use queue inputs; five non-queue test IDs",
             "are ruled out from main-sheet name and category alone. Evidence Level and",
             "Fields Found below are Grok's recorded values, not independent source validation.", "",
             "| Rule | Would skip | Fields found | Verified |",
             "|---|---:|---:|---:|"]
    for label, key in (("Original", "original_backtest"), ("Tightened", "tightened_backtest")):
        r = details[key]
        lines.append(f"| {label} | {r['would_skip']} | {r['with_fields']} | {r['verified']} |")
    lines += ["", "The tightened rule still skips successful research in the backtest.",
              "This is an observed cost of the category-only rule, not proof that a site has no online information.", "",
              "## Every original would-be skip where Grok found fields", "",
              "Yes in the last column means the tightened rule would still skip it.", "",
              "| Place ID | Location Name | Source Tier | Still skipped |", "|---|---|---|---|"]
    still = {r["Place ID"] for r in details["tightened_backtest"]["found_rows"]}
    for r in details["original_backtest"]["found_rows"]:
        lines.append(f"| {r['Place ID']} | {r['Location Name']} | {r['Source Tier']} | "
                     f"{'Yes' if r['Place ID'] in still else 'No'} |")
    lines += ["", "## Original 186 proposed skips: reason breakdown", ""]
    for key, label in (("restrictive_keyword", "Restrictive keyword"), ("category_only", "Category only")):
        group = details["original_186_breakdown"][key]
        lines += [f"### {label}: {group['count']}", "",
                  f"Showing {len(group['samples'])} samples (all rows if fewer than 10).", "",
                  "| Place ID | Location Name | Priority |", "|---|---|---:|"]
        for r in group["samples"]:
            lines.append(f"| {r['Place ID']} | {r['Location Name']} | {r['Priority']} |")
        lines.append("")
    lines += ["## Revised plan", "", f"Total skips: {report['skip_count']}.", "",
              "| Priority | Skips |", "|---|---:|"]
    for priority in ("1", "2", "3", "4"):
        lines.append(f"| {priority} | {report['per_priority'].get(priority, 0)} |")
    lines += ["", f"Autopay rows selected: {len(report['autopay_out_of_scope'])}.",
              f"Rows retained by public signals: {len(details['retained_by_public_signs'])}.",
              f"OSM input coverage: {details['osm_coverage']['with_osm_input']} queue rows.",
              f"Independent reading mismatches: {report['second_reading']['mismatches']}.", "",
              "Name phrases are matched as whole words after punctuation normalization.",
              "For example, Car Park matches car park, but does not expand to carpark.", "",
              "### 15 revised samples", "", "| Place ID | Location Name | Priority |", "|---|---|---:|"]
    for r in report["samples"]:
        lines.append(f"| {r['Place ID']} | {r['Location Name']} | {r['Priority']} |")
    text = "\n".join(lines).replace(chr(8211), "-").replace(chr(8212), "-") + "\n"
    with (Path(out) / "review.md").open("x", encoding="utf-8") as f:
        f.write(text)


def review(tabs, original, object_tags, packets, original_plan):
    main = tabs[gs.sheets.TAB][1]
    headers, queue = tabs[gs.QUEUE]
    enriched = gs.attach_osm(queue, main, object_tags, packets)
    old_queue = gs.attach_osm(original[gs.QUEUE][1], main, object_tags, packets)
    old_ids = {e["place_id"] for e in original_plan["rows"]}
    old_selected = [r for r in old_queue if r["Place ID"] in old_ids]
    if len(old_selected) != len(old_ids):
        raise ValueError("Original plan IDs missing from original snapshot")
    groups = {"restrictive_keyword": [], "category_only": []}
    for row in old_selected:
        key = "restrictive_keyword" if gs.NAME_MATCH.search(row["Location Name"]) else "category_only"
        groups[key].append({k: row[k] for k in gs.SKIP_COLUMNS if k != "Reason"})
    results = tabs[gs.RESULTS][1]
    completed = {r["Place ID"] for r in results}
    # The old and revised backtests use the same result population and queue inputs.
    baseline = gs.backtest(enriched, results, tightened=False, fallback_rows=main)
    tightened = gs.backtest(enriched, results, tightened=True, fallback_rows=main)
    retained = [{"Place ID": r["Place ID"], "Location Name": r["Location Name"],
                 "Keep signals": "; ".join(gs.public_signs(r))}
                for r in enriched if r["Place ID"] not in completed
                and gs.skip_reason(r, tightened=False) and not gs.skip_reason(r)]
    details = {
        "original_backtest": baseline, "tightened_backtest": tightened,
        "original_186_breakdown": {k: {"count": len(v), "samples": v[:10], "all_rows": v}
                                   for k, v in groups.items()},
        "original_results_count": len(original[gs.RESULTS][1]),
        "backtest_results_count": len(results),
        "osm_coverage": {"queue_rows": len(enriched),
                         "with_osm_input": sum(bool(r["_osm_provenance"]) for r in enriched),
                         "without_osm_input": [r["Place ID"] for r in enriched if not r["_osm_provenance"]]},
        "retained_by_public_signs": retained,
        "main_sheet_noncandidate_inputs": [{k: r.get(k, "") for k in (
            "Place ID", "Location Name", "Place Category")} for r in main
            if r["Place ID"] in baseline["main_sheet_noncandidates"]],
    }
    return (headers, enriched), details


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--original-run", type=Path, required=True)
    parser.add_argument("--osm-object-tags", type=Path, required=True)
    parser.add_argument("--osm-packets", type=Path, nargs="*", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    tabs = json.loads(args.snapshot.read_text())
    original = json.loads((args.original_run / "snapshot.json").read_text())
    original_plan = json.loads((args.original_run / "plan.json").read_text())
    tags = json.loads(args.osm_object_tags.read_text())
    packets = []
    for path in args.osm_packets:
        with path.open(encoding="utf-8", newline="") as f:
            packets.extend(csv.DictReader(f))
    queue, details = review(tabs, original, tags, packets, original_plan)
    details["sources"] = {"sheet_snapshot": str(args.snapshot),
                          "original_run": str(args.original_run),
                          "object_tags": str(args.osm_object_tags),
                          "object_tags_extracted_from": "data/raw/greater-london-latest.osm.pbf via osm_match.Collector",
                          "match_packets": [str(p) for p in args.osm_packets]}
    report = gs.prepare(queue, tabs[gs.RESULTS], args.out, review=details)
    write_report(args.out, report, details)
    if report["autopay_out_of_scope"]:
        raise ValueError("Autopay scope overlap requires explicit review; nothing written to Sheets")
    print(json.dumps({"skip_count": report["skip_count"], "per_priority": report["per_priority"],
                      "second_reading": report["second_reading"],
                      "backtests": {label: {k: v for k, v in details[label].items()
                                    if k not in {"all_would_skip", "found_rows"}}
                                    for label in ("original_backtest", "tightened_backtest")}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
