# Document cleanup proposal

No files have been deleted, moved or renamed. Deletion needs Deshan's explicit approval in chat. This inventory found 23 existing Markdown files, rather than the expected 21, before MAP.md and this proposal were created. All 23 are listed below. The two new documents remain active: MAP.md owns code navigation; this file owns the pending deletion decisions.

The current order is EXECUTION_CHECKLIST.md. CLAUDE.md, AGENTS.md and PP_rules_and_pilot.md retain their safety authority. Historical counts and copied instructions below do not authorise an apply or override today's instructions.

| Existing file | Outcome | Reason and destination |
|---|---|---|
| `AGENTS.md` | keep | Governs sheet safety, approvals, protected fields, tests and commits. |
| `CLAUDE.md` | keep | Governs every session and now points to the checklist and code map. |
| `EXECUTION_CHECKLIST.md` | keep | Owns current work order, completed runs, remaining gates and merged continuation details. |
| `README.md` | keep | Owns setup, runnable commands, database query examples and user procedures; code ownership belongs in MAP.md. |
| `ADD_PLACES_RUNBOOK.md` | keep | Owns the reusable creation, undo and redo operating procedure. |
| `docs/PP_rules_and_pilot.md` | keep | Owns R1-R10 and the evidence behind the safety rules. |
| `docs/PP_Validator_prompt_v2_OSM.md` | keep | Owns bot instructions, field definitions, exact values and verification rules. |
| `docs/PP_architecture_OSM_first.md` | keep | Owns the target architecture diagrams and unresolved product decisions; it is not the current execution sequence. |
| `docs/OSM_IDENTITY_BRIEF.md` | keep | Owns the implemented identity contract and its acceptance tests. |
| `docs/holds_reviewer_prompt.md` | keep | Remains executable input to the independent hold reviewers. |
| `docs/grok_import.md` | keep | Owns importer artifacts, approval procedure and retry/handoff instructions. |
| `docs/grok_skip.md` | keep | Records the owner's decision against applying skip rules and the reason; prevents accidental reactivation. |
| `docs/GPT_LONDON_EXECUTION_GUIDE.md` | merge into EXECUTION_CHECKLIST.md | Preserve Rules for the execution, sections 1, 2, 5, 6, 7 and Final report and continuation record as reference detail; the checklist already replaces its step order. |
| `docs/2026-11-10_GPT_EXECUTION_CHECKPOINT.md` | merge into EXECUTION_CHECKLIST.md | Preserve Verified baseline, Artifacts, Stop guard and restart, and Roles and changed files as dated history; its claim that insertion is unimplemented is superseded. |
| `docs/2026-11-10_IMPLEMENTATION_REPORT.md` | merge into EXECUTION_CHECKLIST.md | Preserve Category result, Research result and File-by-file code summary as dated run evidence; later extractor fixes govern current behaviour. |
| `docs/HANDOVER.md` | delete | Deshan says it is finished and no longer wanted; unique 11 November open items and live continuation details are preserved in the checklist. |
| `docs/STEP3_PLAN.md` | delete | Completed hold work, applied outcomes and corrected rules are recorded in the checklist; its old postcode-centroid rule is superseded. |
| `docs/DB_EXPANSION_PLAN.md` | delete | The checklist and add-places runbook replace its pre-creation model and old pilot sequence. |
| `docs/CODEX_NEXT_PROMPT.md` | delete | One-session task prompt is fulfilled by matcher, map and cleanup work; the identity brief retains the reusable contract. |
| `docs/holds_codex_audit_prompt.md` | delete | One-off audit completed; the checklist's applied step 3 record preserves its findings and fixes. |
| `docs/PP_IMPLEMENTATION.md` | delete | Finished implementation inventory; current ownership is in MAP.md and procedures remain in README.md. |
| `docs/PP_DISCOVERY_FOLLOWUP.md` | delete | Finished discovery follow-up and fixture report; current commands and ownership are documented elsewhere. |
| `docs/PP_CATEGORY_POSTCODE_REVIEW.md` | delete | Historical review counts and file summary; reusable postcode/category procedures remain in README.md and MAP.md. |

## README ownership content copied into MAP.md

Keep setup, command examples, SQL queries, evidence rules and apply procedures in README.md. MAP.md now owns the implementation descriptions from these README sections: Why adding places needed new code; PP matching and review tools; Local database; Created records; Router; Plan files; Category default; Car park evidence and the no_evidence stage; Probes; Category fills; Fetchers; Category metadata, research reports and Grok queue; Phase 7: publish. Each relevant module and configuration file now has a single ownership line there.

The long README remains intact in this pass so no original content is lost. A later edit can reduce those sections to commands, inputs, outputs and a MAP.md link. Do not move the SQL cookbook into MAP.md: it is a user procedure, not code ownership.

## Preservation performed

The three merge rows above have been copied into labelled reference sections in EXECUTION_CHECKLIST.md. The guide's old session prompt, old order and model-role recommendations were not carried forward. They are superseded handoff instructions, not missing operating content. Historical copies are explicitly marked as snapshots, not current counts or apply authority. Unique unresolved HANDOVER items are copied into the current continuation section. Every original remains in place for deletion approval.
