# Ferro parking: rules for every session

- Read EXECUTION_CHECKLIST.md and docs/PP_rules_and_pilot.md (rules R1-R10) before working. docs/HANDOVER.md is historical and pending approved deletion.
- Read docs/MAP.md before writing a new module; reuse the owner listed there.
- Never delete, overwrite or move anything under data/runs/. Run folders are append-only. If a folder exists, create a new one with a suffix (_2, _3). Never run rm -rf, rm -r, or any recursive delete anywhere in the project. Deleting any file needs Deshan's explicit approval in the chat.
- Never write to the Google Sheet without a dry run, an undo file saved first, Verification Result written last, and an independent re-export compare afterwards. Stop everything on any mismatch.
- Never edit protected columns (Postcode Area, Confidence (1-5), Free Stay Countdown (mins), Ferro Autopay, Parking Charge (£), Total incl. Ferro Fee (£), Captured By, Date Captured, Latitude, Longitude, Place ID, every "(as captured)" column, Charges (as published), Enforcement Details). Never write to the "ALL LONDON" tab. Never touch rows where Verified By is "Tharidu" (hand-checked). Report their issues instead.
- Find columns by header text. Match rows by Place ID. Never insert, delete, sort or reorder rows or columns. Add new columns only at the end.
- Never set Free, Anyone or a max stay without site-specific evidence (R7). Silence is not No (R9), except Presumed under R10.
- Every bug fix gets a regression test. All tests must pass before a commit.
- Do not use an em dash or an en dash in any output, cell or file.
- End every task with a file-by-file summary.
