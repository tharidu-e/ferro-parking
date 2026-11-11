"""Read-only OSM geometry identity proposals for active created records.

Uses discovery's category vocabulary and collector geometry handling. Identity
is evidence of a nearby venue, never evidence of a parking permission or price.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path
import sqlite3

from shapely import wkb

from shapely.strtree import STRtree

from . import db, discovery, fill, plan, grok_import
from .osm_match import osm_url
from .osm_places import is_parking
from .run_paths import new_run_dir, reserve_output

METHODS = ("inside the car park", "inside the site", "beside it")
PROPOSAL_HEADERS = ("place_id", "source_ref", "anchor_name", "anchor_category",
                    "method", "metres", "brand", "place_category")


def clean(value):
    return str(value or "").replace("\u2013", "-").replace("\u2014", "-").strip()


class Collector(discovery.DiscoveryCollector):
    """Reuse discovery's node/area reader in one extract traversal."""

    def __init__(self, categories):
        super().__init__(categories)
        self.parking = {}
        self.anchors = []

    def way(self, way):
        # Closed ways are supplied by osmium's area assembler, including holes
        # and relation membership. Open ways need their own line geometry.
        if way.is_closed():
            return
        tags = {tag.k: tag.v for tag in way.tags}
        category = discovery.classify_osm(tags, self.categories)
        if not category:
            return
        try:
            geom = wkb.loads(self.wkb.create_linestring(way), hex=True)
        except (RuntimeError, ValueError):
            return
        self._add_feature("way", way.id, tags, category, geom, way.timestamp)

    def _add_feature(self, kind, oid, tags, category, geom, ts):
        super()._add_feature(kind, oid, tags, category, geom, ts)
        feature = self.features.pop()
        if is_parking(tags):
            self.parking[f"{kind}/{oid}"] = feature
        elif category != "car_park" and tags.get("name", "").strip():
            self.anchors.append(feature)


def collect(path, categories):
    handler = Collector(categories)
    handler.apply_file(str(path), locations=True)
    return handler


class Matcher:
    def __init__(self, anchors):
        self.anchors = anchors
        self.tree = STRtree([anchor["geom"] for anchor in anchors])

    def match(self, parking):
        """All anchors at the strongest matching strength, with edge distance."""
        geom = parking["geom"]
        matches = [[], [], []]
        for index in sorted(self.tree.query(geom.buffer(40))):
            anchor = self.anchors[index]
            other = anchor["geom"]
            distance = geom.distance(other)
            if geom.geom_type in {"Polygon", "MultiPolygon"} and geom.contains(other.representative_point()):
                strength = 0
            elif other.geom_type in {"Polygon", "MultiPolygon"} and other.contains(geom):
                strength = 1
            elif distance <= 40:
                strength = 2
            else:
                continue
            matches[strength].append((anchor, distance))
        for method, found in zip(METHODS, matches):
            if found:
                return method, found
        return "", []


