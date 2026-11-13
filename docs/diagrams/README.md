# Ferro parking system design

Open [the diagram gallery](index.html) in a browser to read all eight diagrams.
Open [the editable drawing](ferro-system-design.excalidraw) in Excalidraw to edit the shapes and text.
Use Excalidraw's Open command to load the file. Each numbered frame contains one diagram.

This is a new local drawing. The supplied Excalidraw link was inaccessible through the available tools.
The online file was neither read nor changed. The diagrams use the repository's documented workflow and implementation.
Architecture was reviewed on 13 November 2026. All counts come from the saved 12 November status unless stated otherwise.

## Reading order

| Diagram | Question it answers |
|---|---|
| 01 Project overview | What does the project do for drivers? |
| 02 Data sources | Which sources identify places or support parking facts? |
| 03 Discovery | How does a candidate become a distinct place? |
| 04 Routing | How does the system choose the next research path? |
| 05 Research | How does a page become an accepted field value? |
| 06 Storage | What does SQLite store, and how are current rows assembled? |
| 07 Publication | How do reviewed changes reach the Sheet? |
| 08 Delays | Why does filling the records take time? |

Blue marks sources, purple marks processing, amber marks review or approval, red marks holds, and green marks outcomes.
Arrows describe the main relationships. They do not represent every code branch or SQL foreign key.
The project uses Python command-line batch tools, a local SQLite store and Google Sheets.
These diagrams do not assert that a driver application, public API or automatic scheduler is deployed.

## Why the work takes time

The project must answer separate questions for each site: where it is, who can park, what it costs, and which restrictions apply.
Finding a location answers only the first question. A source that says "Car parking" does not establish free parking or a maximum stay.
The rules require stronger evidence for answers that can expose a driver to a charge or fine.

The saved status gives concrete examples of the delay:

- The station reader attempted 473 records and produced values for 119. It added no price, maximum stay or eligible-user answer.
- The M&S work added answers to five records. Their cost stayed Unknown, so none became showable.
- Grok batch 2 took 71 minutes for 200 rows. Its first import accepted 82 and rejected 106, largely for formatting problems.
- Grok batch 4 returned 162 shallow misses. A reread opened 710 pages and found a fact for 137 of those places.
- The database status lists 1,176 records needing an on-site check. More code cannot supply a missing sign or resolve every conflicting source.
- Local database changes did not reach the Sheet in the reported publication runs. Publication requires its own reviewed plan and owner approval.

These examples show causes, but they do not measure each cause's share of total elapsed time.
The remaining 3,578 rows in the saved bot queue are a research workload, not a forecast of successful fills.
That queue differs from the later route's 4,037 Grok-stage rows because the snapshots and selection rules differ.

The useful next actions already exist in PLAN.md: reuse saved evidence, target exact missing answers, preflight bot results, and separate held cases.
New readers need a measured source that actually states useful facts. Repeating silent or blocked sources adds little progress.
Accepted batches can proceed to publication without waiting for every place or field to be complete.

## Interpret the progress measures carefully

| Measure | Saved value | Meaning and limit |
|---|---:|---|
| Records | 11,560 | Includes identities without supported parking answers. |
| Blank Verification Result | 6,192 | A workflow field, not a count of every missing driver answer. |
| Active OSM-created identities | 3,951 | Location coverage, not parking permission. |
| Boroughs with zero inventory gaps | 20 of 33 | Only within the named inventories. Limited lists do not prove full borough coverage. |
| Legacy showable | 1,606 | Cell-based readiness. It does not require evidence-table quotes. |
| Legacy complete | 1,098 | The existing readiness calculation, not the full driver information standard. |
| Records with the three core evidence fields | 1,038 | STATUS labels these evidence-supported showable, but includes 121 explicit no-parking answers. Do not present all 1,038 as usable car parks. |
| Evidence-supported complete | 0 | Saved status measure, not a new computation in this task. |
| Publication pilot | 20 rows | Category-only dry run dated 11 November. It was not a completed Sheet write. |

Research complete for now means useful sources were read and remaining gaps have a reason and revisit trigger.
Driver information complete means all applicable information needed to use the car park safely is supported.
The readiness code has a narrower definition: it can count sourced "Not published" hours or maximum stay as complete.
Do not equate that calculation with the driver information standard in PLAN.md.

The saved route lists 1,186 on-site skips, while the status table lists 1,176 on-site records.
These are different saved measures. This documentation does not reconcile them or claim a live database count.
Historical status also describes code that can route some finished rows with gaps and fill blank cells.
The governing owner instructions are stricter: keep finished and personally verified rows unchanged. The diagrams retain that operating rule.

## Source map and maintenance

Use [STATUS.md](../STATUS.md) for current work and [PLAN.md](../PLAN.md) for the operating sequence.
Use [the parking rules](../PP_rules_and_pilot.md) for evidence and publication controls.
Use [MAP.md](../MAP.md) to find the module responsible for each step.

The implementation review covered `db.py`, `route.py`, `fetch_fill.py`, `plan.py`, `publish.py` and `readiness.py` under `src/ferro_parking/`.
The command index was read with `python -m ferro_parking --help` before drawing.
If workflow or counts change, update both the Excalidraw drawing and its HTML gallery.
Keep the snapshot date visible. The gallery is a static preview, not a live dashboard.
