"""Conservative, read-only Grok Results importer planning.

Run python -m ferro_parking.grok_import. There is no sheet write mode.
Plans use the existing fill writer's plan/undo format, with preflight required
before applying: re-resolve Place IDs, check source and target snapshots and
reviewer locks, apply validation changes, use the existing writer, and compare
an independent full export. Approval is required before every sheet mutation.
"""
import argparse
import csv
import json
import re
import tomllib
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from . import fill, page_fill, sheets
from .capture_extract import matches_r9
from .fill_round2 import second_reading, to_write_plan
from .osm_match import norm

CONFIG = Path(__file__).resolve().parents[2] / "config/grok_value_map.toml"
RESULTS = "Grok Results"
ALIASES = {
    "Can Park?": fill.CAN_PARK,
    "Parking Control Type": "Parking Control Type (Cameras / Barrier / Patrol)",
    "PCN amount (£)": "PCN (Penalty Charge Notice) amount (£)",
    "Evidence Detail": "Evidence Detail (what the source shows)",
    "Source URLs": "Source URLs (primary first)",
    "Proposed Result": "Verification Result",
    "Researched Date": "Verified Date",
}
IGNORED = {"Place ID", "Location Name", "Fields Found", "Minutes Spent", "_sheet_row"}
RESULT_COLUMNS = ["Place ID", "Location Name", "Can Park?", "Who Can Park", "Location Status",
                  "Rules Summary", "Cost Type", "Price Status", "Tariff Type", "Tariff Detail",
                  "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)", "Hours Basis",
                  "Parking Control Type", "Operator", "PCN amount (£)", "Evidence Type",
                  "Evidence Detail", "Source URLs", "Source Tier", "Specificity", "Rules Stated",
                  "Prices Stated", "Evidence Age", "Agreeing Sources", "Conflict", "Evidence Level",
                  "Notes", "Review Flag", "Decision Reason", "Proposed Result", "Fields Found",
                  "Minutes Spent", "Researched Date"]
PRICE = r"£\d+\.\d{2}"
NUMBER = r"\d+(?:\.\d+)?"
BAND = re.compile(rf"({NUMBER})-({NUMBER}) (hrs|mins) ({PRICE})")
HOURLY_FREE = re.compile(rf"Free for \d+ mins, then {PRICE} per hour")
OFFICIAL = page_fill.STRONG_SOURCE_TIERS - {"Google Maps - tariff photo"}


def load_config(path=CONFIG):
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def valid_bands(text):
    parts = text.split("; ")
    previous = None
    for part in parts:
        match = BAND.fullmatch(part)
        if not match:
            return False
        lo, hi = Decimal(match[1]), Decimal(match[2])
        if match[3] == "hrs":
            lo, hi = lo * 60, hi * 60
        if hi <= lo or (previous is not None and lo != previous):
            return False
        previous = hi
    return bool(parts)


def valid_tariff(text):
    return bool(text in {"Free", "Not published", "Not applicable"}
                or re.fullmatch(r"Free for up to \d+(?:\.\d+)? (?:hrs|mins)", text)
                or HOURLY_FREE.fullmatch(text)
                or re.fullmatch(rf"{PRICE} per (?:hour|24 hours|night)", text)
                or valid_bands(text))


def append_text(existing, extra):
    return " | ".join(x for x in (existing, extra) if x)


def out_of_scope_reason(source, target):
    """Require an explicit scope marker and HGV/coach wording, not a name guess."""
    for row in (source, target):
        for column in ("Notes", "Review Flag"):
            text = str(row.get(column, "")).replace(chr(8211), "-").replace(chr(8212), "-")
            if (re.search(r"\bout[\s-]+of[\s-]+scope\b", text, re.I)
                    and re.search(r"\b(?:HGVs?|coaches|coach)\b", text, re.I)):
                return "scope: HGV/coach explicitly marked out of scope"
    return ""


