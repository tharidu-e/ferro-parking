"""Command line entry point: python -m ferro_parking <command> [options]

Commands:
  match   Stage 1: match sheet rows to OpenStreetMap and pick a research route
  export  Save the live sheet tab to data/raw/all_london_clean.csv
  fill    Stage 2-3: dry run fill for one borough (never writes to the sheet)
  capture-extract  Build extracted.jsonl for one borough from captured text (pattern match)
  capture-fill  Dry run fill from text already captured in the sheet (rule R8)
  write   Write a plan.json to the sheet (--apply to actually write)
  undo    Restore an undo.json to the sheet (--apply to actually write)
  sync    Dry run: find new rows in ALL LONDON not yet in ALL LONDON (clean)
          (never writes to the sheet)
  sync-apply  Append the sync plan to the clean tab's bottom (--apply to
          actually write; dry run reports the row range otherwise)
  evidence-level-column    Dry run: report where the Evidence Level column
          would go (--apply to write only the header and dropdown)
  evidence-level-backfill  Dry run: plan Evidence Level for finished rows
  policy-fill  Dry run: cautious chain-policy / presumed-no-parking rows
          for one borough (rule R10, never writes to the sheet)
  clear-unverified  Plan to blank unverified answers; apply requires both
          --apply and --confirm-wipe
  discover  Read-only: fetch official/source candidates, London filter, dedupe and draft
  validate  Check a plan.json or candidates.csv without network access
  propose-categories  Read-only: propose category values from captured types
  fill-postcodes  Read-only: propose postcodes from a local centroid directory
  triage-blanks  Read-only: bucket blank parking answers from a local CSV
  readiness  Read-only: count showable and complete rows, by borough and district
  osm-gaps  Read-only: list unmatched public/customer parking from a London PBF
  db-import  Load a sheet export into the local SQLite store (no sheet access)
  db-export  Write the store back out as a sheet CSV in sheet column order
  db-rebuild  Recompute the derived places and parking tables from raw
  route  Give every row one research stage, write the routing table and
          data/runs/<date>/route/routing.csv (never writes to the sheet)
  db-apply  Apply a JSON lines plan file to the database (dry run unless
          --apply; any refusal blocks the whole plan)
  db-undo  Undo one run of applied database changes (dry run unless --apply)
  grok-import  Turn an export of the bot's results tab into a plan file
  default-fill  Dry run: the category default (R1, R10) as a plan file, for
          rows the latest routing run put on stage "default"
  tranche1  Read-only: filter and score discovery's tranche 1 missing
          places, ready for review before writing (never writes to the sheet)
  tranche1-write  Dry run: select, de-duplicate and plan the tranche 1
          append to the sheet (never writes to the sheet)
  tranche1-write-apply  Append the tranche1-write plan to the sheet's
          bottom (--apply to actually write; dry run reports the plan
          otherwise)
  fill-round2  Dry run: osm fill, capture fill, policy fill and a draft
          category policy on every blank-Verification-Result row, each
          pass checked against page_fill's consistency checks (never
          writes to the sheet)
"""
import csv
import sys
from pathlib import Path


def cmd_export(argv):
    from . import sheets
    service = sheets.get_service()
    headers, rows = sheets.read_tab(service)
    out = Path("data/raw/all_london_clean.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for row in rows:
            w.writerow({h: row.get(h, "") for h in headers})
    print(f"Wrote {len(rows)} rows to {out}")
    return 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, argv = sys.argv[1], sys.argv[2:]
    if cmd == "propose-categories":
        from .propose_categories import main as propose_main
        return propose_main(argv)
    if cmd == "fill-postcodes":
        from .fill_postcodes import main as postcodes_main
        return postcodes_main(argv)
    if cmd == "triage-blanks":
        from .triage_blanks import main as triage_main
        return triage_main(argv)
    if cmd == "readiness":
        from .readiness import main as readiness_main
        return readiness_main(argv)
    if cmd == "default-fill":
        from .category_default import main as default_fill_main
        return default_fill_main(argv)
    if cmd == "db-apply":
        from .plan import apply_main
        return apply_main(argv)
    if cmd == "db-undo":
        from .plan import undo_main
        return undo_main(argv)
    if cmd == "grok-import":
        from .plan import grok_import_main
        return grok_import_main(argv)
    if cmd == "route":
        from .route import main as route_main
        return route_main(argv)
    if cmd == "db-import":
        from .db import import_main
        return import_main(argv)
    if cmd == "db-export":
        from .db import export_main
        return export_main(argv)
    if cmd == "db-rebuild":
        from .db import rebuild_main
        return rebuild_main(argv)
    if cmd == "validate":
        from .validation import main as validate_main
        return validate_main(argv)
    if cmd == "osm-gaps":
        from .gaps import main as gaps_main
        return gaps_main(argv)
    if cmd == "match":
        from .osm_match import main as match_main
        return match_main(argv)
    if cmd == "export":
        return cmd_export(argv)
    if cmd == "fill":
        from .fill import main as fill_main
        return fill_main(argv)
    if cmd == "capture-extract":
        from .capture_extract import main as capture_extract_main
        return capture_extract_main(argv)
    if cmd == "capture-fill":
        from .capture_fill import main as capture_fill_main
        return capture_fill_main(argv)
    if cmd == "write":
        from .fill import write_main
        return write_main(argv)
    if cmd == "undo":
        from .fill import undo_main
        return undo_main(argv)
    if cmd == "sync":
        from .sync import main as sync_main
        return sync_main(argv)
    if cmd == "sync-apply":
        from .sync import apply_main
        return apply_main(argv)
    if cmd == "evidence-level-column":
        from .evidence_level import column_main
        return column_main(argv)
    if cmd == "evidence-level-backfill":
        from .evidence_level import backfill_main
        return backfill_main(argv)
    if cmd == "policy-fill":
        from .policy_fill import main as policy_fill_main
        return policy_fill_main(argv)
    if cmd == "clear-unverified":
        from .clear_unverified import main as clear_unverified_main
        return clear_unverified_main(argv)
    if cmd == "discover":
        from .discover import main as discover_main
        return discover_main(argv)
    if cmd == "tranche1":
        from .tranche1 import main as tranche1_main
        return tranche1_main(argv)
    if cmd == "tranche1-write":
        from .tranche1_write import main as tranche1_write_main
        return tranche1_write_main(argv)
    if cmd == "tranche1-write-apply":
        from .tranche1_write import apply_main as tranche1_write_apply_main
        return tranche1_write_apply_main(argv)
    if cmd == "fill-round2":
        from .fill_round2 import main as fill_round2_main
        return fill_round2_main(argv)
    print(f"Unknown command: {cmd}\n\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