def propose(conn, handler, categories, limit=0):
    """Return plan lines and review reports without mutating the store."""
    _, rows = db.current_rows(conn)
    current = {row["Place ID"]: row for row in rows}
    _, routing = db.latest_routing(conn)
    matcher = Matcher(handler.anchors)
    automation = set(grok_import.load_config()["reviewers"]["automation"]) | {"OSM discovery", "OSM identity match"}
    lines, proposals, held, absent = [], [], [], []
    records = list(conn.execute(
        "SELECT c.place_id, c.source_ref FROM created c WHERE c.active = 1 AND c.source = 'osm'"
        " AND NOT EXISTS (SELECT 1 FROM raw r WHERE r.place_id = c.place_id) ORDER BY c.place_id"))
    if limit:
        records = records[:limit]
    for record in records:
        pid, ref = record["place_id"], record["source_ref"]
        base = {"place_id": pid, "source_ref": ref}
        parking = handler.parking.get(ref)
        if parking is None:
            absent.append({**base, "reason": "reference absent from extract"})
            continue
        row = current.get(pid)
        if row is None or row.get(fill.VERIFICATION_RESULT, "").strip() or (
                row.get(fill.VERIFIED_BY, "").strip() and
                row[fill.VERIFIED_BY].strip() not in automation):
            held.append({**base, "reason": "finished, personally verified or unavailable row"})
            continue
        if pid not in routing:
            held.append({**base, "reason": "no stage in latest routing run"})
            continue
        method, found = matcher.match(parking)
        identities = {clean(a["tags"].get("brand", "").strip() or a["tags"]["name"]) for a, _ in found}
        if len(identities) != 1:
            reason = "no anchor within 40 m" if not found else "ambiguous anchors: " + "; ".join(sorted(identities))
            held.append({**base, "reason": reason})
            continue
        # Stable choice for duplicate representations of the same identity.
        found.sort(key=lambda pair: (pair[1], pair[0]["type"], pair[0]["id"]))
        anchor, metres = found[0]
        mapped = categories[anchor["category"]].get("sheet_place_categories", [])
        if not mapped:
            held.append({**base, "reason": "anchor category has no sheet category: " + anchor["category"]})
            continue
        brand = next(iter(identities))
        quote = "; ".join(f"{clean(k)}={clean(v)}" for k, v in sorted(anchor["tags"].items()))
        quote += f"; {metres:.1f} m from the car park ({method})"
        sentence = f"OSM identity: {clean(anchor['tags']['name'])}, {method}, {metres:.1f} m from the car park; parking rules not checked."
        values = {"Brand": brand, "Place Category": mapped[0], "Notes": sentence}
        before = len(lines)
        for column, value in values.items():
            # db-apply cannot append to a filled Notes cell without stronger
            # evidence. Keep that cell intact; every line retains the quote.
            if not plan.is_placeholder(row.get(column, ""), row):
                continue
            if column == "Notes" and row.get(column, "").strip():
                value = clean(row[column]) + " | " + value
            if value == row.get(column, ""):
                continue
            lines.append({"place_id": pid, "column": column, "new_value": value,
                          "quote": quote, "source_url": osm_url(anchor),
                          "stage": routing[pid], "verified_by": "OSM identity match"})
        if len(lines) == before:
            held.append({**base, "reason": "all permitted columns already filled"})
            continue
        proposals.append({**base, "anchor_name": clean(anchor["tags"]["name"]),
                          "anchor_category": anchor["category"], "method": method,
                          "metres": round(metres, 1), "brand": brand, "place_category": mapped[0]})
    return lines, proposals, held, absent


def write_outputs(out, lines, proposals, held, absent):
    plan.write_plan(out / "plan.jsonl", lines)
    counts = Counter({method: 0 for method in METHODS})
    counts.update(p["method"] for p in proposals)
    counts.update({"proposed": len(proposals), "held": len(held), "absent": len(absent), "plan_lines": len(lines)})
    brands = Counter(p["brand"] for p in proposals)
    for filename, headers, rows in (
        ("proposals.csv", PROPOSAL_HEADERS, proposals),
        ("held.csv", ("place_id", "source_ref", "reason"), held),
        ("absent.csv", ("place_id", "source_ref", "reason"), absent),
        ("counts.csv", ("kind", "name", "count"),
         [{"kind": "count", "name": key, "count": value} for key, value in counts.items()] +
         [{"kind": "brand", "name": key, "count": value} for key, value in brands.most_common()])):
        with (out / filename).open("x", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
    return counts, brands


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", required=True)
    parser.add_argument("--db", default=str(db.DB_PATH))
    parser.add_argument("--out")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    if args.limit < 0:
        parser.error("--limit must be non-negative")
    categories = discovery.load_categories()
    handler = collect(args.pbf, categories)
    # db.connect creates schema and may write. This command must not do either.
    with sqlite3.connect(Path(args.db).resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        result = propose(conn, handler, categories, args.limit)
        _, rejected = plan.check_plan(conn, result[0])
        if rejected:
            raise ValueError(f"identity plan refused: {rejected}")
    out = reserve_output(args.out) if args.out else new_run_dir("osm_identity")
    counts, brands = write_outputs(out, *result)
    for key, count in counts.items():
        print(f"{key}: {count}")
    print("Top 20 brands by proposal count")
    for brand, count in brands.most_common(20):
        print(f"  {brand}: {count}")
    print(f"Plan: {out / 'plan.jsonl'}")
    return 0