def site_identity_supported(source, target):
    evidence = norm(source.get("Evidence Detail", "") + " " + source.get("Source URLs", ""))
    name = norm(source.get("Location Name", ""))
    postcode = norm(target.get("Postcode", ""))
    generic = {"car park", "parking", "station", "unknown", "main car park", "visitor car park"}
    return bool((len(name) >= 6 and name not in generic and name in evidence)
                or (len(postcode) >= 5 and postcode in evidence))


def map_values(source, target, config):
    mapped = {k: str(source.get(k, "")) for k in RESULT_COLUMNS if k not in IGNORED}
    changes, errors = [], []

    def change(column, value, rule):
        old = mapped.get(column, "")
        if old != value:
            mapped[column] = value
            changes.append({"Rule": rule, "Column": column, "Before": old, "After": value})

    def note(text, rule):
        change("Notes", append_text(mapped["Notes"], text), rule)

    for column, values in config["direct"].items():
        old = mapped[column]
        if old in values:
            change(column, values[old], f"{column}: {old}")
    rules = config["conditional"]
    if mapped["Source Tier"] == rules["other_source"]:
        if source.get("Fields Found") == "None":
            change("Source Tier", "None found", "Source Tier: Other with no fields")
        else:
            errors.append("mapping: Other source with fields requires review")

    detail = mapped["Tariff Detail"]
    daily = re.fullmatch(config["tariff_patterns"]["daily"], detail)
    free_hourly = re.fullmatch(config["tariff_patterns"]["free_hourly"], detail)
    free_bands = re.fullmatch(config["tariff_patterns"]["free_bands"], detail)
    if daily:
        change("Tariff Detail", f"£{Decimal(daily[1]):.2f} per 24 hours", "Tariff Detail: per day")
    elif free_hourly:
        change("Tariff Detail", f"Free for {free_hourly[1]} mins, then {free_hourly[2]}",
               "Tariff Detail: remove up to before hourly")
    elif free_bands and valid_bands(free_bands[2]):
        change("Tariff Detail", free_bands[2], "Tariff Detail: free prefix before bands")
        note(f"Free for first {free_bands[1]} mins", "Notes: free period before bands")

    if mapped["Tariff Type"] == rules["flat_rate"]:
        if detail.endswith(("per day", "per 24 hours")):
            change("Tariff Type", "Flat rate per 24 hours", "Tariff Type: Flat rate daily")
        else:
            errors.append("mapping: Flat rate without an explicit daily period")
    if mapped["Tariff Type"] == rules["free_period"]:
        if HOURLY_FREE.fullmatch(mapped["Tariff Detail"]):
            change("Tariff Type", "Free period, then hourly", "Tariff Type: Free period then paid hourly")
        else:
            errors.append("mapping: Free period then paid does not match hourly template")
    if mapped["Parking Control Type"] in rules["payment_controls"]:
        original = mapped["Parking Control Type"]
        change("Parking Control Type", "Not published", f"Parking Control Type: {original}")
        note(f"Payment: {original.lower()}", f"Notes: payment {original}")
    if mapped["Specificity"] == rules["unclear_specificity"]:
        official_site = mapped["Source Tier"] in OFFICIAL and site_identity_supported(source, target)
        change("Specificity", "Site-specific" if official_site else "Area only", "Specificity: Unclear")
    if mapped["Evidence Type"] == rules["conflicting_evidence"]:
        change("Evidence Type", "Official site: partial info", "Evidence Type: Conflicting sources")
        change("Conflict", "Yes", "Conflict: conflicting evidence")
    if mapped["Evidence Type"] == rules["forum_evidence"]:
        if mapped["Source Tier"] in OFFICIAL:
            change("Evidence Type", "Official site: partial info", "Evidence Type: forum with official source")
        else:
            change("Evidence Type", "No info found", "Evidence Type: forum only")
            change("Review Flag", append_text(mapped["Review Flag"], "Forum evidence only"),
                   "Review Flag: forum only")
    if (mapped["Source Tier"] in rules.get("third_party_sources", [])
            and source.get("Fields Found", "").strip().lower() not in {"", "none"}):
        change("Evidence Type", "Third-party only", "Evidence Type: weak source with fields")
    # A route label identifies this importer, without inventing a research route A-E.
    if mapped["Decision Reason"] and "Route" not in mapped["Decision Reason"]:
        change("Decision Reason", "Route Grok detail pass: " + mapped["Decision Reason"],
               "Decision Reason: importer route label")

    new = {ALIASES.get(k, k): v for k, v in mapped.items()}
    new["Verified By"] = "Grok (detail pass)"
    for column in ("Notes", "Review Flag"):
        new[column] = append_text(target.get(column, ""), new[column])
    new["Source URLs (primary first)"] = " ; ".join(dict.fromkeys(
        part.strip() for text in (new["Source URLs (primary first)"], target.get("Source URLs (primary first)", ""))
        for part in text.split(";") if part.strip()))
    if new["Review Flag"]:
        new["Flag Status"] = "Open"
    for source_column in config.get("normalization", {}).get("free_text_columns", []):
        column = ALIASES.get(source_column, source_column)
        before = new[column]
        after = before.replace(chr(8211), "-").replace(chr(8212), "-")
        if before != after:
            new[column] = after
            changes.append({"Rule": f"Typography: {source_column}", "Column": source_column,
                            "Before": before, "After": after})
    # Location Status is explicitly permitted by this task. fill's identity lock
    # is intentionally stricter for OSM fills; all other columns use its guard.
    fill.assert_not_protected({k: v for k, v in new.items() if k != "Location Status"})
    return new, changes, errors


