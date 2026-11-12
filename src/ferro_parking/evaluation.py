"""Offline, field-level reference evaluation. Human labels are never truth by default.

Run with ``python -m ferro_parking.evaluation --input bundle.json --out NEW_DIR``.
Add ``--replay KEY`` to run one registered fetcher over the frozen pages and
score its own answers. The replayed extractor receives the allowlisted
identity and the frozen page only, so no reference answer and no reviewer note
can reach it. The command prints supported accuracy per field with its
denominator.
This diagnostic does not authorise database or Sheet applies. Identity binding
to an actual mutation plan remains a separate required control.
The bundle supplies original/clean/database rows, explicit field assessments,
frozen source pages and extractor answers. No network or database writes occur.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .sync import normalize_name, normalize_postcode, split_address
from .run_paths import reserve_output

FIELDS = (
    "Can Park? (Yes/No/Conditional)", "Who Can Park", "Cost Type", "Tariff Detail",
    "Max Stay (mins)", "Hours (OpenStreetMap opening_hours format)", "Rules Summary",
)
STATUSES = {"supported", "unsupported", "conflicting", "unresolved"}
ABSTENTIONS = {"", "unknown", "not published", "not stated", "unclear", "unresolved"}


def is_abstention(value):
    return value is None or str(value).strip().casefold() in ABSTENTIONS
IDENTITY_FIELDS = ("Location Name", "Street Address", "Postcode", "Latitude", "Longitude", "Place ID")


def snapshot(rows, *, title, retrieved_at):
    """Preserve every source cell, including reviewer notes and original labels."""
    saved = deepcopy(rows)
    digest = hashlib.sha256(json.dumps(saved, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"title": title, "retrieved_at": retrieved_at, "sha256": digest, "rows": saved}


def _identity(row):
    name = normalize_name(row.get("Location Name") or row.get("sheet", ""))
    _, extracted = split_address(row.get("Address / Postcode", ""))
    postcode = normalize_postcode(row.get("Postcode") or extracted)
    return name, postcode


def reconcile(reference_rows, target_rows):
    """Unique identity joins only. Ambiguous and reused targets remain unresolved."""
    proposals = []
    for number, row in enumerate(reference_rows):
        pid = row.get("Place ID")
        name, postcode = _identity(row)
        candidates = []
        for index, target in enumerate(target_rows):
            other_name, other_postcode = _identity(target)
            other_pid = target.get("Place ID")
            if pid and other_pid and pid != other_pid:
                continue
            if postcode and other_postcode and postcode != other_postcode:
                continue
            if (pid and pid == other_pid) or (name and name == other_name):
                candidates.append(index)
        proposals.append({"reference_index": number, "candidate_indices": candidates})
    counts = Counter(p["candidate_indices"][0] for p in proposals if len(p["candidate_indices"]) == 1)
    for item in proposals:
        candidates = item["candidate_indices"]
        unique = len(candidates) == 1 and counts[candidates[0]] == 1
        item.update(status="mapped" if unique else "unresolved", target_index=candidates[0] if unique else None)
    return proposals


def extractor_input(identity, source):
    """Allowlist identity; expected answers and human notes cannot leak."""
    return {"identity": {key: identity.get(key, "") for key in IDENTITY_FIELDS},
            "source": {key: source.get(key, "") for key in ("url", "retrieved_at", "sha256", "text")}}


def replay(cases, extractor):
    """Replay an extractor on frozen pages with only allowlisted identity data.

    The extractor returns a mapping of field names to answers. Reviewer claim
    support stays separate and must be supplied after reviewing these answers.
    """
    replayed = deepcopy(cases)
    for case in replayed:
        source = case.get("source", {})
        digest = hashlib.sha256(source.get("text", "").encode()).hexdigest()
        if source.get("sha256") != digest:
            raise ValueError("Frozen source hash mismatch")
        request = extractor_input(case.get("identity", {}), source)
        case["answers"] = dict(extractor(request))
        case["answer_source_sha256"] = digest
        # A previous answer's support cannot certify a newly extracted answer.
        case["claim_support"] = {}
    return replayed


def assess_reference(reference, assessment, source):
    """A supported field needs explicit site evidence from the frozen version.

    Assessment is a separate reviewer artifact, never inferred from row labels.
    Literal quote presence is necessary but not sufficient: the reviewer must
    explicitly attest exact claim and site support.
    """
    status = assessment.get("status", "unresolved")
    if status not in STATUSES:
        raise ValueError(f"Invalid reference status: {status}")
    if status == "supported":
        quote = assessment.get("quote", "")
        valid = (not is_abstention(reference)
                 and isinstance(quote, str) and quote.strip() and quote in source.get("text", "")
                 and source.get("url") and source.get("retrieved_at")
                 and source.get("http_status", 200) == 200
                 and source.get("blocked", False) is False
                 and assessment.get("exact_site") is True
                 and assessment.get("supports_claim") is True
                 and assessment.get("source_sha256") == source.get("sha256")
                 and assessment.get("value") == reference)
        if not valid:
            return "unresolved"
    return status


def evaluate(cases):
    """Score only supported references; expose disputes and abstention coverage."""
    totals = {field: Counter() for field in FIELDS}
    details = []
    blockers = []
    for case in cases:
        source = case.get("source", {})
        text = source.get("text", "")
        actual_hash = hashlib.sha256(text.encode()).hexdigest()
        if source.get("sha256") != actual_hash:
            raise ValueError("Frozen source hash mismatch")
        for field in FIELDS:
            count = totals[field]
            count["total"] += 1
            expected = case.get("reference", {}).get(field, "")
            answer = case.get("answers", {}).get(field, "")
            assessment = case.get("assessments", {}).get(field, {})
            status = assess_reference(expected, assessment, source)
            claim = case.get("claim_support", {}).get(field, {})
            supported_claim = assess_reference(answer, claim, source) == "supported"
            drift = case.get("answer_source_sha256", actual_hash) != actual_hash
            if drift:
                outcome = "source_drift"
            elif status != "supported":
                outcome = "unevaluable"
            elif is_abstention(answer):
                outcome = "abstention"
            elif str(answer) == str(expected) and supported_claim:
                outcome = "correct"
            else:
                outcome = "wrong"
            count[status] += 1
            count[outcome] += 1
            if status == "supported" and not drift:
                count["accuracy_denominator"] += 1
                if not is_abstention(answer) and supported_claim:
                    count["answered_supported"] += 1
                # A fresh replay has no attestation for its own answers yet, so
                # every answer scores wrong until a reviewer reads it. This
                # counts the plain agreement with the supported reference, so a
                # replay still says something before that review happens.
                if str(answer) == str(expected):
                    count["matched_reference"] += 1
            # Unsupported assertions still matter even when the reference is disputed.
            positive = not is_abstention(answer)
            if positive and not supported_claim and not drift:
                count["unsupported_positive"] += 1
            critical = field in FIELDS[:5] and positive and (outcome == "wrong" or not supported_claim) and not drift
            if critical:
                blockers.append({"case_id": case["case_id"], "field": field})
            details.append({"case_id": case["case_id"], "field": field,
                            "reference_status": status, "outcome": outcome, "answer": answer})
    summary = {}
    for field, counts in totals.items():
        values = dict(counts)
        denom = counts["accuracy_denominator"]
        values["supported_answer_coverage"] = counts["answered_supported"] / denom if denom else None
        values["accuracy"] = counts["correct"] / denom if denom else None
        values["reference_match"] = counts["matched_reference"] / denom if denom else None
        summary[field] = values
    return {"fields": summary, "details": details, "critical_blockers": blockers,
            "evaluation_checks_passed": bool(cases) and not blockers
            and not any(c["wrong"] or c["unsupported_positive"] or c["source_drift"] for c in totals.values())
            and any(
                counts["correct"] for counts in totals.values()), "benchmark": "regression reference, not unseen holdout"}


def fetcher_extractor(key):
    """An extractor that answers from a frozen page with one registered fetcher.

    It receives the allowlisted request only, so the reference answers, the
    reviewer notes and the row's own existing values never reach it."""
    from .fetch_fill import CACHE_ONLY, REGISTRY

    if key in CACHE_ONLY:
        raise SystemExit(f"{key!r} is cache only and answers nothing.")
    fetcher = REGISTRY.get(key)
    if fetcher is None:
        raise SystemExit(f"No fetcher registered for {key!r}. "
                         f"Registered: {', '.join(sorted(REGISTRY))}")

    def answer(request):
        values = fetcher.values(request["source"]["text"], request["identity"])[0]
        return {field: values.get(field, "") for field in FIELDS}
    return answer


