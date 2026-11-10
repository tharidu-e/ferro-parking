"""Apply an explicitly approved Grok import through the existing writer."""
import argparse
import copy
import json
from pathlib import Path

from . import fill, grok_import as gi, sheets, sync


def unique(rows):
    index, duplicates = gi.indexed(rows, "apply")
    if duplicates or len(index) != len(rows):
        raise ValueError("Missing or duplicate Place IDs")
    return index


def preflight(saved, plan, undo, live, source_headers, source_rows, config):
    headers, rows = live
    old_headers, old_rows = saved["tabs"][sheets.TAB]
    if headers != old_headers or source_headers != saved["tabs"][gi.RESULTS][0]:
        raise ValueError("Headers changed since approval")
    old, current = unique(old_rows), unique(rows)
    old_source, source = unique(saved["tabs"][gi.RESULTS][1]), unique(source_rows)
    undo_by_id = {e["place_id"]: e for e in undo}
    if len({e["place_id"] for e in plan}) != len(plan):
        raise ValueError("Duplicate plan Place ID")
    resolved, restored = [], []
    for entry in plan:
        pid = entry["place_id"]
        target = current.get(pid)
        if target is None or pid not in old_source or pid not in source:
            raise ValueError(f"{pid}: missing source or target")
        if target.get("Verification Result", "").strip():
            raise ValueError(f"{pid}: already finished")
        if target.get("Verified By", "") not in config["reviewers"]["automation"]:
            raise ValueError(f"{pid}: person-locked reviewer")
        if gi.out_of_scope_reason(source[pid], target):
            raise ValueError(f"{pid}: HGV/coach marked out of scope")
        if any(str(target.get(c, "")) != str(old[pid].get(c, "")) for c in headers):
            raise ValueError(f"{pid}: target snapshot changed")
        if any(str(source[pid].get(c, "")) != str(old_source[pid].get(c, "")) for c in source_headers):
            raise ValueError(f"{pid}: research changed")
        if pid not in undo_by_id or undo_by_id[pid]["old"] != {c: target.get(c, "") for c in entry["new"]}:
            raise ValueError(f"{pid}: undo does not match fresh target")
        fill.assert_not_protected({c: v for c, v in entry["new"].items() if c != "Location Status"})
        if gi.validate(source[pid], entry["new"], config, gi.datetime.now(gi.ZoneInfo("Europe/London")).date()):
            raise ValueError(f"{pid}: approved values fail validation")
        resolved.append({**entry, "sheet_row": target["_sheet_row"]})
        restored.append({**undo_by_id[pid], "sheet_row": target["_sheet_row"]})
    _, failures = gi.second_reading({e["place_id"]: (current[e["place_id"]], e["new"]) for e in resolved}, "grok_apply")
    if failures:
        raise ValueError("Second reading failed")
    return resolved, restored


def read_validation(service, headers, column):
    letter = sheets.col_letter(headers.index(column))
    request = service.spreadsheets().get(spreadsheetId=sheets.SPREADSHEET_ID,
        ranges=[f"'{sheets.TAB}'!{letter}2:{letter}"],
        fields="sheets(properties,data(startRow,startColumn,rowData(values(dataValidation))))")
    # Repeated column validation rules can legitimately exceed httplib2's
    # gzip amplification limit. Request plain HTTP content instead of
    # weakening that protection or truncating the validation snapshot.
    request.headers["accept-encoding"] = "identity"
    return request.execute()


def validation_rules(meta):
    sheet = next(s for s in meta["sheets"] if s["properties"]["title"] == sheets.TAB)
    rules = {}
    for grid in sheet.get("data", []):
        for r, row in enumerate(grid.get("rowData", []), grid.get("startRow", 0)):
            if row.get("values") and row["values"][0].get("dataValidation"):
                rules[r] = row["values"][0]["dataValidation"]
    return sheet["properties"], rules