def validate(source, new, config, today):
    errors = list(page_fill.consistency_checks(new))
    for column, allowed in config["dropdowns"].items():
        if column in new and new[column] not in allowed:
            errors.append(f"dropdown: {column}={new[column]!r}")
    for column, value in new.items():
        if any(c in str(value) for c in (chr(8211), chr(8212))):
            errors.append(f"typography: non-plain dash in {column}")
    if not valid_tariff(new["Tariff Detail"]):
        errors.append("tariff: unrecognised Tariff Detail template")
    can, who, tier = new[fill.CAN_PARK], new["Who Can Park"], new["Source Tier"]
    strong = tier in page_fill.STRONG_SOURCE_TIERS
    site_strong = strong and new["Specificity"] == "Site-specific"
    if can == "Yes" and (who not in {"Anyone", "Anyone (paid)"} or not strong
                         or new["Verification Result"] == "Needs on-site check"):
        errors.append("safety: Yes requires public access, strong source and no on-site check")
    if new["Evidence Level"] == "Verified" and not strong:
        errors.append("safety: Verified requires strong source")
    if new["Evidence Level"] == "Verified" and new["Specificity"] != "Site-specific":
        errors.append("safety: Verified requires site-specific evidence")
    if source.get("Fields Found") == "None" and new["Evidence Level"] != "Presumed":
        errors.append("safety: Fields Found None requires Presumed")
    risky = (new["Cost Type"] == "Free" or can == "Yes" or who in {"Anyone", "Anyone (paid)"}
             or "£" in new["Tariff Detail"])
    if risky and not site_strong:
        errors.append("safety: free, public access or prices require strong site-specific evidence")
    if risky and source.get("Fields Found") == "None":
        errors.append("safety: Fields Found None cannot establish free, public access or prices")
    max_stay = new["Max Stay (mins)"]
    if max_stay not in {"Not published", "Not applicable", "No limit"} and not re.fullmatch(r"\d+", max_stay):
        errors.append("numeric: Max Stay must be whole minutes or an allowed marker")
    if max_stay not in {"Not published", "Not applicable"} and not site_strong:
        errors.append("safety: max stay requires strong site-specific evidence")
    pcn = new["PCN (Penalty Charge Notice) amount (£)"]
    if pcn not in {"Not published", "Not applicable"} and not re.fullmatch(r"\d+(?:\.\d{1,2})?", pcn):
        errors.append("numeric: invalid PCN amount")
    if new["Agreeing Sources"] not in {"0", "1", "2", "3"}:
        errors.append("numeric: Agreeing Sources must be 0-3")
    try:
        researched = date.fromisoformat(new["Verified Date"])
        if researched.isoformat() != new["Verified Date"] or researched > today:
            raise ValueError
    except ValueError:
        errors.append("date: invalid or future Researched Date")
    if new["Location Status"] == "Closed" and can != "No":
        errors.append("consistency: Closed requires Can Park No")
    if new["Cost Type"] == "Free" and new["Tariff Type"] not in {
            "Free (time limit not published)", "Free with time limit"}:
        errors.append("consistency: Free requires a free-only Tariff Type")
    if new["Cost Type"] == "Free then paid" and new["Tariff Type"] == "Banded by stay length":
        first = BAND.fullmatch(new["Tariff Detail"].split("; ")[0])
        if not ((first and Decimal(first[4][1:]) == 0) or re.search(r"Free for first \d+ mins", new["Notes"])):
            errors.append("consistency: Free then paid bands require an explicit free period")
    if can == "No" and (not site_strong or not matches_r9(new["Evidence Detail (what the source shows)"])):
        errors.append("safety: No requires an explicit site-specific no-parking statement")
    if strong and (not source.get("Evidence Detail", "").strip() or not any(
            urlparse(u.strip()).scheme in {"http", "https"} and urlparse(u.strip()).netloc
            for u in source.get("Source URLs", "").split(";"))):
        errors.append("evidence: strong source lacks detail or URL")
    if new["Conflict"] == "Yes" and not new["Review Flag"]:
        errors.append("consistency: Conflict Yes requires a Review Flag")
    if new["Verification Result"] == "Confirmed" and (not site_strong or any(new[c] in {
            "Not published", "Unknown", ""} for c in ("Who Can Park", "Max Stay (mins)",
            "Hours (OpenStreetMap opening_hours format)"))):
        errors.append("consistency: Confirmed requires complete strong evidence")
    detail = new["Tariff Detail"]
    expected_type = {"Free": "Free (time limit not published)", "Not published": "Not published",
                     "Not applicable": "Not applicable"}.get(detail)
    if re.fullmatch(r"Free for up to \d+(?:\.\d+)? (?:hrs|mins)", detail):
        expected_type = "Free with time limit"
    elif HOURLY_FREE.fullmatch(detail):
        expected_type = "Free period, then hourly"
    elif re.fullmatch(rf"{PRICE} per hour", detail):
        expected_type = "Hourly rate"
    elif re.fullmatch(rf"{PRICE} per 24 hours", detail):
        expected_type = "Flat rate per 24 hours"
    elif re.fullmatch(rf"{PRICE} per night", detail):
        expected_type = "Flat rate per night"
    elif valid_bands(detail):
        expected_type = "Banded by stay length"
    if expected_type and new["Tariff Type"] != expected_type:
        errors.append("tariff: Tariff Type disagrees with Tariff Detail")
    return list(dict.fromkeys(errors))


