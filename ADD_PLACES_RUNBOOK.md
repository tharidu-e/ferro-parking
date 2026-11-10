# Runbook: add London car parks to the database

These are the commands that add car park records to the local database. Run
them from the project root. Every command is a dry run until you add `--apply`.

No command here touches the Google Sheet. Publication is step 6 of
`EXECUTION_CHECKLIST.md` and it stops for your approval.

## What a created record is

A created record is a place the database made itself, from OpenStreetMap. No
sheet row stands behind it. It holds an identity only: a name, a point, a
borough, a category and the OpenStreetMap reference.

Every parking answer stays blank. The record does not say who can park, what it
costs, or how long a driver can stay. OpenStreetMap proves that a car park
exists. It does not prove permission. Research fills those columns later,
through `db-apply`, under the evidence rules R7, R9 and R10.

## Before you start

Make a copy of the database. The create step writes to it.

```
cp data/db/ferro_parking.sqlite data/db/ferro_parking.sqlite.backup-$(date +%Y%m%dT%H%M%S)
```

Make sure that the tests pass.

```
python -m pytest -q
```

## Step 1: propose the candidates

This command reads the extract and writes a create plan. It is read-only. It
touches no database and makes no network request.

```
python -m ferro_parking osm-places data/raw/greater-london-latest.osm.pbf
```

It prints a count for every filter and writes three files under
`data/runs/<today>/osm_places/`:

- `candidates.jsonl`, the create plan.
- `candidates.csv`, the same records for review, with the OpenStreetMap tags
  that admitted each one.
- `counts.json`, the count at every filter.

Open `candidates.csv` and read it before you go on. The `qualifier` column says
why each record is a candidate. A value of `access tag` means OpenStreetMap
states public access. Any other value means the feature has no access tag and
one other tag admitted it.

## Step 2: dry run the create

```
python -m ferro_parking db-create --plan data/runs/<today>/osm_places/candidates.jsonl
```

Read `plan.csv` and `report.json` in the printed output directory. If
`rejected.csv` exists, the whole plan is blocked. Fix the cause and run again.
Nothing was written.

## Step 3: create a small pilot first

Propose a limited set, create it, and read the result before you add the rest.

```
python -m ferro_parking osm-places data/raw/greater-london-latest.osm.pbf --limit 20 --out data/runs/<today>/osm_pilot
python -m ferro_parking db-create --plan data/runs/<today>/osm_pilot/candidates.jsonl --apply
```

Export the database and compare it against the export you took before.

```
python -m ferro_parking db-export --out data/runs/<today>/export_after_pilot
```

The imported rows must be identical. The new records append at the end.

## Step 4: create the rest

```
python -m ferro_parking db-create --plan data/runs/<today>/osm_places/candidates.jsonl --apply
```

The pilot records are skipped, not refused, because the plan names the same
OpenStreetMap features. The printed line reports how many were skipped. Run the
same plan twice and the second run creates nothing.

## Step 5: route the new records

Routing gives every record a research stage. A created record needs one before
`db-apply` can fill any field.

```
python -m ferro_parking route
```

## If you need to undo a create run

```
python -m ferro_parking db-create-undo --run <run id from the create output>
python -m ferro_parking db-create-undo --run <run id> --apply
```

Undo deactivates the records. It deletes no row and frees no Place ID, so a
later create run never reuses one. Undo is refused for a record that a later
run has changed, because that would discard newer evidence.

## If you undo, fix something, and want the records back

```
python -m ferro_parking db-create-redo --run <run id>
python -m ferro_parking db-create-redo --run <run id> --apply
```

Redo brings back the records one create run made. The duplicate guards run
again, so a record that now duplicates a place stays deactivated. Each record
keeps the Place ID it already has.

A plain `db-create` will not bring an undone record back. That is deliberate.
An undo is a decision, and the next run must not quietly reverse it.

## Duplicates

Two checks stop the same car park being added twice. Neither is a refusal, so
neither blocks the plan.

A record whose OpenStreetMap reference already belongs to a place is skipped.
This is what makes a repeated or interrupted run safe, and it also catches a
car park an earlier discovery round already added to the sheet.

A record whose pin lands within 30 m of a place the database already holds is
held, and listed in `held.csv`. A pin that close is a possible duplicate and
not proof. Different businesses, levels and adjacent car parks sit metres
apart. Read `held.csv` and decide each case yourself. Two candidates in the
same plan that land within 30 m of each other are treated the same way, because
one car park is often mapped twice, once as a node and once as an area.

## What these commands refuse

- A create plan that sets any parking answer, any evidence field, or any of the
  four owner payment columns. Creation establishes identity, not permission.
- A create plan that chooses its own Place ID. The database allocates it.
- A record with no name, or with no usable coordinate.
- The same OpenStreetMap feature twice in one plan.
- An undo of a record a later run has changed.

A single refusal blocks the whole plan, and `rejected.csv` names every reason.

## What the candidate filter excludes

- An access tag of private, no, residents, permit, employees, delivery, staff
  or students.
- Street side, lane, on street, kerb and shoulder parking.
- Lorry, coach and HGV parking, and any parking a car may not enter.
- A disused, abandoned, proposed or construction car park.
- Anything whose point falls outside the union of the Greater London borough
  polygons, read from the extract itself.
- A feature with no access tag and no qualifying tag. The qualifiers are a
  name, an operator, a fee tag, a capacity of 10 or more, a multi-storey or
  underground type, or an area of at least 500 square metres.
