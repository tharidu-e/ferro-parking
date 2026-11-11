# Agent rules

Ferro parking serves real drivers. Accuracy takes priority over coverage.

- Read only documents needed for the task. Do not scan every document at startup.
- For priorities or remaining work, read `docs/STATUS.md`.
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
- Fix bugs in the package with regression tests. Add tests for new rules.
- Run `python -m pytest tests/ -q` before reporting done. Commit each finished task separately.
- End with a file-by-file summary. Keep current work in STATUS.md, not new handovers or session prompts.