def indexed(rows, label):
    index, duplicates = {}, set()
    for row in rows:
        pid = row.get("Place ID", "")
        if not pid.strip():
            continue
        if pid in index:
            duplicates.add(pid)
        index[pid] = row
    return index, duplicates


def mapping_rules(config):
    names = [f"{column}: {old}" for column, values in config["direct"].items() for old in values]
    names += [name for control in config["conditional"]["payment_controls"]
              for name in (f"Parking Control Type: {control}", f"Notes: payment {control}")]
    names += ["Source Tier: Other with no fields", "Tariff Detail: per day",
              "Tariff Detail: remove up to before hourly", "Tariff Detail: free prefix before bands",
              "Notes: free period before bands", "Tariff Type: Flat rate daily",
              "Tariff Type: Free period then paid hourly", "Specificity: Unclear",
              "Evidence Type: Conflicting sources", "Conflict: conflicting evidence",
              "Evidence Type: forum with official source", "Evidence Type: forum only",
              "Review Flag: forum only", "Decision Reason: importer route label"]
    names += ["Evidence Type: weak source with fields"]
    names += [f"Typography: {c}" for c in config.get("normalization", {}).get("free_text_columns", [])]
    return names


def build_plan(headers, rows, result_headers, results, config=None, today=None, verified_by="Grok (detail pass)"):
    config = config or load_config()
    today = today or datetime.now(ZoneInfo("Europe/London")).date()
    if len(headers) != len(set(headers)) or len(result_headers) != len(set(result_headers)):
        raise ValueError("Duplicate input headers")
    if not set(RESULT_COLUMNS).issubset(result_headers):
        raise ValueError("Missing Grok Results headers")
    required = {ALIASES.get(k, k) for k in RESULT_COLUMNS if k not in IGNORED} | {"Place ID", "Verified By", "Flag Status"}
    if not required.issubset(headers):
        raise ValueError(f"Missing main-sheet headers: {sorted(required - set(headers))}")
    main, duplicates = indexed(rows, "main")
    _, result_duplicates = indexed(results, "results")
    candidates, skipped, rejects, audit, mapped_rows, out_of_scope = {}, [], [], [], [], []
    for source in results:
        pid = source.get("Place ID", "")
        base = {"Place ID": pid, "Location Name": source.get("Location Name", "")}
        target = main.get(pid)
        if pid in duplicates or pid in result_duplicates or not pid or pid != pid.strip() or target is None:
            rejects.append({**base, "Reasons": ["identity: missing, duplicate or unknown Place ID"]})
            continue
        scope = out_of_scope_reason(source, target)
        if scope:
            record = {**base, "Reasons": [scope]}
            rejects.append(record)
            out_of_scope.append(record)
            continue
        finished = bool(str(target.get("Verification Result", "")).strip())
        human = target.get("Verified By", "") not in config["reviewers"]["automation"]
        if finished or human:
            skipped.append({**base, "Reasons": [r for r, yes in (
                ("finished", finished), ("person or unrecognised reviewer", human)) if yes]})
            continue
        new, changes, errors = map_values(source, target, config)
        new["Verified By"] = verified_by
        errors.extend(validate(source, new, config, today))
        errors = list(dict.fromkeys(errors))
        for c in changes:
            audit.append({**base, **c, "Disposition": "rejected" if errors else "candidate"})
        mapped_rows.append({**base, "before": {k: source.get(k, "") for k in RESULT_COLUMNS},
                            "after": new, "errors": errors})
        if errors:
            rejects.append({**base, "Reasons": errors})
        else:
            candidates[pid] = (target, new)
    clean, failures = second_reading(candidates, "grok_import")
    for failure in failures:
        rejects.append({"Place ID": failure["Place ID"], "Location Name": failure["Location Name"],
                        "Reasons": ["second reading: " + failure["Violations"]]})
    plan, undo = to_write_plan(clean)
    accepted = set(clean)
    for change in audit:
        if change["Place ID"] in accepted:
            change["Disposition"] = "accepted"
    all_counts = Counter(e["Rule"] for e in audit)
    accepted_counts = Counter(e["Rule"] for e in audit if e["Disposition"] == "accepted")
    return {"plan": plan, "undo": undo, "skipped": skipped, "rejects": rejects, "out_of_scope": out_of_scope,
            "mapping_audit": audit, "mapped_rows": mapped_rows,
            "second_reading": {"checked": len(candidates), "failures": failures},
            "report": {"source_rows": len(results), "accepted": len(plan), "skipped": len(skipped),
                       "rejected": len(rejects),
                       "out_of_scope": len(out_of_scope),
                       "accepted_by_result": dict(Counter(e["new"]["Verification Result"] for e in plan)),
                       "skipped_by_reason": dict(Counter(r for e in skipped for r in e["Reasons"])),
                       "rejected_by_reason": dict(Counter(r for e in rejects for r in e["Reasons"])),
                       "mapping_counts": {k: all_counts[k] for k in mapping_rules(config)},
                       "accepted_mapping_counts": {k: accepted_counts[k] for k in mapping_rules(config)}}}