def accuracy_report(report):
    """One line per field: the supported denominator and what it scored."""
    out = []
    for field, counts in report["fields"].items():
        denominator = counts.get("accuracy_denominator", 0)
        accuracy = counts.get("accuracy")
        match = counts.get("reference_match")
        scored = "no supported reference" if accuracy is None else f"{accuracy:.0%}"
        agreed = "" if match is None else f", agrees with the reference {match:.0%}"
        out.append(f"{field}: {scored} of {denominator} supported "
                   f"({counts.get('correct', 0)} correct, {counts.get('wrong', 0)} wrong, "
                   f"{counts.get('abstention', 0)} abstained{agreed})")
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--replay", metavar="KEY",
                        help="Replay this registered fetcher over the frozen pages "
                             "and score its own answers, instead of the bundle's.")
    args = parser.parse_args(argv)
    bundle = json.loads(Path(args.input).read_text())
    cases = bundle.get("cases", [])
    if args.replay:
        cases = replay(cases, fetcher_extractor(args.replay))
        bundle = {**bundle, "cases": cases, "replayed_with": args.replay}
    report = evaluate(cases)
    report["replayed_with"] = args.replay or ""
    report["original_to_clean"] = reconcile(bundle.get("original_rows", []), bundle.get("clean_rows", []))
    report["clean_to_database"] = reconcile(bundle.get("clean_rows", []), bundle.get("database_rows", []))
    out = reserve_output(args.out)
    (out / "reference_snapshot.json").write_text(json.dumps(bundle, indent=2, ensure_ascii=False))
    (out / "evaluation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if args.replay:
        print(f"Replayed {args.replay!r} over {len(cases)} frozen pages. "
              f"The extractor saw no reference answer and no reviewer note.")
    print("Supported accuracy per field, with the supported denominator:")
    for row in accuracy_report(report):
        print(f"  {row}")
    print(f"Reports in {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
