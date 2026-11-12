# Agent rules

Ferro parking serves real drivers. Accuracy takes priority over coverage.

- Read only documents needed for the task. Do not scan every document at startup.
- Read `docs/STATUS.md` for current work, then `docs/PLAN.md` for batch order and the code-change gate.
- Before proposing or building any capability, run `python -m ferro_parking --help`.
  It lists every command with one line each, generated from the code, so it cannot go stale.
  A capability already there is never rebuilt. This rule exists because an agent proposed
  building a source register while `discover --source generic` already imported source lists.
- Before adding a module, read `docs/MAP.md` and the existing implementation. Reuse existing modules.
- Before data plans, parking logic or Sheet work, read `docs/PP_rules_and_pilot.md`, including cell and publication controls.
- Sheet changes require the owner's explicit go after a dry run, saved undo, six checks and independent second reading.
- Apply through the existing writer, write Verification Result last, and require zero mismatches from an independent re-export.
- Keep ALL LONDON, protected columns, finished rows and personally verified rows unchanged. Match headers by text and rows by Place ID.
- Free, Yes, Anyone and maximum stay need strong evidence for the exact site. Silence is not No. Identity is not parking permission.
- Never print, copy or commit credentials.
- Keep `data/runs/` append-only. Never delete, overwrite or move its contents. Never run a recursive delete.
- File deletion, history rewriting and force-push require explicit owner approval.
- Use plain hyphens, never en or em dashes, in files, cells and messages.
- Fix package bugs with regression tests. Test changed rules and new reader behaviour; reuse existing checks for unchanged paths.
- Run `python -m pytest tests/ -q` before reporting done. Commit each finished task separately.
- End with a file-by-file summary. Keep current work in STATUS.md, not new handovers or session prompts.