def save_json(path, value):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(value, f, indent=2, ensure_ascii=True)


def save_csv(path, columns, rows):
    with Path(path).open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: str(v).replace(chr(8211), "-").replace(chr(8212), "-") for k, v in row.items()})


def dropdown_plan(snapshot, config):
    headers = snapshot["tabs"][sheets.TAB][0]
    live = {}
    for sheet in snapshot.get("validations", {}).get("sheets", []):
        if sheet["properties"]["title"] != sheets.TAB:
            continue
        for grid in sheet.get("data", []):
            start = grid.get("startColumn", 0)
            for row in grid.get("rowData", []):
                for index, cell in enumerate(row.get("values", []), start=start):
                    condition = cell.get("dataValidation", {}).get("condition", {})
                    if index < len(headers) and condition.get("type") == "ONE_OF_LIST":
                        values = [v["userEnteredValue"] for v in condition.get("values", [])]
                        if headers[index] in live and live[headers[index]] != values:
                            raise ValueError(f"Inconsistent live dropdown: {headers[index]}")
                        live[headers[index]] = values
    if not live:
        raise ValueError("Snapshot lacks live dropdown validation; read it before planning")
    for column, allowed in config["dropdowns"].items():
        if column not in live:
            raise ValueError(f"Missing live dropdown validation: {column}")
        extensions = {"Evidence Level": {"Reported"}, "Evidence Type": {"Third-party only"}}
        wanted = set(allowed) - extensions.get(column, set())
        if not wanted.issubset(live[column]):
            raise ValueError(f"Config differs from live dropdown: {column}")
    changes = []
    for column, addition in (("Evidence Level", "Reported"), ("Evidence Type", "Third-party only")):
        before = live[column]
        changes.append({"tab": sheets.TAB, "column": column, "before": before,
                        "after": list(dict.fromkeys(before + [addition])), "apply": False,
                        "action": f"extend ONE_OF_LIST with {addition}, preserving existing validation",
                        "required": addition not in before})
    return {**changes[0], "changes": [c for c in changes if c["required"]]}


