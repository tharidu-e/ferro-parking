Work in /Users/deshan/Documents/ferro-parking on a new branch. Read CLAUDE.md
and docs/PP_rules_and_pilot.md first. Those two set rules you may never break.

You have three jobs, in this order. Job 1 is the real work. Jobs 2 and 3 stop
the next agent rebuilding what already exists.

## Job 1: build the identity matcher

Implement docs/OSM_IDENTITY_BRIEF.md in full. It is a complete specification:
the data shape, the three match methods, the columns you may write, the outputs
and the test list are all decided. Implement them, do not redesign them.

Why it matters. The database holds 11,558 places. 3,951 are car parks the
project created from OpenStreetMap, 3,495 of them have no real name, and 4,817
rows in the research queue have no brand. A car park with no name and no brand
has no website, so no fetcher and no council page can ever say who may park
there. Every later step is blocked on this one.

Reuse what exists. Do not write a new tag table: config/discovery_categories.toml
already maps OpenStreetMap tags to the sheet's Place Category values for 16
categories, and discovery.load_categories and discovery.classify_osm already
read it. Do not write a new extract reader before you have read
osm_places.collect and discovery.DiscoveryCollector.

The command is read only. It writes a db-apply plan and never applies it.

When it runs, report the count per method, the count held, and the top 20
brands by proposal count. That last list is the answer to which source
adapters are worth building next, and nobody has that answer yet.

## Job 2: write one map of the code

Write docs/MAP.md. One line per file under src/ferro_parking and one line per
file under config, saying what that file owns. Read each file before you
describe it. Group the lines under the stage they serve: import and export,
discovery, creation, routing, research, publication, support.

This exists because a worker rebuilt a category mapping that
config/discovery_categories.toml already held, and nearly rebuilt a matcher
that discovery.match_unnamed_car_parks already held. 47 modules and 13,500
lines with no map is why. Keep the map under 150 lines. A line that repeats the
file name is worthless: say what it owns and what calls it.

Add a line to CLAUDE.md telling the next session to read docs/MAP.md before
writing a new module.

## Job 3: propose the document cleanup, and delete nothing

The project holds 21 markdown files and 3,830 lines of them. Several are
finished or superseded, and the overlap misleads every tool that reads them.

Deleting any file needs Deshan's explicit approval in the chat. So write
docs/CLEANUP_PROPOSAL.md listing, for each of the 21 files, one of three
outcomes with a one-line reason:

- keep, because it still governs the work
- merge into EXECUTION_CHECKLIST.md or README.md, and name the sections to move
- delete, because it is finished or superseded

Known facts for your list. docs/HANDOVER.md is no longer wanted: Deshan wrote
it during a Grok outage and has said it is finished. docs/STEP3_PLAN.md
describes work now recorded in EXECUTION_CHECKLIST.md.
docs/GPT_LONDON_EXECUTION_GUIDE.md says in its own words that
EXECUTION_CHECKLIST.md replaces its step order. README.md is 784 lines, which
is too long to be read by anyone, so say which parts belong in MAP.md instead.

Do the merges your own proposal calls for, so the content is safe in its new
home. Then leave every original file in place for Deshan to approve deleting.

## Hard rules

- Every bug fix gets a regression test. Run python -m pytest tests/ -q and make
  the whole suite pass. It is at 1,477 tests now.
- No network in code or in tests.
- Never write a parking answer the evidence does not state. Rules R7, R9 and
  R10. Silence is not No.
- Never write to the Google Sheet. Never delete, overwrite or move anything
  under data/runs. Never run a recursive delete.
- Do not use an em dash or an en dash anywhere.
- End every commit message with:
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
- End your report with a file-by-file summary.
