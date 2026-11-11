Audit the 267 committed decisions on the Ferro parking hold list. Do not change
any file. Report only.

Read docs/STEP3_PLAN.md, the step 3 run record at the end of
EXECUTION_CHECKLIST.md, src/ferro_parking/holds.py and
docs/holds_reviewer_prompt.md.

The decisions are in data/runs/2026-11-11_5/holds_merge/decisions.csv. The
evidence per case is in data/runs/2026-11-11_3/holds/bundle.jsonl. The two
reviewers are data/runs/2026-11-11_3/reviews/reviewer_a.csv and reviewer_b.csv.

Answer four questions, each with counts and named case ids.

1. Of the 258 duplicate verdicts, which ones does the evidence not support?
   Check the 167 the rules decided as well as the 91 the reviewers decided.
2. Of the 9 distinct verdicts, which ones would create a car park the database
   already holds?
3. Does any rule in holds.py decide a case the evidence cannot settle, or let a
   distance measured to a postcode centroid decide anything?
4. Which of the 534 unresolved cases does the evidence in fact settle, and on
   what field?

A duplicate verdict stops a creation, so a wrong one loses a real car park. A
distinct verdict creates a record, so a wrong one adds a duplicate row. Rank
what you find by which of those two it causes.

Do not write an em dash or an en dash.