def report_markdown(result, samples):
    report = result["report"]
    lines = ["# Grok importer dry run", "", "No sheet changes. No Skip column will be added.", "",
             f"Source rows: {report['source_rows']}; accepted: {report['accepted']}; "
             f"skipped: {report['skipped']}; rejected: {report['rejected']}.", "",
             "Accepted means proposed for import, not already written.", "",
             "## Proposed imports", "", "| Proposed Result | Rows |", "|---|---:|"]
    for key, count in report["accepted_by_result"].items():
        lines.append(f"| {key} | {count} |")
    lines += ["", "## Skipped rows", "", "Counts overlap when a finished row also has a person's name.", ""]
    for reason, count in report["skipped_by_reason"].items():
        lines.append(f"- {reason}: {count}")
    lines += ["", "## Reject reasons", "", "Rows may have multiple reasons. Rejected rows never enter plan.json.", "",
              "| Reason | Rows |", "|---|---:|"]
    for reason, count in sorted(report["rejected_by_reason"].items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"| {reason} | {count} |")
    lines += ["", "### Up to five samples for every remaining reject reason", ""]
    for reason in sorted(report["rejected_by_reason"]):
        lines += [f"#### {reason}", "", "| Place ID | Location Name |", "|---|---|"]
        for row in [r for r in result["rejects"] if reason in r["Reasons"]][:5]:
            lines.append(f"| {row['Place ID']} | {row['Location Name']} |")
        lines.append("")
    lines += ["", "## Values changed by mapping rule", "",
              "All mapped rows excludes finished/person-locked rows and includes rejects. Notes and flag",
              "side effects are counted separately. Accepted counts are the changes proposed for writing.", "",
              "| Mapping rule | All mapped rows | Accepted rows |", "|---|---:|---:|"]
    for rule, count in report["mapping_counts"].items():
        lines.append(f"| {rule} | {count} | {report['accepted_mapping_counts'][rule]} |")
    lines += ["", "## Ten sample before/after rows", "",
              "Before is Grok's value; after is the proposed main-sheet value. Full source, target undo,",
              "mapped rows and samples are saved separately as JSON. Long text remains in those files.", ""]
    for sample in samples:
        lines += [f"### {sample['Place ID']}: {sample['Location Name']}", "",
                  f"Proposed Result: {sample['after']['Verification Result']}.", "",
                  "| Column | Before | After |", "|---|---|---|"]
        for change in sample["changes"]:
            values = [change[k].replace("|", "\\|").replace("\n", " ") for k in ("Column", "Before", "After")]
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    lines += ["## Checks and approval boundary", "",
              "Every accepted row passed existing page_fill consistency checks and the existing",
              "fill_round2 second reading, plus importer dropdown, tariff, identity, reviewer,",
              "source-strength, specificity, date, numeric and typography checks.", "",
              f"Second reading: {result['second_reading']['checked']} candidates; "
              f"{len(result['second_reading']['failures'])} failures.", "",
              "The importer accepts Reported and Third-party only. validation_plan.json lists",
              "only the dropdown extensions still required; no validation or cell is changed by this dry run.", "",
              "Before apply, resolve Place IDs afresh and check locks and source/target snapshots.",
              "Use the existing writer, which writes Verification Result last. Require an independent",
              "full re-export comparison with zero mismatches after applying. Do not use the generic",
              "write command directly on stale saved row numbers."]
    return "\n".join(lines).replace(chr(8211), "-").replace(chr(8212), "-") + "\n"