def validation_requests(meta, headers, approved):
    props, rules = validation_rules(meta)
    template = rules.get(1)
    if not template:
        raise ValueError("Missing dropdown template")
    template_values = [v["userEnteredValue"] for v in template.get("condition", {}).get("values", [])]
    if template_values not in (approved["before"], approved["after"]):
        raise ValueError("Dropdown template changed since approval")
    additions = [v for v in approved["after"] if v not in approved["before"]]
    requests, expected = [], {}
    col = headers.index(approved["column"])
    for row in range(1, props["gridProperties"]["rowCount"]):
        rule = copy.deepcopy(rules.get(row, template))
        condition = rule.get("condition", {})
        values = [v["userEnteredValue"] for v in condition.get("values", [])]
        if (condition.get("type") != "ONE_OF_LIST" or not values
                or not set(values).issubset(approved["after"])):
            raise ValueError(f"Dropdown rule changed at data row {row + 1}")
        # Historical rows may offer fewer options than the header template.
        # Approval permits adding one value, not replacing those legacy lists.
        rule["condition"]["values"] = [{"userEnteredValue": v} for v in dict.fromkeys(values + additions)]
        expected[row] = rule
        if rules.get(row) == rule:
            continue
        if requests and requests[-1]["setDataValidation"]["rule"] == rule and requests[-1]["setDataValidation"]["range"]["endRowIndex"] == row:
            requests[-1]["setDataValidation"]["range"]["endRowIndex"] = row + 1
        else:
            requests.append({"setDataValidation": {"range": {"sheetId": props["sheetId"],
                "startRowIndex": row, "endRowIndex": row + 1, "startColumnIndex": col, "endColumnIndex": col + 1}, "rule": rule}})
    return requests, expected


def approved_extensions(envelope):
    changes = envelope.get("changes", [envelope])
    allowed = {"Evidence Level": "Reported", "Evidence Type": "Third-party only"}
    seen = set()
    for change in changes:
        column = change["column"]
        if (change["tab"] != sheets.TAB or column not in allowed or column in seen
                or change["after"] != change["before"] + [allowed[column]]):
            raise ValueError("Only explicitly planned Reported/Third-party only additions are supported")
        seen.add(column)
    return changes


def apply_run(service, run_dir, out):
    run_dir, out = Path(run_dir), Path(out)
    saved = json.loads((run_dir / "snapshot.json").read_text())
    plan = json.loads((run_dir / "plan.json").read_text())
    undo = json.loads((run_dir / "undo.json").read_text())
    config = json.loads((run_dir / "value_map.json").read_text())
    approved = json.loads((run_dir / "validation_plan.json").read_text())
    changes = approved_extensions(approved)
    live = sheets.read_tab(service)
    source = sheets.read_tab(service, tab=gi.RESULTS)
    resolved, restored = preflight(saved, plan, undo, live, *source, config)
    formula_headers, formulas = sheets.read_tab(service, value_render_option="FORMULA")
    if formula_headers != live[0] or [r["Place ID"] for r in formulas] != [r["Place ID"] for r in live[1]]:
        raise ValueError("Sheet changed during preflight")
    metadata, expected_rules, requests = {}, {}, []
    for change in changes:
        column = change["column"]
        metadata[column] = read_validation(service, live[0], column)
        additions, expected_rules[column] = validation_requests(metadata[column], live[0], change)
        requests.extend(additions)
    out.mkdir(parents=True, exist_ok=False)
    for name, data in (("plan", resolved), ("undo", restored), ("pre_write", {"headers": live[0], "rows": live[1]}),
                       ("pre_write_formulas", {"headers": formula_headers, "rows": formulas}),
                       ("validation_undo", metadata), ("validation_requests", requests)):
        gi.save_json(out / f"{name}.json", data)
    # All checks and exclusive undo creation precede the first mutation.
    if requests:
        service.spreadsheets().batchUpdate(spreadsheetId=sheets.SPREADSHEET_ID, body={"requests": requests}).execute()
    for column, expected in expected_rules.items():
        _, rules = validation_rules(read_validation(service, live[0], column))
        if rules != expected:
            raise ValueError("Dropdown readback mismatch; no data rows written")
    writer_result = fill._apply_write(service, live[0], resolved, {e["sheet_row"]: e for e in restored}, True)
    after_headers, after = sheets.read_tab(service, value_render_option="FORMULA")
    value_headers, values = sheets.read_tab(service)
    mismatches = sync.compare_updates(formula_headers, formulas, after_headers, after, resolved)
    if writer_result:
        mismatches.append("Existing writer reported a readback error")
    gi.save_json(out / "reexport_formulas.json", {"headers": after_headers, "rows": after})
    gi.save_json(out / "reexport.json", {"headers": value_headers, "rows": values})
    report = {"rows": len(resolved), "cells": sum(len(e["new"]) for e in resolved),
              "dropdown_changes": changes, "mismatches": mismatches,
              "mismatch_count": len(mismatches), "writer_result": writer_result}
    gi.save_json(out / "compare.json", report)
    if mismatches:
        raise ValueError(f"STOP: {len(mismatches)} independent comparison mismatches")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(apply_run(sheets.get_service(), args.run_dir, args.out), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