def prepare(snapshot, out, config_path=CONFIG, only_ids=None):
    config = load_config(config_path)
    tabs = snapshot["tabs"]
    headers, rows = tabs[sheets.TAB]
    result_headers, all_results = tabs[RESULTS]
    results = all_results
    if only_ids is not None:
        only_ids = set(only_ids)
        missing = only_ids - {r.get("Place ID") for r in all_results}
        if missing:
            raise ValueError(f"Requested reject IDs missing from live results: {sorted(missing)}")
        results = [r for r in all_results if r.get("Place ID") in only_ids]
    validation = dropdown_plan(snapshot, config)
    result = build_plan(headers, rows, result_headers, results, config)
    result["report"]["selection"] = "original reject IDs only" if only_ids is not None else "all result rows"
    result["report"]["selected_ids"] = [r["Place ID"] for r in results]
    proposed = {e["place_id"]: e["new"] for e in result["plan"]}
    simulated_rows = [{**r, **proposed.get(r.get("Place ID"), {})} for r in rows]
    rerun = build_plan(headers, simulated_rows, result_headers, results, config)
    if rerun["plan"]:
        raise ValueError("Rerun simulation unexpectedly proposes further writes")
    result["report"]["rerun_simulation"] = {"accepted": len(rerun["plan"]),
                                            "skipped": len(rerun["skipped"]),
                                            "rejected": len(rerun["rejects"])}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    save_json(out / "snapshot.json", snapshot)
    save_json(out / "value_map.json", config)
    for key in ("plan", "undo", "report", "second_reading", "mapped_rows"):
        save_json(out / f"{key}.json", result[key])
    for key, filename in (("rejects", "grok_rejects.csv"), ("skipped", "grok_skipped.csv"),
                          ("out_of_scope", "out_of_scope.csv")):
        save_csv(out / filename, ["Place ID", "Location Name", "Reasons"], [
            {**r, "Reasons": "; ".join(r["Reasons"])} for r in result[key]])
    main, _ = indexed(rows, "main")
    selected_ids = {r["Place ID"] for r in results}
    previous_scope = [{"Place ID": r["Place ID"], "Location Name": r["Location Name"],
                       "Reasons": out_of_scope_reason(r, main.get(r["Place ID"], {}))}
                      for r in all_results if r["Place ID"] not in selected_ids
                      and main.get(r["Place ID"], {}).get("Verified By") == "Grok (detail pass)"
                      and out_of_scope_reason(r, main.get(r["Place ID"], {}))]
    save_csv(out / "previously_imported_out_of_scope.csv", ["Place ID", "Location Name", "Reasons"], previous_scope)
    save_json(out / "scope_audit.json", {"excluded_from_this_plan": result["out_of_scope"],
              "previously_imported": previous_scope, "note": "Finished rows are reported only; no rollback is proposed or applied"})
    save_csv(out / "mapping_audit.csv", ["Place ID", "Location Name", "Rule", "Column", "Before", "After", "Disposition"], result["mapping_audit"])
    undo = {e["place_id"]: e["old"] for e in result["undo"]}
    dry = [{"Place ID": e["place_id"], "Location Name": e["name"], "Column": column,
            "Before": undo[e["place_id"]][column], "After": value} for e in result["plan"] for column, value in e["new"].items()]
    save_csv(out / "dry_run.csv", ["Place ID", "Location Name", "Column", "Before", "After"], dry)
    # The live dropdown must explicitly accept Reported before any such row is applied.
    save_json(out / "validation_plan.json", validation)
    accepted_ids = {e["place_id"] for e in result["plan"]}
    remaining = [r for r in result["mapped_rows"] if r["Place ID"] in accepted_ids]
    samples, seen_rules = [], set()
    while remaining and len(samples) < 10:
        selected = max(remaining, key=lambda r: len({c["Rule"] for c in result["mapping_audit"]
                       if c["Place ID"] == r["Place ID"]} - seen_rules))
        changes = [c for c in result["mapping_audit"] if c["Place ID"] == selected["Place ID"]]
        samples.append({**selected, "changes": changes})
        seen_rules.update(c["Rule"] for c in changes)
        remaining.remove(selected)
    save_json(out / "samples.json", samples)
    with (out / "report.md").open("x", encoding="utf-8") as f:
        f.write(report_markdown(result, samples))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--rejects-from", type=Path, help="Limit dry run to Place IDs in a prior grok_rejects.csv")
    args = parser.parse_args(argv)
    if args.snapshot:
        snapshot = json.loads(args.snapshot.read_text())
    else:
        service = sheets.get_service()
        snapshot = {"tabs": {tab: sheets.read_tab(service, tab=tab) for tab in (RESULTS, sheets.TAB)}}
        snapshot["validations"] = service.spreadsheets().get(
            spreadsheetId=sheets.SPREADSHEET_ID, ranges=[f"'{sheets.TAB}'!2:3"],
            fields="sheets(properties.title,data(startRow,startColumn,rowData(values(dataValidation))))").execute()
    today = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
    out = args.out or Path("data/runs") / today / "grok_import"
    only_ids = None
    if args.rejects_from:
        with args.rejects_from.open(encoding="utf-8", newline="") as f:
            only_ids = {r["Place ID"] for r in csv.DictReader(f)}
    result = prepare(snapshot, out, only_ids=only_ids)
    print(json.dumps(result["report"], indent=2, ensure_ascii=True))
    print(f"Dry run only: {out}. Nothing written to Sheets. Awaiting go.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
